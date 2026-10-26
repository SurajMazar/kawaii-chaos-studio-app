# Kawaii Chaos Studio

The app's own manual (every page and tab). Start with the [main README](../README.md) for what it is and how to install it.

## Start

    studio/run.sh

The first run creates `studio/.venv`, installs what is missing and builds the web app. Then it opens
**http://localhost:8770**. Stop it with Ctrl+C in that terminal.

**Sign-in.** The very first time, the Studio shows **Create your admin account** (name, email, password — there are no
default passwords). After that everyone signs in with their email and password. The account menu (bottom-left avatar)
has *Change password*, *Two-factor sign-in*, *Sessions & devices* and *Sign out*. Forgot the password? Another admin
resets it on the Users page, or run `studio/.venv/bin/python studio/manage.py reset-password you@example.com`.

**Roles.** *Viewer* looks at everything but changes nothing; *Editor* makes and changes things (scripts, pictures, QA,
reels, lyric edits, posts); *Admin* also manages users, storage (Integrations), tools and settings.

**Putting it on a server** (Docker, HTTPS, S3 / Cloudflare R2): see [DEPLOY.md](DEPLOY.md). Security model and the
review: [SECURITY.md](SECURITY.md).

Every page has a **Tour** button (top right) that walks you through it; the tour also starts by itself the first
time you open a page. *Settings → Show all tours again* brings them all back.

## Pages

### Library (home)
All strips, music videos and lyric edits as cards with their picture and status: **QA passed / needs QA / QA
outdated**, **reel built**, **caption**, **posted** (image / reel). Search, filter by type, couple and status
(*Needs QA*, *Needs a reel*, *Ready to post*, …) and sort. The top row shows followers, posts and posts per couple
from `posting_log.json`. Click a card to open it.

### A strip (`projects/NNN_name`)
The **steps** bar (Script → Layout → Prompt → Pictures → QA → Reel → Post) shows what is done; click a step to go there.

| Tab | What you do there |
|---|---|
| **Script** | Edit `synopsis.md` with a live preview (title line, panels `1. 2. 3.`, `**Caption:**`, `**Pinned comment:**`, `**Song ideas**`). |
| **Layout** | Pick 1–6 panels (+ optional seed) → random panel wireframe (`layout/layout.png`) and its description. |
| **Prompt** | The ChatGPT prompt put together from the `style.md` header, COUPLE RULE, layout text, your panels and the locks you tick — edit it, **Copy prompt**, save as `prompt_final.txt`. **Build board** makes the reference board (A = style master, B = character sheet, C = layout) to attach. **Open ChatGPT**. |
| **Pictures** | Every picture (main, drafts in `raw/`, rejected, layout). Drop your own pictures; **Import from Downloads** (pick pictures, or unpack ChatGPT `*_bundle*.bin` files); ★ = use as `strip.png`, card = use as `charsheet.png`, **Compare** with the style master (both sides zoom together), **Style check** (`style_check.py`), move to **Rejected** with a reason, restore, download. |
| **Character sheet** | `charsheet.png`, its prompt (`charsheet_prompt.txt`), and **Fix the heights** (`sheet_heights.py`) with a before/after view and *Use as charsheet.png*. |
| **QA** | Pick a picture, write what a stranger sees, tick the A–J checks from `qa_rules.md` (hover for the full rule). **Mark PASS** (only when every check is ticked) writes `PASS <sha1> strip.png` into `qa.md`; **Write FAIL** records the failing checks; **Revoke PASS**. The *qa.md* view edits the whole file. |
| **Reel** | **Build reel (automatic)** = `scripts/build_reel.sh` (finds the panels, default timing, render, Instagram copy) as a background job with progress. Refuses without the QA PASS. Plays the result, **Download** / **Export** (copies to your export folder). |
| **Voiceover** | An optional *voiced* version of the reel (`upload/NNN_name_strip_reel_voiceover.mp4`; the silent reel stays). **Voice cast** = which ElevenLabs voice each character uses (`voices.json`, shared: Stark = Valf, Fern = Sarah…; *Choose…* lists your ElevenLabs voices or searches the Voice Library, with samples). **Lines**: who, what, when (seconds; ⌖ takes the player time), volume; **From the script** fills them from the synopsis dialogue on their panels; **Make voice** = ElevenLabs text-to-speech (a new take each time, older takes kept; shows the credit cost) or upload a clip made on elevenlabs.io. **Preview with voices** plays it in the page; **Mix voiced reel** = `scripts/voiceover_mix.py` (clips at their times, music −10 dB ducked under the voices, fades, −16 LUFS). Saved in `voiceover/voiceover.json`. |
| **Post** | Caption + pinned comment (saved to `captions.json` **and** the synopsis), *+ hashtags*, copy buttons. **Mark as posted** (format, date, song from the `songs.md` shortlists or typed, post link) → `posting_log.json`, with the history and *undo*. |
| **Files** | Browse every file of the project, look at it, download it. |

