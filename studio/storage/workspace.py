"""The workspace: every file the API touches goes through here, on top of a Storage driver.

* **Local backend** — the storage root *is* the working tree (by default the repo itself), so behaviour is exactly the
  pre-storage Studio: atomic writes, ``.studio_history/`` backups next to the file, scripts run in place.
* **S3 / R2 / S3-compatible** — the bucket is the source of truth. A local **work cache** (``STUDIO_WORKDIR``) mirrors
  what is needed:

  - an in-memory **index** of every object (one paginated listing, refreshed in the background every
    ``STUDIO_INDEX_TTL`` s and updated immediately by our own writes) answers exists / stat / list without network
    calls;
  - ``local(key)`` downloads an object into the cache only when its ETag changed (a small SQLite manifest remembers
    the ETag + local size/mtime of every cached file);
  - writes go to the bucket first (write-through) and then update the cache, index and manifest;
  - background **jobs** (ffmpeg, PIL scripts, build_reel.sh) declare what they read and write: ``job_sync`` pulls the
    inputs into the cache (incremental by ETag), the job runs on real files, then every new/changed output is pushed
    back (and outputs the job deleted are deleted in the bucket). Jobs on the same project are serialised by a
    per-project lock.
  - history backups are objects under ``<folder>/.studio_history/`` in the bucket (same names as on disk).

``SPath`` is a small pathlib-like handle on a key, so the API code reads like it did with ``pathlib.Path``.
"""
from __future__ import annotations

import fnmatch
import hashlib
import logging
import mimetypes
import os
import posixpath
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator

from .base import BadKey, Entry, NotFound, Storage, StorageError, norm_key
from .local import LocalStorage

log = logging.getLogger('studio.storage')

CONTENT_DIRS = ('projects', 'music_videos', 'upload', 'references', 'fonts', 'mascot', 'batches', '.studio_history')
CONTENT_FILES = ('captions.json', 'posting_log.json', 'songs.md', 'songs_original.md', 'couples.md', 'style.md',
                 'qa_rules.md', 'README.md', 'voices.json')
HISTORY_KEEP = 50
INLINE_MAX = 32 * 1024 * 1024           # remote files up to this size are served from the cache (Range via FileResponse)
PUSH_SKIP = re.compile(r'(^|/)(\.studio_history/|__pycache__/|\.DS_Store$)|\.tmp$|\.rendering|(^|/)\.[^/]+\.[^/]*\.tmp$')


def allowed_key(key: str) -> bool:
    """Only the content folders/files are reachable through the API (never studio/, scripts/, .git, config…)."""
    top = key.split('/', 1)[0]
    if '/' in key: return top in CONTENT_DIRS
    return key in CONTENT_FILES or key in CONTENT_DIRS


def pattern_re(pat: str) -> re.Pattern:
    """Glob over keys: ``*`` and ``?`` stay inside one folder, ``**`` crosses folders."""
    out = ''; i = 0
    while i < len(pat):
        c = pat[i]
        if pat.startswith('**', i): out += '.*'; i += 2; continue
        out += '[^/]*' if c == '*' else '[^/]' if c == '?' else re.escape(c)
        i += 1
    return re.compile(out + r'\Z')


def literal_prefix(pat: str) -> str:
    m = re.search(r'[*?\[]', pat)
    return pat if not m else pat[:m.start()]


