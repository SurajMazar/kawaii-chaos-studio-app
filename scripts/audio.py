#!/usr/bin/env python3
"""Sound design + final mix for comic-reel.

- Synthesised SFX library (click-free: every sound has a soft attack and a faded tail)
- Optional synthesised lo-fi bed with a "tape stop" (music dies when the mood drops)
- Mix: voiceover (cleaned + compressed) + optional music file (ducked under voice) + SFX bed
  -> loudness-normalised to -14 LUFS, true peak -1.5 dB.

Standalone:  python audio.py storyboard.json   (writes _mix.wav next to the storyboard)
"""
import json, os, subprocess, sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt

SR = 44100
rng = np.random.default_rng(7)

def t_(d): return np.arange(int(SR * d)) / SR
def lp(x, f, o=2): return sosfilt(butter(o, f, 'low', fs=SR, output='sos'), x)
def hp(x, f, o=2): return sosfilt(butter(o, f, 'high', fs=SR, output='sos'), x)

# ------------------------------------------------------------------ SFX library
def bell(f, d=1.0, dec=3.0):
    t = t_(d); s = np.zeros_like(t)
    for m, a, dd in [(1, 1, 1), (2.0, .35, 1.6), (2.76, .25, 2.2), (5.4, .12, 3.5)]:
        s += a * np.sin(2 * np.pi * f * m * t) * np.exp(-t * dec * dd)
    return s * np.minimum(1, t / .002)

def sfx_ding():  # phone notification
    a = bell(1568, .09, 6); b = bell(2093, 1.0, 4)
    out = np.zeros(len(a) // 1 + len(b)); out[:len(a)] += a * .9; out[int(.08 * SR):int(.08 * SR) + len(b)] += b
    return out

def sfx_thump(f0=130, f1=45, d=.4, noise=.5, nlp=1500):  # stamp / impact
    t = t_(d); f = f1 + (f0 - f1) * np.exp(-t / .04)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / .11)
    n = lp(rng.normal(0, 1, len(t)), nlp) * np.exp(-t / .025) * noise
    return (s + n) * np.minimum(1, t / .001)

def sfx_thump_low(): return sfx_thump(90, 35, .6, .6, 900)  # big impact (punchline)

def sfx_slap(d=.12):  # paper slap, layer with thump for stamps
    t = t_(d); return hp(rng.normal(0, 1, len(t)), 1500) * np.exp(-t / .018) * np.minimum(1, t / .002)

def sfx_whoosh(d=.4, f0=300, f1=3500, peak=.6):  # continuous swept band-pass noise
    t = t_(d); n = rng.normal(0, 1, len(t)); fc = f0 * (f1 / f0) ** (t / d)
    F = 2 * np.sin(np.pi * np.minimum(fc, 8000) / SR); lo = bd = 0.0; out = np.zeros_like(t)
    for i in range(len(t)):
        hi = n[i] - lo - .9 * bd; bd += F[i] * hi; lo += F[i] * bd; out[i] = bd
    out /= np.abs(out).max() + 1e-9
    env = np.where(t < peak * d, np.sin(.5 * np.pi * t / (peak * d)) ** 2,
                   np.cos(.5 * np.pi * np.clip((t - peak * d) / (d * (1 - peak)), 0, 1)) ** 2)
    return out * env

def sfx_whoosh_down(): return sfx_whoosh(.35, 2500, 300, .5)
def sfx_riser(): return sfx_whoosh(.18, 500, 6000, .95)  # place ~0.17s BEFORE the hit

def sfx_pop():  # bubble / element appears
    t = t_(.09); f = 320 + 700 * np.clip(t / .05, 0, 1)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / .03) * np.minimum(1, t / .002)

def sfx_shimmer(d=2.2):  # sparkle for end card / reveal
    s = np.zeros(int(d * SR))
    for k, f in enumerate([1318.5, 1568, 1975.5, 2637]):
        b = bell(f, d - k * .07, 2.2); i = int(k * .07 * SR); s[i:i + len(b)] += b * .4
    return s

def sfx_buzz(d=.42):  # phone vibrating
    t = t_(d)
    return (np.sin(2 * np.pi * 150 * t) + .3 * np.sin(2 * np.pi * 300 * t)) * (.6 + .4 * np.sin(2 * np.pi * 14 * t)) * np.sin(np.pi * t / d) ** .5

SFX = {'ding': sfx_ding, 'thump': sfx_thump, 'thump_low': sfx_thump_low, 'slap': sfx_slap, 'whoosh': sfx_whoosh,
       'whoosh_down': sfx_whoosh_down, 'riser': sfx_riser, 'pop': sfx_pop, 'shimmer': sfx_shimmer, 'buzz': sfx_buzz}
