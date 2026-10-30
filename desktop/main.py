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


def _free_port(preferred: int = 0) -> int:
    with socket.socket() as s:
        # SO_REUSEADDR like uvicorn: right after a quit the old port sits in TIME_WAIT for a minute and a plain bind fails
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try: s.bind(('127.0.0.1', preferred))
        except OSError: s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _sticky_port(support: Path) -> int:
    """The same port every launch when it's free: the window's localStorage (tours seen, UI choices) belongs to
    http://127.0.0.1:<port>, so a new port each launch made the app forget all of it."""
    f = support / 'desktop_port'
    try: saved = int(f.read_text().strip())
    except (OSError, ValueError): saved = 0
    port = _free_port(saved if 1024 < saved < 65536 else 0)
    if port != saved:
        try: f.write_text(str(port))
        except OSError: pass
    return port


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
    (support / 'logs').mkdir(parents=True, exist_ok=True)
    port, token = (_free_port() if data_dir is not None else _sticky_port(support)), secrets.token_urlsafe(32)
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


def _native_downloads():
    """Every attachment becomes a WebKit download with a Save dialog. pywebview 5.4 on its own shows attachments it can
    display (PNG, MP4) in place of the app, and fetches the rest (Export .zip) without the window's sign-in cookie, so
    the server answers 401 and the saved file is junk. A WKDownload goes through the window's own session.
    KCS_DOWNLOAD_TO=<folder> saves there without the dialog (tests)."""
    import objc
    import AppKit, Foundation, WebKit
    from webview.platforms.cocoa import BrowserView

    keep = []                                                 # delegates are weak: hold them while downloads run

    class SaveDelegate(AppKit.NSObject):
        def downloadDidFinish_(self, download):
            if self in keep: keep.remove(self)

        def download_didFailWithError_resumeData_(self, download, error, data):
            print('download failed:', error, flush=True)
            if self in keep: keep.remove(self)

        def download_decideDestinationUsingResponse_suggestedFilename_completionHandler_(self, download, response, name, done):
            auto = os.environ.get('KCS_DOWNLOAD_TO')
            if auto:
                done(Foundation.NSURL.fileURLWithPath_(os.path.join(auto, name))); return
            dlg = AppKit.NSSavePanel.savePanel()
            dlg.setDirectoryURL_(Foundation.NSURL.fileURLWithPath_(str(HOME / 'Downloads')))
            dlg.setNameFieldStringValue_(name)
            done(dlg.URL() if dlg.runModal() == AppKit.NSModalResponseOK else None)

    def attach(download):
        d = SaveDelegate.alloc().init(); keep.append(d); download.setDelegate_(d)

    def decide_response(self, webview, nav, handler):
        r = nav.response()
        disp = r.valueForHTTPHeaderField_('Content-Disposition') if hasattr(r, 'valueForHTTPHeaderField_') else None
        if (disp or '').lower().startswith('attachment') or not nav.canShowMIMEType():
            handler(WebKit.WKNavigationResponsePolicyDownload)
        else:
            handler(WebKit.WKNavigationResponsePolicyAllow)

    D = BrowserView.BrowserDelegate
    sig = D.webView_decidePolicyForNavigationResponse_decisionHandler_.signature
    objc.classAddMethods(D, [
        objc.selector(decide_response, selector=b'webView:decidePolicyForNavigationResponse:decisionHandler:', signature=sig),
        objc.selector(lambda self, w, nav, dl: attach(dl), selector=b'webView:navigationResponse:didBecomeDownload:', signature=b'v@:@@@'),
        objc.selector(lambda self, w, act, dl: attach(dl), selector=b'webView:navigationAction:didBecomeDownload:', signature=b'v@:@@@'),
    ])


