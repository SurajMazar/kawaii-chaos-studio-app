#!/usr/bin/env python3
"""Render a storyboard.json into a finished vertical video (motion-comic style).

Usage:
  python render.py storyboard.json                 # full render -> output.file
  python render.py storyboard.json --stills 0.5 3  # write still_XX.XX.jpg for review
  python render.py storyboard.json --no-audio      # video only

All paths in the storyboard are relative to the storyboard file.
See references/storyboard-schema.md for the format.
"""
import argparse, json, math, os, subprocess, sys
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audio as AUD  # noqa: E402

# ------------------------------------------------------------------ easing
def c01(x): return max(0.0, min(1.0, x))
def e_linear(x): return c01(x)
def e_inout(x): x = c01(x); return x * x * (3 - 2 * x)
def e_out(x): x = c01(x); return 1 - (1 - x) ** 3
def e_in(x): x = c01(x); return x ** 3
def e_back(x, s=1.9): x = c01(x) - 1; return x * x * ((s + 1) * x + s) + 1
EASE = {'linear': e_linear, 'inout': e_inout, 'out': e_out, 'in': e_in, 'back': e_back}
def lerp(a, b, t): return a + (b - a) * t


# ------------------------------------------------------------------ transitions between shots
# transition_in: {"type": ..., "dur": s, "dir": "left|right|up|down"}  ("dir" = the way the incoming shot / page moves)
TRANSITIONS = ('dissolve', 'dip', 'slide', 'push', 'drop', 'wipe', 'zoom', 'iris', 'pagefold')


def _warp(img, M, W, H, persp=False):
    f = cv2.warpPerspective if persp else cv2.warpAffine
    return f(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def _over(base, top, mask):
    m = mask[..., None].astype(np.float32)
    return base * (1 - m) + top * m


def transition(prev, cur, p, tr):
    """Blend two full frames; p goes 0 -> 1 across the transition window."""
    H, W = cur.shape[:2]; k = tr.get('type'); d = tr.get('dir', 'left'); e = e_inout(p)
    if k == 'dissolve':
        return prev * (1 - e) + cur * e
    if k == 'dip':
        return prev * c01(1 - 2 * e) if e < .5 else cur * c01(2 * e - 1)
    if k in ('slide', 'push'):
        e = e_out(p)   # fast start, gentle landing — like a photo slid across a table
        dx, dy = {'left': (-1, 0), 'right': (1, 0), 'up': (0, -1), 'down': (0, 1)}[d]
        ox, oy = -dx * (1 - e) * W, -dy * (1 - e) * H        # where the incoming shot is now
        out = prev.copy()
        if k == 'push': out = _warp(prev, np.float32([[1, 0, ox + dx * W], [0, 1, oy + dy * H]]), W, H)
        M = np.float32([[1, 0, ox], [0, 1, oy]])
        mask = _warp(np.ones((H, W), np.float32), M, W, H)
        if k == 'slide':   # soft contact shadow under the incoming photo
            sh = cv2.GaussianBlur(_warp(np.ones((H, W), np.float32), np.float32([[1, 0, ox + 10], [0, 1, oy + 10]]), W, H), (0, 0), 14)
            out = out * (1 - .28 * sh[..., None] * (1 - mask[..., None]))
        return _over(out, _warp(cur, M, W, H), mask)
    if k == 'drop':   # a new polaroid falls in from the top, slightly tilted, and settles
        e2 = e_back(p, 1.2); ang = -7 * (1 - e_out(p)); oy = -(1 - e2) * H
        M = cv2.getRotationMatrix2D((W / 2, H / 2), ang, 1.0); M[1, 2] += oy
        mask = _warp(np.ones((H, W), np.float32), M, W, H)
        sh = cv2.GaussianBlur(mask, (0, 0), 18)
        base = prev * (1 - .3 * sh[..., None] * (1 - mask[..., None]))
        return _over(base, _warp(cur, M, W, H), mask)
    if k == 'wipe':   # soft-edged reveal sweeping across
        soft = .12; x = np.linspace(0, 1, W if d in ('left', 'right') else H, dtype=np.float32)
        if d in ('right', 'down'): x = 1 - x
        g = np.clip((e * (1 + soft) - (1 - x)) / soft, 0, 1)
        mask = np.repeat(g[None, :], H, 0) if d in ('left', 'right') else np.repeat(g[:, None], W, 1)
        return _over(prev, cur, mask)
    if k == 'zoom':   # the next photo grows out of the centre while the old one gently pushes in
        sc = lerp(.35, 1.0, e_out(p)); M = cv2.getRotationMatrix2D((W / 2, H / 2), 0, sc)
        mask = _warp(np.ones((H, W), np.float32), M, W, H)
        P2 = cv2.getRotationMatrix2D((W / 2, H / 2), 0, 1 + .08 * e)
        return _over(_warp(prev, P2, W, H), _warp(cur, M, W, H), mask)
    if k == 'iris':   # soft circle opening from the centre
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32); r = np.hypot(xx - W / 2, yy - H / 2) / math.hypot(W / 2, H / 2)
        mask = np.clip((e * 1.15 - r) / .15, 0, 1)
        return _over(prev, cur, mask)
    if k == 'pagefold':   # the old picture turns away like a page on a hinge, revealing the next one underneath
        if d == 'right': return transition(prev[:, ::-1], cur[:, ::-1], p, dict(tr, dir='left'))[:, ::-1]
        a = e * math.pi / 2; w = max(1.0, W * math.cos(a)); lift = H * .08 * math.sin(2 * a)
        src = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
        dst = np.float32([[0, 0], [w, -lift], [w, H + lift], [0, H]])
        M = cv2.getPerspectiveTransform(src, dst)
        page = _warp(prev, M, W, H, True); mask = _warp(np.ones((H, W), np.float32), M, W, H, True)
        shade = np.clip(1 - .45 * e * (np.arange(W, dtype=np.float32) / max(w, 1)), .45, 1)[None, :, None]
        page = page * shade
        xs = np.arange(W, dtype=np.float32); cast = np.clip(1 - (xs - w) / (60 + 120 * e), 0, 1) * (xs >= w) * .35 * (1 - e)
        base = cur * (1 - cast[None, :, None])
        return _over(base, page, mask)
    return cur

