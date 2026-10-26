"""Input validation: upload file types by magic bytes, file-name sanitising, image bomb guard, and checks for the
user-editable render documents (lyric_edit*.json, strip_reel/storyboard.json) so they cannot point the renderers at
files outside the project, use ffmpeg protocols, or ask for absurd render sizes."""
from __future__ import annotations

import io
import re
import unicodedata
import warnings
from pathlib import PurePosixPath

from fastapi import HTTPException

IMG_EXT = {'.png', '.jpg', '.jpeg', '.webp'}
AUDIO_EXT = {'.mp3', '.m4a', '.wav', '.aac', '.ogg', '.flac'}
FONT_EXT = {'.ttf', '.otf', '.ttc'}


def init_image_guard(max_pixels: int):
    """Pillow: refuse decompression bombs instead of only warning."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = max_pixels
    warnings.simplefilter('error', Image.DecompressionBombWarning)


def sanitize_filename(name: str, default: str = 'upload') -> str:
    """Keep the basename, ASCII letters/digits/._- only, no leading dots/dashes, max 120 chars."""
    n = unicodedata.normalize('NFKD', PurePosixPath((name or '').replace('\\', '/')).name)
    n = re.sub(r'[^A-Za-z0-9._\-]+', '_', n).strip('._-')
    n = re.sub(r'\.{2,}', '.', n)
    if len(n) > 120:
        stem, dot, ext = n.rpartition('.')
        n = (stem[:110] + '.' + ext[:8]) if dot else n[:120]
    return n or default


def sniff(data: bytes) -> str | None:
    """File type from magic bytes."""
    h = data[:64]
    if h.startswith(b'\x89PNG\r\n\x1a\n'): return 'png'
    if h.startswith(b'\xff\xd8\xff'): return 'jpg'
    if h[:4] == b'RIFF' and h[8:12] == b'WEBP': return 'webp'
    if h[:4] == b'RIFF' and h[8:12] == b'WAVE': return 'wav'
    if h.startswith(b'ID3') or (len(h) > 1 and h[0] == 0xFF and (h[1] & 0xE0) == 0xE0 and (h[1] & 0x06) != 0): return 'mp3'
    if h.startswith(b'fLaC'): return 'flac'
    if h.startswith(b'OggS'): return 'ogg'
    if h[4:8] == b'ftyp': return 'mp4'                 # m4a / mp4 / mov family
    if len(h) > 1 and h[0] == 0xFF and (h[1] & 0xF6) == 0xF0: return 'aac'   # ADTS
    if h[:4] in (b'\x00\x01\x00\x00', b'OTTO', b'true', b'typ1'): return 'font'
    if h[:4] == b'ttcf': return 'font'
    return None


EXPECT = {'.png': {'png'}, '.jpg': {'jpg'}, '.jpeg': {'jpg'}, '.webp': {'webp'}, '.wav': {'wav'}, '.mp3': {'mp3'},
          '.flac': {'flac'}, '.ogg': {'ogg'}, '.m4a': {'mp4'}, '.aac': {'aac', 'mp4'}, '.ttf': {'font'}, '.otf': {'font'},
          '.ttc': {'font'}}


def check_upload(name: str, data: bytes, allowed: set[str]) -> str:
    """Validates extension + content; returns the sanitised file name. Images are also opened (bomb guard)."""
    fn = sanitize_filename(name)
    ext = PurePosixPath(fn).suffix.lower()
    if ext not in allowed: raise HTTPException(400, f'Files of type "{ext or "?"}" cannot be added here.')
    if not data: raise HTTPException(400, 'The file is empty.')
    kind = sniff(data)
    if kind not in EXPECT.get(ext, set()):
        raise HTTPException(400, f'The file content does not look like a {ext} file.')
    if ext in IMG_EXT:
        from PIL import Image
        try:
            with Image.open(io.BytesIO(data)) as im:
                w, h = im.size
                if w * h > Image.MAX_IMAGE_PIXELS or w > 20000 or h > 20000: raise HTTPException(400, 'That picture is too large.')
                im.verify()
        except HTTPException: raise
        except Exception: raise HTTPException(400, 'That picture cannot be read (damaged or too large).')
    return fn


# ---------------- render documents ----------------
SAFE_REL = re.compile(r'^(?!/)(?!.*(?:^|/)\.\.?(?:/|$))[A-Za-z0-9 _.\-/()+,&@#\'\[\]]{1,200}$')
PATH_KEYS = {'image', 'asset', 'audio', 'file', 'output', 'sfx', 'music', 'path', 'src', 'song', 'mask', 'background', 'bg'}


def safe_rel(v, what='path') -> str:
    if not isinstance(v, str) or not SAFE_REL.match(v) or ':' in v or '\\' in v or '\x00' in v:
        raise HTTPException(400, f'Bad {what}: {str(v)[:80]!r} (use a file inside this project)')
    return v


def _walk_paths(obj, where='', depth=0):
    if depth > 12: raise HTTPException(400, 'document is nested too deeply')
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in PATH_KEYS and isinstance(v, str) and v: safe_rel(v, f'{k} in {where or "document"}')
            elif k == 'fonts' and isinstance(v, dict):
                for fk, fv in v.items():
                    if fv and (not isinstance(fv, str) or not re.fullmatch(r'fonts/[A-Za-z0-9._\-]{1,120}\.(ttf|otf|ttc)', fv)):
                        raise HTTPException(400, f'Font for "{fk}" must be one of the fonts in fonts/ (e.g. fonts/Baloo2.ttf).')
            else: _walk_paths(v, k, depth + 1)
    elif isinstance(obj, list):
        if len(obj) > 5000: raise HTTPException(400, 'document has too many entries')
        for v in obj: _walk_paths(v, where, depth + 1)


def _num(v, lo, hi, what):
    if v is None: return
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not (lo <= v <= hi): raise HTTPException(400, f'{what} must be between {lo} and {hi}')


def check_lyric_edit(edit: dict):
    if not isinstance(edit, dict): raise HTTPException(400, 'edit must be an object')
    _walk_paths(edit)
    if edit.get('output'):
        if not re.fullmatch(r'[A-Za-z0-9_\-]{1,80}\.mp4', str(edit['output'])): raise HTTPException(400, 'output must be a file name like lyric_edit.mp4')
    size = edit.get('size')
    if size is not None:
        if not (isinstance(size, list) and len(size) == 2): raise HTTPException(400, 'size must be [width, height]')
        _num(size[0], 64, 2160, 'width'); _num(size[1], 64, 3840, 'height')
    _num(edit.get('fps'), 1, 60, 'fps')
    st = edit.get('start', 0) or 0; en = edit.get('end')
    _num(st, 0, 24 * 3600, 'start')
    lines = edit.get('lines') or []
    if not isinstance(lines, list) or len(lines) > 2000: raise HTTPException(400, 'too many lines')
    last = max([float(l.get('end', 0) or 0) for l in lines if isinstance(l, dict)] + [float(en or 0)])
    if last - float(st) > 900: raise HTTPException(400, 'An edit can be at most 15 minutes long.')


def check_storyboard(sb: dict):
    if not isinstance(sb, dict): raise HTTPException(400, 'storyboard must be an object')
    _walk_paths(sb)
    o = sb.get('output') or {}
    if not isinstance(o, dict): raise HTTPException(400, 'output must be an object')
    if o.get('file') is not None and not re.fullmatch(r'[A-Za-z0-9_\-]{1,80}\.mp4', str(o['file'])):
        raise HTTPException(400, 'output.file must be a file name like strip_reel.mp4')
    _num(o.get('width'), 64, 2160, 'width'); _num(o.get('height'), 64, 3840, 'height'); _num(o.get('fps'), 1, 60, 'fps')
    _num(o.get('duration'), 0, 300, 'duration')
    shots = sb.get('shots') or []
    if not isinstance(shots, list) or len(shots) > 200: raise HTTPException(400, 'too many shots')
    for s in shots:
        if not isinstance(s, dict): raise HTTPException(400, 'bad shot')
        _num(s.get('start'), 0, 300, 'shot start'); _num(s.get('end'), 0, 300, 'shot end')
