"""Storage integration settings: which backend, its fields and (encrypted) secrets.

* Stored in ``<STUDIO_CONFIG_DIR>/storage.json`` with 0600 permissions (outside the web root, git-ignored).
* Secrets (secret access key) are encrypted with Fernet using ``STUDIO_SECRET_KEY``; without that key the Studio refuses
  to store secrets (use the env vars instead). ``STUDIO_SECRET_KEY_OLD`` (comma separated) still decrypts during a key
  rotation.
* Environment variables override the file (12-factor): STORAGE_BACKEND, S3_ENDPOINT, S3_BUCKET, S3_PREFIX, S3_REGION,
  S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_FORCE_PATH_STYLE, S3_PUBLIC_BASE_URL, S3_PRESIGN_DOWNLOADS,
  R2_ACCOUNT_ID, STUDIO_DATA_DIR (local folder).
* Secrets never leave the server: ``public_view`` replaces them with ``{"set": true}``.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from pathlib import Path

from .base import StorageError
from .local import LocalStorage
from .s3 import S3Storage, r2_endpoint, validate_endpoint

BACKENDS = ('local', 's3', 'r2', 's3compat')
FIELDS = ('backend', 'local_path', 'endpoint', 'region', 'bucket', 'prefix', 'access_key_id', 'secret_access_key',
          'force_path_style', 'public_base_url', 'presign_downloads', 'account_id')
SECRET_FIELDS = ('secret_access_key',)
ENV_MAP = {'backend': 'STORAGE_BACKEND', 'endpoint': 'S3_ENDPOINT', 'bucket': 'S3_BUCKET', 'prefix': 'S3_PREFIX',
           'region': 'S3_REGION', 'access_key_id': 'S3_ACCESS_KEY_ID', 'secret_access_key': 'S3_SECRET_ACCESS_KEY',  # nosec B105 - env var names
           'force_path_style': 'S3_FORCE_PATH_STYLE', 'public_base_url': 'S3_PUBLIC_BASE_URL',
           'presign_downloads': 'S3_PRESIGN_DOWNLOADS', 'account_id': 'R2_ACCOUNT_ID', 'local_path': 'STUDIO_DATA_DIR'}
BOOL_FIELDS = ('force_path_style', 'presign_downloads')
FORBIDDEN_LOCAL = ('/', '/etc', '/proc', '/sys', '/dev', '/bin', '/sbin', '/usr', '/boot', '/var/run', '/private/etc', '/System')


def _fernet(secret_key: str, old: str = ''):
    from cryptography.fernet import Fernet, MultiFernet

    def mk(k: str):
        k = k.strip()
        try:
            raw = base64.urlsafe_b64decode(k.encode())
            if len(raw) == 32: return Fernet(k.encode())
        except Exception: pass  # nosec B110 - not a raw Fernet key: derive one below
        # any passphrase -> a Fernet key (SHA-256); a generated Fernet key is still the recommended form
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(k.encode()).digest()))
    keys = [mk(secret_key)] + [mk(x) for x in old.split(',') if x.strip()]
    return MultiFernet(keys)


class StorageSettings:
    def __init__(self, config_dir: Path, secret_key: str = '', old_keys: str = '',  # nosec B107
                 default_local: Path | None = None,
                 allow_insecure: bool = False):
        self.path = Path(config_dir) / 'storage.json'
        self.secret_key = secret_key; self.old_keys = old_keys
        self.default_local = default_local
        self.allow_insecure = allow_insecure

    # ---------------- file ----------------
    def _read_file(self) -> dict:
        try: return json.loads(self.path.read_text())
        except FileNotFoundError: return {}
        except (json.JSONDecodeError, OSError): return {}

    def _write_file(self, data: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try: os.chmod(self.path.parent, 0o700)
        except OSError: pass
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix='.storage.', suffix='.tmp')
        with os.fdopen(fd, 'w') as f: json.dump(data, f, indent=1)
        os.chmod(tmp, 0o600); os.replace(tmp, self.path)

    def encrypt(self, v: str) -> str:
        if not self.secret_key:
            raise StorageError('STUDIO_SECRET_KEY is not set, so secrets cannot be stored safely. Set it (see .env.example) '
                               'or provide the secret through the S3_SECRET_ACCESS_KEY environment variable.')
        return _fernet(self.secret_key, self.old_keys).encrypt(v.encode()).decode()

    def decrypt(self, v: str) -> str:
        if not v: return ''
        if not self.secret_key: raise StorageError('A stored secret cannot be decrypted: STUDIO_SECRET_KEY is not set.')
        from cryptography.fernet import InvalidToken
        try: return _fernet(self.secret_key, self.old_keys).decrypt(v.encode()).decode()
        except InvalidToken as e: raise StorageError('A stored secret cannot be decrypted with the current STUDIO_SECRET_KEY.') from e

    # ---------------- effective config ----------------
    def env_overrides(self) -> dict:
        out = {}
        for f, name in ENV_MAP.items():
            v = os.environ.get(name)
            if v is not None and v.strip() != '':
                out[f] = (v.strip().lower() in ('1', 'true', 'yes', 'on')) if f in BOOL_FIELDS else v.strip()
        return out

    def stored(self) -> dict:
        return self._read_file()

    def effective(self) -> dict:
        """Full config with decrypted secrets (server side only)."""
        d = {f: None for f in FIELDS}
        d.update(backend='local', force_path_style=False, presign_downloads=False)
        st = self._read_file()
        for f in FIELDS:
            if f in SECRET_FIELDS:
                if st.get(f + '_enc'): d[f] = self.decrypt(st[f + '_enc'])
            elif f in st: d[f] = st[f]
        d.update(self.env_overrides())
        if d['backend'] not in BACKENDS: raise StorageError(f"Unknown storage backend {d['backend']!r} (use {', '.join(BACKENDS)}).")
        return d

    def public_view(self) -> dict:
        try: d = self.effective(); err = None
        except StorageError as e:
            d = {f: self._read_file().get(f) for f in FIELDS if f not in SECRET_FIELDS}; d.setdefault('backend', 'local'); err = str(e)
        env = self.env_overrides()
        out = {f: d.get(f) for f in FIELDS if f not in SECRET_FIELDS}
        for f in SECRET_FIELDS: out[f] = {'set': bool(d.get(f))}
        if out.get('access_key_id'):
            a = str(out['access_key_id']); out['access_key_id_hint'] = (a[:4] + '…' + a[-4:]) if len(a) > 10 else '…'
        out['locked'] = sorted(env)                         # fields set by environment variables (read-only in the UI)
        out['can_store_secrets'] = bool(self.secret_key)
        out['local_path'] = out.get('local_path') or (str(self.default_local) if self.default_local else '')
        if err: out['error'] = err
        return out

    def merged(self, new: dict) -> dict:
        """The effective config with ``new`` applied (blank secret = keep the stored one)."""
        cur = self.effective(); env = self.env_overrides()
        out = dict(cur)
        for f in FIELDS:
            if f in env or f not in new: continue
            v = new[f]
            if f in SECRET_FIELDS:
                if isinstance(v, str) and v.strip(): out[f] = v.strip()
                continue
            if f in BOOL_FIELDS: v = bool(v)
            elif v is not None: v = str(v).strip()
            out[f] = v
        return out

    def save(self, new: dict) -> dict:
        cfg = self.merged(new)
        validate(cfg, self.allow_insecure)
        env = self.env_overrides()
        out = {}
        for f in FIELDS:
            if f in SECRET_FIELDS:
                if f in env: continue                     # never copy env secrets into the file
                v = cfg.get(f)
                if v: out[f + '_enc'] = self.encrypt(v)          # always with the current (primary) key
                continue
            if f in env: continue
            if cfg.get(f) not in (None, ''): out[f] = cfg[f]
        self._write_file(out)
        return cfg


def validate(cfg: dict, allow_insecure: bool = False):
    b = cfg.get('backend')
    if b not in BACKENDS: raise StorageError('Pick a storage backend.')
    if b == 'local':
        p = cfg.get('local_path')
        if p:
            pp = Path(p).expanduser()
            if not pp.is_absolute(): raise StorageError('The local folder must be an absolute path.')
            r = str(pp.resolve())
            if r in FORBIDDEN_LOCAL or any(r == x or r.startswith(x + '/') for x in FORBIDDEN_LOCAL[1:]):
                raise StorageError('That folder cannot be used for Studio data.')
            if not pp.is_dir(): raise StorageError(f'Folder not found: {pp}')
        return
    if not cfg.get('bucket'): raise StorageError('The bucket name is required.')
    import re
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.\-_]{1,62}', cfg['bucket']): raise StorageError('That is not a valid bucket name.')
    if b == 'r2':
        r2_endpoint(cfg.get('account_id') or '')
    elif b == 's3compat':
        if not cfg.get('endpoint'): raise StorageError('An endpoint URL is required for S3-compatible services.')
        validate_endpoint(cfg['endpoint'], allow_insecure)
    elif cfg.get('endpoint'):
        validate_endpoint(cfg['endpoint'], allow_insecure)
    if not cfg.get('access_key_id') or not cfg.get('secret_access_key'):
        if b != 's3':
            raise StorageError('The access key ID and secret access key are required.')
    if cfg.get('public_base_url'):
        from urllib.parse import urlparse
        u = urlparse(cfg['public_base_url'])
        if u.scheme != 'https' and not (allow_insecure and u.scheme == 'http'): raise StorageError('The public base URL must start with https://')


def build_storage(cfg: dict, default_local: Path, allow_insecure: bool = False):
    validate(cfg, allow_insecure)
    b = cfg['backend']
    if b == 'local':
        return LocalStorage(Path(cfg.get('local_path') or default_local).expanduser())
    common = dict(bucket=cfg['bucket'], prefix=cfg.get('prefix') or '', access_key_id=cfg.get('access_key_id') or '',
                  secret_access_key=cfg.get('secret_access_key') or '', public_base_url=cfg.get('public_base_url') or '',
                  allow_insecure=allow_insecure)
    if b == 'r2':
        return S3Storage(endpoint=r2_endpoint(cfg.get('account_id') or ''), region='auto', force_path_style=bool(cfg.get('force_path_style')),
                         label='Cloudflare R2', **common)
    if b == 's3compat':
        return S3Storage(endpoint=cfg['endpoint'], region=cfg.get('region') or 'us-east-1', force_path_style=bool(cfg.get('force_path_style', True)),
                         label='S3-compatible', **common)
    return S3Storage(endpoint=cfg.get('endpoint') or '', region=cfg.get('region') or 'us-east-1',
                     force_path_style=bool(cfg.get('force_path_style')), label='Amazon S3', **common)
