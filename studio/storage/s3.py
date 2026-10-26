"""S3 storage (Amazon S3, Cloudflare R2, MinIO, Backblaze B2, Wasabi, … — anything that speaks the S3 API).

R2 is this driver with endpoint ``https://<accountid>.r2.cloudflarestorage.com`` and region ``auto``.
The endpoint URL is validated against SSRF (see ``validate_endpoint``) before a client is ever built.
"""
from __future__ import annotations

import ipaddress
import mimetypes
import socket
import threading
from typing import Iterator
from urllib.parse import urlparse

from .base import BadKey, Entry, NotFound, Storage, StorageError, friendly, norm_key

CHUNK = 1 << 20
# never reachable as a storage endpoint (cloud metadata services, link-local)
_ALWAYS_BLOCKED = [ipaddress.ip_network(n) for n in (
    '169.254.0.0/16', 'fe80::/10', 'fd00:ec2::254/128', '100.100.100.200/32', '0.0.0.0/8', '::/128', '224.0.0.0/4', 'ff00::/8')]


def r2_endpoint(account_id: str) -> str:
    a = (account_id or '').strip().lower()
    if not a or not all(c in '0123456789abcdef' for c in a) or len(a) > 64:
        raise StorageError('The Cloudflare account ID is the 32-character hex ID shown in the R2 dashboard.')
    return f'https://{a}.r2.cloudflarestorage.com'


def validate_endpoint(url: str, allow_insecure: bool = False, resolve: bool = True) -> str:
    """Only https:// endpoints whose host resolves to public addresses. ``allow_insecure`` (dev only, e.g. a local
    MinIO) additionally permits http:// and private/loopback addresses. Link-local / metadata addresses
    (169.254.169.254 & co.) are always refused."""
    u = (url or '').strip()
    if not u: return ''
    p = urlparse(u)
    if p.scheme not in ('https', 'http'): raise StorageError('The endpoint must start with https://')
    if p.scheme == 'http' and not allow_insecure:
        raise StorageError('The endpoint must use https:// (http:// is only allowed with STUDIO_ALLOW_INSECURE_ENDPOINTS=1 for local testing).')
    if p.username or p.password: raise StorageError('Put credentials in the key fields, not in the endpoint URL.')
    if p.query or p.fragment or (p.path not in ('', '/')): raise StorageError('The endpoint is just scheme://host[:port] (no path or query).')
    host = p.hostname
    if not host: raise StorageError('The endpoint has no host name.')
    try: port = p.port
    except ValueError as e: raise StorageError('Bad port in the endpoint URL.') from e
    addrs = []
    try: addrs = [ipaddress.ip_address(host)]
    except ValueError:
        if resolve:
            try:
                infos = socket.getaddrinfo(host, port or (443 if p.scheme == 'https' else 80), proto=socket.IPPROTO_TCP)
                addrs = list({ipaddress.ip_address(i[4][0].split('%')[0]) for i in infos})
            except socket.gaierror as e: raise StorageError(f'The endpoint host "{host}" does not resolve.') from e
    for a in addrs:
        if any(a in n for n in _ALWAYS_BLOCKED) or (a.version == 6 and a.ipv4_mapped and any(a.ipv4_mapped in n for n in _ALWAYS_BLOCKED)):
            raise StorageError('This endpoint points at a link-local / cloud-metadata address and is not allowed.')
        if not allow_insecure and (a.is_private or a.is_loopback or a.is_reserved or a.is_unspecified):
            raise StorageError('The endpoint resolves to a private/loopback address. Allowed only with STUDIO_ALLOW_INSECURE_ENDPOINTS=1 (local testing).')
    return f'{p.scheme}://{p.netloc}'


