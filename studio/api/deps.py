"""Route authorization (every router is mounted with ``authorize``) and session-cookie helpers."""
from fastapi import HTTPException, Request, Response

from config import CONFIG
from security.context import has_role

ALLOW_WHEN_MUST_CHANGE = {'/api/auth/me', '/api/auth/password', '/api/auth/logout', '/api/auth/state'}


def required_role(route, method: str) -> str | None:
    ep = getattr(route, 'endpoint', None)
    if getattr(ep, '_public', False): return None
    return getattr(ep, '_min_role', None) or ('viewer' if method in ('GET', 'HEAD') else 'editor')


def authorize(request: Request):
    """Deny by default: a signed-in user with at least the route's role (see security.context.min_role)."""
    route = request.scope.get('route')
    need = required_role(route, request.method)
    if need is None: return None
    user = request.scope.get('state', {}).get('user')
    if not user: raise HTTPException(401, 'Please sign in.')
    if user.get('must_change_password') and request.url.path not in ALLOW_WHEN_MUST_CHANGE:
        raise HTTPException(403, 'Please set a new password first (account menu → Change password).')
    if not has_role(user, need):
        raise HTTPException(403, f'Your role ({user["role"]}) cannot do this — it needs {need} access.')
    return user


def secure_cookies(request: Request) -> bool:
    return CONFIG.cookie_is_secure(request.url.scheme)


def set_auth_cookies(request: Request, response: Response, token: str | None, csrf: str):
    sec = secure_cookies(request)
    sname, cname = ('__Host-kcs_session', '__Host-kcs_csrf') if sec else ('kcs_session', 'kcs_csrf')
    for n in ('__Host-kcs_session', 'kcs_session', '__Host-kcs_csrf', 'kcs_csrf'):
        if n in request.cookies and n not in (sname, cname):
            response.delete_cookie(n, path='/', secure=n.startswith('__Host-'), httponly=True, samesite='lax')
    if token:
        response.set_cookie(sname, token, max_age=CONFIG.session_max_hours * 3600, httponly=True, secure=sec, samesite='lax', path='/')
    response.set_cookie(cname, csrf, max_age=CONFIG.session_max_hours * 3600, httponly=False, secure=sec, samesite='strict', path='/')


def clear_auth_cookies(request: Request, response: Response, keep_csrf=True):
    for n in ('__Host-kcs_session', 'kcs_session') + (() if keep_csrf else ('__Host-kcs_csrf', 'kcs_csrf')):
        if n in request.cookies:
            response.delete_cookie(n, path='/', secure=n.startswith('__Host-'), httponly=True, samesite='lax')
