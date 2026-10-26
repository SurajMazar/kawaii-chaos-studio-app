"""Captions (captions.json + synopsis), song shortlists (songs.md), couples (couples.md) and the posting log."""
import re

from fastapi import APIRouter, Body, Depends, HTTPException
from .deps import authorize

from .core import ROOT, get_settings, piece_dir, read_text, today, write_atomic, write_json
from .library import COUPLE, caption_of, couple_guess, invalidate, load_captions, load_log

router = APIRouter(dependencies=[Depends(authorize)])   # deny by default (api/deps.py)
CAP_RE = re.compile(r'(\*\*Caption(?: draft)?:\*\*[ \t]*\n\n)(.*?)(?=\n\n\*\*|\Z)', re.S)
PIN_RE = re.compile(r'^\*\*Pinned comment:\*\*[ \t]*(.*)$', re.M)
SONG_RE = re.compile(r'^\*\*Song ideas[^:]*:\*\*[ \t]*(.*)$', re.M)


def synopsis_parts(text):
    m = CAP_RE.search(text); p = PIN_RE.search(text); s = SONG_RE.search(text)
    return (m.group(2).strip() if m else ''), (p.group(1).strip() if p else ''), (s.group(1).strip() if s else '')


def synopsis_with(text, caption, pinned):
    """Put caption + pinned comment into the synopsis, keeping the format scripts/update_trackers.py reads."""
    caption = caption.strip()
    if CAP_RE.search(text):
        text = CAP_RE.sub(lambda m: m.group(1) + caption, text, count=1)
    elif caption:
        text = text.rstrip('\n') + f'\n\n**Caption:**\n\n{caption}\n'
    if pinned.strip():
        if PIN_RE.search(text): text = PIN_RE.sub(lambda m: f'**Pinned comment:** {pinned.strip()}', text, count=1)
        else:
            m = CAP_RE.search(text)
            if m: text = text[:m.end()] + f'\n\n**Pinned comment:** {pinned.strip()}' + text[m.end():]
            else: text = text.rstrip('\n') + f'\n\n**Pinned comment:** {pinned.strip()}\n'
    return text if text.endswith('\n') else text + '\n'


def parse_songs():
    """[{title, artist, group}] from songs.md: per-couple table cells and per-mood bullets ("Title" (Artist))."""
    out, seen = [], set()
    def add(title, artist, group):
        k = (title.lower(), group)
        if title and k not in seen: seen.add(k); out.append(dict(title=title, artist=artist or '', group=group))
    for line in read_text(ROOT / 'songs.md').splitlines():
        if line.startswith('|') and not line.startswith('|---') and not line.startswith('| Couple'):
            cells = [c.strip() for c in line.strip('|').split('|')]
            if len(cells) < 2: continue
            group = cells[0]
            for cell in cells[1:]:
                for m in re.finditer(r'(?:([^"“”,]+?)\s+)?["“]([^"”]+)["”](?:\s*\(([^)]+)\))?', cell):
                    title = m.group(2).strip(); artist = (m.group(3) or '').strip()
                    if not artist and m.group(1) and 'OP' in m.group(1): artist = m.group(1).strip()
                    add(title, artist, group)
        elif line.startswith('- **'):
            m = re.match(r'- \*\*(.+?):\*\*\s*(.*)', line)
            if m:
                for mm in re.finditer(r'["“]([^"”]+)["”](?:\s*\(([^)]+)\))?', m.group(2)): add(mm.group(1), mm.group(2) or '', 'Mood: ' + m.group(1))
    return out


@router.get('/api/songs')
def songs(): return parse_songs()


@router.get('/api/couples')
def couples(): return couples_list()


def couples_list():
    out = []
    for line in read_text(ROOT / 'couples.md').splitlines():
        if not line.startswith('|') or line.startswith('|---') or line.startswith('| #'): continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if len(cells) < 4: continue
        m = re.match(r'\**(.+?)\**\s*(?:\(`(#[^`]+)`\))?$', cells[1])
        name = (m.group(1) if m else cells[1]).replace('**', '').strip()
        a, _, b = name.partition(' × ')
        def first(n): return n.split()[0] if n else n
        short = next((k for k in set(COUPLE.values()) if all(x in name for x in k.split(' x '))), f'{first(a)} x {first(b)}' if b else name)
        out.append(dict(name=name, tag=(m.group(2) if m else '') or '', series=cells[2].strip('*'), looks=cells[3],
                        short=short, dynamic=cells[4] if len(cells) > 4 else ''))
    return out


COUPLES_INTRO = '# Couples\n\nThe New project wizard suggests these. Add, edit or remove them in the Studio (Settings → Couples).\n\n'
COUPLES_HEAD = '| # | Couple | Series | Looks (canon design) | Dynamic / joke angles |\n|---|---|---|---|---|\n'


def _cell(v, n, what):
    if v is None: return ''
    if not isinstance(v, str) or len(v) > n: raise HTTPException(400, f'{what} is too long (max {n} characters)')
    return re.sub(r'\s+', ' ', v.replace('|', '/')).strip()


