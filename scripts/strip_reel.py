#!/usr/bin/env python3
"""Turn a comic strip (wide panels stacked vertically) into a music-only "strip reel" storyboard.

    python3 scripts/strip_reel.py projects/comics/strips/strip_reel_onepot.png projects/onepot/strip_reel
    python3 scripts/render.py projects/onepot/strip_reel/storyboard.json

Panels are split at the horizontal gutters. The reel opens straight on panel 1 (no full-strip spoiler), shows each
panel as a framed card with a slow push-in and a pop, the last panel gets a punchline thump, and only then the whole strip as the end card. Background music: a style from music_styles.py (--style; default = picked from the strip's filename so every
strip reel sounds different), no voiceover.
"""
import argparse, json, os
import cv2, numpy as np


def find_panels(img, min_h=120, cuts=None):
    """Split at full-width gutters: a light cream line (bright + uniform) or a solid dark border (>=3 dark uniform
    rows). Pass `cuts` (y positions) for strips whose gutter doesn't span the full width."""
    H = img.shape[0]
    if cuts:
        ys = [0] + sorted(cuts) + [H]
        return [(a, b) for a, b in zip(ys, ys[1:]) if b - a >= min_h]
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(float)
    band = g[:, int(img.shape[1] * 0.08):int(img.shape[1] * 0.92)]   # ignore side borders
    m, sd = band.mean(1), band.std(1)
    light = (m > 200) & (sd < 20)
    dark = (m < 60) & (sd < 15)
    dark = dark & (np.convolve(dark, np.ones(3), 'same') >= 3)        # solid border = 3+ dark rows
    ys = np.where(light | dark)[0]
    groups, run = [], []
    for y in ys:                                                       # merge rows within 12px into one gutter
        if run and y - run[-1] > 12:
            groups.append((run[0], run[-1])); run = []
        run.append(y)
    if run:
        groups.append((run[0], run[-1]))
    edges = [(-1, -1)] + groups + [(H, H)]
    panels = [(e0 + 1, s1) for (_, e0), (s1, _) in zip(edges, edges[1:]) if s1 - (e0 + 1) >= min_h]
    return panels or [(0, H)]


