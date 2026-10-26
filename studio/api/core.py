"""Shared helpers: content paths (on the storage workspace), path safety, atomic writes with history, settings, caches.

Every content path is an ``SPath`` (storage key) — with the local backend that is a file in the repo exactly like
before; with S3/R2 it is an object in the bucket, cached on demand in the work cache (see storage/workspace.py).
"""
import hashlib, json, os, re, sys, tempfile, threading
from pathlib import Path

from fastapi import HTTPException

from config import CODE_ROOT, CONFIG, STUDIO
from storage import BadKey, SPath, get_ws
from storage.workspace import ROOT

PROJ = ROOT / 'projects'
MV = ROOT / 'music_videos'
UPLOAD = ROOT / 'upload'
REFS = ROOT / 'references'
FONTS = ROOT / 'fonts'
CODE_FONTS = CODE_ROOT / 'fonts'          # default fonts shipped with the code (scripts/lyric_edit.py uses these)
KINDS = {'strip': PROJ, 'mv': MV}
IMG_EXT = {'.png', '.jpg', '.jpeg', '.webp'}
AUDIO_EXT = {'.mp3', '.m4a', '.wav', '.aac', '.ogg', '.flac'}
VIDEO_EXT = {'.mp4', '.mov', '.m4v', '.webm'}
FONT_EXT = {'.ttf', '.otf', '.ttc'}
PID_RE = re.compile(r'^\d+_[A-Za-z0-9][A-Za-z0-9_\-]*$')
NAME_RE = re.compile(r'^[a-z0-9][a-z0-9_]{0,60}$')
HISTORY_KEEP = 50

if str(CODE_ROOT / 'scripts') not in sys.path: sys.path.insert(0, str(CODE_ROOT / 'scripts'))


class _Scripts:
    """scripts/<name> inside the working tree (a symlink to the code's scripts/ when the data lives elsewhere), so the
    repo scripts that use "<script dir>/.." as their root operate on the working tree."""
    def __truediv__(self, name) -> Path:
        return get_ws().root / 'scripts' / str(name)

    def __str__(self):
        return str(get_ws().root / 'scripts')


SCRIPTS = _Scripts()


def work_root() -> Path:
    return get_ws().root


def natkey(p):
    s = p.key if isinstance(p, SPath) else str(p)
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]


def piece_dir(kind: str, pid: str) -> SPath:
    top = KINDS.get(kind)
    if top is None: raise HTTPException(404, f'unknown kind {kind!r}')
    if not PID_RE.match(pid or ''): raise HTTPException(400, 'bad project name')
    d = top / pid
    if not d.is_dir(): raise HTTPException(404, f'no such project: {pid}')
    return d


def inside(base: SPath, p: SPath) -> bool:
    return p.is_relative_to(base)


def safe_join(base: SPath, rel: str) -> SPath:
    """base + a user-supplied relative path. Rejects '..', absolute paths, backslashes, NUL/control characters and
    anything outside the content folders (storage.norm_key + workspace.allowed_key)."""
    if not isinstance(rel, str): raise HTTPException(400, 'bad path')
    rel = rel.replace('\\', '/')
    if rel.startswith('/') or '\x00' in rel: raise HTTPException(400, 'bad path')
    rel = rel.strip('/')
    if not rel: return base
    if any(part in ('..', '.', '') for part in rel.split('/')): raise HTTPException(400, 'bad path')
    p = base / rel
    try: get_ws().check(p.key)
    except BadKey: raise HTTPException(400, 'bad path')
    if not p.is_relative_to(base): raise HTTPException(400, 'bad path')
    return p


def rel_root(p: SPath) -> str:
    return p.key


def backup(p: SPath):
    """Copy p into <its folder>/.studio_history/<stem>_<time><suffix> (keeps the newest HISTORY_KEEP per file)."""
    try: return get_ws().backup(p.key)
    except BadKey: raise HTTPException(400, 'bad path')


def write_atomic(p: SPath, data, history=True):
    """Atomic write (temp file + rename locally, a single PUT on S3); the previous version is kept in .studio_history/."""
    try: get_ws().write(p.key, data, history=history)
    except BadKey: raise HTTPException(400, 'refusing to write outside the content folders')


def write_json(p: SPath, obj, indent=1, history=True):
    """Same style as the repo's scripts (indent=1, real unicode); a trailing newline only if the file had one."""
    nl = False
    try: nl = p.read_bytes().endswith(b'\n')
    except (FileNotFoundError, BadKey): pass
    write_atomic(p, json.dumps(obj, indent=indent, ensure_ascii=False) + ('\n' if nl else ''), history)


def read_json(p: SPath, default=None):
    try: return json.loads(p.read_text())
    except FileNotFoundError: return default
    except json.JSONDecodeError as e: raise HTTPException(500, f'{p.name} is not valid JSON: {e}')


def read_text(p: SPath, default=''):
    try: return p.read_text()
    except (FileNotFoundError, BadKey): return default


def sha1_file(p: SPath):
    return p.sha1()


def today():
    import time
    return time.strftime('%Y-%m-%d')


