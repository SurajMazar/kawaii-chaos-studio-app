"""Storage interface shared by every backend (local folder, Amazon S3, Cloudflare R2, other S3-compatible services).

Keys are POSIX-style paths relative to the storage root, e.g. ``projects/151_rem_x/strip.png``. They never start with
``/``, never contain ``..``/``.`` components, backslashes, NUL or control characters. ``norm_key`` enforces that for
every call, so a driver can never be tricked into touching something outside its root/bucket prefix.
"""
from __future__ import annotations

import posixpath
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterator

MAX_KEY = 1024
_BAD_CHARS = re.compile(r'[\x00-\x1f\x7f\\]')


class StorageError(Exception):
    """A storage operation failed. ``str(e)`` is safe to show to an admin (never contains secrets)."""


class BadKey(StorageError, ValueError):
    pass


class NotFound(StorageError, FileNotFoundError):
    pass


@dataclass
class Entry:
    key: str
    size: int = 0
    mtime: float = 0.0              # seconds since the epoch
    etag: str | None = None         # S3 ETag (quotes stripped) or "<size>-<mtime_ns>" for local files
    is_dir: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.key.rstrip('/').rsplit('/', 1)[-1]


def norm_key(key: str, allow_root: bool = False) -> str:
    """Validate and normalise a storage key. Raises BadKey for anything that could escape the root."""
    if not isinstance(key, str): raise BadKey('key must be a string')
    if _BAD_CHARS.search(key): raise BadKey('bad characters in path')
    if key.startswith('/'): raise BadKey('absolute paths are not allowed')
    k = key.rstrip('/')
    if not k:
        if allow_root: return ''
        raise BadKey('empty path')
    if len(k) > MAX_KEY: raise BadKey('path too long')
    parts = k.split('/')
    if any(p in ('', '.', '..') for p in parts): raise BadKey('bad path')
    if posixpath.isabs(k) or re.match(r'^[A-Za-z]:', k): raise BadKey('bad path')
    return k


def join_key(*parts: str) -> str:
    return norm_key('/'.join(p.strip('/') for p in parts if p and p.strip('/')), allow_root=True)


class Storage(ABC):
    """Minimal object-store interface. Implementations must be thread-safe."""
    kind = 'abstract'

    @abstractmethod
    def describe(self) -> str: ...

    @abstractmethod
    def stat(self, key: str) -> Entry | None: ...

    @abstractmethod
    def list(self, prefix: str = '', recursive: bool = True) -> Iterator[Entry]:
        """Files under ``prefix`` (a folder key, '' = everything). With recursive=False also yields folder entries
        (is_dir=True) for the direct sub-folders."""

    @abstractmethod
    def read_bytes(self, key: str) -> bytes: ...

    @abstractmethod
    def open_range(self, key: str, start: int | None = None, end: int | None = None) -> tuple[Iterator[bytes], Entry]:
        """Stream bytes [start, end] (inclusive, like HTTP Range). Returns (chunks, entry)."""

    @abstractmethod
    def write_bytes(self, key: str, data: bytes, content_type: str | None = None) -> Entry: ...

    @abstractmethod
    def upload_file(self, key: str, path: str, content_type: str | None = None) -> Entry: ...

    @abstractmethod
    def download_file(self, key: str, path: str) -> Entry: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def copy(self, src: str, dst: str) -> Entry: ...

    def presigned_url(self, key: str, expires: int = 300, filename: str | None = None, inline: bool = True) -> str | None:
        return None

    def _probe_cleanup(self):
        pass

    def exists(self, key: str) -> bool:
        return self.stat(key) is not None

    def probe(self) -> dict:
        """Connection test: list, then put/get/delete a small probe object. Raises StorageError with a clear message."""
        import secrets, time
        steps = []
        t0 = time.time()
        try:
            next(iter(self.list('', recursive=False)), None); steps.append('list')
        except StorageError: raise
        except Exception as e: raise StorageError(f'Listing failed: {friendly(e)}') from e
        key = f'.studio_probe/{secrets.token_hex(8)}.txt'
        body = b'kawaii chaos studio storage probe'
        try:
            self.write_bytes(key, body, 'text/plain'); steps.append('write')
            got = self.read_bytes(key); steps.append('read')
            if got != body: raise StorageError('The probe object came back different from what was written.')
        except StorageError: raise
        except Exception as e: raise StorageError(f'Write/read failed: {friendly(e)}') from e
        finally:
            try: self.delete(key); steps.append('delete')
            except Exception: pass  # nosec B110 - best-effort cleanup of the probe object
            self._probe_cleanup()
        return dict(ok=True, steps=steps, ms=int((time.time() - t0) * 1000), backend=self.describe())


def friendly(e: Exception) -> str:
    """Short, secret-free description of a driver exception (botocore errors carry a code + message)."""
    resp = getattr(e, 'response', None)
    if isinstance(resp, dict) and 'Error' in resp:
        code = resp['Error'].get('Code', ''); msg = resp['Error'].get('Message', '')
        hints = {
            'InvalidAccessKeyId': 'The access key ID is not recognised by the service.',
            'SignatureDoesNotMatch': 'The secret access key is wrong (signature mismatch).',
            'AccessDenied': 'Access denied — the key lacks permission for this bucket/prefix (check the policy).',
            'NoSuchBucket': 'The bucket does not exist (or is in another account/region).',
            'AuthorizationHeaderMalformed': 'Wrong region for this bucket (check the region / use "auto" for R2).',
            'PermanentRedirect': 'Wrong region or endpoint for this bucket.',
        }
        return hints.get(code) or f'{code}: {msg}'.strip(': ')
    name = type(e).__name__
    s = str(e)
    if 'Could not connect' in s or 'EndpointConnectionError' in name: return 'Could not connect to the endpoint (check the URL / network).'
    if 'SSL' in s or 'certificate' in s.lower(): return 'TLS/SSL error talking to the endpoint (certificate problem?).'
    if 'NoCredentials' in name or 'Unable to locate credentials' in s: return 'No credentials configured.'
    if 'timed out' in s.lower() or 'Timeout' in name: return 'The endpoint timed out.'
    return f'{name}: {s[:200]}'
