"""Strip-reel editor: panel boxes on strip.png (layout/layout_actual.json), the reel storyboard
(strip_reel/storyboard.json, rendered by scripts/render.py), preview stills and the build (render + encode for upload)."""
import copy, hashlib, io, json, threading, time
from collections import OrderedDict
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException
from .deps import authorize
from fastapi.responses import Response

from security import ratelimit
from security.context import min_role
from security.validation import check_storyboard, safe_rel
from storage import get_ws

from . import jobs
from .core import SCRIPTS, UPLOAD, backup, get_settings, piece_dir, read_json, script_python, write_atomic, write_json
from .library import invalidate
from .pieces import qa_gate, reel_status, reel_sync

router = APIRouter(dependencies=[Depends(authorize)])   # deny by default (api/deps.py)


def paths(pid):
    d = piece_dir('strip', pid)
    return d, d / 'strip_reel', d / 'layout' / 'layout_actual.json', d / 'strip_reel' / 'storyboard.json'


def boxes_of(layout):
    """quads -> [x0, y0, x1, y1] (0-1)"""
    out = []
    for poly in (layout or {}).get('panels', []):
        xs, ys = [q[0] for q in poly], [q[1] for q in poly]
        out.append([round(min(xs), 4), round(min(ys), 4), round(max(xs), 4), round(max(ys), 4)])
    return out


def rows_of(boxes):
    rows = []
    for b in sorted(boxes, key=lambda b: (b[1] + b[3]) / 2):
        cy = (b[1] + b[3]) / 2
        if rows and rows[-1][0][1] < cy < rows[-1][0][3]: rows[-1].append(b)
        else: rows.append([b])
    return [len(r) for r in rows]


@router.get('/api/reel/{pid}')
def get_reel(pid: str):
    d, rd, la, sb = paths(pid)
    strip = d / 'strip.png'
    size = None
    if strip.exists():
        from PIL import Image
        with Image.open(strip.local()) as im: size = list(im.size)
    src = 'actual' if la.exists() else ('wireframe' if (d / 'layout' / 'layout.json').exists() else None)
    layout = read_json(la) if la.exists() else read_json(d / 'layout' / 'layout.json')
    imgs = sorted(f.name for f in rd.glob('*.png')) if rd.is_dir() else []
    return dict(has_strip=strip.exists(), strip_size=size, strip_mtime=strip.stat().st_mtime if strip.exists() else None,
                boxes=boxes_of(layout), boxes_source=src, storyboard=read_json(sb) if sb.exists() else None,
                images=imgs, upload=reel_status(pid), per=get_settings().get('reel_seconds_per_panel', 3.6))


@router.post('/api/reel/{pid}/detect')
def detect(pid: str):
    d, rd, la, sb = paths(pid)
    if not (d / 'strip.png').exists(): raise HTTPException(409, 'Add the strip picture first.')
    backup(la)
    code, out = jobs.run_sync([script_python(), SCRIPTS / 'detect_panels.py', (d / 'strip.png').lpath, '--out', la.lpath], timeout=120,
                              sync=dict(pull=[(d / 'strip.png').key], push=[la.key], scope=d.key))
    if code: raise HTTPException(500, f'panel detection failed: {out[-500:]}')
    return dict(ok=True, log=out, boxes=boxes_of(read_json(la)))


@router.put('/api/reel/{pid}/boxes')
def save_boxes(pid: str, boxes: list[list[float]] = Body(..., embed=True)):
    d, rd, la, sb = paths(pid)
    clean = []
    for b in boxes:
        if len(b) != 4: raise HTTPException(400, 'each box is [x0, y0, x1, y1]')
        x0, y0, x1, y1 = [min(max(float(v), 0.0), 1.0) for v in b]
        if x1 - x0 < 0.03 or y1 - y0 < 0.03: raise HTTPException(400, 'a panel box is too small')
        clean.append([round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)])
    if not clean: raise HTTPException(400, 'at least one panel')
    panels = [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]] for x0, y0, x1, y1 in clean]
    write_json(la, {'rows': rows_of(clean), 'panels': panels})
    return dict(ok=True)