class S3Storage(Storage):
    kind = 's3'

    def __init__(self, bucket: str, prefix: str = '', endpoint: str = '', region: str = '', access_key_id: str = '',  # nosec B107
                 secret_access_key: str = '', force_path_style: bool = False, public_base_url: str = '',
                 allow_insecure: bool = False, label: str = 'S3', validate: bool = True, client=None):
        import boto3
        from botocore.config import Config
        if not bucket: raise StorageError('A bucket name is required.')
        self.bucket = bucket.strip()
        self.prefix = norm_key(prefix, allow_root=True)
        self.label = label
        self.endpoint = validate_endpoint(endpoint, allow_insecure) if (endpoint and validate) else (endpoint or None)
        self.public_base_url = (public_base_url or '').rstrip('/')
        if self.public_base_url and not self.public_base_url.startswith('https://') and not allow_insecure:
            raise StorageError('The public base URL must start with https://')
        cfg = Config(signature_version='s3v4', retries={'max_attempts': 4, 'mode': 'standard'}, connect_timeout=8, read_timeout=60,
                     s3={'addressing_style': 'path' if force_path_style else 'auto'},
                     request_checksum_calculation='when_required', response_checksum_validation='when_required')
        self.client = client or boto3.session.Session().client(
            's3', endpoint_url=self.endpoint or None, region_name=region or None,
            aws_access_key_id=access_key_id or None, aws_secret_access_key=secret_access_key or None, config=cfg)
        self._lock = threading.Lock()

    def describe(self) -> str:
        where = self.endpoint or 'AWS'
        return f'{self.label} bucket {self.bucket}' + (f' / {self.prefix}' if self.prefix else '') + f' ({where})'

    # ---------------- keys ----------------
    def k(self, key: str, allow_root: bool = False) -> str:
        n = norm_key(key, allow_root=allow_root)
        return f'{self.prefix}/{n}' if self.prefix and n else (self.prefix if not n else n)

    def unk(self, full: str) -> str:
        if self.prefix:
            if not full.startswith(self.prefix + '/'): raise BadKey('object outside the prefix')
            return full[len(self.prefix) + 1:]
        return full

    @staticmethod
    def _etag(v) -> str | None:
        return v.strip('"') if isinstance(v, str) else None

    def _call(self, what, fn, *a, **kw):
        try: return fn(*a, **kw)
        except StorageError: raise
        except Exception as e:
            code = (getattr(e, 'response', None) or {}).get('Error', {}).get('Code')
            if code in ('NoSuchKey', '404', 'NotFound'): raise NotFound(what) from e
            raise StorageError(f'{what}: {friendly(e)}') from e

    # ---------------- interface ----------------
    def stat(self, key: str) -> Entry | None:
        try: r = self._call(key, self.client.head_object, Bucket=self.bucket, Key=self.k(key))
        except NotFound: return None
        return Entry(key=norm_key(key), size=r.get('ContentLength', 0), mtime=r['LastModified'].timestamp() if r.get('LastModified') else 0,
                     etag=self._etag(r.get('ETag')))

    def list(self, prefix: str = '', recursive: bool = True) -> Iterator[Entry]:
        pk = norm_key(prefix, allow_root=True)
        full = self.k(pk, allow_root=True)
        full = (full + '/') if full else ''
        kw = dict(Bucket=self.bucket, Prefix=full)
        if not recursive: kw['Delimiter'] = '/'
        pag = self.client.get_paginator('list_objects_v2')
        try:
            for page in pag.paginate(**kw):
                for cp in page.get('CommonPrefixes', []) or []:
                    k = self.unk(cp['Prefix'].rstrip('/'))
                    yield Entry(key=k, is_dir=True)
                for o in page.get('Contents', []) or []:
                    if o['Key'].endswith('/'): continue          # folder placeholder objects
                    try: k = self.unk(o['Key'])
                    except BadKey: continue
                    try: norm_key(k)
                    except BadKey: continue                     # never surface keys we could not address safely
                    yield Entry(key=k, size=o.get('Size', 0), mtime=o['LastModified'].timestamp(), etag=self._etag(o.get('ETag')))
        except StorageError: raise
        except Exception as e: raise StorageError(f'Listing failed: {friendly(e)}') from e

    def read_bytes(self, key: str) -> bytes:
        r = self._call(key, self.client.get_object, Bucket=self.bucket, Key=self.k(key))
        return r['Body'].read()

    def open_range(self, key: str, start: int | None = None, end: int | None = None):
        kw = dict(Bucket=self.bucket, Key=self.k(key))
        if start is not None or end is not None: kw['Range'] = f"bytes={start or 0}-{'' if end is None else end}"
        r = self._call(key, self.client.get_object, **kw)
        total = r.get('ContentLength', 0)
        cr = r.get('ContentRange')                    # bytes 0-99/1234
        if cr and '/' in cr:
            try: total = int(cr.rsplit('/', 1)[1])
            except ValueError: pass
        e = Entry(key=norm_key(key), size=total, mtime=r['LastModified'].timestamp() if r.get('LastModified') else 0, etag=self._etag(r.get('ETag')))
        body = r['Body']

        def gen():
            try:
                for b in body.iter_chunks(CHUNK): yield b
            finally: body.close()
        return gen(), e

    def write_bytes(self, key: str, data: bytes, content_type: str | None = None) -> Entry:
        ct = content_type or mimetypes.guess_type(key)[0] or 'application/octet-stream'
        r = self._call(key, self.client.put_object, Bucket=self.bucket, Key=self.k(key), Body=data, ContentType=ct)
        import time
        return Entry(key=norm_key(key), size=len(data), mtime=time.time(), etag=self._etag(r.get('ETag')))

    def upload_file(self, key: str, path: str, content_type: str | None = None) -> Entry:
        import os
        size = os.path.getsize(path)
        if size <= 64 * 1024 * 1024:
            with open(path, 'rb') as f: return self.write_bytes(key, f.read(), content_type)
        ct = content_type or mimetypes.guess_type(key)[0] or 'application/octet-stream'
        self._call(key, self.client.upload_file, path, self.bucket, self.k(key), ExtraArgs={'ContentType': ct})
        e = self.stat(key)
        if e is None: raise StorageError(f'{key}: upload did not land')
        return e

    def download_file(self, key: str, path: str) -> Entry:
        e = self.stat(key)
        if e is None: raise NotFound(key)
        self._call(key, self.client.download_file, self.bucket, self.k(key), path)
        return e

    def delete(self, key: str) -> None:
        self._call(key, self.client.delete_object, Bucket=self.bucket, Key=self.k(key))

    def copy(self, src: str, dst: str) -> Entry:
        self._call(src, self.client.copy_object, Bucket=self.bucket, Key=self.k(dst), CopySource={'Bucket': self.bucket, 'Key': self.k(src)})
        e = self.stat(dst)
        if e is None: raise StorageError(f'{dst}: copy did not land')
        return e

    def presigned_url(self, key: str, expires: int = 300, filename: str | None = None, inline: bool = True) -> str | None:
        params = dict(Bucket=self.bucket, Key=self.k(key))
        if filename:
            safe = ''.join(c for c in filename if c.isalnum() or c in '._- ')[:120] or 'file'
            params['ResponseContentDisposition'] = f'{"inline" if inline else "attachment"}; filename="{safe}"'
        return self.client.generate_presigned_url('get_object', Params=params, ExpiresIn=max(30, min(int(expires), 3600)))