# ======================================================================================================================
class _Index:
    """In-memory listing of a remote store: files + derived folder tree."""

    def __init__(self):
        self.files: dict[str, Entry] = {}
        self.children: dict[str, set[str]] = {'': set()}
        self.loaded_at = 0.0
        self.lock = threading.RLock()
        self.recent: 'OrderedDict[str, tuple[float, Entry | None]]' = OrderedDict()   # our own mutations

    def _add_parents(self, key: str):
        parts = key.split('/')
        for i in range(len(parts)):
            parent = '/'.join(parts[:i]); child = parts[i]
            self.children.setdefault(parent, set()).add(child)

    def rebuild(self, entries: Iterable[Entry], started: float):
        files = {e.key: e for e in entries if not e.is_dir}
        with self.lock:
            # re-apply mutations we made while the listing was running
            for k, (t, e) in self.recent.items():
                if t >= started:
                    if e is None: files.pop(k, None)
                    else: files[k] = e
            self.files = files; self.children = {'': set()}
            for k in files: self._add_parents(k)
            self.loaded_at = time.time()
            cutoff = time.time() - 600
            while self.recent and next(iter(self.recent.values()))[0] < cutoff: self.recent.popitem(last=False)

    def put(self, e: Entry):
        with self.lock:
            self.files[e.key] = e; self._add_parents(e.key)
            self.recent[e.key] = (time.time(), e); self.recent.move_to_end(e.key)

    def remove(self, key: str):
        with self.lock:
            self.files.pop(key, None)
            self.recent[key] = (time.time(), None); self.recent.move_to_end(key)
            parts = key.split('/')
            for i in range(len(parts), 0, -1):
                parent = '/'.join(parts[:i - 1]); child = parts[i - 1]; me = '/'.join(parts[:i])
                if me in self.files or self.children.get(me): break
                self.children.get(parent, set()).discard(child); self.children.pop(me, None)

    def is_dir(self, key: str) -> bool:
        with self.lock: return bool(self.children.get(key))

    def list(self, key: str) -> list[tuple[str, Entry | None]]:
        with self.lock:
            out = []
            for name in self.children.get(key, ()):
                k = f'{key}/{name}' if key else name
                out.append((name, self.files.get(k)))
            return out

    def under(self, prefix: str) -> list[Entry]:
        with self.lock:
            if not prefix: return list(self.files.values())
            p = prefix + '/'
            return [e for k, e in self.files.items() if k.startswith(p)]


