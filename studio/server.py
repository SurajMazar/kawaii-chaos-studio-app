"""Kawaii Chaos Studio — a web app for making comic strips and reels (strips, strip reels, music videos,
lyric edits, captions, posting log, tools).

    studio/run.sh                       # local: http://localhost:8770 (first run asks you to create the admin)
    studio/.venv/bin/python studio/server.py

Production: see studio/DEPLOY.md (Docker, HTTPS proxy, S3/R2 storage). Configuration is env-driven (config.py,
.env.example).

Backend modules live in studio/api/: core (content paths, safe atomic writes, settings), jobs (background job runner),
library (dashboard), pieces (per-project texts/images/QA/layout/prompt/board), posts (captions, songs, posting log),
reel (strip-reel editor), lyric (lyric-edit editor), voiceover (voiced strip reels, ElevenLabs), tools (new project wizard, tools page, settings), auth / users
(accounts, sessions), integrations (storage backend). Storage drivers + the work cache: studio/storage/. Security
(sessions, CSRF, headers, limits, validation): studio/security/.
"""
import json, logging, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import Depends, FastAPI, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from config import CODE_ROOT, CONFIG, STUDIO  # noqa: E402
from security.context import public_route, request_id  # noqa: E402

DIST = STUDIO / 'web' / 'dist'


# ---------------- logging ----------------
class JsonFormatter(logging.Formatter):
    SKIP = set(logging.LogRecord('', 0, '', 0, '', (), None).__dict__) | {'message', 'asctime'}

    def format(self, r):
        d = dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(r.created)) + f'.{int(r.msecs):03d}Z', level=r.levelname,
                 logger=r.name, msg=r.getMessage(), request_id=request_id.get())
        d.update({k: v for k, v in r.__dict__.items() if k not in self.SKIP and not k.startswith('_')})
        if r.exc_info and not CONFIG.production: d['exc'] = self.formatException(r.exc_info)
        elif r.exc_info: d['exc_type'] = r.exc_info[0].__name__ if r.exc_info[0] else None
        return json.dumps(d, default=str)


class TextFormatter(logging.Formatter):
    def format(self, r):
        r.request_id = request_id.get()
        return super().format(r)


def setup_logging():
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter() if CONFIG.log_format == 'json' else TextFormatter('%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s'))
    root = logging.getLogger(); root.handlers[:] = [h]; root.setLevel(CONFIG.log_level)
    for n in ('uvicorn.access',): logging.getLogger(n).disabled = True    # our RequestContext logs requests (with ids)
    for n in ('botocore', 'boto3', 's3transfer', 'urllib3'): logging.getLogger(n).setLevel(logging.WARNING)


def load_secret_key():
    """STUDIO_SECRET_KEY, else <config>/secret.key; in development a key file is created on first run (0600)."""
    if CONFIG.secret_key: return
    f = CONFIG.config_dir / 'secret.key'
    try:
        CONFIG.secret_key = f.read_text().strip(); return
    except FileNotFoundError: pass
    if CONFIG.production: return
    from cryptography.fernet import Fernet
    CONFIG.config_dir.mkdir(parents=True, exist_ok=True)
    try: os.chmod(CONFIG.config_dir, 0o700)
    except OSError: pass
    key = Fernet.generate_key().decode()
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as fh: fh.write(key)
    CONFIG.secret_key = key


def seed_data_dir(cfg: dict):
    """First start on a local folder: an empty content folder gets the starter files (starter/; never overwrites)."""
    import shutil
    starter = CODE_ROOT / 'starter'
    if cfg.get('backend', 'local') != 'local' or not starter.is_dir(): return
    d = Path(cfg.get('local_path') or CONFIG.data_dir).expanduser()
    if (d / 'projects').is_dir(): return
    d.mkdir(parents=True, exist_ok=True)
    for src in sorted(starter.rglob('*')):
        dst = d / src.relative_to(starter)
        if src.is_dir(): dst.mkdir(exist_ok=True)
        elif src.name != '.gitkeep' and not dst.exists(): shutil.copy2(src, dst)
    logging.getLogger('studio').info('new content folder %s (from starter/)', d)


