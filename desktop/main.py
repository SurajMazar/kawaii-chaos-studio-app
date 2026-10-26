"""Kawaii Chaos Studio for macOS: the Studio server on 127.0.0.1 inside a native window (WKWebView via pywebview).

Everything stays on this Mac:
  ~/Documents/Kawaii Chaos Studio/                 your comics (plain files, created from starter/ on the first start)
  ~/Library/Application Support/Kawaii Chaos Studio/   the local database (SQLite), settings, encrypted keys, logs
  ~/Library/Caches/Kawaii Chaos Studio/                thumbnails and render caches (safe to delete)

There is no password: the window is signed in with a secret made for this launch only (/api/auth/desktop), and the
server only listens on 127.0.0.1. The packaged app has no separate Python, so the Studio runs its scripts as
`<app> script.py args…` (handled first thing below).

    python desktop/main.py              # from the source tree (needs studio/requirements.txt + desktop/requirements.txt)
    python desktop/main.py --selftest   # headless: start, sign in, make a strip, build its reel, quit (used by CI)
"""
import os
import sys


def _script_mode():
    """`<app> some_script.py …` runs that script with the bundled Python (the Studio's jobs do this)."""
    if len(sys.argv) > 1 and sys.argv[1].endswith('.py') and os.path.isfile(sys.argv[1]):
        import runpy
        script = os.path.abspath(sys.argv[1])
        sys.argv = [script] + sys.argv[2:]
        sys.path.insert(0, os.path.dirname(script))
        try: sys.stdout.reconfigure(line_buffering=True); sys.stderr.reconfigure(line_buffering=True)
        except (AttributeError, ValueError): pass
        runpy.run_path(script, run_name='__main__')
        sys.exit(0)


_script_mode()

import fcntl, secrets, shutil, socket, subprocess, tempfile, threading, time  # noqa: E402  (after the script dispatch on purpose)
from pathlib import Path  # noqa: E402

APP = 'Kawaii Chaos Studio'
FROZEN = getattr(sys, 'frozen', False)
CODE = Path(getattr(sys, '_MEIPASS', '')) if FROZEN else Path(__file__).resolve().parent.parent
HOME = Path.home()
SUPPORT = Path(os.environ.get('KCS_SUPPORT_DIR') or HOME / 'Library' / 'Application Support' / APP)   # env: for testing
CACHES = Path(os.environ.get('KCS_CACHE_DIR') or HOME / 'Library' / 'Caches' / APP)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); return s.getsockname()[1]


def _ffmpeg_on_path(bin_dir: Path):
    """Use an installed ffmpeg (Homebrew) when there is one, else the one inside the app."""
    extra = ['/opt/homebrew/bin', '/usr/local/bin']
    os.environ['PATH'] = os.pathsep.join([os.environ.get('PATH', '/usr/bin:/bin')] + [p for p in extra if p not in os.environ.get('PATH', '')])
    if shutil.which('ffmpeg') and not os.environ.get('KCS_BUNDLED_FFMPEG'): return shutil.which('ffmpeg')   # KCS_BUNDLED_FFMPEG=1: test the bundled one
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
    bin_dir.mkdir(parents=True, exist_ok=True)
    link = bin_dir / 'ffmpeg'
    if link.is_symlink() or link.exists(): link.unlink()
    link.symlink_to(exe)
    os.environ['PATH'] = str(bin_dir) + os.pathsep + os.environ['PATH']
    return str(link)


def _single_instance():
    SUPPORT.mkdir(parents=True, exist_ok=True)
    fh = open(SUPPORT / '.running.lock', 'w')
    try: fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        subprocess.run(['osascript', '-e', f'display alert "{APP} is already open" message "Switch to its window (Cmd-Tab)."'], check=False)  # nosec B603 B607
        sys.exit(0)
    return fh                                   # keep the handle open = keep the lock


