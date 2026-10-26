#!/usr/bin/env python3
"""Synthesised background-music styles for comic reels (so every reel doesn't get the same lo-fi loop).

    from music_styles import generate, STYLES
    mus = generate('pizzicato', length=30, mood='happy', seed=3)   # mono float array at 44.1 kHz, peak 1.0

Styles (pick one per reel to match its format):
  lofi       soft keys + shaker (the original bed)          — cozy, default
  chiptune   square-wave arps, pulse bass, noise hats        — video-game / RPG / tech
  pizzicato  plucky staccato strings + woodblock             — sneaky / courtroom / "oops" comedy
  jazz       swing e-piano 7ths, walking bass, brushes       — smug / cooking show / talk show
  musicbox   waltz bells + soft pad                          — dreamy / bedtime / cute
  bossa      nylon-guitar syncopation, bass, shaker          — chill / cafe / vacation
  synthwave  detuned saw pad, 8th bass, 80s drums, arp       — dramatic / heist / montage
  ukulele    happy strums + claps                            — upbeat / sunny / wholesome
  suspense   low drone, ticking clock, heartbeat, stabs      — thriller / waiting / tension

Every call is seeded: `seed` changes key, chord progression and melody, so two reels with the same style still differ.
"""
import numpy as np
from scipy.signal import butter, sosfilt

SR = 44100
STYLES = ['lofi', 'chiptune', 'pizzicato', 'jazz', 'musicbox', 'bossa', 'synthwave', 'ukulele', 'suspense']
DEFAULT_BPM = {'lofi': 92, 'chiptune': 140, 'pizzicato': 112, 'jazz': 120, 'musicbox': 96, 'bossa': 124,
               'synthwave': 108, 'ukulele': 118, 'suspense': 80}


def t_(d): return np.arange(int(SR * d)) / SR
def lp(x, f, o=2): return sosfilt(butter(o, f, 'low', fs=SR, output='sos'), x)
def hp(x, f, o=2): return sosfilt(butter(o, f, 'high', fs=SR, output='sos'), x)
def bp(x, lo, hi, o=2): return sosfilt(butter(o, [lo, hi], 'band', fs=SR, output='sos'), x)
def nf(n): return 440 * 2 ** ((n - 69) / 12)


def env(d, a=.004, rel=.05, dec=None):
    t = t_(d); e = np.minimum(1, t / a)
    if dec: e = e * np.exp(-t * dec)
    r = min(int(rel * SR), len(t))
    if r: e[-r:] *= np.linspace(1, 0, r)
    return e


# ------------------------------------------------------------------ instruments
def square(f, d, duty=.5, dec=2.0):
    t = t_(d); ph = (f * t) % 1
    return np.where(ph < duty, 1.0, -1.0) * env(d, .002, .02, dec) * .5

def tri(f, d, dec=1.5):
    t = t_(d); ph = (f * t) % 1
    return (4 * np.abs(ph - .5) - 1) * env(d, .003, .03, dec)

def pluck(f, d, bright=1.0, dec=3.0):
    """Plucked string: harmonics with faster decay up the series (guitar / pizz / uke)."""
    t = t_(d); s = np.zeros_like(t)
    for h in range(1, 9):
        if f * h > 9000: break
        s += (bright ** (h - 1)) / h * np.sin(2 * np.pi * f * h * t) * np.exp(-t * dec * (1 + .55 * (h - 1)))
    return s * env(d, .0015, .02)

def epiano(f, d, dec=1.2):
    t = t_(d); mod = np.sin(2 * np.pi * f * 2 * t) * 1.2 * np.exp(-t * 4)
    s = np.sin(2 * np.pi * f * t + mod) + .25 * np.sin(2 * np.pi * f * 3 * t) * np.exp(-t * 3)
    return s * env(d, .004, .08, dec) * (1 + .1 * np.sin(2 * np.pi * 5 * t))

def bellv(f, d, dec=2.5):
    t = t_(d); s = np.zeros_like(t)
    for m, a, dd in [(1, 1, 1), (2.0, .4, 1.5), (3.01, .2, 2.2), (4.2, .12, 3)]:
        s += a * np.sin(2 * np.pi * f * m * t) * np.exp(-t * dec * dd)
    return s * env(d, .002, .03)

def saw_pad(f, d, rng):
    t = t_(d); s = np.zeros_like(t)
    for det in (-.006, 0, .006):
        ph = (f * (1 + det) * t + rng.uniform()) % 1; s += 2 * ph - 1
    return lp(s / 3, 1800) * env(d, .25, .3)

