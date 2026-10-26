#!/usr/bin/env python3
"""Upscale illustrations 4x with Real-ESRGAN (anime model) on CPU, keeping original colours.

  python upscale.py in.png [more.png ...] [--scale 4] [--outdir upscaled]

Needs `pip install ncnn`. Model files are downloaded once to ~/.cache/comic-reel.
Without ncnn it falls back to Lanczos + light sharpening.
The ESRGAN result is used for edges/detail only; low frequencies (colour, paper texture
tone) come from the original, so the look doesn't shift.
"""
import argparse, os, sys, time, zipfile, urllib.request
import numpy as np, cv2

CACHE = os.path.expanduser('~/.cache/comic-reel')
ZIP_URL = 'https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-ubuntu.zip'
MODEL = 'realesrgan-x4plus-anime'

def model_paths():
    p = os.path.join(CACHE, 'models', MODEL)
    if not os.path.exists(p + '.bin'):
        os.makedirs(CACHE, exist_ok=True); z = os.path.join(CACHE, 'r.zip')
        print('downloading Real-ESRGAN models (~45MB, once)...', file=sys.stderr)
        urllib.request.urlretrieve(ZIP_URL, z)
        with zipfile.ZipFile(z) as f:
            for n in f.namelist():
                if n.startswith('models/') or '/models/' in n:
                    name = n.split('models/')[-1]
                    if name.startswith(MODEL):
                        os.makedirs(os.path.join(CACHE, 'models'), exist_ok=True)
                        open(os.path.join(CACHE, 'models', name), 'wb').write(f.read(n))
        os.remove(z)
    return p + '.param', p + '.bin'

def esrgan(img_bgr, tile=192, pad=12):
    import ncnn
    par, binf = model_paths()
    net = ncnn.Net(); net.opt.num_threads = os.cpu_count() or 2
    net.load_param(par); net.load_model(binf)
    img = img_bgr[:, :, ::-1].astype(np.float32) / 255.
    H, W, _ = img.shape; S = 4
    out = np.zeros((H * S, W * S, 3), np.float32)
    ys, xs = range(0, H, tile), range(0, W, tile); n = len(ys) * len(xs); k = 0; t0 = time.time()
    for y in ys:
        for x in xs:
            y0, x0, y1, x1 = max(0, y - pad), max(0, x - pad), min(H, y + tile + pad), min(W, x + tile + pad)
            ex = net.create_extractor(); ex.input('data', ncnn.Mat(np.ascontiguousarray(img[y0:y1, x0:x1].transpose(2, 0, 1))))
            _, o = ex.extract('output'); o = np.array(o).transpose(1, 2, 0)
            th, tw = (min(H, y + tile) - y) * S, (min(W, x + tile) - x) * S
            out[y * S:y * S + th, x * S:x * S + tw] = o[(y - y0) * S:(y - y0) * S + th, (x - x0) * S:(x - x0) * S + tw]
            k += 1
            if k == 1: print(f'  ~{(time.time() - t0) * n:.0f}s for {n} tiles', file=sys.stderr)
    return (np.clip(out, 0, 1)[:, :, ::-1] * 255).astype(np.float32)

def upscale(path, outdir, scale=4):
    src = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    alpha = src[:, :, 3] if src.ndim == 3 and src.shape[2] == 4 else None
    bgr = src[:, :, :3] if src.ndim == 3 else cv2.cvtColor(src, cv2.COLOR_GRAY2BGR)
    H, W = bgr.shape[:2]
    lan = cv2.resize(bgr, (W * 4, H * 4), interpolation=cv2.INTER_LANCZOS4).astype(np.float32)
    try:
        u = esrgan(bgr); s = 6
        out = cv2.GaussianBlur(lan, (0, 0), s) + (u - cv2.GaussianBlur(u, (0, 0), s)) * .9 + (lan - cv2.GaussianBlur(lan, (0, 0), s)) * .25
    except ImportError:
        print('[warn] ncnn not installed (pip install ncnn) -> Lanczos fallback', file=sys.stderr)
        out = lan + (lan - cv2.GaussianBlur(lan, (0, 0), 2)) * .5
    out = np.clip(out, 0, 255).astype(np.uint8)
    if scale != 4: out = cv2.resize(out, (W * scale, H * scale), interpolation=cv2.INTER_AREA)
    if alpha is not None:
        out = np.dstack([out, cv2.resize(alpha, (out.shape[1], out.shape[0]), interpolation=cv2.INTER_CUBIC)])
    os.makedirs(outdir, exist_ok=True)
    dst = os.path.join(outdir, os.path.basename(path))
    cv2.imwrite(dst, out); print(dst)

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('images', nargs='+')
    ap.add_argument('--scale', type=int, default=4); ap.add_argument('--outdir', default='upscaled')
    a = ap.parse_args()
    for p in a.images: upscale(p, a.outdir, a.scale)
