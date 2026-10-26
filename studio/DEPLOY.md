# Deploying Kawaii Chaos Studio

The Studio runs in two ways:

| | Local (your Mac) | Server (Docker) |
|---|---|---|
| Start | `studio/run.sh` → http://localhost:8770 | `docker compose up -d` behind HTTPS |
| `STUDIO_ENV` | `development` | `production` |
| Files | the repo itself (local storage) | a `/data` volume **or** S3 / Cloudflare R2 / S3-compatible |
| Accounts | first start shows *Create your admin* | same, but the setup screen needs a one-time code from the log (or `STUDIO_ADMIN_EMAIL` / `STUDIO_ADMIN_PASSWORD`) |
| Secrets key | `studio/.config/secret.key` created automatically | `STUDIO_SECRET_KEY` (required to save storage keys / use 2FA) |

All configuration is environment variables — every one is documented in [`.env.example`](../.env.example).
Environment variables always win over what is saved in the UI.

---

## 1. Architecture in one picture

```
browser ──HTTPS──► Caddy / nginx ──HTTP──► studio container (uvicorn, 1 process)
                                             ├─ /config  users DB (SQLite), encrypted storage settings, app settings
                                             ├─ /cache   thumbnails (disposable)
                                             ├─ /work    S3/R2 work cache (disposable)
                                             ├─ /data    content, when STORAGE_BACKEND=local
                                             └─ S3 / R2 bucket, when STORAGE_BACKEND=s3|r2|s3compat
```

**One process, one worker.** Renders, reel builds and tools run as background jobs *inside* the server process (job
list, progress, cancel, per-project locks). Run exactly one container with one uvicorn worker (the image does). Do
not scale horizontally or use `--workers N`: jobs and locks are not shared between processes. A bigger machine
(more CPU for ffmpeg/opencv) is the way to scale; `STUDIO_MAX_JOBS` controls how many jobs run at once.

**Storage + work cache.** With a bucket, the bucket is the source of truth. The server keeps an in-memory listing
(refreshed every `STUDIO_INDEX_TTL` s and updated immediately by its own writes). Reads stream from the bucket or
come from the work cache when fresh (ETag match); writes go to the bucket first (write-through), then the cache.
Jobs pull exactly the files they need into `/work`, run ffmpeg / the PIL scripts on real files, and push new and
changed outputs back. `.studio_history/` backups are objects in the bucket. `/work` is disposable (bounded by
`STUDIO_CACHE_MAX_GB`).

---

## 2. Docker on a VPS with HTTPS (recommended)

Any Linux VPS with 2+ vCPU / 4 GB RAM (renders are CPU-heavy) and Docker.

```bash
git clone https://github.com/SurajMazar/kawaii-chaos-comics.git && cd kawaii-chaos-comics
cp .env.example .env
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # → STUDIO_SECRET_KEY in .env
# in .env also set: STUDIO_ALLOWED_HOSTS=studio.example.com   (and the storage block, or choose it later in the UI)
docker compose up -d --build
docker compose logs studio | grep "FIRST-RUN SETUP"     # one-time setup code for the admin screen
```

The compose file publishes the app only on `127.0.0.1:8770`; put a reverse proxy with TLS in front. In production the
session cookie is always `Secure`, so sign-in only works over HTTPS (for a quick plain-http trial on a private network
set `STUDIO_COOKIE_SECURE=false` — never on the internet).

### Caddy (automatic HTTPS)

`/etc/caddy/Caddyfile`:

```caddy
studio.example.com {
    encode zstd gzip
    request_body {
        max_size 210MB          # a little above STUDIO_MAX_UPLOAD_MB
    }
    reverse_proxy 127.0.0.1:8770 {
        transport http {
            read_timeout 10m    # long downloads / slow uploads
        }
    }
}
```

Caddy sends `X-Forwarded-For` / `X-Forwarded-Proto`; the Studio trusts them from `STUDIO_TRUSTED_PROXIES`
(default `127.0.0.1`, right when Caddy runs on the host). If the proxy runs in another container, set
`STUDIO_TRUSTED_PROXIES` to its address. With HTTPS the cookies become `__Host-` + `Secure` and HSTS is sent.