class _Manifest:
    """SQLite record of what is in the cache: key -> etag, local size, local mtime_ns, last use; plus sha1 per etag."""

    def __init__(self, path: Path):
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS files (key TEXT PRIMARY KEY, etag TEXT, size INTEGER, mtime_ns INTEGER, used REAL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS shas (key TEXT, etag TEXT, sha1 TEXT, PRIMARY KEY(key, etag))')
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            r = self.db.execute('SELECT etag, size, mtime_ns FROM files WHERE key=?', (key,)).fetchone()
        return r

    def put(self, key, etag, size, mtime_ns):
        with self.lock:
            self.db.execute('INSERT OR REPLACE INTO files VALUES (?,?,?,?,?)', (key, etag, size, mtime_ns, time.time()))

    def touch(self, key):
        with self.lock: self.db.execute('UPDATE files SET used=? WHERE key=?', (time.time(), key))

    def remove(self, key):
        with self.lock: self.db.execute('DELETE FROM files WHERE key=?', (key,))

    def keys_under(self, prefix: str):
        with self.lock:
            if not prefix: return [r[0] for r in self.db.execute('SELECT key FROM files')]
            return [r[0] for r in self.db.execute('SELECT key FROM files WHERE key >= ? AND key < ?', (prefix + '/', prefix + '0'))]

    def lru(self):
        with self.lock: return self.db.execute('SELECT key, size FROM files ORDER BY used ASC').fetchall()

    def total(self):
        with self.lock: return self.db.execute('SELECT COALESCE(SUM(size),0) FROM files').fetchone()[0]

    def sha(self, key, etag):
        with self.lock:
            r = self.db.execute('SELECT sha1 FROM shas WHERE key=? AND etag=?', (key, etag)).fetchone()
        return r[0] if r else None

    def put_sha(self, key, etag, sha):
        with self.lock: self.db.execute('INSERT OR REPLACE INTO shas VALUES (?,?,?)', (key, etag, sha))


class _Stat:
    """os.stat_result look-alike for SPath.stat()."""
    def __init__(self, size=0, mtime=0.0, mtime_ns=None, ctime=None, mode=0o100644):
        self.st_size = size; self.st_mtime = mtime; self.st_mtime_ns = mtime_ns if mtime_ns is not None else int(mtime * 1e9)
        self.st_ctime = ctime if ctime is not None else mtime; self.st_birthtime = self.st_ctime; self.st_mode = mode


# ======================================================================================================================
class Workspace:
    def __init__(self, store: Storage, workdir: Path | None = None, index_ttl: float = 30.0, cache_max_bytes: int = 20 << 30,
                 code_root: Path | None = None, start_refresher: bool = True):
        self.store = store
        self.remote = not isinstance(store, LocalStorage)
        self.root: Path = (Path(workdir).expanduser().resolve() if self.remote else store.root)
        self.index_ttl = index_ttl
        self.cache_max = cache_max_bytes
        self._proj_locks: dict[str, threading.RLock] = {}
        self._job_locks: dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()
        self._dl_locks = [threading.Lock() for _ in range(64)]
        self._sha_local: dict = {}
        self._placeholder_keys: set = set()
        self._closed = threading.Event()
        self.code_root = code_root
        if self.remote:
            self.root.mkdir(parents=True, exist_ok=True)
            self.index = _Index()
            self.manifest = _Manifest(self.root / '.studio_cache.db')
            self.refresh_index()
            if start_refresher: threading.Thread(target=self._refresher, daemon=True, name='index-refresh').start()
        self._link_scripts()

    def describe(self) -> str:
        return self.store.describe()

    def close(self):
        self._closed.set()

    # ---------------- scripts symlink (so repo scripts that use "<script dir>/.." as ROOT work in the cache) -----------
    def _link_scripts(self):
        if not self.code_root: return
        src = (self.code_root / 'scripts').resolve(); dst = self.root / 'scripts'
        if dst.is_symlink() and dst.resolve() != src:
            dst.unlink()                                    # stale link (code moved): relink
        if dst.exists() or dst.is_symlink():
            return
        try: dst.symlink_to(src, target_is_directory=True)
        except OSError as e: log.warning('could not link scripts into %s: %s', self.root, e)

    # ---------------- index ----------------
    def refresh_index(self):
        if not self.remote: return
        t0 = time.time()
        entries = []
        for top in self._tops():
            entries.extend(self.store.list(top, recursive=True) if top in CONTENT_DIRS else
                           [e for e in [self.store.stat(top)] if e])
        self.index.rebuild(entries, t0)
        log.debug('index refreshed: %d objects in %.2fs', len(self.index.files), time.time() - t0)

    def _tops(self):
        return list(CONTENT_DIRS) + list(CONTENT_FILES)

    def _refresher(self):
        while not self._closed.wait(self.index_ttl):
            try: self.refresh_index()
            except Exception as e: log.warning('index refresh failed: %s', e)

    # ---------------- keys ----------------
    def check(self, key: str, allow_root=False) -> str:
        k = norm_key(key, allow_root=allow_root)
        if k and not allowed_key(k): raise BadKey('not a content path')
        return k

    def lpath(self, key: str) -> Path:
        """Local path of a key in the working tree (no download)."""
        k = norm_key(key, allow_root=True)
        return self.root / k if k else self.root

    # ---------------- reads ----------------
    def stat(self, key: str) -> Entry | None:
        k = self.check(key)
        if not self.remote:
            p = self.store.path(k)
            try: st = p.stat()
            except (FileNotFoundError, NotADirectoryError): return None
            return Entry(key=k, size=st.st_size, mtime=st.st_mtime, etag=f'{st.st_size}-{st.st_mtime_ns}', is_dir=p.is_dir(),
                         extra=dict(mtime_ns=st.st_mtime_ns, ctime=getattr(st, 'st_birthtime', st.st_ctime), mode=st.st_mode))
        e = self.index.files.get(k)
        if e: return e
        if self.index.is_dir(k):
            kids = self.index.under(k)
            mt = max((x.mtime for x in kids), default=0.0); ct = min((x.mtime for x in kids), default=0.0)
            return Entry(key=k, is_dir=True, mtime=mt, extra=dict(ctime=ct))
        return None

    def is_file(self, key: str) -> bool:
        e = self.stat(key); return bool(e and not e.is_dir)

    def is_dir(self, key: str) -> bool:
        k = self.check(key, allow_root=True)
        if not k: return True
        if not self.remote: return self.store.path(k).is_dir()
        return self.index.is_dir(k)

    def exists(self, key: str) -> bool:
        return self.stat(key) is not None

    def listdir(self, key: str) -> list[Entry]:
        """Direct children (files and folders) of a folder key."""
        k = self.check(key, allow_root=True)
        if not self.remote:
            base = self.store.path(k, allow_root=True)
            if not base.is_dir(): return []
            out = []
            for c in base.iterdir():
                ck = f'{k}/{c.name}' if k else c.name
                if not k and not allowed_key(c.name): continue
                try:
                    if c.is_symlink() and not self.store._inside(c): continue
                    st = c.stat()
                except (FileNotFoundError, OSError): continue
                out.append(Entry(key=ck, size=st.st_size, mtime=st.st_mtime, etag=f'{st.st_size}-{st.st_mtime_ns}', is_dir=c.is_dir(),
                                 extra=dict(mtime_ns=st.st_mtime_ns, ctime=getattr(st, 'st_birthtime', st.st_ctime), mode=st.st_mode)))
            return out
        out = []
        for name, e in self.index.list(k):
            ck = f'{k}/{name}' if k else name
            if not k and not allowed_key(name): continue
            out.append(e if e else self.stat(ck))
        return [e for e in out if e]

    def walk(self, key: str) -> list[Entry]:
        """Every file under a folder key (recursive)."""
        k = self.check(key, allow_root=True)
        if not self.remote:
            return [e for e in self.store.list(k, recursive=True) if (k or allowed_key(e.key))]
        return [e for e in self.index.under(k) if allowed_key(e.key)]

    def read_bytes(self, key: str) -> bytes:
        k = self.check(key)
        if not self.remote: return self.store.read_bytes(k)
        return self.local(k).read_bytes()

    def local(self, key: str) -> Path:
        """A fresh local copy of a file (the file itself with the local backend)."""
        k = self.check(key)
        if not self.remote:
            p = self.store.path(k)
            if not p.is_file(): raise NotFound(k)
            return p
        e = self.index.files.get(k)
        if e is None:
            e = self.store.stat(k)
            if e is None: raise NotFound(k)
            self.index.put(e)
        p = self.root / k
        with self._dl_locks[hash(k) % 64]:
            m = self.manifest.get(k)
            if m and m[0] == e.etag:
                try:
                    st = p.stat()
                    if st.st_size == m[1] and st.st_mtime_ns == m[2]:
                        self.manifest.touch(k); return p
                except FileNotFoundError: pass
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f'.{p.name}.', suffix='.tmp'); os.close(fd)
            try:
                self.store.download_file(k, tmp)
                os.replace(tmp, p)
            except BaseException:
                try: os.unlink(tmp)
                except OSError: pass
                raise
            st = p.stat()
            self.manifest.put(k, e.etag, st.st_size, st.st_mtime_ns)
        return p

    # ---------------- writes ----------------
    def project_scope(self, key: str) -> str:
        parts = key.split('/')
        if parts[0] in ('projects', 'music_videos') and len(parts) > 1: return '/'.join(parts[:2])
        return parts[0]

    def proj_lock(self, key: str) -> threading.RLock:
        s = self.project_scope(key)
        with self._locks_lock:
            return self._proj_locks.setdefault(s, threading.RLock())

    def job_lock(self, scope: str) -> threading.Lock:
        with self._locks_lock:
            return self._job_locks.setdefault(scope, threading.Lock())

    def write(self, key: str, data: bytes | str, history: bool = True, content_type: str | None = None) -> Entry:
        k = self.check(key)
        if isinstance(data, str): data = data.encode()
        with self.proj_lock(k):
            if history: self.backup(k)
            if not self.remote:
                return self.store.write_bytes(k, data, content_type)
            e = self.store.write_bytes(k, data, content_type)
            self.index.put(e)
            self._cache_put(k, data, e)
            return e

    def _cache_put(self, k: str, data: bytes, e: Entry):
        p = self.root / k; p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f'.{p.name}.', suffix='.tmp')
        with os.fdopen(fd, 'wb') as f: f.write(data)
        os.chmod(tmp, 0o644); os.replace(tmp, p)
        st = p.stat(); self.manifest.put(k, e.etag, st.st_size, st.st_mtime_ns)

    def upload_local(self, key: str, path: Path) -> Entry:
        """Store a file that already exists in the working tree (remote: push it; local: nothing to do)."""
        k = self.check(key)
        if not self.remote:
            e = self.store.stat(k)
            if e is None: raise NotFound(k)
            return e
        e = self.store.upload_file(k, str(path))
        st = Path(path).stat()
        self.index.put(e); self.manifest.put(k, e.etag, st.st_size, st.st_mtime_ns)
        return e

    def history_key(self, key: str) -> str:
        d, name = posixpath.split(key)
        stem, suf = posixpath.splitext(name)
        h = f'{d}/.studio_history' if d else '.studio_history'
        ts = time.strftime('%Y%m%d-%H%M%S')
        dst = f'{h}/{stem}_{ts}{suf}'; n = 2
        while self.exists(dst): dst = f'{h}/{stem}_{ts}_{n}{suf}'; n += 1
        return dst

    def backup(self, key: str) -> str | None:
        """Copy the current version into <folder>/.studio_history/<stem>_<time><suffix>; keep the newest 50."""
        k = self.check(key)
        e = self.stat(k)
        if not e or e.is_dir: return None
        with self.proj_lock(k):
            dst = self.history_key(k)
            ne = self.store.copy(k, dst)
            if self.remote: self.index.put(ne)
            d, name = posixpath.split(k); stem, suf = posixpath.splitext(name)
            h = f'{d}/.studio_history' if d else '.studio_history'
            rx = re.compile(re.escape(f'{h}/{stem}_2') + '[^/]*' + re.escape(suf) + r'\Z')
            olds = sorted(x.key for x in self.listdir(h) if not x.is_dir and rx.match(x.key))
            for o in olds[:-HISTORY_KEEP]:
                try: self.delete(o)
                except StorageError: pass
            return dst

    def delete(self, key: str):
        k = self.check(key)
        with self.proj_lock(k):
            self.store.delete(k)
            if self.remote:
                self.index.remove(k); self.manifest.remove(k)
                try: (self.root / k).unlink()
                except FileNotFoundError: pass

    def copy(self, src: str, dst: str) -> Entry:
        s, d = self.check(src), self.check(dst)
        with self.proj_lock(d):
            e = self.store.copy(s, d)
            if self.remote:
                self.index.put(e)
                sp = self.root / s
                m = self.manifest.get(s)
                if m and sp.exists():
                    dp = self.root / d; dp.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(sp, dp)
                    st = dp.stat(); self.manifest.put(d, e.etag, st.st_size, st.st_mtime_ns)
            return e

    def move(self, src: str, dst: str) -> Entry:
        s, d = self.check(src), self.check(dst)
        if not self.remote:
            with self.proj_lock(d): return self.store.move(s, d)
        e = self.copy(s, d); self.delete(s)
        return e

    def mkdir(self, key: str):
        k = self.check(key)
        if not self.remote: self.store.path(k).mkdir(parents=True, exist_ok=True)
        else: (self.root / k).mkdir(parents=True, exist_ok=True)   # folders are implicit in buckets

    # ---------------- sha1 ----------------
    def sha1(self, key: str) -> str | None:
        try: k = self.check(key)
        except BadKey: return None
        e = self.stat(k)
        if not e or e.is_dir: return None
        if not self.remote:
            p = self.store.path(k)
            ck = (str(p), e.extra.get('mtime_ns'), e.size)
            v = self._sha_local.get(ck)
            if v: return v
            v = _sha1_path(p); self._sha_local[ck] = v
            return v
        v = self.manifest.sha(k, e.etag)
        if v: return v
        v = _sha1_path(self.local(k)); self.manifest.put_sha(k, e.etag, v)
        return v

    # ---------------- job sync ----------------
    def _match(self, pats: list[str]):
        rxs = [pattern_re(p) for p in pats]
        return lambda k: any(r.match(k) for r in rxs)

    def pull(self, patterns: list[str], exclude: list[str] = ()) -> int:
        """Bring every object matching the patterns into the cache (download only what changed). Files we cached
        earlier that were deleted in the bucket are removed locally; files the cache does not know are left alone."""
        if not self.remote or not patterns: return 0
        inc = self._match(patterns); exc = self._match(list(exclude) + ['**/.studio_history/**', '.studio_history/**'])
        prefixes = {literal_prefix(p).rstrip('/').rsplit('/', 1)[0] if '/' in literal_prefix(p) else '' for p in patterns}
        cands: dict[str, Entry] = {}
        for pre in prefixes:
            for e in (self.index.under(pre) if pre else list(self.index.files.values())):
                if inc(e.key) and not exc(e.key): cands[e.key] = e
        todo = []
        for k, e in cands.items():
            m = self.manifest.get(k); p = self.root / k
            ok = False
            if m and m[0] == e.etag:
                try: st = p.stat(); ok = st.st_size == m[1] and st.st_mtime_ns == m[2]
                except FileNotFoundError: ok = False
            if not ok: todo.append(k)
        if todo:
            with ThreadPoolExecutor(max_workers=8) as ex: list(ex.map(self.local, todo))
        for pre in prefixes:
            for k in self.manifest.keys_under(pre):
                if inc(k) and not exc(k) and k not in self.index.files:
                    try: (self.root / k).unlink()
                    except FileNotFoundError: pass
                    self.manifest.remove(k)
        return len(todo)

    def placeholders(self, patterns: list[str]) -> int:
        """Empty stand-ins for objects a whole-library script only checks with os.path.exists (e.g. upload/*.mp4 for
        update_trackers.py) so they need not be downloaded. They are never pushed and a real read replaces them."""
        if not self.remote or not patterns: return 0
        inc = self._match(patterns); n = 0
        for e in list(self.index.files.values()):
            if not inc(e.key): continue
            p = self.root / e.key
            if p.exists(): continue
            p.parent.mkdir(parents=True, exist_ok=True); p.touch(); self._placeholder_keys.add(e.key); n += 1
        return n

    def push(self, patterns: list[str], exclude: list[str] = ()) -> dict:
        """Upload new/changed cache files matching the patterns; delete in the bucket what the job deleted locally."""
        if not self.remote or not patterns: return dict(uploaded=0, deleted=0)
        inc = self._match(patterns); exc = self._match(list(exclude))
        up = dl = 0
        seen = set()
        for pat in patterns:
            pre = literal_prefix(pat); base = pre.rsplit('/', 1)[0] if '/' in pre else ''
            bp = self.root / base if base else self.root
            if bp.is_file(): files = [bp]
            elif bp.is_dir(): files = [Path(dp) / f for dp, dns, fs in os.walk(bp) for f in fs]
            else: files = []
            for f in files:
                try: k = f.relative_to(self.root).as_posix()
                except ValueError: continue
                if k in seen or not inc(k) or exc(k) or PUSH_SKIP.search(k) or f.is_symlink(): continue
                seen.add(k)
                try: k = self.check(k)
                except BadKey: continue
                st = f.stat(); m = self.manifest.get(k)
                if k in self._placeholder_keys and m is None and st.st_size == 0: continue
                if m and m[1] == st.st_size and m[2] == st.st_mtime_ns and k in self.index.files: continue
                self.upload_local(k, f); up += 1
            for k in self.manifest.keys_under(base):
                if inc(k) and not exc(k) and not (self.root / k).exists():
                    m = self.manifest.get(k); cur = self.index.files.get(k)
                    if cur and m and cur.etag == m[0]:
                        self.store.delete(k); self.index.remove(k); dl += 1
                    self.manifest.remove(k)
        return dict(uploaded=up, deleted=dl)

    @contextmanager
    def job_sync(self, pull: list[str] = (), push: list[str] = (), scope: str = '', exclude: list[str] = (), stubs: list[str] = ()):
        """Remote backends: pull inputs (minus ``exclude``) -> run -> push outputs, holding the project's job lock (jobs
        on one project run one after the other). Local backend: nothing to do."""
        if not self.remote:
            yield self.root; return
        lk = self.job_lock(scope or 'global')
        with lk:
            with self.proj_lock(scope or 'global'):
                self.pull(list(pull), exclude); self.placeholders(list(stubs))
            ok = False
            try:
                yield self.root; ok = True
            finally:
                with self.proj_lock(scope or 'global'):
                    res = self.push(list(push))
                if res['uploaded'] or res['deleted']: log.info('job sync %s: pushed %s', scope, res)
                if ok: self.evict()

    def evict(self):
        """Keep the cache under STUDIO_CACHE_MAX_GB (least recently used files first; skip busy projects)."""
        if not self.remote: return
        total = self.manifest.total()
        if total <= self.cache_max: return
        busy = {s for s, lk in self._job_locks.items() if lk.locked()}
        for k, size in self.manifest.lru():
            if total <= self.cache_max * 0.8: break
            if self.project_scope(k) in busy: continue
            try: (self.root / k).unlink()
            except FileNotFoundError: pass
            self.manifest.remove(k); total -= size or 0

    # ---------------- HTTP responses ----------------
    def response(self, key: str, request=None, download: bool = False, filename: str | None = None, presign: bool = False):
        from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
        k = self.check(key)
        name = filename or posixpath.basename(k)
        disp = 'attachment' if download else 'inline'
        if not self.remote:
            p = self.local(k)
            return FileResponse(p, headers={'Cache-Control': 'no-cache'}, filename=name if download else None, content_disposition_type=disp)
        e = self.stat(k)
        if e is None or e.is_dir: raise NotFound(k)
        if presign:
            url = self.store.presigned_url(k, 300, name, inline=not download)
            if url: return RedirectResponse(url, status_code=307, headers={'Cache-Control': 'no-store'})
        m = self.manifest.get(k)
        if e.size <= INLINE_MAX or (m and m[0] == e.etag):
            p = self.local(k)
            return FileResponse(p, headers={'Cache-Control': 'no-cache'}, filename=name if download else None, content_disposition_type=disp)
        # big object not in the cache: stream from the bucket, honouring Range (video seeking)
        rng = request.headers.get('range') if request is not None else None
        start = end = None
        if rng:
            mm = re.match(r'bytes=(\d*)-(\d*)$', rng.strip())
            if mm and (mm.group(1) or mm.group(2)):
                if mm.group(1): start = int(mm.group(1)); end = int(mm.group(2)) if mm.group(2) else None
                else: start = max(0, e.size - int(mm.group(2))); end = None
        ct = mimetypes.guess_type(k)[0] or 'application/octet-stream'
        if start is not None and start >= e.size:
            from fastapi.responses import Response
            return Response(status_code=416, headers={'Content-Range': f'bytes */{e.size}'})
        chunks, ent = self.store.open_range(k, start, end)
        headers = {'Accept-Ranges': 'bytes', 'Cache-Control': 'no-cache', 'ETag': f'"{e.etag}"'}
        if download: headers['Content-Disposition'] = f'attachment; filename="{_ascii(name)}"'
        if start is not None:
            last = e.size - 1 if end is None else min(end, e.size - 1)
            headers['Content-Range'] = f'bytes {start}-{last}/{e.size}'; headers['Content-Length'] = str(last - start + 1)
            return StreamingResponse(chunks, status_code=206, media_type=ct, headers=headers)
        headers['Content-Length'] = str(e.size)
        return StreamingResponse(chunks, media_type=ct, headers=headers)


