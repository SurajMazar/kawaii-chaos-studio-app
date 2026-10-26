#!/usr/bin/env python3
"""Generate music beds and sound effects locally with open-source models.

  python gen_audio.py music "cozy lofi piano, warm, gentle, 90 bpm" --seconds 20 --out audio/music.wav
  python gen_audio.py sfx "cartoon rubber stamp thud on paper" --seconds 1.5 --out audio/stamp.wav

Engines (auto-picked; override with --engine):
  musicgen      facebook/musicgen-small via transformers. Music only. Ungated.
                Weights are CC-BY-NC 4.0 = NON-COMMERCIAL use only.
  stable-audio  stabilityai/stable-audio-open-1.0 via diffusers. Music AND sound effects, max 47s.
                Gated: accept the licence on Hugging Face and `huggingface-cli login` once.
                Stability AI Community Licence (free under $1M annual revenue).

Setup (once):  pip install torch transformers diffusers soundfile accelerate
Runs on Apple Silicon (MPS), CUDA or CPU. First run downloads the weights (~1.2-3GB).
If neither engine is available, use the built-in synthesised SFX in audio.py (no model needed).
"""
import argparse, os, sys
import numpy as np

def device():
    import torch
    if torch.cuda.is_available(): return 'cuda'
    if getattr(torch.backends, 'mps', None) and torch.backends.mps.is_available(): return 'mps'
    return 'cpu'

def musicgen(prompt, seconds, seed):
    import torch
    from transformers import AutoProcessor, MusicgenForConditionalGeneration
    torch.manual_seed(seed)
    name = os.environ.get('MUSICGEN_MODEL', 'facebook/musicgen-small')
    proc = AutoProcessor.from_pretrained(name)
    model = MusicgenForConditionalGeneration.from_pretrained(name).to(device())
    inputs = proc(text=[prompt], padding=True, return_tensors='pt').to(model.device)
    tokens = int(seconds * model.config.audio_encoder.frame_rate)
    out = model.generate(**inputs, do_sample=True, guidance_scale=3.0, max_new_tokens=tokens)
    return out[0, 0].float().cpu().numpy(), model.config.audio_encoder.sampling_rate

def stable_audio(prompt, seconds, seed, steps=100):
    import torch
    from diffusers import StableAudioPipeline
    dev = device(); dtype = torch.float16 if dev == 'cuda' else torch.float32
    pipe = StableAudioPipeline.from_pretrained('stabilityai/stable-audio-open-1.0', torch_dtype=dtype).to(dev)
    g = torch.Generator('cpu').manual_seed(seed)
    audio = pipe(prompt, negative_prompt='low quality, noise, distortion, music' if seconds < 5 else 'low quality, distortion',
                 num_inference_steps=steps, audio_end_in_s=min(seconds, 47), num_waveforms_per_prompt=1, generator=g).audios
    return audio[0].T.float().cpu().numpy(), pipe.vae.sampling_rate

def finish(x, sr, kind):
    x = np.asarray(x, np.float32)
    if kind == 'sfx':  # trim silence at the start so the hit lands on the event time
        mono = np.abs(x if x.ndim == 1 else x.mean(1)); idx = np.where(mono > 0.02 * mono.max())[0]
        if len(idx): x = x[max(0, idx[0] - int(.005 * sr)):]
    f_in, f_out = int(.004 * sr), int((.02 if kind == 'sfx' else 1.0) * sr)
    env = np.ones(len(x), np.float32); env[:f_in] = np.linspace(0, 1, f_in); env[-f_out:] *= np.linspace(1, 0, f_out)
    x = x * (env if x.ndim == 1 else env[:, None])
    return x / (np.abs(x).max() + 1e-9) * .9

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('kind', choices=['music', 'sfx']); ap.add_argument('prompt')
    ap.add_argument('--seconds', type=float, default=10); ap.add_argument('--out', required=True)
    ap.add_argument('--engine', choices=['musicgen', 'stable-audio']); ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--steps', type=int, default=100)
    a = ap.parse_args()
    eng = a.engine or ('musicgen' if a.kind == 'music' else 'stable-audio')
    if a.kind == 'sfx' and eng == 'musicgen': sys.exit('musicgen cannot make sound effects; use --engine stable-audio')
    try:
        x, sr = musicgen(a.prompt, a.seconds, a.seed) if eng == 'musicgen' else stable_audio(a.prompt, a.seconds, a.seed, a.steps)
    except ImportError as e:
        sys.exit(f'missing package ({e}). pip install torch transformers diffusers soundfile accelerate')
    import soundfile as sf
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    sf.write(a.out, finish(x, sr, a.kind), sr); print('wrote', a.out)
