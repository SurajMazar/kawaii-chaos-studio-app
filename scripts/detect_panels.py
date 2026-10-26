#!/usr/bin/env python3
"""Find the real panel boxes in a generated comic strip (the art rarely matches the wireframe exactly).

    python3 scripts/detect_panels.py projects/<name>/strip.png [--out projects/<name>/layout/layout_actual.json]

Panels are separated by light cream gutters that connect to the outer margin. Flood-fill the light pixels from the
page edge (after sealing small gaps in the sketchy borders), the remaining big blobs are panels. Writes the same JSON
format as comic_layout.py (normalised quads in reading order) so strip_reel.py --layout can use it, plus a debug png.
"""
import argparse, json, os
import cv2, numpy as np


def detect(img, min_frac=0.03):
    H, W = img.shape[:2]
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    dark = (g < 110).astype(np.uint8)
    dark = cv2.dilate(dark, np.ones((5, 5), np.uint8))           # seal gaps in sketchy borders
    light = ((g > 200) & (dark == 0)).astype(np.uint8)
    # flood fill the gutters from every light pixel on the outer 6px frame
    mask = np.zeros((H + 2, W + 2), np.uint8)
    fill = light.copy() * 255
    for y in list(range(0, 6)) + list(range(H - 6, H)):
        for x in range(0, W, 7):
            if fill[y, x] == 255:
                cv2.floodFill(fill, mask, (x, y), 128)
    for x in list(range(0, 6)) + list(range(W - 6, W)):
        for y in range(0, H, 7):
            if fill[y, x] == 255:
                cv2.floodFill(fill, mask, (x, y), 128)
    gutter = (fill == 128).astype(np.uint8)
    gutter = cv2.morphologyEx(gutter, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    inside = (1 - gutter).astype(np.uint8)
    inside = cv2.morphologyEx(inside, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(inside, 8)
    boxes = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if a > min_frac * H * W and w < 0.995 * W:
            boxes.append((x, y, x + w, y + h))
    # reading order: group into rows by vertical overlap, then left to right
    boxes.sort(key=lambda b: (b[1] + b[3]) / 2)
    rows = []
    for b in boxes:
        cy = (b[1] + b[3]) / 2
        if rows and rows[-1][0][1] < cy < rows[-1][0][3]:
            rows[-1].append(b)
        else:
            rows.append([b])
    ordered = [b for r in rows for b in sorted(r, key=lambda b: b[0])]
    return ordered, [len(r) for r in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('strip')
    ap.add_argument('--out', default='')
    a = ap.parse_args()
    img = cv2.imread(a.strip)
    H, W = img.shape[:2]
    boxes, rows = detect(img)
    out = a.out or os.path.join(os.path.dirname(a.strip), 'layout', 'layout_actual.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    pad = 3
    panels = [[[round((x0 + pad) / W, 4), round((y0 + pad) / H, 4)], [round((x1 - pad) / W, 4), round((y0 + pad) / H, 4)],
               [round((x1 - pad) / W, 4), round((y1 - pad) / H, 4)], [round((x0 + pad) / W, 4), round((y1 - pad) / H, 4)]]
              for x0, y0, x1, y1 in boxes]
    json.dump({'rows': rows, 'panels': panels}, open(out, 'w'), indent=1)
    dbg = img.copy()
    for k, (x0, y0, x1, y1) in enumerate(boxes):
        cv2.rectangle(dbg, (x0, y0), (x1, y1), (0, 0, 255), 4)
        cv2.putText(dbg, str(k + 1), (x0 + 12, y0 + 60), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 5)
    cv2.imwrite(out.replace('.json', '_debug.jpg'), cv2.resize(dbg, (W // 2, H // 2)))
    print(f'{len(boxes)} panels, rows {rows} -> {out}')


if __name__ == '__main__':
    main()