# ------------------------------------------------------------------ io helpers
def load_rgb(path):
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im is None: sys.exit(f'cannot read image: {path}')
    if im.ndim == 2: im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
    if im.shape[2] == 4: im = im[:, :, :3]
    return im

def load_asset(path):
    """Return premultiplied BGRA float32. PNG alpha is used if present, else a
    green (#00FF00) or near-uniform-corner background is keyed out."""
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im is None: sys.exit(f'cannot read asset: {path}')
    if im.ndim == 2: im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
    if im.shape[2] == 4 and im[:, :, 3].min() < 250:
        rgb = im[:, :, :3].astype(np.float32); a = im[:, :, 3].astype(np.float32) / 255.
    else:
        rgb = im[:, :, :3].astype(np.float32)
        corners = np.concatenate([rgb[:8, :8].reshape(-1, 3), rgb[:8, -8:].reshape(-1, 3),
                                  rgb[-8:, :8].reshape(-1, 3), rgb[-8:, -8:].reshape(-1, 3)])
        key = np.median(corners, 0)
        d = np.linalg.norm(rgb - key, axis=2)
        a = np.clip((d - 40) / 60, 0, 1)
        if key[1] > key[0] + 60 and key[1] > key[2] + 60:  # green screen: despill
            g = rgb[:, :, 1]; lim = np.maximum(rgb[:, :, 0], rgb[:, :, 2])
            rgb[:, :, 1] = np.minimum(g, lim + 10)
        a = cv2.GaussianBlur(a.astype(np.float32), (0, 0), 0.8)
    ys, xs = np.where(a > 0.02)
    if len(ys):  # trim empty borders
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        rgb, a = rgb[y0:y1, x0:x1], a[y0:y1, x0:x1]
    return np.dstack([rgb * a[..., None], a]).astype(np.float32)

