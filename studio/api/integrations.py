"""Settings → Integrations: storage backend (local folder / Amazon S3 / Cloudflare R2 / other S3-compatible).

Test connection, dry-run + migrate (copy everything; the source is never deleted), save & switch. Admin only.
Secrets never go back to the browser and are stored encrypted (storage/settings.py).
"""
import hashlib
import logging
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Body, Depends, HTTPException
from .deps import authorize

from config import CODE_ROOT, CONFIG
from security.context import min_role
from storage import StorageError, Workspace, get_ws, set_workspace
from storage.local import LocalStorage
from storage.settings import FIELDS, StorageSettings, build_storage
from storage.workspace import CONTENT_DIRS, CONTENT_FILES

from . import jobs

router = APIRouter(dependencies=[Depends(authorize)])   # deny by default (api/deps.py)
log = logging.getLogger('studio.storage')
STATE = {'error': None, 'switching': False}
_switch_lock = threading.Lock()


def settings_obj() -> StorageSettings:
    return StorageSettings(CONFIG.config_dir, CONFIG.secret_key, os.environ.get('STUDIO_SECRET_KEY_OLD', ''),
                           default_local=CONFIG.data_dir, allow_insecure=CONFIG.allow_insecure_endpoints)


def make_workspace(cfg: dict) -> Workspace:
    store = build_storage(cfg, CONFIG.data_dir, CONFIG.allow_insecure_endpoints)
    workdir = CONFIG.workdir / _workdir_name(cfg) if cfg['backend'] != 'local' else None
    return Workspace(store, workdir=workdir, index_ttl=CONFIG.index_ttl, cache_max_bytes=int(CONFIG.cache_max_gb * (1 << 30)),
                     code_root=CODE_ROOT)


def _workdir_name(cfg: dict) -> str:
    """One cache folder per bucket/prefix/endpoint, so switching never mixes caches."""
    ident = f"{cfg['backend']}|{cfg.get('endpoint') or cfg.get('account_id') or ''}|{cfg.get('bucket')}|{cfg.get('prefix') or ''}"
    return hashlib.sha256(ident.encode()).hexdigest()[:16]


def init_storage():
    """Called at startup. If the configured backend is unreachable the API answers 503 until an admin fixes it."""
    try:
        cfg = settings_obj().effective()
        set_workspace(make_workspace(cfg)); STATE['error'] = None
        log.info('storage: %s', get_ws().describe())
    except Exception as e:
        STATE['error'] = str(e)
        log.error('storage is not available: %s', e)


def _status():
    try: ws = get_ws()
    except RuntimeError: return dict(active=None, remote=None, error=STATE['error'])
    out = dict(active=ws.describe(), remote=ws.remote, error=STATE['error'], kind=ws.store.kind)
    if ws.remote:
        out.update(objects=len(ws.index.files), index_age=round(time.time() - ws.index.loaded_at, 1),
                   cache_bytes=ws.manifest.total(), cache_dir=str(ws.root))
    return out


@router.get('/api/integrations/storage')
@min_role('admin')
def get_storage():
    return dict(config=settings_obj().public_view(), status=_status(),
                allow_insecure=CONFIG.allow_insecure_endpoints, running_jobs=len(jobs.running()))


def _candidate(body: dict) -> dict:
    s = settings_obj()
    try: return s.merged({k: v for k, v in body.items() if k in FIELDS})
    except StorageError as e: raise HTTPException(400, str(e))


@router.post('/api/integrations/storage/test')
@min_role('admin')
def test_storage(body: dict = Body(...)):
    cfg = _candidate(body)
    try:
        st = build_storage(cfg, CONFIG.data_dir, CONFIG.allow_insecure_endpoints)
        res = st.probe()
    except StorageError as e:
        return dict(ok=False, error=str(e))
    except Exception as e:                                   # never leak secrets / stack traces
        log.warning('storage test failed: %s', type(e).__name__)
        return dict(ok=False, error=f'The connection test failed ({type(e).__name__}).')
    return res


# ---------------- migration ----------------
def content_entries(store):
    out = {}
    for top in CONTENT_DIRS:
        for e in store.list(top, recursive=True): out[e.key] = e
    for f in CONTENT_FILES:
        e = store.stat(f)
        if e: out[e.key] = e
    return out


def _md5(path) -> str:
    h = hashlib.md5()  # nosec B324 - compared with S3 ETags (which are MD5), not a security use
    with open(path, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''): h.update(c)
    return h.hexdigest()


