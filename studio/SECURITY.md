# Kawaii Chaos Studio — security

## Reporting a problem

Please do **not** open a public issue. Email the owner (repository owner on GitHub: SurajMazar) with the steps to
reproduce; you will get an answer within a few days. Include the version (git commit) and whether it was a local or a
Docker deployment.

## Threat model

The Studio is a small multi-user web app for one Instagram account's team. Assets: the comic content (strips, videos,
captions, posting log), the storage credentials (S3/R2 keys), user accounts, and the server itself (it runs ffmpeg and
Python scripts).

| Actor | Can | Must not be able to |
|---|---|---|
| Anonymous internet | reach the sign-in page, `/api/health`, `/api/ready`, static files | read or change anything; enumerate users; brute-force passwords; take over a fresh install |
| Viewer | read everything, preview frames | change anything, start jobs |
| Editor | create/edit/upload/render/mark posts | manage users, storage, settings, run repo-wide tools |
| Admin | everything incl. users, storage integration, tools | read stored secrets back (never returned to the browser) |
| Other sites in the user's browser | — | act with the user's session (CSRF), frame the app (clickjacking), read API responses (CORS) |
| A malicious/compromised editor | edit content | escape the content folders, run commands, read server files, SSRF, exhaust the server |

Trust boundaries: browser ↔ server (auth, CSRF, headers, validation); server ↔ storage (scoped keys, validated
endpoint); server ↔ subprocess scripts (argument lists only, validated names, scrubbed environment).

## Controls

**Authentication** — accounts in SQLite (`<config>/studio.db`, 0600 in a 0700 folder); argon2id password hashes
(argon2-cffi defaults, rehash on parameter change); password policy (10–256 chars, not trivial, not the email). No
default credentials: the first admin is created on a one-time setup screen (production requires a setup code printed in
the server log, or `STUDIO_SETUP_TOKEN`) or from `STUDIO_ADMIN_EMAIL`/`STUDIO_ADMIN_PASSWORD`; setup is refused once any
user exists (checked inside a write transaction). Optional TOTP two-factor sign-in (pyotp), secrets Fernet-encrypted.

**Sessions** — 256-bit random opaque token, only its SHA-256 stored; cookie `HttpOnly`, `SameSite=Lax`, `Secure` +
`__Host-` prefix on HTTPS / in production; idle expiry (12 h) and absolute expiry (14 days); a new session on every
sign-in and password change (no fixation), other sessions revoked on password change/reset/disable; "sign out
everywhere"; admins can list and revoke anyone's sessions.

**Brute force** — per-account lockout with exponential backoff (5 free failures, then 30 s doubling to 1 h, stored in
the DB) + per-IP limit (30 failures / 15 min, in memory); identical "Wrong email or password." for unknown users, wrong
passwords and disabled accounts; unknown users still pay for an argon2 verify (no timing oracle); constant-time token
comparisons.

**Authorization** — deny by default: an ASGI gate returns 401 for every `/api/*` request without a valid session except
an explicit allowlist (`/api/health`, `/api/ready`, `/api/auth/state|login|setup|logout`); every router is created with
the `authorize` dependency, which enforces the route's minimum role (GET = viewer, other methods = editor, admin routes
marked explicitly) and the "set a new password first" state. The server refuses to start if any API route lacks it,
and a test enumerates every route and asserts 401 (anonymous) / 403 (viewer and editor below the minimum). Jobs record
their owner; only the owner or an admin can cancel. Admins cannot remove the last admin or lock themselves out.

**CSRF** — double-submit token: a non-HttpOnly `kcs_csrf` cookie (`SameSite=Strict`) that must equal the
`X-CSRF-Token` header *and* the token stored with the session, on every POST/PUT/PATCH/DELETE (including sign-in).
Requests with an `Origin` that is not our own are refused. CORS is off (same origin) unless `STUDIO_ALLOWED_ORIGINS`.