def configure(data_dir: Path | None = None, support: Path = SUPPORT, caches: Path = CACHES, log_file: bool = True) -> dict:
    """Environment for a local, single-person Studio. Returns {port, token, ffmpeg}."""
    port, token = _free_port(), secrets.token_urlsafe(32)
    (support / 'logs').mkdir(parents=True, exist_ok=True)
    env = {
        'STUDIO_ENV': 'development',                         # local features on (Downloads import, export folder)
        'STUDIO_CODE_ROOT': str(CODE),
        # only a default: Settings → Integrations → Local folder can point the app at another folder (STUDIO_DATA_DIR would lock it)
        'STUDIO_DEFAULT_DATA_DIR': str(data_dir or HOME / 'Documents' / APP),
        'STUDIO_CONFIG_DIR': str(support / 'config'),
        'STUDIO_CACHE_DIR': str(caches / 'cache'),
        'STUDIO_WORKDIR': str(caches / 'work'),
        'STUDIO_HOST': '127.0.0.1', 'PORT': str(port),
        'STUDIO_ALLOWED_HOSTS': '127.0.0.1,localhost',
        'STUDIO_DESKTOP_TOKEN': token,
        'STUDIO_SESSION_IDLE_MINUTES': str(60 * 24 * 30), 'STUDIO_SESSION_MAX_HOURS': str(24 * 365),
        'STUDIO_SCRIPT_PYTHON': sys.executable,              # the app itself runs the scripts (see _script_mode)
        'STUDIO_NO_AUTOAPP': '1',
    }
    if data_dir is not None: env['STUDIO_DATA_DIR'] = str(data_dir)          # selftest: a throw-away folder
    os.environ.update(env)
    os.environ.setdefault('STUDIO_ART_SOURCE', 'own')
    ff = _ffmpeg_on_path(support / 'bin')
    if FROZEN and log_file:                                  # Finder apps have no terminal: log to a file
        log = open(support / 'logs' / 'studio.log', 'a', buffering=1)
        sys.stdout = sys.stderr = log
    return dict(port=port, token=token, ffmpeg=ff)


def start_server(port: int):
    if not FROZEN: sys.path.insert(0, str(CODE / 'studio'))
    import uvicorn
    import server
    app = server.create_app()
    srv = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_config=None, server_header=False,
                                        proxy_headers=False, lifespan='off'))
    t = threading.Thread(target=srv.run, daemon=True, name='studio-server'); t.start()
    for _ in range(300):
        if srv.started: return srv, t
        if not t.is_alive(): raise RuntimeError('the Studio server stopped while starting (see the log)')
        time.sleep(0.05)
    raise RuntimeError('the Studio server did not start')


def main():
    lock = _single_instance()  # noqa: F841 - held for the app's lifetime
    c = configure()
    srv, t = start_server(c['port'])
    import webview
    webview.settings['ALLOW_DOWNLOADS'] = True                # Export .zip, Download buttons → Save dialog
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True # ChatGPT / ElevenLabs links open in your browser
    url = f"http://127.0.0.1:{c['port']}/api/auth/desktop?token={c['token']}"
    webview.create_window(APP, url, width=1440, height=920, min_size=(1000, 680), text_select=True)
    webview.start(private_mode=False, storage_path=str(SUPPORT / 'webview'))
    srv.should_exit = True; t.join(timeout=8)


