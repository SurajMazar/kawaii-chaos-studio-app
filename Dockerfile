# Kawaii Chaos Studio — production image.
#   docker build -t kawaii-chaos-studio .
#   docker run -p 127.0.0.1:8770:8770 --env-file .env -v kcs-data:/data -v kcs-config:/config kawaii-chaos-studio
# See studio/DEPLOY.md. Content (projects/, music_videos/, upload/, references/) is NOT baked into the image: it lives
# in the /data volume (local backend) or in your S3 / R2 bucket.

# ---------- 1) web app ----------
# Node only builds the web app (not in the final image); pinned to a release with the October 2026 security fixes
FROM node:24.22.1-bookworm-slim AS web
WORKDIR /web
COPY studio/web/package.json studio/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY studio/web/ ./
RUN npm run build

# ---------- 2) python runtime ----------
FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# ffmpeg for the renders, perl for `shasum` in build_reel.sh, fonts for emoji + the PDF book, tini as PID 1
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg perl fonts-noto-color-emoji fonts-dejavu-core tini ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY studio/requirements.txt studio/requirements.txt
RUN pip install -r studio/requirements.txt
COPY scripts/ scripts/
COPY fonts/ fonts/
COPY starter/ starter/
COPY studio/ studio/
COPY --from=web /web/dist studio/web/dist
RUN rm -rf studio/tests studio/web/node_modules studio/web/src studio/.venv studio/.cache studio/.config studio/.workcache \
 && groupadd --system --gid 10001 studio && useradd --system --uid 10001 --gid studio --home /home/studio --create-home studio \
 && mkdir -p /data /config /cache /work && chown -R studio:studio /data /config /cache /work

ENV STUDIO_ENV=production \
    STUDIO_HOST=0.0.0.0 \
    PORT=8770 \
    STUDIO_DATA_DIR=/data \
    STUDIO_CONFIG_DIR=/config \
    STUDIO_CACHE_DIR=/cache \
    STUDIO_WORKDIR=/work \
    STUDIO_SCRIPT_PYTHON=/usr/local/bin/python
USER studio
VOLUME ["/data", "/config", "/cache", "/work"]
EXPOSE 8770
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8770/api/health', timeout=4)"]
ENTRYPOINT ["/usr/bin/tini", "--"]
# one process, one uvicorn worker: background jobs live in this process (see DEPLOY.md)
CMD ["python", "studio/server.py"]