@router.put('/api/couples')
def save_couples(couples: list = Body(..., embed=True)):
    """Write the couples table (couples.md); the text above the table is kept."""
    if len(couples) > 300: raise HTTPException(400, 'At most 300 couples.')
    rows, seen = [], set()
    for i, c in enumerate(couples, 1):
        if not isinstance(c, dict): raise HTTPException(400, 'bad couple')
        name = re.sub(r'\s+x\s+', ' × ', _cell(c.get('name'), 120, 'Couple'))
        if not name: raise HTTPException(400, 'Every couple needs a name, e.g. "Hero x Heroine".')
        if name.lower() in seen: raise HTTPException(400, f'"{name}" is in the list twice.')
        seen.add(name.lower())
        tag = _cell(c.get('tag'), 60, 'Hashtag').replace('`', '')
        if tag and not re.fullmatch(r'#[\w]+', tag): raise HTTPException(400, f'The hashtag of {name} must look like #HeroxHeroine')
        rows.append(f"| {i} | **{name}**{f' (`{tag}`)' if tag else ''} | {_cell(c.get('series'), 120, 'Series')} | "
                    f"{_cell(c.get('looks'), 600, 'Looks')} | {_cell(c.get('dynamic'), 600, 'Dynamic')} |")
    f = ROOT / 'couples.md'; old = read_text(f)
    intro = old[:old.index('\n|') + 1] if '\n|' in old else (old.rstrip() + '\n\n' if old.strip() else COUPLES_INTRO)
    write_atomic(f, intro + COUPLES_HEAD + ''.join(r + '\n' for r in rows))
    return couples_list()


@router.get('/api/p/{kind}/{pid}/post')
def post_info(kind: str, pid: str):
    d = piece_dir(kind, pid); caps = load_captions(); log = load_log()
    cap, pinned = caption_of(caps, pid)
    s_cap, s_pin, s_songs = synopsis_parts(read_text(d / 'synopsis.md'))
    posts = [p for p in log.get('posts' if kind == 'strip' else 'music_video_posts', []) if p.get('project') == pid]
    ideas = [x.strip() for x in re.split(r'\s+·\s+|;', s_songs) if x.strip()]
    for p in posts:
        for x in re.split(r'\s+·\s+', p.get('song_ideas') or ''):
            if x.strip() and x.strip() not in ideas: ideas.append(x.strip())
    st = get_settings()
    return dict(caption=cap or s_cap, pinned=pinned or s_pin, in_captions_json=pid in caps, synopsis_caption=s_cap,
                synopsis_pinned=s_pin, song_ideas=ideas, posts=posts, couple=couple_guess(pid, next((p.get('couple') for p in posts), None)),
                hashtags=st.get('hashtags', ''), handle=st.get('handle', ''))


@router.put('/api/p/{kind}/{pid}/caption')
def save_caption(kind: str, pid: str, caption: str = Body(...), pinned: str = Body('')):
    d = piece_dir(kind, pid)
    if len(caption) > 5000 or len(pinned) > 2000: raise HTTPException(400, 'The caption is too long (Instagram allows 2,200 characters).')
    caps = load_captions(); old = caps.get(pid)
    if isinstance(old, dict) or pinned.strip():
        v = dict(old) if isinstance(old, dict) else {}
        v['caption'] = caption.strip()
        if pinned.strip() or 'pinned' in v: v['pinned'] = pinned.strip()
        caps[pid] = v
    else:
        caps[pid] = caption.strip()
    write_json(ROOT / 'captions.json', caps)
    syn = d / 'synopsis.md'
    write_atomic(syn, synopsis_with(read_text(syn, f'# {pid}\n'), caption, pinned)); invalidate()
    return dict(ok=True)


FORMATS = {'image', 'strip_reel', 'carousel', 'music_video', 'story'}


@router.post('/api/p/{kind}/{pid}/posted')
def mark_posted(kind: str, pid: str, format: str = Body(...), date: str = Body(''), song: str = Body(''), url: str = Body(''),
                note: str = Body('')):
    piece_dir(kind, pid)
    if format not in FORMATS: raise HTTPException(400, 'bad format')
    if url and not re.match(r'^https?://[^\s<>"]+$', url): raise HTTPException(400, 'The post link must start with https://')
    if len(url) > 500 or len(song) > 200 or len(note) > 1000: raise HTTPException(400, 'One of the fields is too long.')
    date = date or today()
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date): raise HTTPException(400, 'date must look like 2026-10-24')
    log = load_log(); key = 'posts' if kind == 'strip' else 'music_video_posts'
    posts = log.setdefault(key, [])
    e = next((p for p in posts if p.get('project') == pid and p.get('format') == format), None)
    if e is None:
        e = dict(project=pid, couple=couple_guess(pid), format=format)
        if kind == 'strip': e['file'] = f'upload/{pid}_strip_reel.mp4' if format == 'strip_reel' else f'upload/{pid}_strip.png'
        posts.append(e)
    e.update(posted=True, date=date, status=f'posted ({date}, marked in Kawaii Chaos Studio)', posted_by='owner')
    if url: e['url'] = url
    if song: e['song'] = song
    if note: e['note'] = note
    write_json(ROOT / 'posting_log.json', log); invalidate()
    return dict(ok=True, entry=e)


@router.post('/api/p/{kind}/{pid}/unposted')
def unmark_posted(kind: str, pid: str, format: str = Body(..., embed=True)):
    log = load_log(); key = 'posts' if kind == 'strip' else 'music_video_posts'
    e = next((p for p in log.get(key, []) if p.get('project') == pid and p.get('format') == format), None)
    if not e: raise HTTPException(404, 'no such post entry')
    e['posted'] = False; e['status'] = f'ready (unmarked {today()})'
    write_json(ROOT / 'posting_log.json', log); invalidate()
    return dict(ok=True)
