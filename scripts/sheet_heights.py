#!/usr/bin/env python3
"""Set exact relative heights on a character sheet (figures standing in a row on a plain background).

Image generators often ignore height specs on chibi sheets (e.g. 0.88-0.93 instead of the wanted 0.84), so heights are
fixed deterministically: each figure is cut out (colour distance from the background), measured from its top ink row to
the floor, and scaled (down only) about its bottom-centre to `ratio x reference height`. Labels/floor line stay put.

    python3 scripts/sheet_heights.py in.png out.png --ratios 1.08,0.92,0.84,1.0 [--ref 3]
ratios are left-to-right, relative to figure --ref (index, default: the one with ratio 1.0).
The output is a fresh canvas: figures pasted scaled, labels copied; a drawn floor line is dropped.
"""
import argparse
import numpy as np
from PIL import Image
from scipy import ndimage

ap = argparse.ArgumentParser()
ap.add_argument('src'); ap.add_argument('dst'); ap.add_argument('--ratios', required=True)
ap.add_argument('--ref', type=int); ap.add_argument('--label-frac', type=float)   # default: found automatically
a = ap.parse_args()
ratios = [float(x) for x in a.ratios.split(',')]
ref = a.ref if a.ref is not None else ratios.index(1.0)

im = Image.open(a.src).convert('RGB'); A = np.asarray(im).astype(int); H, W, _ = A.shape
bg = np.median(np.concatenate([A[:20].reshape(-1, 3), A[:, :20].reshape(-1, 3)]), 0)
fg = np.abs(A - bg).sum(2) > 40
if a.label_frac is None:                                             # labels = the bottom ink block below a blank gap
    rows = fg.sum(1) > 0; y = H - 1
    while y > 0 and not rows[y]: y -= 1
    while y > 0 and rows[y]: y -= 1
    a.label_frac = (y + 1) / H if y > H * 0.6 else 0.86
