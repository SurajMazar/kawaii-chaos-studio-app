"""One generic background job runner.

A job runs either a list of subprocess steps (stdout+stderr streamed line by line into job['log']) or a Python function
in a thread. Progress comes from parseable lines ("frame 60/540", "5.0s / 34.0s", "42%"), from a polled
`progress_fn(job)` (e.g. files appearing), or from the function itself. Jobs can be cancelled (process group SIGTERM,
or job['cancel'] for in-process functions).

Deployment notes:
* jobs live in this process (single server process / single uvicorn worker — see DEPLOY.md);
* at most STUDIO_MAX_JOBS run at once (the rest wait as "queued"); a user may have STUDIO_MAX_JOBS_PER_USER active
  jobs and start STUDIO_JOB_STARTS_PER_MINUTE per minute (429 otherwise);
* with an S3/R2 backend, ``sync`` = dict(pull=[patterns], push=[patterns], scope='projects/151_x') pulls the inputs into
  the work cache before the steps and pushes the outputs back afterwards (storage/workspace.py: job_sync).
"""
import os, re, signal, subprocess, threading, time, uuid  # nosec B404 - argument lists only, never a shell
from collections import OrderedDict, deque

from fastapi import APIRouter, Depends, HTTPException
from .deps import authorize

from config import CONFIG
from security.context import current_user, min_role
from storage import get_ws

from .core import script_env

router = APIRouter(dependencies=[Depends(authorize)])   # deny by default (api/deps.py)
JOBS: 'OrderedDict[str, dict]' = OrderedDict()
_lock = threading.Lock()
MAX_LOG = 4000
PROG_RE = [re.compile(r'(\d+(?:\.\d+)?)s?\s*/\s*(\d+(?:\.\d+)?)s?\b'), re.compile(r'(\d+(?:\.\d+)?)\s*%')]
PUBLIC_SKIP = {'cancel', 'log', '_proc', 'fn', 'owner_id'}
_slots = threading.BoundedSemaphore(CONFIG.max_jobs)
_starts: dict = {}


def _check_limits(uid):
    if uid is None: return
    now = time.time()
    q = _starts.setdefault(uid, deque())
    while q and q[0] < now - 60: q.popleft()
    if len(q) >= CONFIG.job_starts_per_minute: raise HTTPException(429, 'Too many jobs started in the last minute — wait a moment.')
    mine = [j for j in JOBS.values() if j.get('owner_id') == uid and j['state'] in ('queued', 'running')]
    if len(mine) >= CONFIG.max_jobs_per_user:
        raise HTTPException(429, f'You already have {len(mine)} jobs running — wait for one to finish (see Jobs).')
    q.append(now)


def new_job(kind, title, ref=None, meta=None):
    u = current_user.get()
    _check_limits(u['id'] if u else None)
    jid = uuid.uuid4().hex[:10]
    job = dict(id=jid, kind=kind, title=title, ref=ref, state='queued', progress=0.0, done=0, total=0,
               started=time.time(), finished=None, error=None, result=None, log=[], cancel=False, step='',
               owner_id=u['id'] if u else None, owner=(u.get('name') or u.get('email')) if u else None, **(meta or {}))
    with _lock:
        JOBS[jid] = job
        while len(JOBS) > 60:
            old = next(iter(JOBS))
            if JOBS[old]['state'] in ('queued', 'running'): break
            JOBS.pop(old)
    return job


def log(job, line):
    line = line.rstrip('\n')
    job['log'].append(line)
    if len(job['log']) > MAX_LOG: del job['log'][:len(job['log']) - MAX_LOG]


def public(job, since=None):
    out = {k: v for k, v in job.items() if k not in PUBLIC_SKIP}
    out['log_total'] = len(job['log'])
    if since is not None: out['log'] = job['log'][since:] if since <= len(job['log']) else job['log'][-200:]
    return out


def running(ref=None, kind=None):
    return [j for j in JOBS.values() if j['state'] in ('queued', 'running')
            and (ref is None or j.get('ref') == ref) and (kind is None or j.get('kind') == kind)]


def ensure_free(ref, kind):
    if running(ref, kind): raise HTTPException(409, 'This is already running — wait for it to finish (see Jobs).')


def _parse_progress(line):
    if re.search(r'\d{4}-\d{2}-\d{2}', line): return None
    for rx in PROG_RE:
        m = rx.search(line)
        if m:
            if rx is PROG_RE[1]: return min(1.0, float(m.group(1)) / 100)
            a, b = float(m.group(1)), float(m.group(2))
            if b > 0 and a <= b: return a / b
    return None


def _set_progress(job, step_i, weights, inner):
    tot = sum(weights) or 1
    job['progress'] = round(min(1.0, (sum(weights[:step_i]) + weights[step_i] * max(0.0, min(1.0, inner))) / tot), 4)


def _acquire_slot(job):
    while not _slots.acquire(timeout=0.5):
        if job['cancel']: raise KeyboardInterrupt


def _sync_ctx(sync):
    ws = get_ws()
    if not sync: return ws.job_sync()
    return ws.job_sync(pull=sync.get('pull', ()), push=sync.get('push', ()), scope=sync.get('scope', ''), exclude=sync.get('exclude', ()),
                       stubs=sync.get('stubs', ()))


