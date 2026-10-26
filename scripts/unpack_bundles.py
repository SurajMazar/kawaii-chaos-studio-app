#!/usr/bin/env python3
"""Unpack ChatGPT result bundles (~/Downloads/*_bundle*.bin, written by the in-page pump) into projects/NNN_<base>/raw/.

Bundle = 10-char length header + JSON [{name, size}] + the PNG blobs. Job names: <base>[_charsheet][_<variant>] where the
variant is b-h or v<digit><letter>; files land as raw/{charsheet|strip}_<variant><k>.png (variant 'a' when none).
"""
import json, os, glob, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = []
for f in sorted(glob.glob(os.path.expanduser('~/Downloads/*_bundle*.bin')), key=os.path.getmtime):
    b = open(f, 'rb').read(); n = int(b[:10]); meta = json.loads(b[10:10 + n]); o = 10 + n; keep = False
    for m in meta:
        name = m['name'][:-4]; data = b[o:o + m['size']]; o += m['size']
        kind = 'charsheet' if '_charsheet' in name else 'strip'
        base = name.replace('_charsheet', '')
        mm = re.search(r'_(v\d[a-z]?|[b-h])$', base); variant = mm.group(1) if mm else 'a'
        base = base[:mm.start()] if mm else base
        projs = glob.glob(os.path.join(ROOT, 'projects', f'*_{base}'))
        if not projs: print('no project for', name, '(bundle kept)'); keep = True; continue
        raw = os.path.join(projs[0], 'raw'); os.makedirs(raw, exist_ok=True)
        k = 1
        while os.path.exists(f'{raw}/{kind}_{variant}{k}.png'): k += 1
        dst = f'{raw}/{kind}_{variant}{k}.png'; open(dst, 'wb').write(data); out.append(os.path.relpath(dst, ROOT))
    if not keep: os.remove(f)
print('\n'.join(out) or 'nothing')
