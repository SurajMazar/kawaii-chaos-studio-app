#!/usr/bin/env python3
"""Voiced strip reel: place the voice clips on the silent reel, duck the music under them, put the mix on the video.

  python scripts/voiceover_mix.py projects/048_fern_cold            # -> voiceover/final_mix.wav + upload/<pid>_strip_reel_voiceover.mp4
  python scripts/voiceover_mix.py projects/048_fern_cold --no-video # only voiceover/final_mix.wav

Reads <project>/voiceover/voiceover.json (Kawaii Chaos Studio → Voiceover tab writes it):
{
 "video": "upload/048_fern_cold_strip_reel.mp4",             # the silent reel (repo-relative)
 "output": "upload/048_fern_cold_strip_reel_voiceover.mp4",  # optional, this is the default
 "lines": [{"id": "l1", "character": "Stark", "text": "Take my scarf.", "at": 2.1, "clip": "stark1.wav", "gain_db": 0}],
 "music": {"file": "bg_little_mischief.mp3", "gain_db": -10, "start": 0, "fade_in": 0.6, "fade_out": 1.8, "duck": true},
 "loudness": -16
}
Clip and music files live in voiceover/. Every clip at its time, music -10 dB sidechain-ducked by the voices, fade in
0.6 s / out 1.8 s, loudnorm -16 LUFS, video stream copied.
"""
import argparse, json, os, subprocess, sys, tempfile  # nosec B404 - argument lists only

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
SR = 48000


def duration(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],  # nosec B603 B607
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def inside(base, rel):
    p = os.path.abspath(os.path.join(base, rel))
    if not p.startswith(os.path.abspath(base) + os.sep): sys.exit(f'refusing a path outside {base}: {rel}')
    return p


def build(cfg, vo_dir, D, out_wav):
    inputs, chains, voices = [], [], []
    for ln in cfg.get('lines', []):
        if not ln.get('clip'): continue
        f = inside(vo_dir, ln['clip'])
        if not os.path.isfile(f): sys.exit(f"line {ln.get('id', '?')}: clip not found: {ln['clip']}")
        i = len(inputs) // 2; ms = max(0, int(round(float(ln.get('at', 0)) * 1000)))
        inputs += ['-i', f]
        chains.append(f"[{i}:a]aresample={SR},aformat=channel_layouts=stereo,volume={float(ln.get('gain_db', 0)):.2f}dB,"
                      f"adelay={ms}:all=1[v{i}]")
        voices.append(f'[v{i}]')
    m = cfg.get('music') or {}
    if not voices and not m.get('file'): sys.exit('nothing to mix: add a voice clip or music')
    if voices:
        chains.append(f"{''.join(voices)}amix=inputs={len(voices)}:normalize=0:duration=longest,apad=whole_dur={D},atrim=0:{D}"
                      + (',asplit=2[vo][vosc]' if m.get('file') and m.get('duck', True) else '[vo]'))
    mix = ['[vo]'] if voices else []
    if m.get('file'):
        f = inside(vo_dir, m['file'])
        if not os.path.isfile(f): sys.exit(f"music not found: {m['file']}")
        i = len(inputs) // 2; st = max(0.0, float(m.get('start', 0)))
        fi, fo = max(0.0, float(m.get('fade_in', 0.6))), max(0.0, float(m.get('fade_out', 1.8)))
        inputs += ['-i', f]
        chain = (f"[{i}:a]aresample={SR},aformat=channel_layouts=stereo,atrim=start={st}:end={st + D},asetpts=PTS-STARTPTS,"
                 f"volume={float(m.get('gain_db', -10)):.2f}dB,apad=whole_dur={D}")
        if fi: chain += f',afade=t=in:d={fi}'
        if fo: chain += f',afade=t=out:st={max(0.0, D - fo)}:d={fo}'
        if voices and m.get('duck', True):
            chains.append(chain + '[mu]')
            chains.append('[mu][vosc]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=300[mud]')
            mix.append('[mud]')
        else:
            chains.append(chain + '[mu]'); mix.append('[mu]')
    lufs = float(cfg.get('loudness', -16))
    chains.append(f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:duration=longest,atrim=0:{D},"
                  f"loudnorm=I={lufs}:TP=-1.5:LRA=11[o]")
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *inputs, '-filter_complex', ';'.join(chains),  # nosec B603 B607
                    '-map', '[o]', '-ar', str(SR), '-c:a', 'pcm_s16le', out_wav], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('project'); ap.add_argument('--no-video', action='store_true')
    a = ap.parse_args()
    proj = os.path.abspath(a.project); pid = os.path.basename(proj.rstrip('/'))
    vo_dir = os.path.join(proj, 'voiceover')
    cfg = json.load(open(os.path.join(vo_dir, 'voiceover.json')))
    video = inside(ROOT, cfg.get('video') or f'upload/{pid}_strip_reel.mp4')
    if not os.path.isfile(video): sys.exit(f'the silent reel is missing: {os.path.relpath(video, ROOT)} (build the strip reel first)')
    D = round(duration(video), 3)
    print('1/3 mixing the voices and music', flush=True)
    final = os.path.join(vo_dir, 'final_mix.wav')
    fd, tmp = tempfile.mkstemp(dir=vo_dir, prefix='.mix.', suffix='.tmp.wav'); os.close(fd)
    try:
        build(cfg, vo_dir, D, tmp); os.replace(tmp, final)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    print(f'2/3 wrote {os.path.relpath(final, ROOT)} ({D:.2f} s)', flush=True)
    if a.no_video: return
    out = inside(ROOT, cfg.get('output') or f'upload/{pid}_strip_reel_voiceover.mp4')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + '.rendering.mp4'
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', video, '-i', final, '-map', '0:v:0', '-map', '1:a:0',  # nosec B603 B607
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-t', str(D), '-movflags', '+faststart', tmp], check=True)
    os.replace(tmp, out)
    print(f'3/3 wrote {os.path.relpath(out, ROOT)}', flush=True)


if __name__ == '__main__':
    main()
