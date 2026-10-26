#!/usr/bin/env python3
"""Lyric-edit video (Instagram lyric-edit look) from a JSON file.

One full-screen comic picture per line. The words build up ON the picture (no boxes): verse lines are cute hand-lettering
that types on, stack lines build word by word with mixed sizes, chorus lines slam in as heavy colour caps with an ink outline,
*emphasis* words come in big in a marker font. Optional crayon-painted colour stripe behind the text, emoji accents,
white flash on the beat. The lettering has a subtle hand-drawn jitter; pictures stay still (owner: no wobble on the image).
Pictures ghost-crossfade into each other and punch in. Ends on a black signature card.

    python3 scripts/lyric_edit.py music_videos/13_rem_lovegrows/lyric_edit.json             # full render
    python3 scripts/lyric_edit.py music_videos/13_rem_lovegrows/lyric_edit.json --preview   # half size, 15 fps
    python3 scripts/lyric_edit.py music_videos/13_rem_lovegrows/lyric_edit.json --still 3.2 # PNG of video second 3.2

Times are SONG seconds ([mm:ss.xx] in an .lrc -> mm*60+ss.xx). Video second 0 = song second "start".

TEXT MARKUP in "text":   "/" = new row      *word* = emphasis (big marker word)
    "Her / clothes / are kinda / *FUNNY*"        "and nobody / *knows* / like me"

Per line:  start, end, text, image | shots, style, anim, stripe, y, align, emoji, flash, word_times
  shots   several cuts inside one line: [{"image": "f1.png"}, {"at": 28.0, "image": "f2.png", "cut": "flash"},
          {"at": 29.0, "zoom": 1.7, "focus": [0.5, 0.35]}]   (no "image" = same picture as the shot before, e.g. a close-up)
          at = song second the cut happens (default: evenly spread)   zoom/focus = close-up crop (focus 0-1 of the picture)
          cut = ghost (soft crossfade, default for a new line) | hard (default inside a line) | flash | shake | whoosh
  style   verse  — cute hand-lettering, types on letter by letter            (default anim: type)
          stack  — rows alternate left/right, words rise in one by one       (default anim: rise)
          chorus — HEAVY CAPS cycling yellow/white/red + ink outline, slam    (default anim: slam)
          block  — lyric-edit block: left-aligned stack, *BIG* words + small rows, white caps with soft shadow
                   (default anim: slide; no *word* given = the first word is big)
  anim    type | rise | slam | pop | drop | wave | slide
  stripe  colour like "#FFD84D" → crayon-painted band wipes in behind the text (null = none)
  y       0-1 centre of the text block (default 0.2)     align  left | center | right
  emoji   e.g. "😹😹😹" pops in under the text             flash  true = white flash at the line start
Top level: output, size, fps, start, end, audio, fit (extend = full width + paper on top | cover = fill the screen), signature (text on the black end card), signature_seconds,
           boil_image (picture wobble, default 0 = off — owner), boil_text (letter jitter, default 1, 0 = off), fonts {verse, heavy, marker, script, emoji}, palette, accent, ink
"""
import argparse, copy, json, math, os, random, subprocess, sys, types
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FD = os.path.join(ROOT, 'fonts')
DEF = dict(output='lyric_edit.mp4', size=[1080, 1920], fps=30, start=0.0, end=None, audio=None,
           signature='', signature_seconds=1.6, boil_image=0.0, boil_text=1.0,
           fonts=dict(verse=os.path.join(FD, 'Gaegu-Bold.ttf'), heavy=os.path.join(FD, 'Baloo2.ttf'),
                      marker=os.path.join(FD, 'PermanentMarker.ttf'), script=os.path.join(FD, 'CaveatBrush.ttf'),
                      emoji='/System/Library/Fonts/Apple Color Emoji.ttc'),
           ink='#2E2228', palette=['#FFD84D', '#FFFFFF', '#F0445E'], accent='#F0445E',
           verse_size=110, heavy_size=124, marker_size=158, y=0.2, margin=0.07, fit='extend',
           block_big=165, block_small=82, block_fill='#FFFFFF')