def selftest() -> int:
    """No window: start on throw-away folders, sign in like the window does, make a strip from a drawing, QA it, build
    the reel (runs the bash + Python scripts through this executable and ffmpeg). Exit code 0 = the build works."""
    import http.cookiejar, io, json, urllib.request, uuid
    tmp = Path(tempfile.mkdtemp(prefix='kcs_selftest_'))
    c = configure(data_dir=tmp / 'data', support=tmp / 'support', caches=tmp / 'caches', log_file=False)
    print('ffmpeg:', c['ffmpeg'], flush=True)
    srv, t = start_server(c['port'])
    base = f"http://127.0.0.1:{c['port']}"
    jar = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def call(method, path, body=None, ctype='application/json'):
        csrf = next((x.value for x in jar if x.name.endswith('kcs_csrf')), '')
        data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(base + path, data=data, method=method, headers={'content-type': ctype, 'x-csrf-token': csrf})
        with op.open(req, timeout=300) as r: return json.loads(r.read() or b'{}')
    op.open(base + f"/api/auth/desktop?token={c['token']}", timeout=30).read()
    st = call('GET', '/api/auth/state'); assert st['user'] and st['desktop'], st
    p = call('POST', '/api/new', dict(kind='strip', name='selftest', couple='', tag='', premise='Test', panels=2, seed=1, layout=True,
                                      mood='', lines='', start=0))['id']
    from PIL import Image, ImageDraw
    im = Image.new('RGB', (1122, 1402), (250, 244, 232)); d = ImageDraw.Draw(im)
    for x, y in ((30, 30), (30, 716)):
        d.rectangle([x, y, x + 1062, y + 656], outline=(30, 25, 30), width=8, fill=(255, 250, 240))
        d.ellipse([x + 400, y + 200, x + 660, y + 460], outline=(30, 25, 30), width=6, fill=(255, 200, 210))
    buf = io.BytesIO(); im.save(buf, 'PNG')
    bnd = uuid.uuid4().hex
    body = (f'--{bnd}\r\nContent-Disposition: form-data; name="file"; filename="drawing.png"\r\nContent-Type: image/png\r\n\r\n').encode() + buf.getvalue() + \
        (f'\r\n--{bnd}\r\nContent-Disposition: form-data; name="dest"\r\n\r\nraw\r\n--{bnd}\r\nContent-Disposition: form-data; name="role"\r\n\r\nstrip\r\n--{bnd}--\r\n').encode()
    call('POST', f'/api/p/strip/{p}/upload', body, f'multipart/form-data; boundary={bnd}')
    keys = [x['key'] for x in call('GET', f'/api/p/strip/{p}/qa')['checklist']]
    call('POST', f'/api/p/strip/{p}/qa/pass', dict(file='strip.png', checks={k: True for k in keys}, notes={}, stranger='selftest'))
    job = call('POST', f'/api/p/strip/{p}/reel/auto')
    for _ in range(600):
        j = call('GET', f"/api/jobs/{job['id']}")
        if j['state'] not in ('queued', 'running'): break
        time.sleep(1)
    log = call('GET', f"/api/jobs/{job['id']}?since=0").get('log', [])
    out = tmp / 'data' / 'upload' / f'{p}_strip_reel.mp4'
    ok = j['state'] == 'done' and out.is_file() and out.stat().st_size > 10000
    print('\n'.join(log[-15:]), flush=True)
    print(f"selftest: reel job {j['state']}, {out.name} {'OK' if ok else 'MISSING'} ({out.stat().st_size if out.exists() else 0} bytes)", flush=True)

    # voiced reel: a generated tone as a voice clip -> scripts/voiceover_mix.py (ffmpeg filters, no ffprobe needed)
    import math, struct, wave
    wav = io.BytesIO()
    with wave.open(wav, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
        w.writeframes(b''.join(struct.pack('<h', int(8000 * math.sin(2 * math.pi * 440 * i / 22050))) for i in range(22050)))
    body = (f'--{bnd}\r\nContent-Disposition: form-data; name="file"; filename="hello.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode() + wav.getvalue() + f'\r\n--{bnd}--\r\n'.encode()
    clip = call('POST', f'/api/p/strip/{p}/voiceover/clip', body, f'multipart/form-data; boundary={bnd}')['name']
    cfg = call('GET', f'/api/p/strip/{p}/voiceover')['config']
    cfg['lines'] = [dict(id='l1', character='Narrator', text='hello', at=0.5, clip=clip, gain_db=0, takes=[clip])]
    job = call('POST', f'/api/p/strip/{p}/voiceover/mix', dict(config=cfg))
    for _ in range(300):
        j2 = call('GET', f"/api/jobs/{job['id']}")
        if j2['state'] not in ('queued', 'running'): break
        time.sleep(0.5)
    vo = tmp / 'data' / 'upload' / f'{p}_strip_reel_voiceover.mp4'
    ok2 = j2['state'] == 'done' and vo.is_file()
    print(f"selftest: voiceover mix {j2['state']} {'OK' if ok2 else 'FAILED: ' + str(j2.get('error'))}", flush=True)

    # lyric edit preview frame: scripts/lyric_edit.py imported inside the server
    mv = call('POST', '/api/new', dict(kind='lyric', name='selftest_lyric', couple='', tag='', premise='', panels=4, seed=None, layout=False,
                                       mood='', lines='hello / world', start=0))['id']
    edit = call('GET', f'/api/lyric/{mv}/edit?file=lyric_edit.json'); edit['size'] = [216, 384]
    req = urllib.request.Request(base + f'/api/lyric/{mv}/still', data=json.dumps(dict(edit=edit, t=0.5, scale=0.5)).encode(), method='POST',
                                 headers={'content-type': 'application/json', 'x-csrf-token': next((x.value for x in jar if x.name.endswith('kcs_csrf')), '')})
    with op.open(req, timeout=120) as r: png = r.read()
    ok3 = png[:3] == b'\xff\xd8\xff' and len(png) > 1000           # a JPEG frame
    print(f"selftest: lyric preview frame {'OK' if ok3 else 'FAILED'}", flush=True)
    ok = ok and ok2 and ok3
    srv.should_exit = True; t.join(timeout=8)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.stdout.reconfigure(line_buffering=True)
        sys.exit(selftest())
    main()