# ---------------- settings (app defaults; lives in the config dir, never in the web root) ----------------
LEGACY_SETTINGS = STUDIO / 'settings.json'
DEFAULT_SETTINGS = dict(
    handle='',
    signature='',
    hashtags='#AnimeComics #ChibiArt #FanArt',
    python=os.environ.get('STUDIO_SCRIPT_PYTHON') or sys.executable,
    downloads=str(Path.home() / 'Downloads'),
    export_dir=str(Path.home() / 'Desktop' / 'kawaii_exports'),
    chatgpt_url='https://chatgpt.com/',
    style_ref='style_ref.png',
    reel_seconds_per_panel=3.6,
    art_source=os.environ.get('STUDIO_ART_SOURCE', 'own'),   # 'chatgpt' (prompt + board) or 'own' (your own drawings)
)
LOCAL_ONLY = ('python', 'downloads', 'export_dir')      # server-filesystem settings: only with STUDIO_LOCAL_FEATURES
_settings_lock = threading.Lock()


def settings_file() -> Path:
    return CONFIG.config_dir / 'settings.json'


def get_settings():
    s = dict(DEFAULT_SETTINGS)
    for f in (LEGACY_SETTINGS, settings_file()):
        try: s.update(json.loads(f.read_text()))
        except (FileNotFoundError, json.JSONDecodeError, OSError): pass
    s = {k: v for k, v in s.items() if k in DEFAULT_SETTINGS}
    if not CONFIG.local_features:
        s['python'] = os.environ.get('STUDIO_SCRIPT_PYTHON') or sys.executable
    return s


def save_settings(new: dict):
    with _settings_lock:
        s = get_settings()
        for k, v in new.items():
            if k in DEFAULT_SETTINGS and (CONFIG.local_features or k not in LOCAL_ONLY): s[k] = v
        f = settings_file(); f.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=f.parent, prefix='.settings.', suffix='.tmp')
        with os.fdopen(fd, 'w') as fh: json.dump(s, fh, indent=1, ensure_ascii=False)
        os.chmod(tmp, 0o600); os.replace(tmp, f)
        return s


def script_python():
    env_py = os.environ.get('STUDIO_SCRIPT_PYTHON')
    if env_py and Path(env_py).exists(): return env_py
    p = get_settings().get('python') or sys.executable
    return p if Path(p).exists() else sys.executable


def script_env():
    keep = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR', 'TZ', 'USER', 'SHELL', 'PYTHONPATH', 'SYSTEMROOT')
    env = {k: v for k, v in os.environ.items() if k in keep}     # never hand storage/auth secrets to the scripts
    py = script_python()
    env['PY'] = py
    env['PATH'] = str(Path(py).parent) + os.pathsep + env.get('PATH', '/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin')
    for extra in ('/opt/homebrew/bin', '/usr/local/bin'):
        if extra not in env['PATH'].split(os.pathsep): env['PATH'] += os.pathsep + extra
    env['PYTHONUNBUFFERED'] = '1'
    return env


def first_line_title(syn: SPath, fallback: str):
    try: line = syn.read_text().split('\n', 1)[0]
    except (FileNotFoundError, BadKey): return fallback
    return line.lstrip('#').strip() or fallback


def font_file(path: str) -> Path:
    """'fonts/X.ttf' -> a local file: the uploaded font from storage, else the default font shipped with the code."""
    name = Path(path).name
    p = FONTS / name
    if p.is_file(): return p.local()
    q = CODE_FONTS / name
    if q.is_file(): return q
    raise FileNotFoundError(path)


def thumb_file(p: SPath, w: int = 240) -> Path:
    from PIL import Image
    ws = get_ws(); w = max(32, min(int(w), 2000))
    if isinstance(p, Path):                       # a local file outside the storage (Downloads import preview)
        st = p.stat(); src = p
        key = hashlib.sha1(f'{p}{st.st_mtime_ns}{st.st_size}{w}'.encode()).hexdigest()  # nosec B324 - cache key
    elif ws.remote:
        e = ws.stat(p.key)
        if not e: raise FileNotFoundError(p.key)
        key = hashlib.sha1(f'{p.key}{e.etag}{w}'.encode()).hexdigest()   # nosec B324 - cache key
    else:
        lp = p.local(); st = lp.stat()
        key = hashlib.sha1(f'{lp}{st.st_mtime_ns}{st.st_size}{w}'.encode()).hexdigest()  # nosec B324 - cache key (unchanged format)
    cache = CONFIG.cache_dir; cache.mkdir(parents=True, exist_ok=True); c = cache / f'{key}.jpg'
    if not c.exists():
        with Image.open(src if isinstance(p, Path) else p.local()) as im0:
            im0.draft('RGB', (w, w * 3))
            im = im0.convert('RGB'); im.thumbnail((w, w * 3))
            fd, tmp = tempfile.mkstemp(dir=cache, suffix='.jpg'); os.close(fd)
            im.save(tmp, 'JPEG', quality=82); os.replace(tmp, c)
    return c