def _native_share(w):
    """Share button (Files tab) → the macOS share menu (AirDrop, Messages, Mail, Notes…) for the file itself, opened
    next to the button. The server thread asks; AppKit has to show it on the main thread."""
    import AppKit, Foundation
    from PyObjCTools import AppHelper
    from webview.platforms.cocoa import BrowserView
    from api import native
    keep = []                                                 # the picker must stay alive while its menu is open

    def share(path, rect):
        def show():
            try:
                bv = BrowserView.instances.get(w.uid)
                if bv is None: return
                view = bv.webview
                x, y, rw, rh = rect
                flipped = view.isFlipped()
                if not flipped: y = view.bounds().size.height - y - rh
                picker = AppKit.NSSharingServicePicker.alloc().initWithItems_([Foundation.NSURL.fileURLWithPath_(str(path))])
                keep[:] = [picker]
                picker.showRelativeToRect_ofView_preferredEdge_(Foundation.NSMakeRect(x, y, max(rw, 1), max(rh, 1)), view,
                                                                Foundation.NSMaxYEdge if flipped else Foundation.NSMinYEdge)  # below the button
            except Exception as e:                            # never take the window down over a share menu
                print('share failed:', repr(e), flush=True)
        AppHelper.callAfter(show)
    native.share = share


# Pages with a first-run tour (usePageTour keys in studio/web/src).
TOUR_PAGES = ('dashboard', 'new', 'strip', 'mv', 'reel', 'lyric', 'voice', 'music', 'tools', 'settings', 'integrations', 'users')
# run_js, not evaluate_js: evaluate_js wraps the script in eval(), which the Studio's CSP (script-src 'self') blocks
READ_TOURS_JS = "JSON.stringify(Object.keys(localStorage).filter(k => k.startsWith('kcs.tour.') && localStorage.getItem(k) === 'done').map(k => k.slice(9)))"


class Tours:
    """Which page tours are done, mirrored into Application Support. The window's localStorage belongs to
    http://127.0.0.1:<port>; if the port ever has to change, the marks are copied into the new origin so the tours
    don't start over. While the port stays the same the file just follows localStorage (Settings → "Show all tours
    again" still works)."""

    def __init__(self, f: Path, port: int, existing: bool):
        import json
        self.f, self.port, self.json = f, port, json
        try: d = json.loads(f.read_text())
        except (OSError, ValueError): d = dict(port=0, done=list(TOUR_PAGES) if existing else [])
        self.done, self.inject = set(d.get('done', [])), d.get('port') != port

    def save(self):
        try: self.f.write_text(self.json.dumps(dict(port=self.port, done=sorted(self.done))))
        except OSError: pass

    def sync(self, w):
        try: got = self.json.loads(str(w.run_js(READ_TOURS_JS)))
        except Exception: return
        if not isinstance(got, list): return              # page not ready: never mistake that for "no tours done"
        seen = set(got)
        if self.inject:                                     # a new origin: bring the marks over once, then reload
            self.inject = False
            missing = sorted(self.done - seen)
            if missing:
                self.save()                                 # reload on a timer: a reload inside the call never returns
                w.run_js("(() => { %s.forEach(k => localStorage.setItem('kcs.tour.' + k, 'done')); setTimeout(() => location.reload(), 50); return true })()"
                              % self.json.dumps(missing))
                return
        self.done = seen; self.save()

    def follow(self, w):
        """Keep the file in step while the window is open (tours are marked done when they are closed)."""
        w.events.loaded += lambda: self.sync(w)
        def loop():
            while True:
                time.sleep(15)
                try: self.sync(w)
                except Exception: return
        threading.Thread(target=loop, daemon=True, name='tours').start()


def main():
    lock = _single_instance()  # noqa: F841 - held for the app's lifetime
    existing = (SUPPORT / 'config').is_dir()                 # used the app before (tours may already be done)
    c = configure()
    srv, t = start_server(c['port'])
    import webview
    _native_downloads()
    webview.settings['ALLOW_DOWNLOADS'] = True                # Export .zip, Download buttons → Save dialog
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True # ChatGPT / ElevenLabs links open in your browser
    url = f"http://127.0.0.1:{c['port']}/api/auth/desktop?token={c['token']}"
    w = webview.create_window(APP, url, width=1440, height=920, min_size=(1000, 680), text_select=True)
    Tours(SUPPORT / 'tours_seen.json', c['port'], existing).follow(w)
    _native_share(w)
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