def _same(src_store, dst_store, se, de) -> bool:
    if de is None or de.size != se.size: return False
    if se.etag and de.etag and se.etag == de.etag: return True
    loc, rem = (src_store, de) if isinstance(src_store, LocalStorage) else (dst_store, se) if isinstance(dst_store, LocalStorage) else (None, None)
    if loc is not None and rem.etag and '-' not in rem.etag:
        key = se.key
        return _md5(loc.path(key)) == rem.etag
    return False


def _copy_one(src, dst, key):
    if isinstance(src, LocalStorage):
        dst.upload_file(key, str(src.path(key))); return
    fd, tmp = tempfile.mkstemp(prefix='kcs_mig_'); os.close(fd)
    try:
        src.download_file(key, tmp); dst.upload_file(key, tmp)
    finally:
        try: os.unlink(tmp)
        except OSError: pass


@router.post('/api/integrations/storage/migrate/plan')
@min_role('admin')
def migrate_plan(body: dict = Body(...)):
    cfg = _candidate(body)
    try:
        dst = build_storage(cfg, CONFIG.data_dir, CONFIG.allow_insecure_endpoints)
        src = get_ws().store
        if dst.describe() == src.describe(): raise HTTPException(400, 'That is the storage already in use.')
        s = content_entries(src); d = content_entries(dst)
    except StorageError as e: raise HTTPException(400, str(e))
    same_size = sum(1 for k, e in s.items() if k in d and d[k].size == e.size)
    return dict(source=src.describe(), target=dst.describe(), objects=len(s), bytes=sum(e.size for e in s.values()),
                existing_same_size=same_size, target_objects=len(d))


@router.post('/api/integrations/storage/migrate')
@min_role('admin')
def migrate(body: dict = Body(...)):
    cfg = _candidate(body)
    try:
        dst = build_storage(cfg, CONFIG.data_dir, CONFIG.allow_insecure_endpoints)
        dst.probe()
    except StorageError as e: raise HTTPException(400, str(e))
    src = get_ws().store
    if dst.describe() == src.describe(): raise HTTPException(400, 'That is the storage already in use.')

    def go(job):
        jobs.log(job, f'Copying from {src.describe()} to {dst.describe()} (the source is not changed).')
        s = content_entries(src); d = content_entries(dst)
        keys = sorted(s); job['total'] = len(keys); total_b = sum(e.size for e in s.values()) or 1
        done_b = [0]; copied = [0]; skipped = [0]; failed = []
        lk = threading.Lock()

        def one(k):
            if job['cancel']: return
            try:
                if _same(src, dst, s[k], d.get(k)):
                    with lk: skipped[0] += 1
                else:
                    _copy_one(src, dst, k)
                    with lk: copied[0] += 1
            except Exception as e:
                with lk: failed.append(k); jobs.log(job, f'FAILED {k}: {e}')
            with lk:
                done_b[0] += s[k].size; job['done'] += 1; job['progress'] = round(done_b[0] / total_b, 4)
                if job['done'] % 200 == 0: jobs.log(job, f"{job['done']}/{job['total']} files")
        with ThreadPoolExecutor(max_workers=8) as ex: list(ex.map(one, keys))
        if job['cancel']: raise KeyboardInterrupt
        jobs.log(job, f'Done: {copied[0]} copied, {skipped[0]} already there, {len(failed)} failed.')
        if failed: raise RuntimeError(f'{len(failed)} files could not be copied (see details) — run Migrate again to retry.')
        return dict(copied=copied[0], skipped=skipped[0], failed=len(failed), target=dst.describe())
    job = jobs.start_fn('migrate', 'Copy all files to the new storage', go, ref='integrations/migrate')
    return jobs.public(job)


@router.put('/api/integrations/storage')
@min_role('admin')
def save_storage(body: dict = Body(...)):
    """Save & switch. The new backend is tested first; nothing is copied or deleted (use Migrate before switching)."""
    if jobs.running(): raise HTTPException(409, 'Wait until the running jobs finish (see Jobs), then switch.')
    s = settings_obj()
    cfg = _candidate(body)
    with _switch_lock:
        try:
            ws = make_workspace(cfg)
            ws.store.probe()
            s.save({k: v for k, v in body.items() if k in FIELDS})
        except StorageError as e: raise HTTPException(400, str(e))
        set_workspace(ws); STATE['error'] = None
    from .library import invalidate
    invalidate()
    log.info('storage switched to %s', ws.describe())
    return dict(ok=True, config=s.public_view(), status=_status())
