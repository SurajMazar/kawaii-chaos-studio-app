#!/usr/bin/env python3
"""Style check: crops of your style reference next to the image's character crops at the same scale, side by side.

    python3 scripts/style_check.py projects/NNN_x/raw/strip_a1.png [out.jpg] [--master references/style_ref.png]
Takes the two densest-ink regions (where the characters are) of the style reference and of the image. Look at it before
QA: line darkness/weight, fill texture, eye style, proportions.
"""
import argparse, os
import numpy as np
from PIL import Image
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def dense_crops(im, n=2, win=(320, 360), step=60):
    g = np.asarray(im.convert('L')) < 90
    H, W = g.shape; win = (min(win[0], W), min(win[1], H)); best = []
    for y in range(0, max(1, H - win[1]), step):
        for x in range(0, max(1, W - win[0]), step):
            best.append((g[y:y + win[1], x:x + win[0]].mean(), x, y))
    best.sort(reverse=True); picked = []
    for _, x, y in best:
        if all(abs(x - px) > 300 or abs(y - py) > 300 for px, py in picked): picked.append((x, y))
        if len(picked) == n: break
    return [im.crop((x, y, x + win[0], y + win[1])) for x, y in picked]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('src'); ap.add_argument('out', nargs='?'); ap.add_argument('--master')
    a = ap.parse_args()
    out = a.out or os.path.splitext(a.src)[0] + '_stylecheck.jpg'
    master = a.master or next((p for p in (os.path.join(ROOT, 'references', n) for n in ('style_ref_master.jpg', 'style_ref.png', 'style_ref.jpg'))
                               if os.path.exists(p)), None)
    im = Image.open(a.src).convert('RGB')
    crops = dense_crops(Image.open(master).convert('RGB')) if master else []
    left = len(crops)
    crops += dense_crops(im)
    h = 330; crops = [c.resize((max(1, int(c.width * h / c.height)), h)) for c in crops]
    o = Image.new('RGB', (sum(c.width for c in crops) + 40, h), 'white'); x = 0
    for i, c in enumerate(crops):
        o.paste(c, (x, 0)); x += c.width + (30 if i == left - 1 else 10)
    o.save(out, quality=92); print(out)
    if not master: print('no style reference in references/ (style_ref.png) — only the image crops are shown')


if __name__ == '__main__':
    main()