EMOJI_LINUX = '/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf'   # used only when the macOS emoji font is missing


def font_path(p):
    """Font paths may be absolute or relative to the repo (e.g. "fonts/MyFont.ttf" uploaded in the Studio)."""
    if p and not os.path.isabs(p) and not os.path.exists(p) and os.path.exists(os.path.join(ROOT, p)): return os.path.join(ROOT, p)
    return p


def hexc(s, a=255): s = s.lstrip('#'); return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4)) + (a,)
def clamp(x): return min(max(x, 0.0), 1.0)
def ease_out(x): x = clamp(x); return 1 - (1 - x) ** 3
def ease_back(x, k=1.9): x = clamp(x) - 1; return 1 + (k + 1) * x ** 3 + k * x ** 2


def fit_picture(path, W, H, mode='extend', zoom=1.0, focus=(0.5, 0.5)):
    """extend: full width, bottom-anchored, the empty paper at the top is extended upward so nothing is cropped.
    cover: fill the whole screen (sides cropped). zoom > 1 = close-up crop around focus (0-1 of the picture)."""
    im = Image.open(path).convert('RGB')
    if zoom > 1:
        cw, ch = im.width / zoom, im.height / zoom
        x0 = min(max(focus[0] * im.width - cw / 2, 0), im.width - cw); y0 = min(max(focus[1] * im.height - ch / 2, 0), im.height - ch)
        im = im.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))); mode = 'cover'
    if mode == 'extend' and im.width / im.height > W / H:
        s = W / im.width; im = im.resize((W, round(im.height * s)), Image.LANCZOS)
        top = im.crop((0, 0, W, max(4, im.height // 40))).resize((1, 1), Image.LANCZOS).getpixel((0, 0))
        out = Image.new('RGB', (W, H), top); out.paste(im, (0, H - im.height))
        b = int(120 * W / 1080)
        out.paste(Image.new('RGB', (W, b), top), (0, H - im.height), Image.linear_gradient('L').resize((W, b)).transpose(Image.FLIP_TOP_BOTTOM))
        return out
    s = max(W / im.width, H / im.height); im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    x, y = (im.width - W) // 2, (im.height - H) // 2; return im.crop((x, y, x + W, y + H))


def boil_variants(img, amp, n=3, seed=0):
    """n slightly warped copies (smooth random displacement) — cycling them makes lines 'boil' like hand animation."""
    if amp <= 0: return [img]
    a = np.asarray(img); h, w = a.shape[:2]; out = []; rnd = np.random.default_rng(seed)
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    for _ in range(n):
        dx = cv2.resize(rnd.standard_normal((h // 90 + 2, w // 90 + 2)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC) * amp
        dy = cv2.resize(rnd.standard_normal((h // 90 + 2, w // 90 + 2)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC) * amp
        out.append(Image.fromarray(cv2.remap(a, gx + dx, gy + dy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)))
    return out


def crayon_stripe(w, h, color, seed):
    """Hand-painted crayon band: ragged edges, visible strokes, a little paper showing through."""
    rnd = random.Random(seed); im = Image.new('RGBA', (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(im); c = hexc(color)
    for k in range(int(h / 3)):
        y = k * 3 + rnd.uniform(-1, 1)
        d.line([(rnd.uniform(0, 18), y), (w - rnd.uniform(0, 26), y + rnd.uniform(-3, 3))], fill=c[:3] + (int(rnd.uniform(150, 235)),), width=rnd.choice([3, 4, 5]))
    edge = Image.new('L', (w, h), 0)
    pts = [(rnd.uniform(0, 14), 0)] + [(w * t / 20 + rnd.uniform(-6, 6), rnd.uniform(0, 10)) for t in range(1, 20)] + \
          [(w - rnd.uniform(0, 16), 0), (w - rnd.uniform(0, 20), h)] + \
          [(w * (20 - t) / 20 + rnd.uniform(-6, 6), h - rnd.uniform(0, 12)) for t in range(1, 20)] + [(rnd.uniform(0, 18), h)]
    ImageDraw.Draw(edge).polygon(pts, fill=255)
    im.putalpha(Image.composite(im.getchannel('A'), Image.new('L', (w, h), 0), edge)); return im


def text_sprite(word, font, fill, ink, outline, shadow, soft=0):
    """Word drawn on a shared BASELINE (font ascent/descent, not the word's own bbox) so mixed words line up.
    soft > 0: blurred dark halo behind the word (readable on busy pictures)."""
    asc, desc = font.getmetrics(); d0 = ImageDraw.Draw(Image.new('L', (1, 1)))
    l, _, r, _ = d0.textbbox((0, 0), word, font=font, stroke_width=outline)
    pad = outline + shadow + 6 + 2 * soft; im = Image.new('RGBA', (r - l + 2 * pad, asc + desc + 2 * pad), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    if soft:
        m = Image.new('L', im.size, 0); ImageDraw.Draw(m).text((pad - l + shadow, pad + asc + shadow), word, font=font, fill=255, stroke_width=outline + soft // 2, anchor='ls')
        halo = Image.new('RGBA', im.size, ink[:3] + (0,)); halo.putalpha(m.filter(ImageFilter.GaussianBlur(soft)).point(lambda v: int(v * 0.8))); im.alpha_composite(halo)
    if shadow: d.text((pad - l + shadow, pad + asc + shadow), word, font=font, fill=ink, stroke_width=outline, stroke_fill=ink, anchor='ls')
    d.text((pad - l, pad + asc), word, font=font, fill=fill, stroke_width=outline, stroke_fill=ink if outline else fill, anchor='ls')
    return im, pad


def parse(text):
    rows = []
    for grp in text.split('/'):
        ws = [(w.strip('*'), w.startswith('*') and w.endswith('*') and len(w) > 2) for w in grp.split()]
        if ws: rows.append(ws)
    return rows


def load(raw, base, scale=1.0, fps=None):
    """Build a renderer from a lyric-edit dict. base = folder the image paths are relative to.
    scale < 1 renders smaller (previews); fps overrides the JSON fps. Returns a namespace with
    render(song_s, frame_no) -> RGBA Image, plus W, H, fps, start, end (song s, incl. end card), last (song s of last line end)."""
    raw = copy.deepcopy(raw); cfg = {**DEF, **raw}; cfg['fonts'] = {**DEF['fonts'], **raw.get('fonts', {})}
    W, H = (int(round(v * scale / 2)) * 2 for v in cfg['size']); fps = fps or cfg['fps']; start = cfg['start']
    sc = W / cfg['size'][0]
    lines = sorted(cfg['lines'], key=lambda l: l['start'])
    sig_s = cfg['signature_seconds'] if cfg.get('signature') else 0
    last = cfg['end'] or max(l['end'] for l in lines); end = last + sig_s
    STY = {'verse': 'type', 'stack': 'rise', 'chorus': 'slam', 'block': 'slide'}
    pics, shots, cur = {}, [], None                     # shots = every picture cut (a line can hold several)
    for i, l in enumerate(lines):
        l['_i'] = i; l.setdefault('style', 'stack'); l.setdefault('anim', STY[l['style']])
        sh = l.get('shots') or ([{'image': l['image']}] if l.get('image') else [])
        n = len(sh)
        for j, s_ in enumerate(sh):
            img = os.path.join(base, s_['image']) if s_.get('image') else cur
            if img is None: continue
            cur = img; z = float(s_.get('zoom', 1.0)); fc = tuple(s_.get('focus', (0.5, 0.5)))
            key = (img, z, fc, s_.get('fit', cfg['fit']))
            if key not in pics: pics[key] = boil_variants(fit_picture(img, W, H, key[3], z, fc), 1.6 * sc * cfg['boil_image'], seed=len(pics))
            t = s_.get('at', l['start'] + (l['end'] - l['start']) * j / n)
            shots.append(dict(t=t, key=key, cut=s_.get('cut', 'ghost' if j == 0 else 'hard')))
    shots.sort(key=lambda s_: s_['t'])
    for k, s_ in enumerate(shots): s_['k'] = k; s_['end'] = shots[k + 1]['t'] if k + 1 < len(shots) else last
    F = {}
    def font(kind, size):
        if (kind, size) not in F:
            f = ImageFont.truetype(font_path(cfg['fonts'][kind]), int(size * sc))
            if kind == 'heavy':
                try: f.set_variation_by_name('ExtraBold')
                except Exception: pass
            F[(kind, size)] = f
        return F[(kind, size)]
    sprites, stripes, layouts = {}, {}, {}

    def layout(l, mul=1.0):
        if l['_i'] in layouts: return layouts[l['_i']]
        rows = parse(l['text']); style = l['style']; out = []; k = 0; y = 0; bw = 0
        if len(rows) == 1:                                   # no "/" given -> auto-split into rows that fit the style
            lim = {'verse': 15, 'stack': 12, 'chorus': 12, 'block': 11}[style]
            words, rows, cr = rows[0], [], []
            for w in words:
                if cr and len(' '.join(x[0] for x in cr + [w])) > lim: rows.append(cr); cr = []
                cr.append(w)
            if cr: rows.append(cr)
        if style == 'block' and not any(e for r in rows for _, e in r): rows[0][0] = (rows[0][0][0], True)   # first word big
        for r_i, row in enumerate(rows):
            items, x, rh, gap = [], 0, 0, 0
            for w, emph in row:
                if style == 'block':                                                # lyric-edit block: BIG / small white caps
                    f = font('heavy', int(cfg['block_big' if emph else 'block_small'] * mul)); fill = hexc(cfg['block_fill']); w = w.upper()
                    ol, sh = (int(7 * sc), int(9 * sc)) if emph else (int(5 * sc), int(6 * sc))   # thick ink outline: reads on cream AND night frames
                    key = (w, f.size, fill, ol, 'b')
                    if key not in sprites: sprites[key] = text_sprite(w, f, fill, hexc(cfg['ink']), ol, sh, soft=int(10 * sc))
                elif emph: f = font('marker', int(cfg['marker_size'] * mul)); fill = hexc(cfg['accent']); ol, sh = int(5 * sc), int(7 * sc)
                elif style == 'chorus': f = font('heavy', int(cfg['heavy_size'] * mul)); fill = hexc(cfg['palette'][k % len(cfg['palette'])]); ol, sh = int(6 * sc), int(8 * sc); w = w.upper()
                else: f = font('verse', int(cfg['verse_size'] * mul)); fill = hexc(cfg['ink']); ol, sh = 0, 0
                if style != 'block':
                    key = (w, f.size, fill, ol)
                    if key not in sprites: sprites[key] = text_sprite(w, f, fill, hexc(cfg['ink']), ol, sh)
                sp, pad = sprites[key]; gap = int(f.size * (0.2 if style == 'block' else 0.26)); gw = sp.width - 2 * pad
                items.append(dict(w=w, x=x - pad, sprite=sp, pad=pad, k=k, emph=emph, font=f, gh=sp.height - 2 * pad))
                x += gw + gap; rh = max(rh, sp.height - 2 * pad); k += 1
            rw = x - gap
            for it in items: it['y'] = y - it['pad'] + (rh - it['gh']); it['rw'] = rw; it['row'] = r_i     # shared baseline per row
            out += items; y += int(rh * (0.86 if style == 'chorus' else 0.8 if style == 'block' else 0.98)); bw = max(bw, rw)
        maxw = W * (1 - 2 * cfg['margin'])
        if bw > maxw and mul > 0.45: return layout(l, mul * maxw / bw * 0.98)        # too wide -> shrink to fit
        if y > 0.4 * H and mul > 0.45: return layout(l, mul * 0.4 * H / y * 0.98)  # too tall -> shrink (keeps clear of the art)
        for it in out:
            al = l.get('align') or ('stack' if style == 'stack' else 'left')
            if al == 'stack': it['x'] += (bw - it['rw']) / 2 + (-1) ** it['row'] * min(70 * sc, (bw - it['rw']) / 2)   # gentle zig-zag
            else: it['x'] += 0 if al == 'left' else (bw - it['rw']) if al == 'right' else (bw - it['rw']) / 2
        layouts[l['_i']] = (out, bw, y); return layouts[l['_i']]

    def picture(sh, st, f):
        vs = pics[sh['key']]; p = vs[(f // 4) % len(vs)]                      # boil: swap variant every 4 frames
        lt = st - sh['t']; dur = max(sh['end'] - sh['t'], 0.1); z = 1 + 0.045 * clamp(lt / dur)   # slow push-in
        if sh['cut'] != 'whoosh': z *= 1 + 0.08 * (1 - ease_out(lt / 0.3))     # punch-in on every cut
        else: z *= 1 + 0.3 * (1 - ease_out(lt / 0.28))
        w2, h2 = int(W * z), int(H * z); im = p.resize((w2, h2), Image.BILINEAR)
        x, y = (w2 - W) // 2, (h2 - H) // 2
        if sh['cut'] == 'shake' and lt < 0.4:                                    # camera shake on the hit
            r = random.Random(f); amp = 26 * sc * (1 - lt / 0.4); x += int(r.uniform(-amp, amp)); y += int(r.uniform(-amp, amp))
            x = min(max(x, 0), w2 - W); y = min(max(y, 0), h2 - H)
        return im.crop((x, y, x + W, y + H)).convert('RGBA')

    def render(st, f):
        if st >= last:                                                         # black signature end card
            fr = Image.new('RGBA', (W, H), (12, 10, 14, 255)); p = clamp((st - last) / 0.5)
            ft = font('script', 120); d0 = ImageDraw.Draw(fr); tw = d0.textlength(cfg['signature'], font=ft)
            layer = Image.new('RGBA', (W, H), (0, 0, 0, 0)); jit = random.Random(f // 4)
            ImageDraw.Draw(layer).text(((W - tw) / 2 + jit.uniform(-1.5, 1.5) * sc, H * 0.46 + jit.uniform(-1.5, 1.5) * sc), cfg['signature'], font=ft, fill=(255, 255, 255, int(255 * p)))
            fr.alpha_composite(layer); return fr
        act = [l for l in lines if l['start'] <= st < l['end']]
        if not shots:                                                          # no pictures yet: plain background
            fr = Image.new('RGBA', (W, H), (24, 20, 28, 255))
        else:
            sh = max([x for x in shots if x['t'] <= st] or shots[:1], key=lambda x: x['t'])
            fr = picture(sh, st, f); lt = st - sh['t']
            if sh['k'] > 0 and sh['cut'] == 'ghost' and 0 <= lt < 0.3:        # ghost crossfade between pictures
                pv = shots[sh['k'] - 1]; fr = Image.blend(picture(pv, pv['end'], f), fr, ease_out(lt / 0.3))
            if sh['cut'] == 'flash' and 0 <= lt < 0.2:                        # white flash cut
                fr.alpha_composite(Image.new('RGBA', (W, H), (255, 255, 255, int(235 * (1 - ease_out(lt / 0.2))))))
        if st > last - 0.4: fr = Image.blend(fr, Image.new('RGBA', (W, H), (12, 10, 14, 255)), ease_out((st - (last - 0.4)) / 0.4))
        jit = random.Random(f // 4); jt = 1.2 * cfg['boil_text']                # subtle hand-lettering jitter (pictures stay still)
        for l in act:
            lt = st - l['start']; dur = l['end'] - l['start']
            items, bw, bh = layout(l); n = max(len(items), 1)
            # words spread over the WHOLE line (sung-along feel); the full line is complete for the last 'hold' seconds
            hold = min(0.6, max(0.25, dur * 0.12)); span = max(dur - hold - 0.2, 0.2)
            wt = l.get('word_times') or [l['start'] + span * i / max(n - 1, 1) for i in range(n)]
            out_p = ease_out((st - (l['end'] - 0.14)) / 0.14) if st > l['end'] - 0.14 else 0.0
            if l['style'] == 'stack' or l.get('align') == 'center': bx = (W - bw) / 2
            elif l.get('align') == 'right': bx = W - cfg['margin'] * W - bw
            else: bx = cfg['margin'] * W
            by = min(max(l.get('y', cfg['y']) * H - bh / 2, 0.04 * H), 0.96 * H - bh)   # never off the top/bottom
            if l.get('stripe'):
                key = (l['_i'], int(bh))
                if key not in stripes: stripes[key] = crayon_stripe(int(W * 1.06), int(bh + 130 * sc), l['stripe'], 77 + l['_i'])
                s_im = stripes[key]; cw = int(s_im.width * ease_out(lt / 0.28))
                if cw > 2:
                    part = s_im.crop((0, 0, cw, s_im.height))
                    if out_p: part.putalpha(part.getchannel('A').point(lambda v: int(v * (1 - out_p))))
                    fr.alpha_composite(part, (int(-W * 0.03), int(by - 65 * sc)))
            for it, t0 in zip(items, wt):
                p = (st - t0) / 0.22
                if p <= 0: continue
                sp = it['sprite']; dy = 0.0; s = 1.0; al = 1.0; sp_dx = 0.0
                anim = 'pop' if it['emph'] and l['anim'] in ('type', 'rise') else l['anim']
                if it['emph'] and anim == 'slide': p = (st - t0) / 0.16
                if anim == 'type':
                    nch = len(it['w']); vis = min(nch, int(nch * clamp((st - t0) / max(0.045 * nch, 0.09))) + 1)
                    if vis < nch:
                        pw = int(ImageDraw.Draw(Image.new('L', (1, 1))).textlength(it['w'][:vis], font=it['font']))
                        sp = sp.crop((0, 0, it['pad'] + pw + 3, sp.height))
                elif anim == 'rise': dy = 36 * sc * (1 - ease_out(p)); al = clamp(p * 1.6)
                elif anim == 'slam': s = 1 + 0.75 * (1 - ease_out(p)); al = clamp(p * 2.5)
                elif anim == 'pop': s = ease_back(p)
                elif anim == 'drop': dy = -90 * sc * (1 - ease_out(p)); al = clamp(p * 2)
                elif anim == 'slide':
                    if it['emph']: s = 1 + 0.35 * (1 - ease_out(p)); al = clamp(p * 2.5)          # big word lands
                    else: dy = 0; al = clamp(p * 2); sp_dx = -28 * sc * (1 - ease_out(p))
                elif anim == 'wave': s = ease_back(p); dy = 7 * sc * math.sin(st * 5 + it['k'])
                if it['emph'] and p > 1 and l['style'] != 'block': s *= 1 + 0.035 * math.sin(st * 9)            # emphasis word keeps pulsing on the beat
                if s != 1.0: sp = sp.resize((max(1, int(sp.width * s)), max(1, int(sp.height * s))), Image.BILINEAR)
                a_ = al * (1 - out_p)
                if a_ < 1: sp = sp.copy(); sp.putalpha(sp.getchannel('A').point(lambda v: int(v * a_)))
                ow, oh = it['sprite'].width, it['sprite'].height
                fr.alpha_composite(sp, (int(bx + it['x'] + sp_dx + (ow - sp.width) / 2 * (anim != 'type') + jit.uniform(-jt, jt) * sc),
                                        int(by + it['y'] + dy + (oh - sp.height) / 2 + jit.uniform(-jt, jt) * sc)))
            if l.get('emoji') and lt > min(0.6, dur * 0.4):
                try:
                    ep = font_path(cfg['fonts']['emoji'])
                    if not os.path.exists(ep) and os.path.exists(EMOJI_LINUX): ef = ImageFont.truetype(EMOJI_LINUX, 109)   # Docker/Linux: Noto (bitmap, 109 px only)
                    else: ef = ImageFont.truetype(ep, 96)
                    ei = Image.new('RGBA', (int(ef.size * 1.3 * len(l['emoji'])), int(ef.size * 1.3)), (0, 0, 0, 0))
                    ImageDraw.Draw(ei).text((0, 0), l['emoji'], font=ef, embedded_color=True)
                    s = ease_back((lt - min(0.6, dur * 0.4)) / 0.25) * 0.85 * sc
                    if ef.size != 96: s *= 96 / ef.size
                    ei = ei.resize((max(1, int(ei.width * s)), max(1, int(ei.height * s))), Image.BILINEAR)
                    fr.alpha_composite(ei, (int(bx + bw / 2 - ei.width / 2), int(by + bh + 24 * sc)))
                except Exception: pass
            if l.get('flash') and lt < 0.12: fr.alpha_composite(Image.new('RGBA', (W, H), (255, 255, 255, int(255 * (1 - lt / 0.12)))))
        return fr

    return types.SimpleNamespace(render=render, W=W, H=H, fps=fps, start=start, end=end, last=last, cfg=cfg, base=base)


def write_video(ed, out, progress=None, audio=None, cancel=None, preset='medium', crf=18):
    """Encode the whole edit to out (atomic: temp file, swapped in at the end). progress(done_frames, total_frames);
    cancel() -> True aborts. audio = song file baked in from song second `start` (None = silent; IG adds the song)."""
    final = out; out = out[:-4] + '.rendering.mp4'
    silent = out[:-4] + '_noaudio.mp4' if audio else out
    ff = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{ed.W}x{ed.H}', '-r', str(ed.fps), '-i', '-',
                           '-c:v', 'libx264', '-preset', preset, '-crf', str(crf), '-pix_fmt', 'yuv420p', '-movflags', '+faststart', silent], stdin=subprocess.PIPE)
    n = int(round((ed.end - ed.start) * ed.fps))
    try:
        for f in range(n):
            if cancel and cancel(): raise KeyboardInterrupt('cancelled')
            ff.stdin.write(ed.render(ed.start + f / ed.fps, f).convert('RGB').tobytes())
            if progress: progress(f + 1, n)
    except BaseException:
        ff.stdin.close(); ff.wait()
        for x in {out, silent}:
            if os.path.exists(x): os.remove(x)
        raise
    ff.stdin.close(); ff.wait()
    if audio:
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', silent, '-ss', str(ed.start), '-i', audio, '-map', '0:v', '-map', '1:a',
                        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', out], check=True); os.remove(silent)
    os.replace(out, final); return final


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('json'); ap.add_argument('--preview', action='store_true')
    ap.add_argument('--still', type=float, default=None); a = ap.parse_args()
    raw = json.load(open(a.json)); base = os.path.dirname(os.path.abspath(a.json))
    ed = load(raw, base, 0.5 if a.preview else 1.0, max(1, raw.get('fps', 30) // 2) if a.preview else None)
    if a.still is not None:
        p = os.path.join(base, f'still_{a.still:.2f}.png'); ed.render(ed.start + a.still, int(a.still * ed.fps)).convert('RGB').save(p); print('->', p); return
    out = os.path.join(base, ed.cfg['output']); out = out.replace('.mp4', '_preview.mp4') if a.preview else out
    aud = ed.cfg['audio'] and (ed.cfg['audio'] if os.path.isabs(ed.cfg['audio']) else os.path.join(base, ed.cfg['audio']))
    last_pct = [-1]
    def prog(d, n):
        pct = d * 100 // n
        if pct // 10 != last_pct[0] // 10: print(f'{d / ed.fps:5.1f}s / {n / ed.fps:.1f}s', file=sys.stderr)
        last_pct[0] = pct
    print('->', write_video(ed, out, prog, aud))


if __name__ == '__main__':
    main()