def split_row(row, min_w=200):
    """Split one row into side-by-side panels at vertical gutters (2x2 grids, 3-up rows). Returns x ranges."""
    cols = find_panels(np.ascontiguousarray(row.transpose(1, 0, 2)), min_h=min_w)
    widths = [b - a for a, b in cols]
    # real grid columns are near-equal; an uneven split is a vertical line inside the art (mirror, door frame)
    if len(cols) > 1 and min(widths) / max(widths) > 0.7:
        return cols
    return [(0, row.shape[1])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('strip')
    ap.add_argument('outdir')
    ap.add_argument('--per', type=float, default=3.3, help='seconds per panel')
    ap.add_argument('--mood', default='happy', choices=['happy', 'sad'])
    ap.add_argument('--bpm', type=int, default=0, help='0 = the style default')
    ap.add_argument('--style', default='', help='music style (see music_styles.STYLES); default: picked per strip')
    ap.add_argument('--cuts', default='', help='manual gutter y positions, e.g. 480,909')
    ap.add_argument('--no-music', action='store_true',
                    help='no music bed (the song is picked in the Instagram app); keep only soft SFX')
    ap.add_argument('--silent', action='store_true', help='no music and no SFX: a fully silent video')
    ap.add_argument('--layout', default='', help='layout.json from comic_layout.py: crop each panel by its polygon box')
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    img = cv2.imread(a.strip)
    H, W = img.shape[:2]
    cv2.imwrite(os.path.join(a.outdir, 'strip.png'), img)
    panels = find_panels(img, cuts=[int(c) for c in a.cuts.split(',') if c])
    names = []
    if a.layout:   # strip drawn from a comic_layout.py wireframe: use its panel boxes (slanted panels too)
        panels = []
        for k, poly in enumerate(json.load(open(a.layout))['panels']):
            xs, ys = [int(q[0] * W) for q in poly], [int(q[1] * H) for q in poly]
            n = f'panel{k + 1}.png'
            cv2.imwrite(os.path.join(a.outdir, n), img[max(min(ys), 0):min(max(ys), H), max(min(xs), 0):min(max(xs), W)])
            names.append((n, (max(xs) - min(xs)) / (max(ys) - min(ys))))
    for y0, y1 in panels:
        row = img[y0:y1]
        for x0, x1 in ([(0, W)] if a.cuts else split_row(row)):
            n = f'panel{len(names) + 1}.png'
            cv2.imwrite(os.path.join(a.outdir, n), row[:, x0:x1])
            names.append((n, (x1 - x0) / (y1 - y0)))

    card = lambda aspect, intro=False: {"width": 0.98, "aspect": round(aspect, 3), "y": 0.5, "intro": intro,
                                        "radius": 30, "border": 10, "border_color": [242, 228, 205], "bg_dark": 0.42}
    shots, events, t = [], [], 0.0
    t = 0.0   # no full-strip reveal up front: open on panel 1, show the whole strip only as the end card
    single = len(names) == 1
    for i, (n, aspect) in enumerate(names):
        last = i == len(names) - 1
        d = a.per + (1.2 if last else 0) + (2.0 if single else 0)
        if aspect > 1.3:
            # wide panel: show ~70% of it and glide left -> right in ONE smooth eased move over a longer shot, with a
            # slight push-in so it never stops (owner 2026-10-24: the old fast pan was unreadable; stop-go holds felt stiff)
            d += 1.6 if aspect > 1.9 else 0.8
            cam = [{"t": 0, "x": 0.0, "y": 0.5, "zoom": 1.0}, {"t": round(d, 2), "x": 1.0, "zoom": 1.04, "ease": "inout"}]
            view = max(aspect / 1.45, 1.0)
        elif single:
            # single-panel strip: start close on the top (the line), drift down and out; full view only at the end
            cam = [{"t": 0, "x": 0.45, "y": 0.25, "zoom": 1.7}, {"t": round(d, 2), "x": 0.5, "y": 0.6, "zoom": 1.25}]
            view = aspect
        else:
            cam = [{"t": 0, "x": 0.5, "y": 0.5, "zoom": 1.0}, {"t": round(d, 2), "zoom": 1.12}]
            view = aspect
        shots.append({"id": f"p{i + 1}", "image": n, "start": round(t, 2), "end": round(t + d, 2), "mode": "card",
                      "card": card(view, intro=(i == 0)), "camera": cam,
                      **({"transition_in": {"type": "dissolve", "dur": 0.25}} if i else {})})
        events.append({"t": round(t + 0.15, 2), "sfx": "thump_low" if last and not single else "pop",
                       "gain": 0.55 if last else 0.35})
        if last and not single:
            events.append({"t": round(t + 0.15, 2), "type": "shake", "amp": 8, "decay": 0.12})
        t += d
    end = 2.6
    shots.append({"id": "end", "image": "strip.png", "start": round(t, 2), "end": round(t + end, 2), "mode": "card",
                  "card": card(W / H), "transition_in": {"type": "dissolve", "dur": 0.35},
                  "camera": [{"t": 0, "x": 0.5, "y": 0.5, "zoom": 1.0}, {"t": end, "zoom": 1.03}]})
    events.append({"t": round(t + 0.1, 2), "sfx": "shimmer", "gain": 0.4})
    t += end
    import zlib
    h = zlib.crc32(os.path.basename(a.strip).encode())
    happy = ['ukulele', 'pizzicato', 'jazz', 'bossa', 'musicbox', 'chiptune', 'lofi']
    style = a.style or (['musicbox', 'suspense', 'lofi'][h % 3] if a.mood == 'sad' else happy[h % len(happy)])
    music = {"synth": style, "mood": a.mood, "seed": h % 1000, "outro_at": round(t - end, 2), "volume": 0.9}
    if a.bpm: music["bpm"] = a.bpm
    sb = {"output": {"width": 1080, "height": 1920, "fps": 30, "duration": round(t, 2), "file": "strip_reel.mp4",
                     "fade_in": 0.1, "fade_out": 0.6},
          **({} if (a.no_music or a.silent) else {"music": music}),
          "grade": {"warmth": 0.02, "contrast": 1.03, "vignette": 0.2, "grain": 2.5},
          "shots": shots, "events": events}
    if a.silent:
        sb["events"] = [e for e in events if "sfx" not in e]
    elif a.no_music:
        for e in sb["events"]:
            if "gain" in e:
                e["gain"] = round(e["gain"] * 0.6, 2)
    json.dump(sb, open(os.path.join(a.outdir, 'storyboard.json'), 'w'), indent=1)
    print(f'{len(names)} panel(s), {t:.1f}s -> {a.outdir}/storyboard.json')


if __name__ == '__main__':
    main()