def sine_pad(f, d):
    t = t_(d); return (np.sin(2 * np.pi * f * t) + .3 * np.sin(2 * np.pi * f * 2 * t)) * env(d, .4, .5)

def kick(d=.35):
    t = t_(d); f = 45 + 110 * np.exp(-t * 28)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9) * env(d, .001, .02)

def snare(rng, d=.18):
    t = t_(d); return (hp(rng.normal(0, 1, len(t)), 1500) * .7 + np.sin(2 * np.pi * 190 * t) * .4) * np.exp(-t * 22)

def hat(rng, d=.05, open_=False):
    t = t_(d); return hp(rng.normal(0, 1, len(t)), 7000) * np.exp(-t * (18 if open_ else 70))

def shaker(rng, d=.08):
    t = t_(d); return bp(rng.normal(0, 1, len(t)), 4000, 9000) * np.minimum(1, t / .01) * np.exp(-t * 35)

def woodblock(d=.12):
    t = t_(d); return (np.sin(2 * np.pi * 900 * t) + .5 * np.sin(2 * np.pi * 1340 * t)) * np.exp(-t * 45)

def clap(rng, d=.2):
    t = t_(d); n = bp(rng.normal(0, 1, len(t)), 900, 3500)
    e = sum(np.exp(-np.maximum(t - o, 0) * 60) * (t >= o) for o in (0, .012, .024)) / 3
    return n * e

def noise_hat(rng, d=.04):  # chiptune noise channel
    t = t_(d); return np.sign(rng.normal(0, 1, len(t))) * np.exp(-t * 80) * .5


# ------------------------------------------------------------------ harmony
PROGS = {
    'happy': [[0, 4, 7], [7, 11, 14], [9, 12, 16], [5, 9, 12]],          # I V vi IV
    'happy2': [[0, 4, 7], [9, 12, 16], [5, 9, 12], [7, 11, 14]],         # I vi IV V
    'happy3': [[5, 9, 12], [7, 11, 14], [4, 7, 11], [9, 12, 16]],        # IV V iii vi
    'jazzy': [[2, 5, 9, 12], [7, 11, 14, 17], [0, 4, 7, 11], [9, 13, 16, 19]],  # ii7 V7 Imaj7 VI7
    'sad': [[9, 12, 16], [5, 9, 12], [0, 4, 7], [7, 11, 14]],            # vi IV I V
    'sad2': [[0, 3, 7], [8, 12, 15], [3, 7, 10], [10, 14, 17]],          # i VI III VII
    'tense': [[0, 3, 7], [1, 5, 8], [0, 3, 7], [11, 14, 17]],            # i bII i VII (phrygian-ish)
}
MAJOR = [0, 2, 4, 5, 7, 9, 11]
MINOR = [0, 2, 3, 5, 7, 8, 10]


class Song:
    def __init__(self, length, bpm, mood, seed, style):
        self.rng = np.random.default_rng(seed * 7919 + STYLES.index(style) * 101 + 17)
        self.L = length; self.beat = 60 / bpm; self.buf = np.zeros(int((length + 4) * SR))
        minor = mood == 'sad' or style == 'suspense'
        if style == 'jazz': pool = ['jazzy']
        elif style == 'suspense': pool = ['tense']
        elif minor: pool = ['sad', 'sad2']
        else: pool = ['happy', 'happy2', 'happy3']
        self.prog = PROGS[pool[self.rng.integers(len(pool))]]
        self.root = 48 + int(self.rng.integers(-3, 5))          # random key
        self.scale = MINOR if (minor and pool != ['sad']) else MAJOR

    def add(self, sig, t0, g=1.0):
        i = int(t0 * SR)
        if i >= len(self.buf) or i < 0: return
        n = min(len(sig), len(self.buf) - i); self.buf[i:i + n] += sig[:n] * g

    def bars(self, beats_per_bar=4):
        b, t = 0, 0.0
        while t < self.L:
            yield b, t, [self.root + n for n in self.prog[b % len(self.prog)]]
            b += 1; t = b * beats_per_bar * self.beat

    def melody(self, n_notes, octave=24, span=7):
        """Seeded random walk over the scale (stays singable, returns MIDI notes)."""
        deg = int(self.rng.integers(0, 5)); out = []
        for _ in range(n_notes):
            deg = int(np.clip(deg + self.rng.choice([-2, -1, -1, 0, 1, 1, 2, 3]), -2, span))
            o, d = divmod(deg, 7); out.append(self.root + octave + 12 * o + self.scale[d])
        return out

    def done(self):
        x = lp(self.buf[:int(self.L * SR)], 8500)   # tame fizzy highs so it sits under the voice
        return x / (np.abs(x).max() + 1e-9)


