#!/usr/bin/env python3
"""Draws the app icon (pink rounded square, "KC" in Baloo 2) and turns it into icon.icns with macOS iconutil.

    python desktop/make_icon.py     # -> desktop/build/icon.icns
"""
import os, subprocess, sys  # nosec B404
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, '..', 'fonts', 'Baloo2.ttf')


def draw(size: int) -> Image.Image:
    s = size * 4
    im = Image.new('RGBA', (s, s), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    pad = int(s * 0.09)
    d.rounded_rectangle([pad, pad, s - pad, s - pad], radius=int(s * 0.2), fill=(255, 93, 143), outline=(255, 216, 77), width=int(s * 0.035))
    f = ImageFont.truetype(FONT, int(s * 0.42))
    d.text((s / 2, s * 0.53), 'KC', font=f, fill=(255, 255, 255), anchor='mm', stroke_width=int(s * 0.012), stroke_fill=(120, 30, 70))
    d.ellipse([s * 0.68, s * 0.2, s * 0.8, s * 0.32], fill=(255, 216, 77))
    return im.resize((size, size), Image.LANCZOS)


def main():
    out = os.path.join(HERE, 'build'); iconset = os.path.join(out, 'icon.iconset')
    os.makedirs(iconset, exist_ok=True)
    for px in (16, 32, 128, 256, 512):
        draw(px).save(os.path.join(iconset, f'icon_{px}x{px}.png'))
        draw(px * 2).save(os.path.join(iconset, f'icon_{px}x{px}@2x.png'))
    draw(1024).save(os.path.join(out, 'icon.png'))
    if sys.platform == 'darwin':
        subprocess.run(['iconutil', '-c', 'icns', iconset, '-o', os.path.join(out, 'icon.icns')], check=True)  # nosec B603 B607
    print(os.path.join(out, 'icon.icns'))


if __name__ == '__main__':
    main()
