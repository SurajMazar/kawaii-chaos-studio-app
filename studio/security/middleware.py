"""ASGI middleware: request IDs + access log, security headers, body-size limits, authentication gate + CSRF.

Order (outermost first): RequestContext -> SecurityHeaders -> BodyLimit -> AuthGate -> app.
The AuthGate denies every /api/ request without a valid session except an explicit allowlist; the per-route role
check is the ``authorize`` dependency (api/deps.py) that every router is mounted with.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import time
from http.cookies import SimpleCookie
from urllib.parse import urlparse

from config import CONFIG

from .auth import consteq, store
from .context import current_user, request_id

log = logging.getLogger('studio.http')
SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}
PUBLIC_API = {'/api/health', '/api/ready', '/api/auth/state', '/api/auth/login', '/api/auth/setup', '/api/auth/logout'}
SESSION_COOKIES = ('__Host-kcs_session', 'kcs_session')
CSRF_COOKIES = ('__Host-kcs_csrf', 'kcs_csrf')
CSRF_HEADER = 'x-csrf-token'
RID_RE = re.compile(r'^[A-Za-z0-9._\-]{6,64}$')


def cookies_of(scope) -> dict:
    for k, v in scope.get('headers', []):
        if k == b'cookie':
            c = SimpleCookie()
            try: c.load(v.decode('latin-1'))
            except Exception: return {}
            return {k: m.value for k, m in c.items()}
    return {}


def header(scope, name: str) -> str | None:
    n = name.lower().encode()
    for k, v in scope.get('headers', []):
        if k == n: return v.decode('latin-1')
    return None


def client_ip(scope) -> str:
    c = scope.get('client')
    return c[0] if c else '?'


def scheme_of(scope) -> str:
    return scope.get('scheme', 'http')


async def send_json(send, status: int, body: dict, extra_headers=()):
    data = json.dumps(body).encode()
    await send({'type': 'http.response.start', 'status': status,
                'headers': [(b'content-type', b'application/json'), (b'content-length', str(len(data)).encode()), (b'cache-control', b'no-store'), *extra_headers]})
    await send({'type': 'http.response.body', 'body': data})


def host_allowed(host_header: str | None) -> bool:
    allowed = CONFIG.allowed_hosts
    if '*' in allowed: return True
    h = (host_header or '').strip().lower()
    if h.startswith('['): h = h[1:h.find(']')] if ']' in h else h
    elif h.count(':') == 1: h = h.split(':', 1)[0]
    if not h: return False
    for a in allowed:
        if a == h or (a.startswith('*.') and h.endswith(a[1:])): return True
    return False


class HostCheck:
    """Refuse requests whose Host is not ours (DNS rebinding against a local install, host-header tricks)."""
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and scope.get('path') not in ('/api/health', '/api/ready') and not host_allowed(header(scope, 'host')):
            return await send_json(send, 400, {'detail': 'Invalid host header (see STUDIO_ALLOWED_HOSTS).'})
        await self.app(scope, receive, send)


class RequestContext:
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http': return await self.app(scope, receive, send)
        rid = header(scope, 'x-request-id') or ''
        if not RID_RE.match(rid): rid = secrets.token_hex(8)
        tok = request_id.set(rid)
        scope.setdefault('state', {})['request_id'] = rid
        t0 = time.time(); status = {'v': 0}

        async def _send(msg):
            if msg['type'] == 'http.response.start':
                status['v'] = msg['status']
                msg['headers'] = list(msg.get('headers', [])) + [(b'x-request-id', rid.encode())]
            await send(msg)
        try:
            await self.app(scope, receive, _send)
        finally:
            path = scope.get('path', '')
            if path.startswith('/api/') or status['v'] >= 400:
                u = scope.get('state', {}).get('user')
                lvl = logging.WARNING if status['v'] >= 500 else logging.INFO
                if not (path.startswith('/api/jobs') and status['v'] < 400):   # job polling is too chatty
                    log.log(lvl, '%s %s %s %dms', scope.get('method'), path, status['v'], int((time.time() - t0) * 1000),
                            extra=dict(user_id=u['id'] if u else None, ip=client_ip(scope), status=status['v']))
            request_id.reset(tok)


def csp_header() -> str:
    extra = ' '.join(CONFIG.allowed_origins)
    return ("default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "     # Ant Design (CSS-in-JS) injects <style>
            "font-src 'self' data: https://fonts.gstatic.com; "
            "img-src 'self' data: blob:; "
            "media-src 'self' blob:; "
            f"connect-src 'self' {extra}".rstrip() + "; "
            "worker-src 'self' blob:; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


class SecurityHeaders:
    def __init__(self, app):
        self.app = app
        self.csp = csp_header().encode()

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http': return await self.app(scope, receive, send)
        https = scheme_of(scope) == 'https'

        async def _send(msg):
            if msg['type'] == 'http.response.start':
                h = [x for x in msg.get('headers', []) if x[0].lower() not in (b'server',)]
                names = {x[0].lower() for x in h}
                add = [(b'x-content-type-options', b'nosniff'), (b'x-frame-options', b'DENY'),
                       (b'referrer-policy', b'same-origin'), (b'cross-origin-opener-policy', b'same-origin'),
                       (b'cross-origin-resource-policy', b'same-origin'),
                       (b'permissions-policy', b'camera=(), microphone=(), geolocation=(), payment=(), usb=()'),
                       (b'content-security-policy', self.csp)]
                if https and CONFIG.hsts: add.append((b'strict-transport-security', b'max-age=31536000; includeSubDomains'))
                if scope.get('path', '').startswith('/api/') and b'cache-control' not in names:
                    add.append((b'cache-control', b'no-store'))
                msg['headers'] = h + [a for a in add if a[0] not in names]
            await send(msg)
        await self.app(scope, receive, _send)


class BodyLimit:
    """413 for bodies over the limit: STUDIO_MAX_JSON_MB for JSON, STUDIO_MAX_UPLOAD_MB for multipart uploads."""
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('method') in SAFE_METHODS: return await self.app(scope, receive, send)
        ct = (header(scope, 'content-type') or '').lower()
        mb = CONFIG.max_import_mb if scope.get('path') == '/api/import' else CONFIG.max_upload_mb
        limit = (mb if ct.startswith('multipart/') else CONFIG.max_json_mb) * 1024 * 1024
        cl = header(scope, 'content-length')
        if cl:
            try:
                if int(cl) > limit: return await send_json(send, 413, {'detail': f'Too large (max {limit // (1024 * 1024)} MB).'})
            except ValueError: return await send_json(send, 400, {'detail': 'bad content-length'})
        seen = {'n': 0}

        async def _receive():
            msg = await receive()
            if msg['type'] == 'http.request':
                seen['n'] += len(msg.get('body', b''))
                if seen['n'] > limit: raise _TooLarge()
            return msg
        try:
            await self.app(scope, _receive, send)
        except _TooLarge:
            await send_json(send, 413, {'detail': f'Too large (max {limit // (1024 * 1024)} MB).'})


class _TooLarge(Exception):
    pass


def same_origin(scope, origin: str) -> bool:
    if not origin or origin == 'null': return False
    o = urlparse(origin)
    host = header(scope, 'host') or ''
    if o.netloc and o.netloc.lower() == host.lower(): return True
    return origin.rstrip('/') in CONFIG.allowed_origins


class AuthGate:
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http': return await self.app(scope, receive, send)
        path = scope.get('path', '')
        if not path.startswith('/api/') and path != '/api': return await self.app(scope, receive, send)
        method = scope.get('method', 'GET')
        ck = cookies_of(scope)
        tok = next((ck[n] for n in SESSION_COOKIES if n in ck), None)
        sess = None
        if tok:
            from starlette.concurrency import run_in_threadpool
            sess = await run_in_threadpool(store().session, tok)
        st = scope.setdefault('state', {})
        if sess:
            st['session'], st['user'] = sess
        if path not in PUBLIC_API and not sess:
            return await send_json(send, 401, {'detail': 'Please sign in.', 'code': 'auth_required'})
        if method not in SAFE_METHODS:
            origin = header(scope, 'origin')
            if origin and not same_origin(scope, origin):
                return await send_json(send, 403, {'detail': 'Cross-site request refused.', 'code': 'bad_origin'})
            sent = header(scope, CSRF_HEADER)
            cookie = next((ck[n] for n in CSRF_COOKIES if n in ck), None)
            ok = consteq(sent, cookie)
            if ok and sess: ok = consteq(sent, sess[0]['csrf'])
            if not ok:
                return await send_json(send, 403, {'detail': 'Security check failed (CSRF). Reload the page and try again.', 'code': 'csrf'})
        tokc = current_user.set(sess[1] if sess else None)
        try:
            await self.app(scope, receive, send)
        finally:
            current_user.reset(tokc)


class CatchAll:
    """Innermost: turns unexpected exceptions into a JSON 500 (no stack trace in production) so the outer middleware
    still adds the request id and security headers."""
    def __init__(self, app, on_error):
        self.app = app; self.on_error = on_error

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http': return await self.app(scope, receive, send)
        started = {'v': False}

        async def _send(msg):
            if msg['type'] == 'http.response.start': started['v'] = True
            await send(msg)
        try:
            await self.app(scope, receive, _send)
        except Exception as exc:
            if started['v']: raise
            status, body = self.on_error(scope, exc)
            await send_json(send, status, body)
