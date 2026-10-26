# Kawaii Chaos Studio

A friendly web app for making **comic strips and comic reels** for Instagram and TikTok: write the script, draw (or
import) the strip, check it, turn it into a panel-by-panel reel, add character voices, write the caption and keep track of
what you posted. It runs on your own computer, and can also be put on a server for a small team.

Made for chibi fan-comic accounts, but nothing in it is tied to one series, couple or account.

## What it does

| | |
|---|---|
| **Strips** | Script with panels → optional random panel layout to draw on → your drawing (or a ChatGPT picture) → QA checklist → strip reel → caption → posted. |
| **Strip reels** | A 9:16 video that shows the strip panel by panel and only reveals the whole strip at the end. Automatic, or fix the panel boxes, timing and camera moves in the **Reel editor**. Silent, so you add a song in the Instagram/TikTok app. |
| **Voiced reels** | Character voices on the reel: a **voice cast** (the same ElevenLabs voice for a character every time), lines placed on the timeline, music ducked under the voices, one mix. Use the ElevenLabs API or upload clips you recorded or made elsewhere. |
| **Lyric edits / music videos** | Pictures + lyric lines timed to a song (tap to time), fonts, colours and camera moves, a smooth in-browser preview and a final render. |
| **QA gate** | Your own checklist (`qa_rules.md`). A reel is only built for a picture that passed it. |
| **Posting** | Captions, pinned comments, song ideas, a posting log, an export folder (e.g. AirDrop). |
| **Your own way** | Your drawings, fonts, songs and checklist. ChatGPT steps are optional (Settings → *Where do the pictures come from?*). |
| **Team & server** | Accounts with roles (viewer / editor / admin), optional two-factor sign-in, storage on the local disk, Amazon S3, Cloudflare R2 or any S3-compatible service, Docker. |

## Mac app (easiest)

Download **`Kawaii-Chaos-Studio-<version>-mac-arm64.dmg`** from [Releases](../../releases), open it and drag the app
into Applications. It needs macOS 12+ on Apple Silicon (M1 or newer). Nothing else to install — ffmpeg is included.

- **First open:** the app is not notarized by Apple yet, so macOS warns. Right-click the app → **Open** → **Open**
  (macOS 15+: try to open it once, then System Settings → Privacy & Security → **Open Anyway**).
- **No account, no password:** the app signs you in by itself and only listens on your own Mac.
- **Your comics** are plain files in `Documents/Kawaii Chaos Studio/`; the app's local database (SQLite), settings and
  logs are in `~/Library/Application Support/Kawaii Chaos Studio/`.
- **Move projects** between Macs or friends: a project's **Export** button makes a `.zip`; **Library → Import** adds it.

## Run from source (macOS, Linux, Windows with WSL)

You need **Python 3.11+**, **Node.js 24 LTS** (24.22.1 or newer; see `.nvmrc`) and **ffmpeg** (macOS: `brew install python node ffmpeg`;
Ubuntu: `sudo apt install python3-venv nodejs npm ffmpeg`).

```bash
git clone <this repo> kawaii-chaos-studio
cd kawaii-chaos-studio
studio/run.sh
```

The first run installs what it needs, builds the web app and opens **http://localhost:8770**. Create your admin
account on the first screen (there are no default passwords). Your comics are kept in **`data/`** (git-ignored); it is
created from `starter/` the first time. Use another folder with `STUDIO_DATA_DIR=/path/to/folder studio/run.sh`.

Then: **New project** → write the panels → **Pictures**: drop your drawing (it becomes `strip.png`) → **QA** →
**Reel** → **Post**. Every page has a **Tour** button that walks you through it.

## Your content folder

```
data/
  projects/NNN_name/       one strip: synopsis.md, strip.png, qa.md, raw/ drafts, layout/, strip_reel/, voiceover/
  music_videos/NN_name/    a music video or lyric edit: frames, lyric_edit*.json, audio/
  upload/                  finished files to post (strip images, reels, voiced reels)
  references/              style references (style_ref.png) and character references
  fonts/                   your uploaded fonts (the defaults in fonts/ are always available)
  qa_rules.md  style.md  couples.md  songs.md  voices.json  captions.json  posting_log.json
```

It is a plain folder of files: back it up, put it in iCloud/Dropbox, or keep it in your own git repo.

## Settings worth knowing

| Where | What |
|---|---|
| Settings → Defaults | Your handle, end-card text, default hashtags, *where the pictures come from* (your drawings / ChatGPT), export folder. |
| Settings → Integrations | Storage (local folder, S3, R2, S3-compatible) and the **ElevenLabs** API key for voices (stored encrypted). |
| `.env` / environment | Everything for servers — see [.env.example](.env.example). `STUDIO_ART_SOURCE=own|chatgpt`, `ELEVENLABS_API_KEY`, `STUDIO_DATA_DIR`, … |

## On a server

Docker image, HTTPS reverse proxy, S3/R2 storage, backups and key rotation: [studio/DEPLOY.md](studio/DEPLOY.md).
Security model (sessions, CSRF, roles, upload checks, path safety, rate limits): [studio/SECURITY.md](studio/SECURITY.md).

```bash
cp .env.example .env    # set STUDIO_SECRET_KEY etc.
docker compose up -d
```

## The manual

Every page and tab is described in [studio/README.md](studio/README.md).

## Development

- Backend: FastAPI (`studio/server.py`, `studio/api/`), storage drivers (`studio/storage/`), security (`studio/security/`).
- Frontend: React + TypeScript + Vite + Ant Design (`studio/web/`): `cd studio/web && npm ci && npm run dev`
  (port 5173, proxies `/api` to the server).
- Render scripts: `scripts/` (Python + ffmpeg), runnable on their own too.
- Tests: `cd studio && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/python -m pytest tests`
  (they use throw-away folders, never your content). Lint: `ruff check .`, `npx eslint src`.

### Building the Mac app yourself

```bash
cd studio/web && npm ci && npm run build && cd ../..
python3 -m venv .venv-app && .venv-app/bin/pip install -r studio/requirements.txt -r desktop/requirements.txt
.venv-app/bin/python desktop/make_icon.py
.venv-app/bin/pyinstaller --noconfirm --distpath desktop/dist --workpath desktop/build/pyi desktop/kawaii.spec
"desktop/dist/Kawaii Chaos Studio.app/Contents/MacOS/Kawaii Chaos Studio" --selftest   # builds a test reel, exits 0 when OK
```

Releases are built by GitHub Actions ([release.yml](.github/workflows/release.yml)) when a version tag is pushed
(`git tag v0.2.0 && git push origin v0.2.0`): tests, app build, the self-test, then the `.dmg` and its checksum are
attached to the release.

## Contributing

Issues and forks are welcome; pull requests are only accepted from the maintainer — see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

[MIT](LICENSE). Bundled third-party software (FFmpeg in the Mac app, fonts, libraries): [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Fan art

Comics about existing characters are fan art: the characters belong to their creators. Only use songs, voices and
pictures you are allowed to use; licensed songs go in through the Instagram/TikTok app, never baked into the video.
