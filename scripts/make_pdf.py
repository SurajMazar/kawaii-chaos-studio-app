#!/usr/bin/env python3
"""Collect every finished strip into one PDF book: cover, a contents page, a divider per couple, one strip per page
with its caption and posted status.

    python3 scripts/make_pdf.py [out.pdf] [--title "My Comics"] [--handle @my.account]   # default: upload/comics_book.pdf

The couple of a strip comes from posting_log.json, else "(A x B)" in the first line of its synopsis.md.
"""
import argparse, json, os, re
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(ROOT, *a)
base = lambda n: re.sub(r'^\d+_', '', n)   # numbered project folders: 001_rem_jacket

W, H = 1240, 1754                      # A4 portrait at 150 dpi
CREAM, INK, PINK, MUTED = (253, 248, 238), (45, 40, 50), (232, 120, 150), (130, 120, 125)
FONT = '/System/Library/Fonts/Avenir Next.ttc'
def f(size, idx=0):
    if os.path.exists(FONT): return ImageFont.truetype(FONT, size, index=idx)
    # not a Mac (e.g. the Docker image): the repo's Baloo 2 for bold/demi, DejaVu Sans (or Baloo 2) for regular text
    reg = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    return ImageFont.truetype(reg if idx == REG and os.path.exists(reg) else P('fonts', 'Baloo2.ttf'), size)
BOLD, REG, DEMI = 0, 7, 2              # face indexes inside Avenir Next.ttc

def couple_of(n, log_couple):
    if log_couple and log_couple != '?': return log_couple.replace(' x ', ' × ')
    try: first = open(P('projects', n, 'synopsis.md')).readline()
    except OSError: return 'Other'
    m = re.search(r'\(([^(),]+?\s[x×]\s[^(),]+?)[,)]', first)
    return m.group(1).replace(' x ', ' × ').strip() if m else 'Other'


def group_of(n, couples):
    return 'Specials' if base(n).startswith('milestone') else couples.get(n, 'Other')


def mv_frames(d):
    fs = [x for x in os.listdir(d) if re.fullmatch(r'(frame|p)\d+\.png', x)]
    return [os.path.join(d, x) for x in sorted(fs, key=lambda x: int(re.sub(r'\D', '', x)))]


def no_emoji(s):
    return re.sub(r'[^\u0000-ɏ‐-‧×]+', '', s).strip()


def qa_ok(n):
    """Strips made before the QA gate have no qa.md; gated strips need 'PASS <sha1 of the current strip.png>'."""
    q = P('projects', n, 'qa.md')
    if not os.path.exists(q): return True
    import hashlib
    sha = hashlib.sha1(open(P('projects', n, 'strip.png'), 'rb').read()).hexdigest()
    return any(l.startswith('PASS ' + sha) for l in open(q))


def title_of(name):
    s = open(P('projects', name, 'synopsis.md')).read().splitlines()[0]
    m = re.search(r'"(.+?)"', s)
    if m: return m.group(1)
    return base(name).split('_', 1)[1].replace('_', ' ').title()


def centered(d, y, text, font, fill):
    w = d.textlength(text, font=font)
    d.text(((W - w) / 2, y), text, font=font, fill=fill)