def crop_panels(d, rd, boxes):
    from PIL import Image
    with Image.open((d / 'strip.png').local()) as im0: im = im0.convert('RGB')
    W, H = im.size
    get_ws().copy((d / 'strip.png').key, (rd / 'strip.png').key)
    aspects = []
    for k, (x0, y0, x1, y1) in enumerate(boxes):
        box = (max(int(x0 * W), 0), max(int(y0 * H), 0), min(int(x1 * W), W), min(int(y1 * H), H))
        buf = io.BytesIO(); im.crop(box).save(buf, 'PNG'); write_atomic(rd / f'panel{k + 1}.png', buf.getvalue(), history=False)
        aspects.append((box[2] - box[0]) / max(1, box[3] - box[1]))
    for f in list(rd.glob('panel*.png')):
        try: n = int(f.stem[5:])
        except ValueError: continue
        if n > len(boxes): f.unlink()
    return aspects


@router.post('/api/reel/{pid}/storyboard')
def make_storyboard(pid: str, per: float = Body(3.6), keep_timing: bool = Body(False)):
    """Fresh storyboard from the panel boxes (scripts/strip_reel.py --silent, the same defaults build_reel.sh uses)."""
    d, rd, la, sb = paths(pid)
    if not (d / 'strip.png').exists(): raise HTTPException(409, 'Add the strip picture first.')
    per = max(1.0, min(float(per), 10.0))
    if not la.exists():
        code, out = jobs.run_sync([script_python(), SCRIPTS / 'detect_panels.py', (d / 'strip.png').lpath, '--out', la.lpath], timeout=120,
                                  sync=dict(pull=[(d / 'strip.png').key], push=[la.key], scope=d.key))
        if code: raise HTTPException(500, f'panel detection failed: {out[-500:]}')
    old = read_json(sb) if sb.exists() else None
    backup(sb)
    for f in list(rd.glob('panel*.png')) if rd.is_dir() else []: f.unlink()
    code, out = jobs.run_sync([script_python(), SCRIPTS / 'strip_reel.py', (d / 'strip.png').lpath, rd.lpath, '--layout', la.lpath, '--silent', '--per', str(per)],
                              timeout=120, sync=dict(pull=[(d / 'strip.png').key, la.key], push=[f'{rd.key}/**'], exclude=[f'{rd.key}/*.mp4'], scope=d.key))
    if code: raise HTTPException(500, f'storyboard failed: {out[-500:]}')
    invalidate()
    return dict(ok=True, log=out, storyboard=read_json(sb), previous=bool(old))


@router.post('/api/reel/{pid}/recrop')
def recrop(pid: str):
    """Re-cut the panel pictures from the saved boxes and update each card's aspect; keeps your timing/camera edits."""
    d, rd, la, sb = paths(pid)
    boxes = boxes_of(read_json(la))
    if not boxes: raise HTTPException(409, 'Save the panel boxes first.')
    s = read_json(sb)
    if not s: return make_storyboard(pid)
    panel_shots = [x for x in s['shots'] if str(x.get('image', '')).startswith('panel')]
    if len(panel_shots) != len(boxes):
        return make_storyboard(pid)
    aspects = crop_panels(d, rd, boxes)
    for x in panel_shots:
        try: k = int(Path(x['image']).stem[5:]) - 1
        except ValueError: continue
        if 0 <= k < len(aspects) and x.get('card'):
            a = aspects[k]; wide = any(c.get('x') in (0.0, 1.0) for c in x.get('camera', []))
            x['card']['aspect'] = round(max(a / 1.9, 1.0) if wide and a > 1.3 else a, 3)
    write_json(sb, s); invalidate()
    return dict(ok=True, storyboard=s)


@router.put('/api/reel/{pid}/storyboard')
def save_storyboard(pid: str, storyboard: dict = Body(..., embed=True)):
    d, rd, la, sb = paths(pid)
    if not isinstance(storyboard.get('shots'), list) or not storyboard['shots']: raise HTTPException(400, 'storyboard needs shots')
    check_storyboard(storyboard)
    for s in storyboard['shots']:
        if not (rd / safe_rel(str(s.get('image', '')), 'picture')).is_file(): raise HTTPException(400, f"missing picture {s.get('image')} — rebuild the storyboard")
        if s['end'] <= s['start']: raise HTTPException(400, f"shot {s.get('id')} has no length")
    write_json(sb, storyboard); invalidate()
    return dict(ok=True, saved=time.time())


