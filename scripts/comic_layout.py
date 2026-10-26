#!/usr/bin/env python3
"""Generate a random comic-page panel layout (slanted gutters, uneven splits) for a strip prompt.

    python3 scripts/comic_layout.py projects/wfh/layout --panels 5 --seed 7

Writes into the output folder:
  layout.png   wireframe to attach to the image prompt ("follow this panel layout exactly")
  layout.json  panel polygons in reading order (0-1 coordinates), reusable by strip_reel.py --layout
  layout.txt   a plain-language description of the layout to paste into the prompt

The page is split into 2-4 rows whose borders may tilt, and each row into 1-3 panels whose dividers may slant,
so every run gives a different pattern (like a hand-drawn comic page). The last panel is kept large for the
punchline unless --no-punch is passed.
"""
import argparse, json, os, random
import cv2, numpy as np

W, H, M, G = 1122, 1402, 26, 16          # page size (4:5-ish), outer margin, gutter width


def line(p, q):
    """Line through p, q as (a, b, c) with a*x + b*y = c and (a, b) unit length."""
    (x1, y1), (x2, y2) = p, q
    a, b = y2 - y1, x1 - x2
    n = np.hypot(a, b)
    a, b = a / n, b / n
    return a, b, a * x1 + b * y1


def offset(l, d):
    a, b, c = l
    return a, b, c + d


def cross(l1, l2):
    a1, b1, c1 = l1
    a2, b2, c2 = l2
    det = a1 * b2 - a2 * b1
    return ((c1 * b2 - c2 * b1) / det, (a1 * c2 - a2 * c1) / det)


def side(l, pt):
    a, b, c = l
    return a * pt[0] + b * pt[1] - c


def inset(l, inside_pt, d):
    """Move line l by d towards inside_pt."""
    return offset(l, d if side(l, inside_pt) > 0 else -d)


def make_layout(n_panels, rng, punch=True):
    # how many panels per row, top to bottom
    for _ in range(200):
        rows = rng.randint(2, 4)
        per = [rng.randint(1, 3) for _ in range(rows)]
        if punch:
            per[-1] = rng.choice([1, 1, 2])
        if sum(per) == n_panels:
            break
    else:
        per = [2] * (n_panels // 2) + ([1] if n_panels % 2 else [])
    rows = len(per)
    # row borders: y positions with random tilt (left/right differ)
    weights = [rng.uniform(0.8, 1.3) for _ in range(rows)]
    if punch:
        weights[-1] *= 1.35
    cum = np.cumsum([0] + weights) / sum(weights)
    borders = [line((0, M), (W, M))]
    for k in range(1, rows):
        y = M + cum[k] * (H - 2 * M)
        tilt = rng.choice([0, 0, rng.uniform(-70, 70)])
        borders.append(line((0, y - tilt / 2), (W, y + tilt / 2)))
    borders.append(line((0, H - M), (W, H - M)))
    left, right = line((M, 0), (M, H)), line((W - M, 0), (W - M, H))

    panels = []
    for r in range(rows):
        top, bot = borders[r], borders[r + 1]
        ws = [rng.uniform(0.7, 1.4) for _ in range(per[r])]
        cx = np.cumsum([0] + ws) / sum(ws)
        divs = [left]
        for k in range(1, per[r]):
            x = M + cx[k] * (W - 2 * M)
            slant = rng.choice([0, rng.uniform(-110, 110)])
            ya, yb = cross(top, line((x, 0), (x, H)))[1], cross(bot, line((x, 0), (x, H)))[1]
            divs.append(line((x - slant / 2, ya), (x + slant / 2, yb)))
        divs.append(right)
        for k in range(per[r]):
            l_, r_ = divs[k], divs[k + 1]
            # a rough centre to know which side is "inside"
            c = ((cross(top, l_)[0] + cross(bot, r_)[0]) / 2, (cross(top, l_)[1] + cross(bot, r_)[1]) / 2)
            t2 = top if r == 0 else inset(top, c, G / 2)
            b2 = bot if r == rows - 1 else inset(bot, c, G / 2)
            l2 = l_ if k == 0 else inset(l_, c, G / 2)
            r2 = r_ if k == per[r] - 1 else inset(r_, c, G / 2)
            poly = [cross(t2, l2), cross(t2, r2), cross(b2, r2), cross(b2, l2)]
            panels.append([[round(x / W, 4), round(y / H, 4)] for x, y in poly])
    return per, panels


def describe(per, panels):
    vpos = lambda y: 'top' if y < 0.36 else ('bottom' if y > 0.64 else 'middle')
    hpos = lambda x: 'left' if x < 0.4 else ('right' if x > 0.6 else 'center')
    out = [f"PANEL LAYOUT (follow the attached wireframe exactly, not a grid): {len(panels)} panels in {len(per)} "
           f"rows ({' / '.join(str(p) for p in per)} panels per row), thin cream gutters, crisp dark borders."]
    for i, p in enumerate(panels):
        xs, ys = [q[0] for q in p], [q[1] for q in p]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        cx, cy = sum(xs) / 4, sum(ys) / 4
        where = f"{vpos(cy)} " + ('full width' if w > 0.85 else hpos(cx))
        slanted = abs(p[0][1] - p[1][1]) > 0.02 or abs(p[2][1] - p[3][1]) > 0.02 or \
                  abs(p[0][0] - p[3][0]) > 0.02 or abs(p[1][0] - p[2][0]) > 0.02
        size = 'large' if w * h > 0.2 else ('small' if w * h < 0.1 else 'medium')
        out.append(f"Panel {i + 1}: {where}, {size}" + (", slanted edges" if slanted else "") + '.')
    out.append("Read left-to-right, top-to-bottom; the last panel is the punchline.")
    return ' '.join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('outdir')
    ap.add_argument('--panels', type=int, default=0, help='3-6 (default: random)')
    ap.add_argument('--seed', type=int, default=None)
    ap.add_argument('--no-punch', action='store_true')
    a = ap.parse_args()
    rng = random.Random(a.seed)
    n = a.panels or rng.randint(3, 6)
    per, panels = make_layout(n, rng, punch=not a.no_punch)
    os.makedirs(a.outdir, exist_ok=True)
    img = np.full((H, W, 3), 247, np.uint8)
    for i, p in enumerate(panels):
        pts = np.array([[x * W, y * H] for x, y in p], np.int32)
        cv2.polylines(img, [pts], True, (60, 60, 60), 4, cv2.LINE_AA)
        c = pts.mean(0).astype(int)
        cv2.putText(img, str(i + 1), (int(c[0]) - 18, int(c[1]) + 20), cv2.FONT_HERSHEY_SIMPLEX, 2, (170, 170, 170), 4,
                    cv2.LINE_AA)
    cv2.imwrite(os.path.join(a.outdir, 'layout.png'), img)
    json.dump({"rows": per, "panels": panels}, open(os.path.join(a.outdir, 'layout.json'), 'w'), indent=1)
    txt = describe(per, panels)
    open(os.path.join(a.outdir, 'layout.txt'), 'w').write(txt + '\n')
    print(txt)


if __name__ == '__main__':
    main()
