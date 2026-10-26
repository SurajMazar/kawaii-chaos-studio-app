"""Local-folder storage: keys map to files under ``root``. Writes are atomic (temp file + os.replace).

Symlinks are only followed when their target stays inside the root, so a link planted in a content folder cannot be
used to read or write outside it.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterator

from .base import BadKey, Entry, NotFound, Storage, StorageError, norm_key

CHUNK = 1 << 20


def local_etag(st: os.stat_result) -> str:
    return f'{st.st_size}-{st.st_mtime_ns}'


class LocalStorage(Storage):
    kind = 'local'

    def __init__(self, root: str | os.PathLike):
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir(): raise StorageError(f'Local folder not found: {self.root}')

    def describe(self) -> str:
        return f'local folder {self.root}'

    # ---------------- paths ----------------
    def path(self, key: str, allow_root: bool = False) -> Path:
        k = norm_key(key, allow_root=allow_root)
        p = self.root / k if k else self.root
        # resolve symlinks of the existing part of the path and make sure we are still inside the root
        try: real = p.resolve()
        except (OSError, RuntimeError) as e: raise BadKey('bad path') from e
        if real != self.root and self.root not in real.parents: raise BadKey('path escapes the storage root')
        return p

    def _entry(self, key: str, p: Path, st: os.stat_result | None = None) -> Entry:
        st = st or p.stat()
        return Entry(key=key, size=st.st_size, mtime=st.st_mtime, etag=local_etag(st), is_dir=p.is_dir(),
                     extra=dict(mtime_ns=st.st_mtime_ns, ctime=getattr(st, 'st_birthtime', st.st_ctime)))

    def _probe_cleanup(self):
        try: (self.root / '.studio_probe').rmdir()
        except OSError: pass

    # ---------------- interface ----------------
    def stat(self, key: str) -> Entry | None:
        p = self.path(key)
        try: st = p.stat()
        except (FileNotFoundError, NotADirectoryError): return None
        if not p.is_file(): return None
        return self._entry(norm_key(key), p, st)

    def list(self, prefix: str = '', recursive: bool = True) -> Iterator[Entry]:
        base = self.path(prefix, allow_root=True)
        pk = norm_key(prefix, allow_root=True)
        if not base.is_dir(): return
        if not recursive:
            for c in sorted(base.iterdir(), key=lambda c: c.name):
                k = f'{pk}/{c.name}' if pk else c.name
                try:
                    if c.is_symlink() and not self._inside(c): continue
                    yield self._entry(k, c)
                except FileNotFoundError: continue
            return
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            dirnames.sort()
            rel = os.path.relpath(dirpath, self.root).replace(os.sep, '/')
            rel = '' if rel == '.' else rel
            for f in sorted(filenames):
                p = Path(dirpath) / f
                if p.is_symlink() and not self._inside(p): continue
                try: yield self._entry(f'{rel}/{f}' if rel else f, p)
                except FileNotFoundError: continue

    def _inside(self, p: Path) -> bool:
        try: r = p.resolve()
        except OSError: return False
        return r == self.root or self.root in r.parents

    def read_bytes(self, key: str) -> bytes:
        p = self.path(key)
        try: return p.read_bytes()
        except (FileNotFoundError, IsADirectoryError) as e: raise NotFound(key) from e

    def open_range(self, key: str, start: int | None = None, end: int | None = None):
        p = self.path(key); e = self.stat(key)
        if e is None: raise NotFound(key)
        s = start or 0; last = e.size - 1 if end is None else min(end, e.size - 1)

        def gen():
            with open(p, 'rb') as f:
                f.seek(s); left = last - s + 1
                while left > 0:
                    b = f.read(min(CHUNK, left))
                    if not b: break
                    left -= len(b); yield b
        return gen(), e

    def write_bytes(self, key: str, data: bytes, content_type: str | None = None, mode: int | None = None) -> Entry:
        p = self.path(key); k = norm_key(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f'.{p.name}.', suffix='.tmp')
        try:
            with os.fdopen(fd, 'wb') as f: f.write(data)
            if mode is None:
                try: mode = p.stat().st_mode & 0o777
                except FileNotFoundError: mode = 0o644
            os.chmod(tmp, mode)
            os.replace(tmp, p)
        except BaseException:
            try: os.unlink(tmp)
            except OSError: pass
            raise
        return self._entry(k, p)

    def upload_file(self, key: str, path: str, content_type: str | None = None) -> Entry:
        p = self.path(key)
        if Path(path).resolve() == p.resolve(): return self._entry(norm_key(key), p)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=f'.{p.name}.', suffix='.tmp'); os.close(fd)
        try:
            shutil.copy2(path, tmp); os.replace(tmp, p)
        except BaseException:
            try: os.unlink(tmp)
            except OSError: pass
            raise
        return self._entry(norm_key(key), p)

    def download_file(self, key: str, path: str) -> Entry:
        p = self.path(key)
        if not p.is_file(): raise NotFound(key)
        if Path(path).resolve() != p.resolve(): shutil.copy2(p, path)
        return self._entry(norm_key(key), p)

    def delete(self, key: str) -> None:
        p = self.path(key)
        try: p.unlink()
        except FileNotFoundError: pass

    def copy(self, src: str, dst: str) -> Entry:
        s = self.path(src); d = self.path(dst)
        if not s.is_file(): raise NotFound(src)
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
        return self._entry(norm_key(dst), d)

    def move(self, src: str, dst: str) -> Entry:
        s = self.path(src); d = self.path(dst)
        if not s.exists(): raise NotFound(src)
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        return self._entry(norm_key(dst), d)
