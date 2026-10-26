#!/usr/bin/env python3
"""Numbered project folders (owner, 2026-10-10: "serial number in front so I can sort by order").

Comic strips live in projects/NNN_<name>/ (3 digits), music videos in music_videos/NN_<name>/ (2 digits), numbered in
creation order. Upload files carry the same prefix (upload/046_rem_puck_strip_reel.mp4, upload/music_videos/05_lasttrain_reel.mp4).

    python3 scripts/new_project.py rem_new_idea                 # -> projects/124_rem_new_idea (created)
    python3 scripts/new_project.py lasttrain --kind music_videos
Existing names resolve to their folder (rem_puck -> projects/046_rem_puck), so it is safe to call twice.
"""
import argparse, glob, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIDTH = {'projects': 3, 'music_videos': 2}


def folder(name, kind='projects', create=True):
    """Path of the numbered folder for `name` (bare or already numbered); creates the next number if new."""
    top = os.path.join(ROOT, kind)
    bare = re.sub(r'^\d+_', '', name)
    hit = [p for p in glob.glob(os.path.join(top, '*')) if os.path.isdir(p)
           and re.fullmatch(r'\d+_' + re.escape(bare), os.path.basename(p))]
    if hit: return hit[0]
    nums = [int(m.group(1)) for p in os.listdir(top) if (m := re.match(r'(\d+)_', p))] if os.path.isdir(top) else []
    path = os.path.join(top, f'{max(nums, default=0) + 1:0{WIDTH[kind]}d}_{bare}')
    if create: os.makedirs(path, exist_ok=True)
    return path


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('name'); ap.add_argument('--kind', default='projects', choices=list(WIDTH))
    a = ap.parse_args()
    print(os.path.relpath(folder(a.name, a.kind), ROOT))