**Browser hardening** — `Content-Security-Policy` (`default-src 'self'`, scripts only from the app, no inline scripts,
`frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`; `style-src 'unsafe-inline'` is
needed for Ant Design's CSS-in-JS), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: same-origin`, `Cross-Origin-Opener-Policy`/`-Resource-Policy: same-origin`, `Permissions-Policy`, HSTS
on HTTPS, `Cache-Control: no-store` on API responses. Markdown previews (synopsis, qa.md) escape raw HTML and are then
sanitised with DOMPurify (http/https/mailto links only, `rel=noopener`). `.html/.svg/.xml/.js` files are only ever
served as downloads. Host-header allowlist (`STUDIO_ALLOWED_HOSTS`, localhost-only by default for local runs) stops
DNS-rebinding attacks on a fresh local install.

**Files and paths** — every content path goes through `storage.norm_key` (no `..`/`.`, absolute paths, backslashes,
NUL/control characters, empty segments) and the workspace allowlist (only `projects/`, `music_videos/`, `upload/`,
`references/`, `fonts/`, `mascot/`, `batches/`, `.studio_history/` and the known top-level JSON/MD files — never
`studio/`, `scripts/`, `.git`, the config). The local driver resolves symlinks and refuses anything that leaves the root.
Project ids, edit-file names and text names are matched against strict regexes/allowlists. Uploads: extension allowlist
+ magic-byte check + sanitised file names; pictures are opened with Pillow (decompression-bomb guard: Pillow's warning
is an error, `STUDIO_IMAGE_MAX_PIXELS`, 20 000 px max side). Fonts must parse as fonts.

**Render documents** — `lyric_edit*.json` and `storyboard.json` are user-editable and drive ffmpeg/renderers, so every
path-like field (`image`, `asset`, `audio`, `output`, `file`, `sfx`, …) must be a safe relative name (no `..`, no
absolute paths, no `scheme:` → no ffmpeg protocols such as `http:`/`concat:`), fonts must be `fonts/<name>.ttf|otf|ttc`,
output names are plain `*.mp4`, and sizes/fps/durations are bounded.

**Commands** — subprocesses always get argument lists (no `shell=True`), names are validated (`^\d+_[A-Za-z0-9][…]$`,
tool arguments regex-checked, no leading `-`), and the child environment is scrubbed (no storage/auth secrets).
Settings that point at the server's file system or pick the Python interpreter (`python`, `downloads`, `export_dir`)
are admin-only, validated, and disabled entirely in production (`STUDIO_LOCAL_FEATURES`). Downloads-folder import and
bundle unpacking are local-only features.

**SSRF** — storage endpoints must be `https://` with a host that resolves to public addresses; `http://` and
private/loopback addresses need `STUDIO_ALLOW_INSECURE_ENDPOINTS=1` (dev); link-local / cloud-metadata ranges
(169.254.0.0/16, fe80::/10, fd00:ec2::254, 100.100.100.200) are always refused; no credentials/paths/queries in the URL.

**Secrets** — storage secret keys are Fernet-encrypted with `STUDIO_SECRET_KEY` in `<config>/storage.json` (0600);
without the key the server refuses to store them; they are never returned to the browser (`{"set": true}`), never
logged (request logs carry method, path, status, user id, request id — no query strings, bodies or cookies), never
passed to scripts. Env vars override the file. Key rotation: `manage.py rotate-secret-key` with
`STUDIO_SECRET_KEY_OLD`. `.env`, `studio/.config/`, the work cache and MinIO data are git-ignored and docker-ignored.

**Denial of service** — body limits (JSON `STUDIO_MAX_JSON_MB`, uploads `STUDIO_MAX_UPLOAD_MB`, enforced on
Content-Length and while streaming), bounded text fields, at most `STUDIO_MAX_JOBS` jobs at once (others queue),
`STUDIO_MAX_JOBS_PER_USER` active jobs and `STUDIO_JOB_STARTS_PER_MINUTE` starts per user, preview-frame rate limit
per user, bounded render sizes, caches with fixed sizes.

**Errors & logging** — production never returns stack traces (generic message + request id); `X-Request-ID` on every
response and in every log line; JSON logs in production; OpenAPI docs disabled in production; no `Server` header.

**Supply chain / CI** — pinned web stack, `pip-audit`, `npm audit --audit-level=high`, `bandit`, `ruff`, tests and a
Docker build + smoke test in the GitHub Actions workflow (`studio/ci/github-workflow-studio.yml`). The container runs as an unprivileged user (uid 10001), read-only root
file system, all capabilities dropped, `no-new-privileges`, tini as PID 1.

## Security review — findings fixed (2026-10-25)

| # | Finding (before) | Severity | Fix |
|---|---|---|---|
| 1 | No authentication at all; anyone who could reach port 8770 could read/modify everything and run tools | Critical | accounts, sessions, roles, deny-by-default gate + per-route role checks |
| 2 | `PUT /api/settings` let anyone set `python` to any executable (run on every job) and `downloads`/`export_dir` to any folder (read pictures from / copy files to anywhere) | Critical (RCE / file write) | admin-only, validated, disabled in production |
| 3 | `storyboard.json` `output.file` and shot `image` paths were joined unchecked: absolute paths let `render.py` write anywhere and ffmpeg read any file / use network protocols | High (arbitrary write, SSRF) | render-document validation (safe relative names, plain `*.mp4`) |
| 4 | Lyric edits could point fonts/images/audio anywhere on disk | Medium (file read) | same validation + font allowlist |
| 5 | No CSRF protection (any site could POST to the local server from the owner's browser) | High | double-submit token bound to the session + Origin check |
| 6 | No security headers (clickjacking, sniffing) | Medium | CSP, XFO, nosniff, Referrer-Policy, COOP/CORP, HSTS |
| 7 | Uploads trusted the extension only; no bomb guard | Medium | magic bytes, Pillow open + pixel limits |
| 8 | Markdown preview used `dangerouslySetInnerHTML` with `marked` output (`javascript:` links possible) | Medium (stored XSS) | DOMPurify + URI allowlist |
| 9 | No request size limits | Medium (DoS) | body-size middleware, field length caps |
| 10 | Jobs unbounded (any number of parallel renders) | Medium (DoS) | global job slots, per-user active/start limits, still rate limit |
| 11 | Scripts inherited the server's whole environment | Low | scrubbed environment |
| 12 | `upload_encode` project names could start with `-` (option injection into the script) | Low | stricter regex |
| 13 | DNS rebinding could reach a fresh local install's setup screen | Medium | Host allowlist (localhost-only by default locally) |
| 14 | `.svg/.html` files in a project would be served inline on our origin | Low | forced download for active types (+ CSP) |
| 15 | Dependencies with known CVEs: Starlette 0.46.2 (several), python-multipart 0.0.20 (several), DOMPurify < 3.4.17 | High | FastAPI 0.162 / Starlette 1.10 / python-multipart 0.0.32 / DOMPurify 3.4.17 — `pip-audit` and `npm audit` clean |
| 16 | (found while testing) shared SQLite connection read rows outside its lock → concurrent requests could see another request's row (wrong role / spurious 401) | High (authz confusion) | rows are fetched while holding the lock; regression test |

Checked and clean: secrets in git history (no keys, tokens or private keys in any of the commits); `bandit` (no
issues; remaining `nosec` marks are justified inline: subprocess argument lists, SHA-1/MD5 used as content fingerprints
for the existing `qa.md` format and S3 ETags, env-var names); open redirects (none — the only redirect is to a
server-generated presigned bucket URL); session fixation; info leaks in errors.

## Residual risks / known limitations

- **Single process.** Jobs, locks, rate limits and the login IP counter live in memory: run exactly one process
  (documented). A restart forgets running jobs (their partial outputs are not pushed) and the IP counters.
- **DNS rebinding of the storage endpoint**: the endpoint host is resolved and checked when it is saved/tested; a
  hostile DNS server could later return a private address. Use provider endpoints you trust.
- **Bucket consistency**: other tools writing to the bucket are seen after `STUDIO_INDEX_TTL` seconds; two Studio
  servers on one bucket are not supported. Last writer wins if a job output and a manual edit hit the same file.
- **TOTP** codes are not single-use within their 30–60 s window (no replay cache).
- **`style-src 'unsafe-inline'`** is required by Ant Design's CSS-in-JS; scripts remain strictly `'self'`.
- **Google Fonts** are loaded by the web app (privacy: the browser contacts Google). Self-host the two fonts if needed.
- **Admins are trusted**: they can point storage anywhere allowed, run the repo tools and (locally) choose the script
  Python. Give the admin role sparingly and turn on two-factor sign-in.
- **Content scripts** (`scripts/*.py`) are trusted code from this repo; they are not sandboxed beyond the container.
- **Local mode** binds to 127.0.0.1 and generates `studio/.config/secret.key` automatically; anyone with a shell on the
  Mac can read it (as before, they can read the repo too).