fg[int(H * a.label_frac) - 1:] = False                              # name labels live below this line
dark = np.abs(A - bg).sum(2) > 150                                   # drawn floor line: long thin horizontal stroke
runs = ndimage.binary_opening(dark, np.ones((1, W // 4)))
runs0 = runs.copy()                                                   # the long strokes, before the thin-line test
thick = np.roll(dark, 8, 0) | np.roll(dark, -8, 0)                   # a LINE is thin: nothing drawn 8 px above/below
runs &= ~ndimage.binary_opening(thick, np.ones((1, 15)))
floorline = ndimage.binary_dilation(runs, np.ones((5, 9)))
fg &= ~floorline
fg = ndimage.binary_closing(fg, np.ones((5, 5)))
lab, n = ndimage.label(fg)
objs = ndimage.find_objects(lab)
# drop floor lines / long thin things (wider than 40% of the sheet, flatter than 20 px)
keep = [i + 1 for i, s in enumerate(objs) if not ((s[1].stop - s[1].start) > W * 0.4 and (s[0].stop - s[0].start) < 20)]
big = [i for i in keep if (lab == i).sum() > H * W * 0.004]
# split figures by the column projection: n-1 cuts at the emptiest columns between the figures
proj = np.isin(lab, big).sum(0).astype(float)
k = len(ratios); xs = np.where(proj > 0)[0]; x0, x1 = xs.min(), xs.max()
cuts = []
for j in range(1, k):
    g = x0 + (x1 - x0) * j / k; lo, hi = int(g - (x1 - x0) / k * 0.45), int(g + (x1 - x0) / k * 0.45)
    cuts.append(lo + int(np.argmin(ndimage.uniform_filter1d(proj[lo:hi], 9))))
bounds = [x0] + cuts + [x1 + 1]
# a component goes whole to the figure holding most of its pixels (an arm crossing a cut stays whole); a component
# shared substantially by several figures (touching figures merged into one blob) is split at the cut columns
seg = np.searchsorted(bounds[1:-1], np.arange(W), side='right')
masks = [np.zeros((H, W), bool) for _ in range(k)]
def linelike(sl): return (sl[0].stop - sl[0].start) <= 8 and (sl[1].stop - sl[1].start) >= 25
small = [i for i in keep if i not in big and not linelike(objs[i - 1])]   # stray floor-line bits are dropped
for i in big:
    m = lab == i; cnt = np.bincount(seg[np.where(m)[1]], minlength=k)
    if (cnt > cnt.sum() * 0.15).sum() > 1:
        # touching figures: grow each figure's core (the blob's pixels deep inside its own columns, away from the cut)
        # back over the blob, so every pixel goes to the NEAREST figure (no straight cut through hair spikes)
        core = np.zeros((H, W), np.int32)
        for j in range(k):
            lo, hi = bounds[j], bounds[j + 1]; pad = (hi - lo) // 4
            band = np.zeros(W, bool); band[lo + pad:hi - pad] = True
            core[m & band[None, :]] = j + 1
        # grow the cores only THROUGH the blob (geodesic): an outline goes to the figure it is drawn connected to
        sl = ndimage.find_objects(m.astype(int))[0]; mb, near = m[sl], core[sl].copy()
        while True:
            grown = ndimage.grey_dilation(near, size=(3, 3)) * (mb & (near == 0))
            if not grown.any(): break
            near = np.where(grown > 0, grown, near)
        full = np.zeros((H, W), np.int32); full[sl] = near
        for j in range(k): masks[j] |= m & (full == j + 1)
    else:
        masks[int(np.argmax(cnt))] |= m
# small loose bits (outline fragments, sweat drops) go to the NEAREST figure, not to whatever column they sit in
dist = np.stack([ndimage.distance_transform_edt(~m) for m in masks])
for i in small:
    m = lab == i; masks[int(np.argmin(dist[:, m].min(1)))] |= m
for j, m in enumerate(masks):
    assert m.sum() > H * W * 0.01, f'figure {j} not found — check the split (cuts {cuts})'
masks = [ndimage.binary_fill_holes(ndimage.binary_dilation(m, iterations=2)) for m in masks]
floor = max(np.where(m.any(1))[0].max() for m in masks)
heights = [floor - np.where(m.any(1))[0].min() for m in masks]
target = [r * heights[ref] for r in ratios]
s_all = min(1.0, min(h / t for h, t in zip(heights, target)))        # only ever scale down
scale = [t * s_all / h for h, t in zip(heights, target)]

out = np.empty_like(A); out[:] = bg                                  # fresh canvas: no ghosts of the old figures
lab_row = int(H * a.label_frac); out[lab_row:] = A[lab_row:]          # name labels copied as they are
if runs.sum(1).max() > W / 3:                                        # a drawn floor line: redraw it whole, under the feet
    ys = np.where(runs.any(1))[0]; band = np.zeros((H, 1), bool); band[ys.min() - 3:ys.max() + 4] = True
    line = ndimage.binary_dilation(runs0 & band, np.ones((3, 3)))
    out[line] = A[line]
out = Image.fromarray(out.astype(np.uint8))
for j, (m, sc) in enumerate(zip(masks, scale)):
    ys, xs = np.where(m); bx0, bx1, by0, by1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    rgba = np.dstack([A[by0:by1, bx0:bx1], (m[by0:by1, bx0:bx1] * 255)]).astype(np.uint8)
    fig = Image.fromarray(rgba, 'RGBA')
    nw, nh = max(1, round(fig.width * sc)), max(1, round(fig.height * sc))
    fig = fig.resize((nw, nh), Image.LANCZOS)
    cx = (bx0 + bx1) / 2; bottom = by1 + (floor - (by1 - 1))         # keep feet on the same floor line
    out.paste(fig, (round(cx - nw / 2), round(bottom - nh)), fig)
out.save(a.dst)
new = [round(h * s) for h, s in zip(heights, scale)]
print('before', heights, 'ratios', [round(h / heights[ref], 2) for h in heights])
print('after ', new, 'ratios', [round(h / new[ref], 2) for h in new], 'scales', [round(s, 3) for s in scale])
