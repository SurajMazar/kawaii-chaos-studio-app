#!/usr/bin/env python3
"""Sync captions.json, posting_log.json and the README table with every project that has a strip + reel.

    python3 scripts/update_trackers.py

Captions and song ideas are read from projects/<name>/synopsis.md ("**Caption:**" block, "**Song ideas" line).
Existing posted/song fields in posting_log.json are kept.
"""
import json, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(ROOT, *a)
base = lambda n: re.sub(r'^\d+_', '', n)   # projects are numbered in creation order: 001_rem_jacket

COUPLE: dict = {}      # optional: project-name prefix -> couple, e.g. {'rem': 'Subaru x Rem'}


def parse(name):
    s = open(P('projects', name, 'synopsis.md')).read()
    cap = songs = None
    m = re.search(r'\*\*Caption:\*\*\s*\n\n(.*?)(?:\n\n\*\*Song|\Z)', s, re.S)
    if m:
        cap = m.group(1).strip()
    else:  # older synopses: "**Caption draft:** line" + hashtags paragraph
        m = re.search(r'\*\*Caption(?: draft)?:\*\*\s*(.+?)\n\n(#.+?)\n', s, re.S)
        if m: cap = m.group(1).strip() + '\n\n' + m.group(2).strip()
    m = re.search(r'\*\*Song ideas[^:]*:\*\*\s*(.+)', s)
    songs = m.group(1).strip() if m else None
    return cap, songs


def main():
    names = sorted(n for n in os.listdir(P('projects'))
                   if os.path.exists(P('projects', n, 'strip.png')) and os.path.exists(P('upload', f'{n}_strip_reel.mp4')))
    caps = json.load(open(P('captions.json')))
    log = json.load(open(P('posting_log.json')))
    have = {(p['project'], p['format']) for p in log['posts']}
    rows = []
    for n in names:
        cap, songs = parse(n)
        if cap and n not in caps: caps[n] = cap
        first = (open(P('projects', n, 'synopsis.md')).readline() if os.path.exists(P('projects', n, 'synopsis.md')) else '')
        m = re.search(r'\(([^(),]+?\s[x×]\s[^(),]+?)[,)]', first)
        couple = m.group(1).replace('×', 'x').strip() if m else COUPLE.get(base(n).split('_')[0], '?')
        for fmt, f in (('image', f'upload/{n}_strip.png'), ('strip_reel', f'upload/{n}_strip_reel.mp4')):
            if (n, fmt) not in have:
                e = {'project': n, 'couple': couple, 'format': fmt, 'posted': False, 'status': 'ready', 'file': f}
                if fmt == 'strip_reel': e.update(song=None, song_ideas=songs)
                log['posts'].append(e)
        posted = {p['format']: p for p in log['posts'] if p['project'] == n}
        img = posted.get('image', {}); reel = posted.get('strip_reel', {})
        mark = lambda p: (f"✅ {p.get('date', '')} [post]({p['url']})" if p.get('posted') and p.get('url') else ('✅' if p.get('posted') else '⏸ ready'))
        rows.append(f"| `{n}` | {couple} | {mark(img)} | {mark(reel)} | {reel.get('song') or '—'} | {songs or ''} |")
    json.dump(caps, open(P('captions.json'), 'w'), indent=1, ensure_ascii=False)
    json.dump(log, open(P('posting_log.json'), 'w'), indent=1, ensure_ascii=False)
    r = open(P('README.md')).read()
    head, _, _ = r.partition('## Posts')
    table = ('## Posts\n\n| Project | Couple | Strip (image) | Strip reel | Song used | Song ideas |\n'
             '|---|---|---|---|---|---|\n' + '\n'.join(rows) + '\n')
    open(P('README.md'), 'w').write(head + table)
    print(len(names), 'projects tracked;', sum(1 for p in log['posts'] if p.get('posted')), 'posted')


if __name__ == '__main__':
    main()
