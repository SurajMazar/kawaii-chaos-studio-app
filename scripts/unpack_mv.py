#!/usr/bin/env python3
"""Unpack ~/Downloads/<name>_bundle*.bin into music_videos/NN_<mv>/raw/<name>.png (the MV twin of unpack_bundles.py).

    python3 scripts/unpack_mv.py 13_rem_lovegrows [prefix]
"""
import json, os, glob, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
mv = sys.argv[1]; prefix = sys.argv[2] if len(sys.argv) > 2 else ''
raw = os.path.join(ROOT, 'music_videos', mv, 'raw'); os.makedirs(raw, exist_ok=True)
for f in sorted(glob.glob(os.path.expanduser(f'~/Downloads/{prefix}*_bundle*.bin')), key=os.path.getmtime):
    b = open(f, 'rb').read(); n = int(b[:10]); meta = json.loads(b[10:10 + n]); o = 10 + n
    for m in meta:
        name = m['name']; dst = os.path.join(raw, name); k = 2
        while os.path.exists(dst): dst = os.path.join(raw, name[:-4] + f'_{k}.png'); k += 1
        open(dst, 'wb').write(b[o:o + m['size']]); o += m['size']; print(os.path.relpath(dst, ROOT))
    os.remove(f)