# ------------------------------------------------------------------ styles
def _chiptune(s):
    b = s.beat; mel = s.melody(64, 24)
    for bar, t0, ch in s.bars():
        for k in range(16):  # 16th arps
            s.add(square(nf(ch[k % len(ch)] + 12), b / 4, .25, 6), t0 + k * b / 4, .22)
        for k in range(8):
            s.add(tri(nf(ch[0] - 12 + (7 if k % 4 == 2 else 0)), b / 2, 2), t0 + k * b / 2, .5)
            s.add(noise_hat(s.rng), t0 + k * b / 2 + b / 4, .25)
        for k in range(4):
            if k % 2 == 0: s.add(kick(.2), t0 + k * b, .5)
            if s.rng.random() < .8:
                n = mel[(bar * 4 + k) % len(mel)]; s.add(square(nf(n), b * .9, .5, 1.5), t0 + k * b, .2)

def _pizzicato(s):
    b = s.beat; mel = s.melody(64, 24, 9)
    for bar, t0, ch in s.bars():
        for k in range(4):  # bass on beats, chord stab on the "and"
            s.add(pluck(nf(ch[0] - 12 + (7 if k % 2 else 0)), b * .6, .6, 9), t0 + k * b, .55)
            for j, n in enumerate(ch): s.add(pluck(nf(n + 12), b * .3, .5, 16), t0 + (k + .5) * b + j * .006, .12)
        for k in range(8):  # tiptoe melody, some rests
            if s.rng.random() < .65:
                n = mel[(bar * 8 + k) % len(mel)]; s.add(pluck(nf(n), b * .35, .7, 14), t0 + k * b / 2, .3)
        if bar % 2 == 1: s.add(woodblock(), t0 + 3.5 * b, .25)

def _jazz(s):
    b = s.beat; sw = b * 2 / 3
    for bar, t0, ch in s.bars():
        walk = [ch[0] - 12, ch[1] - 12, ch[2] - 12, ch[0] - 11 + int(s.rng.choice([1, -2, 4]))]
        for k in range(4):
            s.add(pluck(nf(walk[k]), b * .95, .3, 4), t0 + k * b, .6)
            s.add(hat(s.rng, .08), t0 + k * b, .12); s.add(hat(s.rng, .05), t0 + k * b + sw, .08)
        for k in (1, 3):
            off = t0 + k * b + (sw if s.rng.random() < .4 else 0)
            for n in ch: s.add(epiano(nf(n + 12), b * 1.2, 1.6), off, .16)
        mel = s.melody(6, 24)
        for k in range(4):
            if s.rng.random() < .5: s.add(epiano(nf(mel[k]), b * .8, 2.5), t0 + k * b + (sw if k % 2 else 0), .12)

def _musicbox(s):
    b = s.beat; mel = s.melody(96, 36, 8)
    for bar, t0, ch in s.bars(3):  # waltz
        s.add(sine_pad(nf(ch[0]), b * 3.2), t0, .25); s.add(sine_pad(nf(ch[2]), b * 3.2), t0, .15)
        for k in range(3):
            s.add(bellv(nf(mel[(bar * 3 + k) % len(mel)]), b * 2, 2.2), t0 + k * b, .35)
            if k: s.add(bellv(nf(ch[k % len(ch)] + 24), b, 4), t0 + k * b, .12)

def _bossa(s):
    b = s.beat; hits = [0, 1.5, 3, 4.5, 6, 7.5 - 1, 7]  # in 8ths over 2 bars-ish
    for bar, t0, ch in s.bars():
        for h in [0, 1.5, 2.5, 3.5]:
            for j, n in enumerate(ch): s.add(pluck(nf(n + 12), b * .7, .55, 6), t0 + h * b + j * .008, .14)
        for h, n in [(0, ch[0] - 12), (1.5, ch[2] - 12), (2, ch[2] - 12), (3.5, ch[0] - 12)]:
            s.add(pluck(nf(n), b * .9, .3, 3), t0 + h * b, .5)
        for k in range(8): s.add(shaker(s.rng), t0 + k * b / 2, .12 if k % 2 else .2)
        s.add(woodblock(.08), t0 + 2.5 * b, .1)