def _ascii(s: str) -> str:
    return ''.join(c for c in s if c.isalnum() or c in '._- ')[:150] or 'file'


def _sha1_path(p: Path) -> str:
    h = hashlib.sha1()  # nosec B324 - content fingerprint for the QA gate (repo format), not a security use
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''): h.update(chunk)
    return h.hexdigest()


# ======================================================================================================================
_WS: Workspace | None = None
_WS_LOCK = threading.Lock()


def set_workspace(ws: Workspace):
    global _WS
    with _WS_LOCK:
        old, _WS = _WS, ws
    if old is not None and old is not ws: old.close()


def get_ws() -> Workspace:
    if _WS is None: raise RuntimeError('storage is not configured yet')
    return _WS


# ======================================================================================================================
class SPath:
    """pathlib-like handle on a workspace key (always resolved against the *current* workspace)."""
    __slots__ = ('key',)

    def __init__(self, key: str = ''):
        self.key = key.strip('/')

    # --- pure path ---
    def __truediv__(self, other) -> 'SPath':
        o = str(other).replace('\\', '/').strip('/')
        if not o or o == '.': return self
        return SPath(f'{self.key}/{o}' if self.key else o)

    @property
    def name(self) -> str: return self.key.rsplit('/', 1)[-1] if self.key else ''
    @property
    def stem(self) -> str: return PurePosixPath(self.name).stem
    @property
    def suffix(self) -> str: return PurePosixPath(self.name).suffix
    @property
    def parent(self) -> 'SPath': return SPath(self.key.rsplit('/', 1)[0] if '/' in self.key else '')
    @property
    def parts(self) -> tuple: return tuple(self.key.split('/')) if self.key else ()
    def with_name(self, n: str) -> 'SPath': return self.parent / n
    def with_suffix(self, s: str) -> 'SPath': return self.with_name(self.stem + s)

    def relative_to(self, other: 'SPath') -> PurePosixPath:
        o = other.key
        if not o: return PurePosixPath(self.key or '.')
        if self.key == o: return PurePosixPath('.')
        if not self.key.startswith(o + '/'): raise ValueError(f'{self.key} is not under {o}')
        return PurePosixPath(self.key[len(o) + 1:])

    def is_relative_to(self, other: 'SPath') -> bool:
        return not other.key or self.key == other.key or self.key.startswith(other.key + '/')

    def resolve(self) -> 'SPath': return self
    def __eq__(self, o): return isinstance(o, SPath) and o.key == self.key
    def __hash__(self): return hash(('SPath', self.key))
    def __lt__(self, o): return self.parts < o.parts      # same ordering as sorted(pathlib paths)
    def __repr__(self): return f'SPath({self.key!r})'
    def __str__(self): return str(get_ws().lpath(self.key))
    def __fspath__(self):
        """Local file path; for files this guarantees a fresh cached copy (remote backends)."""
        ws = get_ws()
        if ws.remote and self.key and ws.is_file(self.key): return str(ws.local(self.key))
        return str(ws.lpath(self.key))

    @property
    def lpath(self) -> Path:
        """Local working-tree path WITHOUT downloading (for job arguments after job_sync)."""
        return get_ws().lpath(self.key)

    # --- queries ---
    def exists(self) -> bool:
        try: return not self.key or get_ws().exists(self.key)
        except BadKey: return False
    def is_file(self) -> bool:
        try: return bool(self.key) and get_ws().is_file(self.key)
        except BadKey: return False
    def is_dir(self) -> bool:
        try: return get_ws().is_dir(self.key)
        except BadKey: return False

    def stat(self) -> _Stat:
        e = get_ws().stat(self.key) if self.key else None
        if e is None:
            if not self.key: return _Stat()
            raise FileNotFoundError(self.key)
        return _Stat(e.size, e.mtime, e.extra.get('mtime_ns'), e.extra.get('ctime'), e.extra.get('mode', 0o100644))

    def iterdir(self) -> Iterator['SPath']:
        for e in get_ws().listdir(self.key): yield SPath(e.key)

    def glob(self, pattern: str) -> Iterator['SPath']:
        if '/' in pattern or '**' in pattern:
            rx = pattern_re((self.key + '/' if self.key else '') + pattern)
            for e in get_ws().walk(self.key):
                if rx.match(e.key): yield SPath(e.key)
            return
        for e in get_ws().listdir(self.key):
            if fnmatch.fnmatchcase(e.name, pattern): yield SPath(e.key)

    def rglob(self, pattern: str) -> Iterator['SPath']:
        """Files only (folders are implicit in buckets)."""
        for e in get_ws().walk(self.key):
            if fnmatch.fnmatchcase(e.name, pattern): yield SPath(e.key)

    # --- io ---
    def read_bytes(self) -> bytes:
        try: return get_ws().read_bytes(self.key)
        except NotFound as e: raise FileNotFoundError(self.key) from e

    def read_text(self, encoding: str = 'utf-8') -> str:
        return self.read_bytes().decode(encoding)

    def local(self) -> Path:
        try: return get_ws().local(self.key)
        except NotFound as e: raise FileNotFoundError(self.key) from e

    def write_bytes(self, data: bytes, history: bool = False):
        get_ws().write(self.key, data, history=history)

    def write_text(self, s: str, history: bool = False):
        get_ws().write(self.key, s.encode(), history=history)

    def mkdir(self, parents: bool = True, exist_ok: bool = True):
        get_ws().mkdir(self.key)

    def unlink(self, missing_ok: bool = True):
        get_ws().delete(self.key)

    def sha1(self) -> str | None:
        return get_ws().sha1(self.key)


ROOT = SPath('')