def page():
    im = Image.new('RGB', (W, H), CREAM)
    return im, ImageDraw.Draw(im)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('out', nargs='?', default=P('upload', 'comics_book.pdf'))
    ap.add_argument('--title', default='My Comics'); ap.add_argument('--handle', default='')
    a = ap.parse_args(); OUT = a.out
    caps = json.load(open(P('captions.json')))
    log = json.load(open(P('posting_log.json')))
    posted = {(p['project'], p['format']) for p in log['posts'] if p.get('posted')}
    names = sorted(n for n in os.listdir(P('projects')) if os.path.exists(P('projects', n, 'strip.png')) and qa_ok(n))
    couples = {n: couple_of(n, next((p.get('couple') for p in log['posts'] if p.get('project') == n and p.get('couple')), None)) for n in names}
    order = sorted({group_of(n, couples) for n in names}, key=lambda g: (g in ('Other', 'Specials'), -sum(group_of(n, couples) == g for n in names), g))
    groups = [(g, g, '', [n for n in names if group_of(n, couples) == g]) for g in order]
    total = sum(len(g[3]) for g in groups)
    pages = []

    im, d = page()                                              # cover
    cover = next((P('mascot', x) for x in sorted(os.listdir(P('mascot'))) if x.lower().endswith(('.png', '.jpg'))), None) if os.path.isdir(P('mascot')) else None
    if not cover and names: cover = P('projects', names[-1], 'strip.png')
    if cover:
        c = Image.open(cover).convert('RGB'); c.thumbnail((760, 760), Image.LANCZOS)
        im.paste(c, ((W - c.width) // 2, 330))
    centered(d, 150, a.title, f(92, BOLD), INK)
    if a.handle: centered(d, 270, a.handle, f(40, DEMI), PINK)
    centered(d, 1150, f'{total} comic{"" if total == 1 else "s"}', f(48, DEMI), INK)
    names_ = [g[1] for g in groups if g[0] not in ('Other', 'Specials')]
    for li, k0 in enumerate(range(0, len(names_), 3)):
        centered(d, 1225 + 45 * li, ' · '.join(names_[k0:k0 + 3]), f(30, REG), MUTED)
    centered(d, 1600, 'Fan art. Characters belong to their creators.', f(24, REG), MUTED)
    pages.append(im)

    im, d = page()                                              # contents
    d.text((110, 120), 'Contents', font=f(72, BOLD), fill=INK)
    y, pnum = 260, 3
    mvs = [(m, mv_frames(P('music_videos', m))) for m in sorted(os.listdir(P('music_videos')))
           if os.path.isdir(P('music_videos', m))]
    mvs = [(m, fr) for m, fr in mvs if len(fr) >= 4]
    for k, label, series, items in groups + ([('mv', 'Music video stories', '', mvs)] if mvs else []):
        d.text((110, y), label, font=f(40, DEMI), fill=INK)
        sf = f(28, REG); sr = series
        while d.textlength(sr, font=sf) > 330 and len(sr) > 4: sr = sr[:-2]
        if sr != series: sr = sr.rstrip() + '…'
        d.text((520, y + 8), sr, font=sf, fill=MUTED)
        t = f'{len(items)} {("story" if len(items) == 1 else "stories") if k == "mv" else ("strip" if len(items) == 1 else "strips")} · p. {pnum}'
        d.text((W - 110 - d.textlength(t, font=f(30, REG)), y + 6), t, font=f(30, REG), fill=PINK)
        y += 90; pnum += 1 + len(items)
    d.text((110, y + 60), 'Posted on Instagram so far are marked "posted" on their page.', font=f(26, REG), fill=MUTED)
    pages.append(im)

    n_page = 3
    for k, label, series, items in groups:
        im, d = page()                                          # divider
        thumb = Image.open(P('projects', items[0], 'strip.png')).convert('RGB')
        thumb.thumbnail((700, 875))
        im.paste(thumb, ((W - thumb.width) // 2, 560))
        centered(d, 260, label, f(96, BOLD), INK)
        centered(d, 400, series, f(40, REG), PINK)
        centered(d, 1500, f'{len(items)} strip' + ('' if len(items) == 1 else 's'), f(36, DEMI), MUTED)
        pages.append(im); n_page += 1
        for i, n in enumerate(items, 1):
            im, d = page()
            strip = Image.open(P('projects', n, 'strip.png')).convert('RGB')
            sw = W - 160; sh = round(strip.height * sw / strip.width)
            if sh > 1420: sh = 1420; sw = round(strip.width * sh / strip.height)
            strip = strip.resize((sw, sh), Image.LANCZOS)
            top = 120
            d.text((80, 50), f'{label}  ·  {i}/{len(items)}', font=f(28, DEMI), fill=PINK)
            t = title_of(n); d.text((W - 80 - d.textlength(t, font=f(28, DEMI)), 50), t, font=f(28, DEMI), fill=INK)
            im.paste(strip, ((W - sw) // 2, top))
            cap = no_emoji((caps.get(n) or '').split('\n')[0])
            tags = []
            if (n, 'image') in posted: tags.append('posted: image')
            if (n, 'strip_reel') in posted: tags.append('posted: reel')
            y = top + sh + 30
            if cap: d.text((80, y), cap, font=f(30, REG), fill=INK)
            foot = f'{n}' + ('   ·   ' + ', '.join(tags) if tags else '')
            d.text((80, H - 70), foot, font=f(22, REG), fill=MUTED)
            pn = str(len(pages) + 1); d.text((W - 80 - d.textlength(pn, font=f(22, REG)), H - 70), pn, font=f(22, REG), fill=MUTED)
            pages.append(im); n_page += 1

    if mvs:                                                     # music-video stories: frames in a grid
        im, d = page()
        centered(d, 260, 'Music video stories', f(96, BOLD), INK)
        centered(d, 400, 'every reel, frame by frame', f(40, REG), PINK)
        thumb = Image.open(mvs[-1][1][-1]).convert('RGB'); thumb.thumbnail((700, 875))
        im.paste(thumb, ((W - thumb.width) // 2, 560))
        pages.append(im); n_page += 1
        for i, (m, frames) in enumerate(mvs, 1):
            im, d = page()
            first = open(P('music_videos', m, 'synopsis.md')).readline()
            t = (re.search(r'"(.+?)"', first) or re.search(r'_(\w+)', base(m)) or re.search(r'(.+)', base(m))).group(1)
            t = t if '"' in first else base(m).replace('_', ' ').title()
            d.text((80, 50), f'Music video stories  ·  {i}/{len(mvs)}', font=f(28, DEMI), fill=PINK)
            d.text((W - 80 - d.textlength(t, font=f(28, DEMI)), 50), t, font=f(28, DEMI), fill=INK)
            cols = 3 if len(frames) > 8 else 2
            rows = -(-len(frames) // cols)
            gw = (W - 160 - (cols - 1) * 20) // cols
            gh = (H - 230 - (rows - 1) * 20) // rows
            for j, fp in enumerate(frames):
                fr = Image.open(fp).convert('RGB'); fr.thumbnail((gw, gh), Image.LANCZOS)
                x0 = 80 + (j % cols) * (gw + 20) + (gw - fr.width) // 2
                y0 = 120 + (j // cols) * (gh + 20) + (gh - fr.height) // 2
                im.paste(fr, (x0, y0))
            d.text((80, H - 70), m, font=f(22, REG), fill=MUTED)
            pn = str(len(pages) + 1); d.text((W - 80 - d.textlength(pn, font=f(22, REG)), H - 70), pn, font=f(22, REG), fill=MUTED)
            pages.append(im); n_page += 1

    pages[0].save(OUT, save_all=True, append_images=pages[1:], resolution=150, quality=82, optimize=True)
    print(f'{len(pages)} pages, {total} strips -> {OUT} ({os.path.getsize(OUT) / 1e6:.1f} MB)')


if __name__ == '__main__':
    main()