DEFAULT_GAIN = {'ding': .32, 'thump': .55, 'thump_low': .7, 'slap': .22, 'whoosh': .25, 'whoosh_down': .18,
                'riser': .35, 'pop': .32, 'shimmer': .16, 'buzz': .12}

# ------------------------------------------------------------------ synth music
def nf(n): return 440 * 2 ** ((n - 69) / 12)
def keys(f, d):
    t = t_(d); s = np.zeros_like(t)
    for m, a, dd in [(1, 1, 1), (2, .45, 1.8), (3, .18, 2.6), (4, .08, 3.4)]:
        for det in (-.0015, .0015):
            s += a * np.sin(2 * np.pi * f * m * (1 + det) * t + rng.uniform(0, 6)) * np.exp(-t * 1.4 * dd)
    s *= np.minimum(1, t / .004) * (1 + .12 * np.sin(2 * np.pi * 4.5 * t))
    rel = int(.12 * SR); s[-rel:] *= np.linspace(1, 0, rel)
    return lp(s, 3200)

def lofi(length, bpm=92, mood='happy'):
    prog = {'happy': [[53, 57, 60, 64], [52, 55, 59, 62], [50, 53, 57, 60], [48, 52, 55, 59]],
            'sad': [[45, 48, 52, 55], [41, 45, 48, 52], [43, 47, 50, 53], [40, 43, 47, 50]]}[mood]
    beat = 60 / bpm; mus = np.zeros(int((length + 3) * SR))
    def add(sig, t0, g):
        i = int(t0 * SR); n = min(len(sig), len(mus) - i)
        if n > 0: mus[i:i + n] += sig[:n] * g
    bar = 0
    while bar * 2 * beat < length:
        ch = prog[bar % 4]; t0 = bar * 2 * beat
        for k, n in enumerate(ch): add(keys(nf(n), beat * 2.2), t0 + k * .012, .22)
        add(keys(nf(ch[0] - 12), beat * 2.2), t0, .3)
        for j, off in enumerate([0, .75, 1.5]):
            mel = [72, 76, 79, 77, 76, 74, 72, 71, 69, 72, 74, 76][(bar * 3 + j) % 12]
            add(keys(nf(mel), beat * .9) * np.exp(-t_(beat * .9) * 3), t0 + off * beat, .13)
        bar += 1
    for k in range(int(length / beat * 2) + 1):
        sh = hp(rng.normal(0, 1, int(.06 * SR)), 5000) * np.exp(-t_(.06) / .015) * np.minimum(1, t_(.06) / .002)
        add(sh, k * beat / 2, .05 if k % 2 else .025)
    mus = mus[:int(length * SR)]
    return mus / (np.abs(mus).max() + 1e-9)

def tape_stop(x, at, dur=.55):
    i0 = int(at * SR); n = int(dur * SR)
    idx = i0 + np.cumsum(np.linspace(1, 0, n) ** 1.4)
    seg = np.interp(idx, np.arange(len(x)), x) * np.linspace(1, 0, n) ** .7
    return np.concatenate([x[:i0], seg])

def outro_chord(d=3.0):
    s = np.zeros(int(d * SR))
    for k, n in enumerate([53, 57, 60, 64, 67]):
        k_ = keys(nf(n), d - .2) * .5; i = int(k * .11 * SR); s[i:i + len(k_)] += k_[:len(s) - i]
    s[:int((d - .2) * SR)] += keys(nf(41), d - .2) * .6
    return s / (np.abs(s).max() + 1e-9)

# ------------------------------------------------------------------ bed + mix
def load_audio(path):
    p = subprocess.run(['ffmpeg', '-loglevel', 'error', '-i', path, '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'],
                       capture_output=True, check=True)
    return np.frombuffer(p.stdout, np.float32).astype(np.float64)

