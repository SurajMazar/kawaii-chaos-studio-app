#!/bin/bash
# Kawaii Chaos Studio — one command: sets up on first run, builds the web app if needed, starts http://localhost:8770
# Local use: your comics live in ./data (created from starter/ on the first run; git-ignored), settings + accounts in
# studio/.config/ (git-ignored). Use another folder with STUDIO_DATA_DIR=/path/to/folder studio/run.sh
# First start: the browser shows a one-time "create your admin account" screen.
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
# (re)install when a requirement is missing (e.g. after an update added boto3 / argon2 for sign-in and S3 storage)
.venv/bin/python -c "import fastapi, uvicorn, multipart, PIL, numpy, cv2, scipy, boto3, argon2, cryptography, pyotp" 2>/dev/null || .venv/bin/pip install -q -r requirements.txt
# Node builds the web app: refuse versions with known security holes (fixed in 22.23.4 / 24.22.1 / 26.12.1, Oct 2026)
if command -v node >/dev/null; then
  if ! node -e 'const [a,b,c]=process.versions.node.split(".").map(Number);const ok=(a===22&&(b>23||b===23&&c>=4))||(a===24&&(b>22||b===22&&c>=1))||(a===26&&(b>12||b===12&&c>=1))||a>26;process.exit(ok?0:1)'; then
    echo "  Node $(node -v) has known security holes. Install a patched LTS first, e.g.:  nvm install 24.22.1  (or brew upgrade node)"
    [ -d web/dist ] && echo "  (continuing with the already-built web app)" || exit 1
  fi
fi
if [ ! -d web/dist ] || [ -n "$(find web/src web/index.html web/package.json -newer web/dist/index.html 2>/dev/null | head -1)" ]; then
  (cd web && { [ -d node_modules/antd ] && [ -d node_modules/dompurify ] || npm install; } && npm run build)
fi
PORT=${PORT:-8770}
export STUDIO_ENV=${STUDIO_ENV:-development}
if [ ! -f .config/studio.db ] && [ -z "$STUDIO_ADMIN_EMAIL" ]; then
  echo ""
  echo "  First start: the browser opens a one-time screen to create your admin account (email + password)."
  echo ""
fi
( sleep 1.5; open "http://localhost:$PORT" ) >/dev/null 2>&1 &
exec .venv/bin/python server.py