### nginx

```nginx
server {
    listen 443 ssl http2;
    server_name studio.example.com;
    ssl_certificate     /etc/letsencrypt/live/studio.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/studio.example.com/privkey.pem;
    client_max_body_size 210m;
    location / {
        proxy_pass http://127.0.0.1:8770;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        proxy_request_buffering off;
    }
}
```

### Production command

The image runs `python studio/server.py`, which starts uvicorn with one worker, `proxy_headers=True`,
`forwarded_allow_ips=$STUDIO_TRUSTED_PROXIES` and no `Server` header. The equivalent explicit command is

```bash
uvicorn server:app --app-dir studio --host 0.0.0.0 --port 8770 --workers 1 \
        --proxy-headers --forwarded-allow-ips "$STUDIO_TRUSTED_PROXIES" --no-server-header
```

Health checks: `GET /api/health` (process up) and `GET /api/ready` (database + storage reachable; 503 otherwise).

---

## 3. Fly.io / Render

Both work with the Dockerfile. Keep **one** instance and give it persistent disk for `/config` (users + settings).
Use R2/S3 for content (their disks are small and per-machine).

**Fly.io** — `fly launch --no-deploy`, then in `fly.toml`:

```toml
[http_service]
  internal_port = 8770
  force_https = true
  auto_stop_machines = "off"     # background jobs must not be stopped mid-render
  min_machines_running = 1
[[mounts]]
  source = "studio_config"
  destination = "/config"
[env]
  STUDIO_TRUSTED_PROXIES = "*"   # Fly's proxy; the machine is not reachable otherwise
  STUDIO_ALLOWED_HOSTS = "your-app.fly.dev"
```

`fly volumes create studio_config --size 1`, `fly secrets set STUDIO_SECRET_KEY=… S3_SECRET_ACCESS_KEY=…`,
`fly deploy`, then `fly logs | grep FIRST-RUN` for the setup code. Never `fly scale count 2`.

**Render** — New → Web Service → Docker; instance type with ≥ 2 GB RAM; add a Disk mounted at `/config`;
environment: `STUDIO_SECRET_KEY`, `STUDIO_TRUSTED_PROXIES=*`, `STUDIO_ALLOWED_HOSTS=<your>.onrender.com`, storage vars.
Health check path `/api/health`. Instances: 1.

---

## 4. Cloudflare R2 (exact steps)

1. Cloudflare dashboard → **R2 Object Storage** → *Create bucket* (e.g. `kawaii-chaos`), location automatic.
2. Note the **Account ID** (R2 overview page, right side — 32 hex characters).
3. R2 → **Manage R2 API Tokens** → *Create API token*:
   - Permissions: **Object Read & Write**
   - Specify bucket: **only `kawaii-chaos`**
   - TTL as you like → *Create* → copy the **Access Key ID** and **Secret Access Key** (shown once).
4. In the Studio (admin): **Settings → Integrations → Cloudflare R2**: Account ID, bucket, optional folder
   (e.g. `studio`), the two keys → **Test connection** (lists, writes, reads and deletes a small probe object).
5. **Copy my files there…** → check the counts → *Start copying* (the source is never touched; re-run any time, it
   skips identical files).
6. **Save & switch.** The library now reads from R2.

Or with env vars: `STORAGE_BACKEND=r2`, `R2_ACCOUNT_ID`, `S3_BUCKET`, `S3_PREFIX`, `S3_ACCESS_KEY_ID`,
`S3_SECRET_ACCESS_KEY` (region is always `auto`; the endpoint is `https://<account id>.r2.cloudflarestorage.com`).

**Bucket CORS** is *not* needed: the browser always talks to the Studio, which streams from the bucket. Only if you turn
on *Direct downloads* (`S3_PRESIGN_DOWNLOADS`) **and** want scripts in the page to `fetch()` those links would you add a
CORS rule (R2 → bucket → Settings → CORS policy):

