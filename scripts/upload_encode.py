#!/usr/bin/env python3
"""Make Instagram-web-ready copies (<10 MB, the Chrome-MCP upload limit) of rendered reels.

    python3 scripts/upload_encode.py            # every projects/*/reel.mp4 and */strip_reel/strip_reel.mp4
    python3 scripts/upload_encode.py news wfh   # only these projects

Writes projects/upload/<project>.mp4 and projects/upload/<project>_strip_reel.mp4 (2-pass H.264, ~9.3 MB budget).
Skips outputs that are newer than their source. Stand-alone strip reels in projects/comics/strip_reels/<name>/ are
written as projects/upload/strip_<name>.mp4.
"""
import glob, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'projects', 'upload')
BUDGET = 9.3e6  # bytes


def dur(p):
    from media_info import duration
    return duration(p)


def enc(src, dst):
    if os.path.exists(dst) and os.path.getmtime(dst) > os.path.getmtime(src):
        return 'up to date'
    vb = int((BUDGET * 8 / dur(src) - 128000) / 1000)
    rate = ['-c:v', 'libx264', '-preset', 'slow', '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-b:v', f'{vb}k',
            '-maxrate', f'{vb * 3 // 2}k', '-bufsize', f'{vb * 2}k']
    log = os.path.join(OUT, '_2pass')
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', src, *rate, '-pass', '1', '-passlogfile', log, '-an',
                    '-f', 'mp4', os.devnull], check=True)
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-i', src, *rate, '-pass', '2', '-passlogfile', log,
                    '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', dst], check=True)
    for f in glob.glob(log + '*'): os.remove(f)
    return f'{os.path.getsize(dst) / 1e6:.1f} MB'


def main():
    os.makedirs(OUT, exist_ok=True)
    only = set(sys.argv[1:])
    jobs = []
    for p in sorted(glob.glob(os.path.join(ROOT, 'projects', '*', 'reel.mp4'))):
        n = os.path.basename(os.path.dirname(p)); jobs.append((n, p, f'{n}.mp4'))
    for p in sorted(glob.glob(os.path.join(ROOT, 'projects', '*', 'strip_reel', 'strip_reel.mp4'))):
        n = os.path.basename(os.path.dirname(os.path.dirname(p))); jobs.append((n, p, f'{n}_strip_reel.mp4'))
    for p in sorted(glob.glob(os.path.join(ROOT, 'projects', 'comics', 'strip_reels', '*', 'strip_reel.mp4'))):
        n = os.path.basename(os.path.dirname(p)); jobs.append((n, p, f'strip_{n}.mp4'))
    for n, src, out in jobs:
        if only and n not in only: continue
        print(f'{out:40s}', enc(src, os.path.join(OUT, out)), flush=True)


if __name__ == '__main__':
    main()