def run_steps(job, steps, cwd=None, env=None, progress_fn=None, fail_patterns=(), on_done=None, sync=None):
    """steps: [{'cmd': [...], 'label': 'Rendering'}]. Blocks; use start_steps() for a thread."""
    env = env or script_env()
    weights = [float(st.get('weight', 1)) for st in steps]
    stop_ticker = threading.Event()
    slot = False

    def ticker():
        while not stop_ticker.wait(0.7):
            try:
                p = progress_fn(job) if progress_fn else None
                if p is not None: job['progress'] = max(job['progress'], round(p, 4))
            except Exception: pass  # nosec B110 - progress polling is best effort
    try:
        _acquire_slot(job); slot = True
        job['step'] = 'Getting the files ready' if get_ws().remote else ''
        with _sync_ctx(sync) as root:
            job['state'] = 'running'
            wd = str(cwd or root)
            if progress_fn: threading.Thread(target=ticker, daemon=True).start()
            for i, st in enumerate(steps):
                if job['cancel']: raise KeyboardInterrupt
                job['step'] = st.get('label', ''); log(job, f"$ {' '.join(map(str, st['cmd']))}")
                proc = subprocess.Popen([str(c) for c in st['cmd']], cwd=wd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,  # nosec B603 - argument list, no shell
                                        text=True, bufsize=1, start_new_session=True, errors='replace')
                job['_proc'] = proc
                for line in proc.stdout:
                    for part in line.replace('\r', '\n').split('\n'):
                        if not part.strip(): continue
                        log(job, part)
                        if not progress_fn:
                            p = _parse_progress(part)
                            if p is not None: _set_progress(job, i, weights, p)
                        for pat in fail_patterns:
                            if pat in part: job['error'] = part.strip()
                rc = proc.wait(); job['_proc'] = None
                if job['cancel']: raise KeyboardInterrupt
                if rc != 0 and not st.get('allow_fail'): raise RuntimeError(f"{st.get('label') or 'step'} failed (exit code {rc})")
                if job['error']: raise RuntimeError(job['error'])
                if not progress_fn: _set_progress(job, i, weights, 1.0)
            job['step'] = 'Saving the results' if get_ws().remote else job['step']
        if on_done: job['result'] = on_done(job)
        job.update(state='done', progress=1.0)
    except KeyboardInterrupt:
        job['state'] = 'cancelled'; log(job, 'Cancelled.')
    except Exception as e:
        job.update(state='error', error=str(e)); log(job, f'ERROR: {e}')
    finally:
        stop_ticker.set(); job['finished'] = time.time(); job['_proc'] = None
        if slot: _slots.release()


def start_steps(kind, title, steps, ref=None, meta=None, **kw):
    ensure_free(ref, kind)
    job = new_job(kind, title, ref, meta)
    threading.Thread(target=run_steps, args=(job, steps), kwargs=kw, daemon=True).start()
    return job


def start_fn(kind, title, fn, ref=None, meta=None, sync=None):
    """fn(job) runs in a thread; it may update job['done'], job['total'], job['progress'], call log(job, ...), and
    should check job['cancel'] (raise KeyboardInterrupt to stop). Its return value becomes job['result']."""
    ensure_free(ref, kind)
    job = new_job(kind, title, ref, meta)

    def go():
        slot = False
        try:
            _acquire_slot(job); slot = True
            with _sync_ctx(sync):
                job['state'] = 'running'
                job['result'] = fn(job)
            job.update(state='done', progress=1.0)
        except KeyboardInterrupt: job['state'] = 'cancelled'; log(job, 'Cancelled.')
        except Exception as e: job.update(state='error', error=str(e)); log(job, f'ERROR: {e}')
        finally:
            job['finished'] = time.time()
            if slot: _slots.release()
    threading.Thread(target=go, daemon=True).start()
    return job


def run_sync(cmd, timeout=180, cwd=None, sync=None):
    """Run a short script and return (code, output). ``sync`` as for jobs (remote backends)."""
    with _sync_ctx(sync) as root:
        p = subprocess.run([str(c) for c in cmd], cwd=str(cwd or root), env=script_env(), capture_output=True, text=True,  # nosec B603 - argument list, no shell
                           timeout=timeout, errors='replace')
    return p.returncode, (p.stdout + p.stderr).strip()


@router.get('/api/jobs')
def list_jobs(ref: str | None = None, active: bool = False):
    js = [j for j in reversed(JOBS.values()) if (ref is None or j.get('ref') == ref) and (not active or j['state'] in ('queued', 'running'))]
    return [public(j) for j in js]


@router.get('/api/jobs/{jid}')
def get_job(jid: str, since: int | None = None):
    if jid not in JOBS: raise HTTPException(404, 'no such job (the server may have restarted)')
    return public(JOBS[jid], since)


@router.post('/api/jobs/{jid}/cancel')
@min_role('editor')
def cancel_job(jid: str):
    job = JOBS.get(jid)
    if not job: raise HTTPException(404, 'no such job')
    u = current_user.get()
    if u and u['role'] != 'admin' and job.get('owner_id') not in (None, u['id']):
        raise HTTPException(403, 'Only the person who started this job (or an admin) can stop it.')
    job['cancel'] = True
    proc = job.get('_proc')
    if proc and proc.poll() is None:
        try: os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError): pass
    return dict(ok=True)