### Strip-reel editor (`Reel editor` button on a strip)
- **Panel boxes**: the panels drawn over `strip.png`. Drag a box to move it, drag its white dots to resize, add,
  delete, reorder; **Find panels** detects them automatically (`detect_panels.py`). **Save boxes & re-cut** writes
  `layout/layout_actual.json` and cuts new panel pictures (your timing is kept when the panel count stays the same).
- **Timing & camera**: the reel's shots on a timeline (drag a block's right edge to change its length), the preview
  (the real renderer, `scripts/render.py`, at half size — Play/Space), and per shot: length, order (↑ ↓), transition,
  card size, camera presets (push-in, pans, close-up → zoom out, still) or exact start/end framing, easing.
  Whole reel: total length (*Fit* stretches every panel), fades, punchline shake.
- **Build reel** saves `strip_reel/storyboard.json`, renders it and makes `upload/NNN_name_strip_reel.mp4` +
  `upload/NNN_name_strip.png` (same encode as `build_reel.sh`). Needs the QA PASS.
- No storyboard yet? **Make the storyboard** creates one from the boxes (`strip_reel.py --silent`).

### Music videos (`music_videos/NN_name`)
The list of every music-video folder with its lyric edits. A music-video page has Story, Character sheet, Pictures,
QA (every frame gets its own `PASS <sha1> <frame>` line), **Video** (its lyric edits + renders) and Post tabs.

**New lyric edit**: pick the folder and start from *my pictures* (one line per picture), *my lyrics* (one line per
row), *blank* or *a copy of another edit* (shifted to the new start time); choose where the song starts.

### Lyric editor
Unchanged features from Lyric Studio, now in the same look:

| Area | What it does |
|---|---|
| **Lyrics** (left) | Every line with its time. Click a line to jump to it. **+ line** adds a line at the playhead. |
| **Line editor** | Start/end (type `0:29.51`, nudge ±0.05 s, ⌖ = playhead), text, look (Block / Verse / Stack / Chorus), height, align, flash, emoji, stripe colour, pictures & cuts (close-ups: click the thumbnail to aim). |
| **Preview** | The exact frame of the final video (same renderer). **Play** streams it with the song. **IG safe zones**. |
| **Right panel** | **Quick preview** (540p/15 fps) or **Final video** (1080p, saves first). Video start/end, picture fit, **end-card text**, text sizes. **Fonts & colours**: a font per role (block/chorus, verse, big words, end card — your uploaded fonts too) and colours (block text, chorus palette, accent, ink). Song (for listening/timing). Pictures (drop your own). |
| **Timeline** | Drag lyrics, drag edges to retime, drag ✂ cut points, click to scrub, Ctrl/⌘ + wheel zooms. Waveform when a song is loaded. |

**Import LRC** pastes `[mm:ss.xx]` timings onto the lines (optionally the text too). **Copy** makes a variant file.

### New project
Strip, music video or lyric edit: name, couple (from `couples.md` or typed), title, mood, panels, optional lines.
Runs `scripts/new_project.py` (next number), writes a synopsis template (or a first `lyric_edit.json`) and, for strips,
a random layout. Existing names are refused — nothing is overwritten.

### Tools
The repo scripts as buttons, each a background job with a log: **Make the PDF book** (`make_pdf.py`, download
link), **Style check a picture**, **Small upload copies** (`upload_encode.py`), **Build every missing strip reel**
(`build_missing.sh`), **Update trackers** (`update_trackers.py`, backs up the tracker files first), **Import ChatGPT
bundles**. The **Jobs** button (top right everywhere) lists every job with progress, details and Stop.

### Settings
**Defaults** (admins edit them): handle, end-card text for new lyric edits, default hashtags, style reference for
boards, seconds per panel, Downloads folder, export folder, the Python used for the scripts (needs
numpy/opencv/pillow/scipy), ChatGPT link — the last three only when the Studio runs on your own computer. **Fonts**:
upload `.ttf`/`.otf` into `fonts/` and preview them.

**Where do the pictures come from?** *I draw them myself* hides the ChatGPT-only parts (Prompt step and tab, bundle
unpacking) and makes a dropped drawing the strip right away; *ChatGPT* shows them. Switch any time — nothing is deleted.
(Default for new installs: `STUDIO_ART_SOURCE`.)