def create_app() -> FastAPI:
    setup_logging()
    log = logging.getLogger('studio')
    load_secret_key()
    CONFIG.config_dir.mkdir(parents=True, exist_ok=True)
    try: os.chmod(CONFIG.config_dir, 0o700)
    except OSError: pass

    from security.validation import init_image_guard
    init_image_guard(CONFIG.image_max_pixels)

    from security import auth as A
    from storage.settings import _fernet
    fernet = _fernet(CONFIG.secret_key, os.environ.get('STUDIO_SECRET_KEY_OLD', '')) if CONFIG.secret_key else None
    A.set_store(A.AuthStore(CONFIG.config_dir / 'studio.db', CONFIG.session_idle_minutes, CONFIG.session_max_hours, fernet))

    from api import integrations
    try: seed_data_dir(integrations.settings_obj().effective())
    except Exception as e: log.warning('could not prepare the content folder: %s', e)
    integrations.init_storage()

    from api import auth, jobs, library, lyric, pieces, posts, reel, tools, transfer, users, voiceover
    from api.deps import authorize
    auth.bootstrap_admin(); auth.init_setup_token()

    app = FastAPI(title='Kawaii Chaos Studio', docs_url=None if CONFIG.production else '/api/docs', redoc_url=None,
                  openapi_url=None if CONFIG.production else '/api/openapi.json')
    routers = [m.router for m in (auth, users, integrations, jobs, library, pieces, posts, reel, lyric, voiceover, tools, transfer)]
    for r in routers: app.include_router(r)      # each router is created with dependencies=[Depends(authorize)]
    app.state.api_routers = routers

    @app.get('/api/health', dependencies=[Depends(authorize)])
    @public_route
    def health():
        return dict(ok=True, app='Kawaii Chaos Studio')

    @app.get('/api/ready', dependencies=[Depends(authorize)])
    @public_route
    def ready():
        from storage import get_ws
        problems = []
        try: A.store().count_users()
        except Exception: problems.append('database')
        try:
            ws = get_ws()
            if ws.remote and time.time() - ws.index.loaded_at > max(120, CONFIG.index_ttl * 4): problems.append('storage index is stale')
        except RuntimeError: problems.append('storage')
        if problems: return JSONResponse(dict(ok=False, problems=problems), status_code=503)
        return dict(ok=True)

    # ---------------- errors (never leak stack traces in production) ----------------
    from storage import BadKey, NotFound, StorageError

    @app.exception_handler(BadKey)
    async def _bad_key(request: Request, exc: BadKey):
        return JSONResponse({'detail': 'bad path'}, status_code=400)

    @app.exception_handler(NotFound)
    async def _not_found(request: Request, exc: NotFound):
        return JSONResponse({'detail': 'no such file'}, status_code=404)

    @app.exception_handler(StorageError)
    async def _storage(request: Request, exc: StorageError):
        log.warning('storage error: %s', exc)
        return JSONResponse({'detail': f'Storage problem: {exc}'}, status_code=502)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        errs = [dict(loc=list(e.get('loc', [])), msg=e.get('msg')) for e in exc.errors()][:10]
        return JSONResponse({'detail': errs}, status_code=422)

    def on_error(scope, exc):
        rid = request_id.get()
        if isinstance(exc, RuntimeError) and 'storage is not configured' in str(exc):
            return 503, {'detail': f'Storage is not available: {integrations.STATE["error"] or "not configured"}. '
                                   'An admin can fix it in Settings → Integrations.', 'request_id': rid}
        log.error('unhandled error on %s %s', scope.get('method'), scope.get('path'), exc_info=exc)
        msg = 'Something went wrong on the server.' if CONFIG.production else f'{type(exc).__name__}: {exc}'
        return 500, {'detail': msg, 'request_id': rid}

    # ---------------- static web app ----------------
    class _WebFiles(StaticFiles):
        """index.html is never cached (so a rebuilt app shows up on reload); hashed assets are cached forever."""
        async def get_response(self, path, scope):
            r = await super().get_response(path, scope)
            r.headers['Cache-Control'] = 'public, max-age=31536000, immutable' if path.startswith('assets/') else 'no-cache'
            return r

    if DIST.exists(): app.mount('/', _WebFiles(directory=DIST, html=True), name='web')

    # ---------------- middleware (last added = outermost) ----------------
    from security.middleware import AuthGate, BodyLimit, CatchAll, HostCheck, RequestContext, SecurityHeaders
    app.add_middleware(CatchAll, on_error=on_error)
    if CONFIG.allowed_origins:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=CONFIG.allowed_origins, allow_credentials=True,
                           allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'], allow_headers=['content-type', 'x-csrf-token'])
    app.add_middleware(AuthGate)
    app.add_middleware(BodyLimit)
    app.add_middleware(SecurityHeaders)
    app.add_middleware(HostCheck)
    app.add_middleware(RequestContext)

    if not getattr(app, '_routes_checked', False):
        _assert_every_route_guarded(app); app._routes_checked = True
    log.info('Kawaii Chaos Studio ready (%s, storage: %s)', CONFIG.env,
             integrations.get_ws().describe() if not integrations.STATE['error'] else 'UNAVAILABLE')
    return app


def api_routes(app):
    """Every API route object (version-independent: read from the routers, not from FastAPI's internal tree)."""
    from fastapi.routing import APIRoute
    out = [r for r in app.routes if isinstance(r, APIRoute)]
    for router in app.state.api_routers: out += [r for r in router.routes if isinstance(r, APIRoute)]
    return [r for r in out if r.path.startswith('/api')]


def _assert_every_route_guarded(app):
    """Deny by default: refuse to start if any API route was mounted without the authorize dependency."""
    from api.deps import authorize
    for r in api_routes(app):
        if not any(d.call is authorize for d in r.dependant.dependencies):
            raise RuntimeError(f'route {r.path} is not guarded by authorize')


app = create_app() if os.environ.get('STUDIO_NO_AUTOAPP') != '1' else None

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host=CONFIG.host, port=CONFIG.port, proxy_headers=True, forwarded_allow_ips=CONFIG.trusted_proxies,
                server_header=False, log_config=None)