def build_bed(sb, D, base='.'):
    N = int(D * SR) + SR; L = np.zeros(N); R = np.zeros(N)
    def add(sig, t0, gain, pan=0.0):
        i = int(t0 * SR)
        if i >= N: return
        s = sig[:N - i] * gain
        fo = min(len(s) // 4, int(.02 * SR))
        if fo > 0: s = s.copy(); s[-fo:] *= np.linspace(1, 0, fo)
        l, r = np.cos((pan + 1) * np.pi / 4) * 1.414, np.sin((pan + 1) * np.pi / 4) * 1.414
        L[i:i + len(s)] += s * l; R[i:i + len(s)] += s * r
    m = sb.get('music', {})
    if m.get('synth'):
        until = m.get('until', D)
        if m['synth'] == 'lofi' and 'seed' not in m:
            mus = lofi(min(until + 1, D), m.get('bpm', 92), m.get('mood', 'happy'))
        else:  # any style from music_styles.py (chiptune, pizzicato, jazz, musicbox, bossa, synthwave, ukulele, suspense)
            from music_styles import generate
            mus = generate(m['synth'], min(until + 1, D), m.get('bpm'), m.get('mood', 'happy'), m.get('seed', 0))
        mus = tape_stop(mus, until) if m.get('tape_stop') else mus[:int(until * SR)]
        add(mus * .42 * m.get('volume', 1.0), 0, 1.0)
        if m.get('outro_at') is not None:
            o = outro_chord(D - m['outro_at'])
            o *= np.clip((D - m['outro_at'] - np.arange(len(o)) / SR) / .6, 0, 1)  # sample-exact (t_ can drop a sample)
            add(o * .38 * m.get('volume', 1.0), m['outro_at'], 1.0)
    for e in sb.get('events', []):
        if 'sfx_file' in e:  # generated (gen_audio.py) or downloaded sound file
            add(load_audio(os.path.join(base, e['sfx_file'])), e['t'], e.get('gain', .4), e.get('pan', 0.0)); continue
        if 'sfx' not in e: continue
        name = e['sfx']
        if name not in SFX: print(f'[warn] unknown sfx {name}', file=sys.stderr); continue
        sig = SFX[name](e['dur']) if (name == 'buzz' and 'dur' in e) else SFX[name]()
        add(sig, e['t'], e.get('gain', DEFAULT_GAIN.get(name, .3)), e.get('pan', 0.0))
    st = np.stack([L, R], 1)[:int(D * SR)]
    return st / max(1.0, np.abs(st).max() / .89)

def build_mix(sb, base, D, out_wav):
    bed = os.path.join(base, '_bed.wav')
    wavfile.write(bed, SR, (build_bed(sb, D, base) * 32767).astype(np.int16))
    inputs, chains, mixins = ['-i', bed], ['[0:a]volume=0.55[bed]'], ['[bed]']
    vo = sb.get('voiceover'); idx = 1
    if vo:
        off = int(vo.get('offset', 0) * 1000)
        inputs += ['-i', os.path.join(base, vo['file'])]
        chains.append(f'[{idx}:a]aresample={SR},highpass=f=75,acompressor=threshold=-20dB:ratio=3:attack=5:release=80:makeup=3,'
                      f'equalizer=f=3500:t=q:w=1.2:g=2,adelay={off}|{off},pan=stereo|c0=c0|c1=c0,apad=whole_dur={D}[vo]')
        idx += 1
    m = sb.get('music', {})
    if m.get('file'):
        inputs += ['-i', os.path.join(base, m['file'])]
        st, vol = m.get('start', 0), m.get('volume', .15)
        end = m.get('end', D); fo = m.get('fade_out', 1.0)
        chains.append(f'[{idx}:a]aresample={SR},atrim=0:{end - st},afade=t=out:st={max(0, end - st - fo)}:d={fo},'
                      f'adelay={int(st * 1000)}|{int(st * 1000)},volume={vol},apad=whole_dur={D}[mu]')
        if vo and m.get('duck', True):
            chains[1] = chains[1].replace('[vo]', ',asplit=2[vo][vosc]')
            chains.append('[mu][vosc]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=300[mud]')
            mixins.append('[mud]')
        else:
            mixins.append('[mu]')
    if vo: mixins.insert(0, '[vo]')
    fc = ';'.join(chains) + f";{''.join(mixins)}amix=inputs={len(mixins)}:normalize=0:duration=longest,atrim=0:{D}," \
         f"acompressor=threshold=-20dB:ratio=2.5:attack=4:release=120:makeup=2,alimiter=limit=0.8:level=false," \
         f"loudnorm=I=-14:TP=-1.5:LRA=11[o]"  # glue + tame SFX/bell peaks so loudnorm can reach -14
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *inputs, '-filter_complex', fc,
                    '-map', '[o]', '-ar', '48000', '-c:a', 'pcm_s16le', out_wav], check=True)
    return out_wav

if __name__ == '__main__':
    p = sys.argv[1]; sb = json.load(open(p)); base = os.path.dirname(os.path.abspath(p))
    D = sb.get('output', {}).get('duration') or max(s['end'] for s in sb['shots'])
    print(build_mix(sb, base, D, os.path.join(base, '_mix.wav')))