```json
[{ "AllowedOrigins": ["https://studio.example.com"], "AllowedMethods": ["GET", "HEAD"], "AllowedHeaders": ["*"], "MaxAgeSeconds": 3600 }]
```

## 5. Amazon S3 (minimal IAM policy)

Create a bucket (block all public access ON), an IAM user or role for the Studio, and attach (replace `BUCKET` and the
`studio` prefix — drop the prefix parts if you use the whole bucket):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "ListOwnPrefix", "Effect": "Allow", "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::BUCKET",
      "Condition": { "StringLike": { "s3:prefix": ["studio", "studio/*"] } } },
    { "Sid": "ReadWriteOwnPrefix", "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::BUCKET/studio/*" }
  ]
}
```

(`CopyObject`, used for history backups, is covered by Get + Put.) On EC2/ECS with an instance role you can leave both
keys empty. Turn on **bucket versioning** + a lifecycle rule (e.g. expire non-current versions after 30 days) for real
backups.

**Other S3-compatible services** (MinIO, Backblaze B2, Wasabi, DigitalOcean Spaces): *Other S3-compatible*, the
provider's `https://` endpoint, region (usually `us-east-1`), bucket, keys, *Path-style* on for MinIO.
`http://` and private-network endpoints are refused unless `STUDIO_ALLOW_INSECURE_ENDPOINTS=1` (local testing only);
cloud-metadata / link-local addresses are always refused.

---

## 6. Backups

| What | Where | How |
|---|---|---|
| Users, sessions, encrypted storage settings, app settings | `/config` (`studio/.config` locally) | back up the volume (e.g. nightly `tar`); it is small |
| `STUDIO_SECRET_KEY` | your password manager / secret store | without it the stored storage keys and 2FA secrets cannot be decrypted |
| Content | `/data` volume, or the bucket | volume snapshots / restic; for buckets: versioning + lifecycle, or `rclone sync` to a second bucket |
| `.studio_history/` | next to each file | the in-app undo history (last 50 versions per file) — convenient, **not** a backup |

`/cache` and `/work` never need backing up.

## 7. Upgrading

```bash
git pull
docker compose up -d --build          # the DB schema is created/extended automatically at start
docker compose logs -f studio
```

Locally `studio/run.sh` reinstalls missing Python packages and rebuilds the web app when its sources changed.

## 8. Rotating `STUDIO_SECRET_KEY`

```bash
NEW=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
# 1) set STUDIO_SECRET_KEY=$NEW and STUDIO_SECRET_KEY_OLD=<previous key> in .env, restart
docker compose up -d
# 2) re-encrypt stored secrets (storage keys, 2FA secrets) with the new key
docker compose exec studio python studio/manage.py rotate-secret-key
# 3) remove STUDIO_SECRET_KEY_OLD from .env, restart
```

Sessions are not affected (they are random tokens, not signed with this key).

## 9. CI

`.github/workflows/ci.yml` runs ruff, bandit, pip-audit, pytest (with moto S3), eslint, the TypeScript build,
`npm audit --audit-level=high` and a Docker build + smoke test. Enable it by moving it to `.github/workflows/studio.yml`
(pushing workflow files needs a token with the `workflow` scope: `gh auth refresh -s workflow`).

## 10. Admin command line

```bash
docker compose exec studio python studio/manage.py list-users
docker compose exec studio python studio/manage.py reset-password you@example.com   # lost password: one-time temp password
docker compose exec studio python studio/manage.py unlock you@example.com           # too many failed sign-ins
docker compose exec studio python studio/manage.py disable-2fa you@example.com      # lost phone
docker compose exec -it studio python studio/manage.py create-admin you@example.com
```

## 11. Local S3 testing (MinIO)

`docker compose --profile minio up -d --build` starts MinIO (console on http://localhost:9001) and creates the
bucket `kawaii-studio`. MinIO stopped publishing new community images in 2025; if the pull fails set `MINIO_IMAGE` to a
release/mirror you trust, or run the `minio` binary directly (Homebrew: `brew install minio`) and point the Studio at
`http://127.0.0.1:<port>` with `STUDIO_ALLOW_INSECURE_ENDPOINTS=1`.