def composite(frame, prem, A):
    oh, ow = frame.shape[:2]
    w = cv2.warpAffine(prem, A, (ow, oh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    frame *= (1 - w[:, :, 3:4]); frame += w[:, :, :3]
    return frame

def rounded_mask(w, h, r):
    m = np.zeros((h, w), np.uint8); r = int(max(1, min(r, w // 2, h // 2)))
    cv2.rectangle(m, (r, 0), (w - r, h), 255, -1); cv2.rectangle(m, (0, r), (w, h - r), 255, -1)
    for cx, cy in [(r, r), (w - r, r), (r, h - r), (w - r, h - r)]: cv2.circle(m, (cx, cy), r, 255, -1, cv2.LINE_AA)
    return m.astype(np.float32) / 255.

# ------------------------------------------------------------------ renderer
class Renderer:
    def __init__(self, sb, base):
        self.sb, self.base = sb, base
        o = sb.get('output', {})
        self.W, self.H = o.get('width', 1080), o.get('height', 1920)
        self.FPS = o.get('fps', 30)
        self.shots = sorted(sb['shots'], key=lambda s: s['start'])
        self.D = o.get('duration') or max(s['end'] for s in self.shots)
        self.events = sb.get('events', [])
        self.imgs, self.assets, self.bgs = {}, {}, {}
        for s in self.shots:
            p = os.path.join(base, s['image'])
            if p not in self.imgs: self.imgs[p] = load_rgb(p)
            s['_img'] = p
            for ov in s.get('overlays', []):
                ap = os.path.join(base, ov['asset'])
                if ap not in self.assets: self.assets[ap] = load_asset(ap)
                ov['_a'] = ap
        g = sb.get('grade', {})
        self.grade = dict(warmth=g.get('warmth', 0.03), contrast=g.get('contrast', 1.04),
                          vignette=g.get('vignette', 0.25), grain=g.get('grain', 3.0))
        W, H = self.W, self.H
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W * .62)) ** 2 + ((yy - H / 2) / (H * .62)) ** 2)
        self.vig = (1 - self.grade['vignette'] * np.clip(r - .35, 0, 1) ** 1.6)[..., None].astype(np.float32)
        rng = np.random.default_rng(3)
        self.grain = [cv2.resize(cv2.GaussianBlur(rng.normal(0, 1, (H // 2, W // 2)).astype(np.float32), (0, 0), .6), (W, H))[..., None] for _ in range(6)]
        self._warn_resolution()

    # ---------------- helpers
    def _warn_resolution(self):
        for s in self.shots:
            ih, iw = self.imgs[s['_img']].shape[:2]
            zmax = max([k.get('zoom', 1.0) for k in s.get('camera', [{}])] + [1.0])
            ow, oh, asp = self.view_size(s)
            vh = self.base_view_h(iw, ih, asp) / zmax
            if oh / vh > 1.8:
                print(f"[warn] shot {s.get('id')}: image is upscaled {oh / vh:.1f}x at max zoom -> consider scripts/upscale.py", file=sys.stderr)

    def view_size(self, s):
        if s.get('mode', 'full') == 'card':
            c = s.get('card', {}); ih, iw = self.imgs[s['_img']].shape[:2]
            asp = c.get('aspect', min(max(iw / ih, 0.56), 1.6))
            cw = int(self.W * c.get('width', 0.9)); ch = int(cw / asp)
            ch = min(ch, int(self.H * 0.8)); cw = int(ch * asp)
            return cw, ch, cw / ch
        return self.W, self.H, self.W / self.H

    @staticmethod
    def base_view_h(iw, ih, asp):
        return ih if iw / ih > asp else iw / asp

    def shake(self, t):
        dx = dy = 0.0
        for e in self.events:
            if e.get('type') != 'shake': continue
            te, amp, dec = e['t'], e.get('amp', 10), e.get('decay', 0.11)
            dur = e.get('dur')
            if dur:  # sustained buzz (e.g. phone vibrating)
                if te <= t < te + dur:
                    dx += amp * math.sin(2 * math.pi * 9 * (t - te)); dy += amp * .7 * math.sin(2 * math.pi * 7 * (t - te) + 1)
            elif te <= t < te + 6 * dec:
                k = amp * math.exp(-(t - te) / dec)
                dx += k * math.sin(2 * math.pi * 8 * (t - te)); dy += k * math.sin(2 * math.pi * 6.5 * (t - te) + 1.2)
        return dx, dy

    def flash(self, t):
        v = 0.0
        for e in self.events:
            if e.get('type') == 'flash' and e['t'] <= t < e['t'] + e.get('dur', .16):
                v = max(v, e.get('strength', .5) * (1 - (t - e['t']) / e.get('dur', .16)) ** 2)
        return v

    def cam_at(self, s, lt):
        keys = s.get('camera') or [{'t': 0}]
        full, cur = [], {'x': .5, 'y': .5, 'zoom': 1.0, 'rot': 0.0}
        for k in keys:
            cur = {**cur, **{kk: v for kk, v in k.items() if kk in ('x', 'y', 'zoom', 'rot')}}
            full.append((k.get('t', 0), dict(cur), k.get('ease', s.get('ease', 'inout'))))
        if lt <= full[0][0]: return full[0][1]
        for (t0, v0, _), (t1, v1, ez) in zip(full, full[1:]):
            if lt <= t1:
                e = EASE[ez]((lt - t0) / max(t1 - t0, 1e-6))
                return {k: lerp(v0[k], v1[k], e) for k in v0}
        return full[-1][1]

    def cam_matrix(self, s, t, ow, oh, asp, shake=True):
        img = self.imgs[s['_img']]; ih, iw = img.shape[:2]
        c = self.cam_at(s, t - s['start'])
        rot = math.radians(c['rot'])
        vh = self.base_view_h(iw, ih, asp) / max(c['zoom'], 1e-3)
        pad = 0.004 * ih + (6 if shake else 0) * vh / oh
        # shrink until the rotated view fits inside the image (never show outside the art)
        ca, sa = abs(math.cos(rot)), abs(math.sin(rot))
        while True:
            bw, bh = vh * asp * ca + vh * sa, vh * asp * sa + vh * ca
            if bw <= iw - 2 * pad and bh <= ih - 2 * pad: break
            vh *= 0.995
        cx = min(max(c['x'] * iw, pad + bw / 2), iw - pad - bw / 2)
        cy = min(max(c['y'] * ih, pad + bh / 2), ih - pad - bh / 2)
        dx, dy = self.shake(t) if shake else (0, 0)
        sc = vh / oh; co, si = math.cos(rot), math.sin(rot)
        ox, oy = ow / 2 - dx, oh / 2 - dy
        return np.array([[sc * co, -sc * si, cx - sc * (co * ox - si * oy)],
                         [sc * si, sc * co, cy - sc * (si * ox + co * oy)]], np.float32)

    def overlay(self, frame, s, ov, t, Ainv_img):
        """Ainv_img: 3x3 mapping image px -> frame px (for space='image')."""
        t0 = ov['t']
        if t < t0: return frame
        p = self.assets[ov['_a']]; sh, sw = p.shape[:2]
        anim = ov.get('anim', 'pop'); dt = t - t0
        scale, alpha, rot, oy = 1.0, 1.0, ov.get('rot', 0.0), 0.0
        if anim == 'pop':
            e = dt / .32; scale = lerp(.2, 1, e_back(e, 2.2)); alpha = c01(dt / .08); rot += lerp(-4, 0, e_out(e))
        elif anim == 'stamp':
            e = dt / .22; scale = lerp(1.6, 1, e_back(e, 1.6)); alpha = c01(dt / .05); rot += lerp(ov.get('stamp_rot', 7), 0, e_out(e))
        elif anim == 'fade':
            alpha = c01(dt / .25)
        elif anim == 'slide_up':
            e = e_out(dt / .35); oy = lerp(90, 0, e); alpha = c01(dt / .2)
        elif anim == 'grow':
            e = dt / .3; scale = lerp(.55, 1, e_back(e)); alpha = c01(dt / .1)
        if ov.get('pulse'): scale *= 1 + .035 * math.sin(2 * math.pi * 2.2 * dt)
        if ov.get('float', ov.get('space', 'screen') == 'screen'): oy += 5 * math.sin(2 * math.pi * .7 * dt)
        out = ov.get('out')
        if out is not None and t >= out:
            k = (t - out) / .14
            if k >= 1: return frame
            if ov.get('out_anim', 'shrink') == 'shrink': scale *= 1 - e_in(k)
            else: alpha *= 1 - k
        if alpha <= .001 or scale <= .001: return frame
        ax, ay = [v * d for v, d in zip(ov.get('anchor', [.5, .5]), (sw, sh))]
        if ov.get('space', 'screen') == 'image':
            ih, iw = self.imgs[s['_img']].shape[:2]
            k = ov['w'] * iw / sw; px, py = ov['x'] * iw, ov['y'] * ih
        else:
            ow, oh = frame.shape[1], frame.shape[0]
            k = ov['w'] * ow / sw; px, py = ov['x'] * ow, ov['y'] * oh
        r = math.radians(rot); co, si = math.cos(r) * scale * k, math.sin(r) * scale * k
        tx, ty = px + ax * k, py + ay * k + oy
        T = np.array([[co, -si, tx - co * ax + si * ay], [si, co, ty - si * ax - co * ay], [0, 0, 1]])
        if ov.get('space', 'screen') == 'image': T = Ainv_img @ T
        if ov.get('shadow', ov.get('space', 'screen') == 'screen'):
            spr = p.copy(); spr[:, :, :3] = 0; spr *= .28 * alpha
            Ts = T.copy(); Ts[0, 2] += 8; Ts[1, 2] += 14
            frame = composite(frame, cv2.GaussianBlur(spr, (0, 0), max(1, 6 / max(k * scale, .05))), Ts[:2].astype(np.float32))
        return composite(frame, p * alpha, T[:2].astype(np.float32))

    def bg_for(self, s, t):
        key = s['_img']
        if key not in self.bgs:
            img = self.imgs[key]; ih, iw = img.shape[:2]; asp = self.W / self.H
            if iw / ih > asp: nw = int(ih * asp); crop = img[:, (iw - nw) // 2:(iw - nw) // 2 + nw]
            else: nh = int(iw / asp); crop = img[(ih - nh) // 2:(ih - nh) // 2 + nh]
            sm = cv2.GaussianBlur(cv2.resize(crop, (self.W // 6, self.H // 6), interpolation=cv2.INTER_AREA), (0, 0), 5)
            big = cv2.resize(sm, (int(self.W * 1.15), int(self.H * 1.15)), interpolation=cv2.INTER_CUBIC).astype(np.float32)
            dark = s.get('card', {}).get('bg_dark', .42)
            self.bgs[key] = big * dark + np.array([20, 28, 40], np.float32) * (1 - dark) * .5
        bg = self.bgs[key]; bh, bw = bg.shape[:2]
        z = lerp(1, 1.06, c01((t - s['start']) / max(s['end'] - s['start'], .1)))
        A = np.array([[z, 0, self.W / 2 - z * bw / 2], [0, z, self.H / 2 - z * bh / 2]], np.float32)
        return cv2.warpAffine(bg, A, (self.W, self.H), borderMode=cv2.BORDER_REFLECT)

    def place_card(self, frame, content, t, s):
        c = s.get('card', {}); border, radius = c.get('border', 10), c.get('radius', 34)
        col = c.get('border_color', [242, 228, 205])[::-1]
        ch, cw = content.shape[:2]; bw, bh = cw + 2 * border, ch + 2 * border
        full = np.zeros((bh, bw, 3), np.float32); full[:] = col
        inner = np.zeros((bh, bw), np.float32); inner[border:border + ch, border:border + cw] = rounded_mask(cw, ch, max(4, radius - border))
        pad = np.zeros_like(full); pad[border:border + ch, border:border + cw] = content
        full = pad * inner[..., None] + full * (1 - inner[..., None])
        m = rounded_mask(bw, bh, radius)
        lt = t - s['start']; intro = c.get('intro', False)
        scale = lerp(1.12, 1, e_out(lt / .6)) if intro else 1.0
        alpha = c01(lt / .25) if intro else 1.0
        dx, dy = self.shake(t)
        cx, cy = self.W / 2 + dx * .6, self.H * c.get('y', .5) + dy * .6
        prem = np.dstack([full * m[..., None], m]) * alpha
        shs = np.zeros((bh // 4, bw // 4, 4), np.float32); shs[:, :, 3] = cv2.resize(m, (bw // 4, bh // 4)) * .55 * alpha
        shs = cv2.GaussianBlur(cv2.copyMakeBorder(shs, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=0), (0, 0), 7)
        As = np.array([[scale * 4, 0, cx - scale * bw / 2 - scale * 80], [0, scale * 4, cy - scale * bh / 2 + 26 - scale * 80]], np.float32)
        frame = composite(frame, shs, As)
        A = np.array([[scale, 0, cx - scale * bw / 2], [0, scale, cy - scale * bh / 2]], np.float32)
        return composite(frame, prem, A)

    def render_shot(self, s, t):
        img = self.imgs[s['_img']]
        ow, oh, asp = self.view_size(s)
        card = s.get('mode', 'full') == 'card'
        A = self.cam_matrix(s, t, ow, oh, asp, shake=not card)
        f = cv2.warpAffine(img, A, (ow, oh), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REFLECT).astype(np.float32)
        Ainv = np.linalg.inv(np.vstack([A, [0, 0, 1]]))  # image px -> view px
        for ov in s.get('overlays', []):
            if ov.get('space', 'screen') == 'image': f = self.overlay(f, s, ov, t, Ainv)
        if card: f = self.place_card(self.bg_for(s, t), f, t, s)
        for ov in s.get('overlays', []):
            if ov.get('space', 'screen') == 'screen': f = self.overlay(f, s, ov, t, None)
        return f

    def shot_index(self, t):
        for i, s in enumerate(self.shots):
            if s['start'] <= t < s['end']: return i
        return len(self.shots) - 1

    def render(self, t):
        i = self.shot_index(t); s = self.shots[i]
        # dissolve / dip into the NEXT shot if we are in its transition window
        if i + 1 < len(self.shots):
            n = self.shots[i + 1]; tr = n.get('transition_in', {'type': 'cut'})
            d = tr.get('dur', .25)
            if tr.get('type', 'cut') in TRANSITIONS and t >= n['start'] - d / 2: s, i = n, i + 1
        tr = s.get('transition_in', {'type': 'cut'})
        d = tr.get('dur', .25)
        if i > 0 and tr.get('type', 'cut') in TRANSITIONS and t < s['start'] + d / 2:
            p = c01((t - (s['start'] - d / 2)) / d)
            prev = self.render_shot(self.shots[i - 1], min(t, self.shots[i - 1]['end'] - 1e-3))
            cur = self.render_shot(s, max(t, s['start']))
            return transition(prev, cur, p, tr)
        return self.render_shot(s, t)

    def finish(self, f, t, i):
        g = self.grade
        f = f * np.array([1 - g['warmth'] * .8, 1.0, 1 + g['warmth']], np.float32)
        f = (f - 128) * g['contrast'] + 128
        f *= self.vig
        f += self.grain[(i // 2) % len(self.grain)] * g['grain']
        fl = self.flash(t)
        if fl: f = f * (1 - fl) + 255 * fl
        o = self.sb.get('output', {})
        fo, fi = o.get('fade_out', .5), o.get('fade_in', .12)
        if fo and t > self.D - fo: f *= c01((self.D - t) / fo)
        if fi and t < fi: f *= .4 + .6 * t / fi
        return np.clip(f, 0, 255).astype(np.uint8)

# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('storyboard')
    ap.add_argument('--stills', nargs='*', type=float)
    ap.add_argument('--no-audio', action='store_true')
    ap.add_argument('--out')
    a = ap.parse_args()
    base = os.path.dirname(os.path.abspath(a.storyboard))
    sb = json.load(open(a.storyboard))
    R = Renderer(sb, base)
    if a.stills is not None:
        os.makedirs(os.path.join(base, 'stills'), exist_ok=True)
        for t in a.stills:
            p = os.path.join(base, 'stills', f'still_{t:05.2f}.jpg')
            cv2.imwrite(p, R.finish(R.render(t), t, 0), [cv2.IMWRITE_JPEG_QUALITY, 88]); print(p)
        return
    out = os.path.join(base, a.out or sb.get('output', {}).get('file', 'reel.mp4'))
    mix = None
    if not a.no_audio:
        mix = os.path.join(base, '_mix.wav')
        AUD.build_mix(sb, base, R.D, mix)
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24',
           '-s', f'{R.W}x{R.H}', '-r', str(R.FPS), '-i', '-']
    if mix: cmd += ['-i', mix, '-map', '0:v', '-map', '1:a', '-c:a', 'aac', '-b:a', '256k', '-shortest']
    cmd += ['-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(round(R.D * R.FPS))
    for i in range(n):
        t = i / R.FPS
        p.stdin.write(R.finish(R.render(t), t, i).tobytes())
        if i % 60 == 0: print(f'frame {i}/{n}', flush=True)
    p.stdin.close(); p.wait()
    print('wrote', out)

if __name__ == '__main__':
    main()