**Integrations** (admins): where the Studio keeps its files — **Local folder** (`data/` by default), **Amazon S3**,
**Cloudflare R2** or **Other S3-compatible** (MinIO, Backblaze B2, Wasabi…). Fill in the fields (each has a hint),
**Test connection**, **Copy my files there…** (counts first, then copies with progress — your current files are never
deleted) and **Save & switch**. Keys are stored encrypted and never shown again (“••••• set” + *Replace*).
**ElevenLabs**: paste an API key → *Test & save* (shows the plan and credits); used by the Voiceover tab. Stored encrypted
like the storage secret; `ELEVENLABS_API_KEY` on the server wins.

### Users (admins)
Add people (a one-time temporary password is shown to give them; they choose their own at first sign-in), set the
role, reset a password, turn an account off, turn off someone's two-factor (lost phone), see and end their sessions.

## Doing it your own way (no Claude, no ChatGPT)
- **Your own drawings**: Settings → *Where do the pictures come from?* → **I draw them myself**.
- **Your own strip**: New project → Strip → Pictures: drop your drawing with *use as strip.png right away* → QA →
  Reel (automatic, or the Reel editor to fix the panels/timing) → Post.
- **Your own lyric edit**: New project → Lyric edit (paste your lyrics) → Pictures: drop your pictures → open the
  editor → add your song in *Song* → tap **T** to time each line → Fonts & colours → Final video → Post.
- **Your own look**: upload fonts in Settings, pick them per edit, set your colours and end-card text.

## Shortcuts
| Where | Key | Action |
|---|---|---|
| Lyric editor | Space | play / pause |
| | T | the selected line starts now (previous ends), next line selected |
| | [ and ] | selected line start / end = playhead |
| | ← → (Shift) | move the playhead 0.1 s (1 s) |
| | ↑ ↓ | previous / next line |
| | ⌘Z / ⇧⌘Z | undo / redo |
| | ? | shortcuts |
| Reel editor | Space, ← → | play / pause, move the playhead |
| Editors & text tabs | ⌘S | save |

## Files and safety
- Every save is atomic and keeps the previous version in `.studio_history/` next to the file (last 50 per file;
  `captions.json` / `posting_log.json` backups go to the repo-root `.studio_history/`). These folders are git-ignored.
- The app only reads and writes inside your content folder (plus reading your Downloads folder for imports and copying to your
  export folder). File formats are unchanged: `qa.md` PASS lines, `captions.json` (string or `{caption, pinned}`),
  `posting_log.json` entries, `storyboard.json`, `layout_actual.json`, `lyric_edit*.json`.
- Songs are never baked into videos unless you tick the box — add them in the Instagram app.
- Settings, user accounts (`studio.db`), the encrypted storage settings and the generated `secret.key` live in
  `studio/.config/` (git-ignored; an older `studio/settings.json` is still read). Thumbnails: `studio/.cache/`.
- With S3/R2 the bucket holds everything (same folder names, `.studio_history/` included); `studio/.workcache/` keeps the
  files renders and reel builds need (safe to delete).

## Stack
- **Storage:** `storage/` — one interface (`base.py`) with a local-folder driver and an S3 driver (S3, R2, MinIO…);
  `workspace.py` puts every API file access on top of it (index, ETag work cache, write-through, history, job
  pull/push sync, per-project locks).
- **Security:** `security/` — accounts/sessions (`auth.py`, argon2id, SQLite), CSRF + auth gate + headers + limits
  (`middleware.py`), upload/document validation; `api/auth.py`, `api/users.py`, `api/integrations.py`; `manage.py` CLI.
- **Backend:** FastAPI, `server.py` + `api/`: `core` (paths, path safety, atomic writes, settings), `jobs` (one
  background job runner: subprocess steps with streamed logs, progress, cancel), `library`, `pieces` (texts, pictures,
  QA, layout, prompt, board, sheet tools), `posts`, `reel` (strip-reel editor), `lyric` (lyric editor, fonts), `tools`
  (new project, tools, settings). Scripts run with the Python from Settings; previews import `scripts/lyric_edit.py`
  and `scripts/render.py`, so previews match the final videos.
- **Frontend:** React 19 + TypeScript + Vite, **Ant Design 5** (dark theme, pink `#ff5d8f`, yellow `#ffd84d`; Tour for
  the guides), zustand for the lyric editor, Tailwind for layout only, hash routing.
- **Developing the UI:** run `server.py`, then `cd web && npm run dev` (port 5173, proxies `/api`). `npm run build`
  before using port 8770.
- **Tests:** `cd studio && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/python -m pytest tests`
  (uses throw-away data, never your content); lint `ruff check .`, `bandit -r api security storage`.