# ---------------- preview stills (scripts/render.py Renderer, half size) ----------------
_R: 'OrderedDict[str, object]' = OrderedDict(); _lock = threading.Lock()


def renderer(rd, sb: dict, scale: float):
    import render as RD  # scripts/render.py
    check_storyboard(sb)
    get_ws().pull([f'{rd.key}/**'], exclude=[f'{rd.key}/*.mp4'])
    mt = [(rd / s['image']).stat().st_mtime_ns for s in sb['shots'] if (rd / s['image']).exists()]
    key = hashlib.sha1((str(rd) + json.dumps(sb, sort_keys=True) + str(scale) + str(mt)).encode(), usedforsecurity=False).hexdigest()
    with _lock:
        if key in _R: _R.move_to_end(key); return _R[key]
    s = copy.deepcopy(sb); o = s.setdefault('output', {})
    o['width'] = int(round(o.get('width', 1080) * scale / 2) * 2); o['height'] = int(round(o.get('height', 1920) * scale / 2) * 2)
    for sh in s['shots']:
        c = sh.get('card')
        if c:
            c['border'] = max(1, int(round(c.get('border', 10) * scale))); c['radius'] = max(2, int(round(c.get('radius', 34) * scale)))
    for e in s.get('events', []):
        if e.get('type') == 'shake': e['amp'] = e.get('amp', 10) * scale
    R = RD.Renderer(s, str(rd.lpath))
    with _lock:
        _R[key] = R
        while len(_R) > 3: _R.popitem(last=False)
    return R


@router.post('/api/reel/{pid}/still')
@min_role('viewer')
def still(pid: str, storyboard: dict = Body(...), t: float = Body(0.0), scale: float = Body(0.4)):
    import cv2
    ratelimit.hit(ratelimit.user_key('still'), 60, 20, 'preview frames')
    d, rd, la, sb = paths(pid)
    try: R = renderer(rd, storyboard, max(0.2, min(scale, 1.0)))
    except Exception as e: raise HTTPException(400, f'cannot build the preview: {e}')
    t = max(0.0, min(t, R.D - 1e-3))
    f = R.finish(R.render(t), t, int(t * R.FPS))
    ok, buf = cv2.imencode('.jpg', f, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return Response(buf.tobytes(), media_type='image/jpeg')


@router.post('/api/reel/{pid}/build')
def build(pid: str, storyboard: dict | None = Body(None, embed=True)):
    """Render the (edited) storyboard and make the upload copies — the same encode as scripts/build_reel.sh."""
    d, rd, la, sb = paths(pid)
    qa_gate(d)
    if storyboard: save_storyboard(pid, storyboard)
    if not sb.exists(): raise HTTPException(409, 'Make the storyboard first.')
    cur = read_json(sb); check_storyboard(cur)
    out_name = (cur.get('output') or {}).get('file', 'strip_reel.mp4')
    py = script_python(); get_ws().mkdir(UPLOAD.key)
    steps = [dict(cmd=[py, SCRIPTS / 'render.py', sb.lpath], label='Rendering frames', weight=8),
             dict(cmd=['ffmpeg', '-v', 'error', '-y', '-i', (rd / out_name).lpath, '-c:v', 'libx264', '-preset', 'slow', '-crf', '20', '-pix_fmt', 'yuv420p',
                       '-movflags', '+faststart', '-c:a', 'aac', '-b:a', '128k', (UPLOAD / f'{pid}_strip_reel.mp4').lpath], label='Encoding for Instagram'),
             dict(cmd=['cp', (d / 'strip.png').lpath, (UPLOAD / f'{pid}_strip.png').lpath], label='Copying the strip picture')]
    job = jobs.start_steps('reel', f'Build strip reel ({pid})', steps, ref=f'strip/{pid}',
                           on_done=lambda j: (invalidate(), reel_status(pid))[1], sync=reel_sync(pid))
    return jobs.public(job)