def _synthwave(s):
    b = s.beat; mel = s.melody(48, 24)
    for bar, t0, ch in s.bars():
        for n in ch: s.add(saw_pad(nf(n + 12), b * 4.1, s.rng), t0, .14)
        for k in range(8): s.add(lp(np.sign(np.sin(2 * np.pi * nf(ch[0] - 12) * t_(b / 2))) * env(b / 2, .003, .03, 3), 900), t0 + k * b / 2, .35)
        for k in range(4):
            s.add(kick(), t0 + k * b, .6)
            if k % 2: s.add(lp(snare(s.rng, .25), 5000), t0 + k * b, .3)
            s.add(hat(s.rng), t0 + k * b + b / 2, .07)
        for k in range(8):
            s.add(square(nf(ch[k % 3] + 24), b / 2, .3, 5), t0 + k * b / 2, .07)
        if bar % 2 == 1:
            for k in range(4): s.add(saw_pad(nf(mel[(bar * 4 + k) % len(mel)] + 12), b, s.rng), t0 + k * b, .1)

def _ukulele(s):
    b = s.beat; pattern = [(0, 1), (1, 1), (1.5, -1), (2.5, -1), (3, 1), (3.5, -1)]  # D D U U D U
    mel = s.melody(64, 24)
    for bar, t0, ch in s.bars():
        voic = [ch[1] + 12, ch[2] + 12, ch[0] + 12, ch[1] + 24]
        for h, dirn in pattern:
            order = voic if dirn > 0 else voic[::-1]
            for j, n in enumerate(order): s.add(pluck(nf(n), b * .9, .55, 5), t0 + h * b + j * .012, .11 if dirn > 0 else .07)
        s.add(pluck(nf(ch[0] - 12), b * 1.8, .3, 2.5), t0, .4); s.add(pluck(nf(ch[2] - 12), b * 1.8, .3, 2.5), t0 + 2 * b, .35)
        s.add(clap(s.rng), t0 + b, .25); s.add(clap(s.rng), t0 + 3 * b, .25)
        if bar % 2 == 0:
            for k in range(4):
                if s.rng.random() < .7: s.add(bellv(nf(mel[(bar * 4 + k) % len(mel)] + 12), b, 3), t0 + k * b, .1)

def _suspense(s):
    b = s.beat
    t = t_(s.L + 1); drone = np.sin(2 * np.pi * nf(s.root - 12) * t) + .5 * np.sin(2 * np.pi * nf(s.root - 5) * t * 1.003)
    s.add(lp(drone, 500) * np.minimum(1, t / 2), 0, .35)
    for bar, t0, ch in s.bars():
        for k in range(4):
            s.add(woodblock(.05) * .6, t0 + k * b, .2)                    # clock tick
            if k in (0, 1): s.add(kick(.25), t0 + k * b + (.22 if k else 0), .35)  # heartbeat (lub-dub)
        if bar % 2 == 1:
            for n in ch: s.add(saw_pad(nf(n), b * 1.2, s.rng) * env(b * 1.2, .01, .3, 3), t0 + 3 * b, .25)

def _lofi(s):
    from audio import lofi  # original bed
    s.buf[:int(s.L * SR)] = lofi(s.L, int(round(60 / s.beat)), 'sad' if s.prog in (PROGS['sad'], PROGS['sad2']) else 'happy')

GEN = {'chiptune': _chiptune, 'pizzicato': _pizzicato, 'jazz': _jazz, 'musicbox': _musicbox, 'bossa': _bossa,
       'synthwave': _synthwave, 'ukulele': _ukulele, 'suspense': _suspense, 'lofi': _lofi}


def generate(style, length, bpm=None, mood='happy', seed=0):
    if style not in GEN: raise ValueError(f'unknown music style {style!r}; choose from {STYLES}')
    s = Song(length, bpm or DEFAULT_BPM[style], mood, seed, style)
    GEN[style](s)
    return s.done()


if __name__ == '__main__':  # python3 scripts/music_styles.py out_dir  -> one 20 s preview per style
    import os, sys
    from scipy.io import wavfile
    out = sys.argv[1] if len(sys.argv) > 1 else '.'
    os.makedirs(out, exist_ok=True)
    for st in STYLES:
        x = generate(st, 20, seed=1)
        wavfile.write(os.path.join(out, f'{st}.wav'), SR, (x * .8 * 32767).astype(np.int16)); print('wrote', st)
