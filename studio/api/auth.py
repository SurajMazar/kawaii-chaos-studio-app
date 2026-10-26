"""Sign-in, first-run setup, sessions, password change and optional TOTP two-factor sign-in."""
import logging
import os
import secrets

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from .deps import authorize

from config import CONFIG
from security import auth as A
from security.context import min_role, public_route

from .deps import clear_auth_cookies, set_auth_cookies

router = APIRouter(dependencies=[Depends(authorize)])   # deny by default (api/deps.py)
log = logging.getLogger('studio.auth')
SETUP = {'token': None}  # nosec B105 - holder for the one-time setup code, not a password


def _ip(request: Request) -> str:
    return request.client.host if request.client else '?'


def _err(e: A.AuthError):
    raise HTTPException(e.status, detail=str(e) if not e.code else {'message': str(e), 'code': e.code})


def init_setup_token():
    """Production + no users: setup needs a one-time code that is printed in the server log (or STUDIO_SETUP_TOKEN)."""
    import os
    st = A.store()
    if st.count_users(): SETUP['token'] = None; return
    tok = os.environ.get('STUDIO_SETUP_TOKEN') or (secrets.token_urlsafe(12) if CONFIG.production else None)
    SETUP['token'] = tok
    if tok and not os.environ.get('STUDIO_SETUP_TOKEN'):
        log.warning('FIRST-RUN SETUP: no users yet. Open the Studio and use this one-time setup code: %s', tok)


def bootstrap_admin():
    """STUDIO_ADMIN_EMAIL + STUDIO_ADMIN_PASSWORD create the first admin when there are no users (never overwrites)."""
    st = A.store()
    if st.count_users() or not (CONFIG.admin_email and CONFIG.admin_password): return
    try:
        st.create_user(CONFIG.admin_email, CONFIG.admin_password, 'admin', 'Admin', only_if_empty=True)
        log.info('created the first admin from STUDIO_ADMIN_EMAIL')
    except A.AuthError as e:
        log.error('could not create the admin from STUDIO_ADMIN_EMAIL/STUDIO_ADMIN_PASSWORD: %s', e)


def _login_response(request: Request, response: Response, user: dict):
    st = A.store()
    old = request.scope.get('state', {}).get('session')
    if old: st.revoke(old['sid'])                    # rotate: never keep a pre-login session
    tok, s = st.create_session(user['id'], _ip(request), request.headers.get('user-agent', ''))
    set_auth_cookies(request, response, tok, s['csrf'])
    return dict(ok=True, user=st.public_user(user), csrf=s['csrf'])


@router.get('/api/auth/state')
@public_route
def state(request: Request, response: Response):
    st = A.store()
    sess = request.scope.get('state', {}).get('session'); user = request.scope.get('state', {}).get('user')
    have = request.cookies.get('__Host-kcs_csrf') or request.cookies.get('kcs_csrf')
    csrf = sess['csrf'] if sess else (have or secrets.token_urlsafe(24))
    if have != csrf: set_auth_cookies(request, response, None, csrf)
    setup = st.count_users() == 0
    return dict(setup_required=setup, setup_token_required=bool(setup and SETUP['token']),
                user=st.public_user(user) if user else None, csrf=csrf, env=CONFIG.env,
                local_features=CONFIG.local_features, two_factor_available=st.fernet is not None, desktop=bool(desktop_token()))


DESKTOP_EMAIL = 'me@desktop.local'


def desktop_token() -> str:
    """Set by the Mac app for this launch only (a random secret it opens the window with)."""
    return os.environ.get('STUDIO_DESKTOP_TOKEN', '')


@router.get('/api/auth/desktop')
@public_route
def desktop_signin(request: Request, token: str = ''):  # nosec B107 - the launch secret arrives in the query; '' = not given
    """Mac app: the window opens this URL with the launch secret and is signed in as the local owner — no password.
    Without STUDIO_DESKTOP_TOKEN (servers, run.sh) the route does not exist."""
    want = desktop_token()
    if not want or not A.consteq(token, want): raise HTTPException(404, 'Not Found')
    st = A.store()
    u = st.user_by_email(DESKTOP_EMAIL)
    if not u:
        try: u = st.create_user(DESKTOP_EMAIL, secrets.token_urlsafe(32) + 'Aa1!', 'admin', 'Me')
        except A.AuthError as e: _err(e)
    resp = RedirectResponse('/', status_code=303)
    _login_response(request, resp, u)
    return resp


@router.post('/api/auth/setup')
@public_route
def setup(request: Request, response: Response, email: str = Body(...), password: str = Body(...), name: str = Body(''),
          setup_token: str = Body('')):
    st = A.store()
    if st.count_users(): raise HTTPException(409, 'Setup is already done — sign in instead.')
    if SETUP['token'] and not A.consteq(setup_token.strip(), SETUP['token']):
        st._ip_fail(_ip(request))
        raise HTTPException(403, 'The setup code is not right. It is printed in the server log.')
    try: u = st.create_user(email, password, 'admin', name or 'Admin', only_if_empty=True)
    except A.AuthError as e: _err(e)
    SETUP['token'] = None
    log.info('first admin created (user id %s)', u['id'])
    return _login_response(request, response, u)


@router.post('/api/auth/login')
@public_route
def login(request: Request, response: Response, email: str = Body(...), password: str = Body(...), totp: str = Body('')):
    if len(email) > 256 or len(password) > 256: raise HTTPException(400, 'Too long.')
    try: u = A.store().authenticate(email, password, _ip(request), totp or None)
    except A.AuthError as e:
        if e.code in ('bad_credentials', 'locked', 'rate_limited'): log.warning('failed sign-in (%s) from %s', e.code, _ip(request))
        _err(e)
    log.info('sign-in user id %s from %s', u['id'], _ip(request))
    return _login_response(request, response, u)


@router.post('/api/auth/logout')
@public_route
def logout(request: Request, response: Response):
    sess = request.scope.get('state', {}).get('session')
    if sess: A.store().revoke(sess['sid'])
    clear_auth_cookies(request, response, keep_csrf=True)
    return dict(ok=True)


@router.post('/api/auth/logout-all')
@min_role('viewer')
def logout_all(request: Request, response: Response):
    u = request.scope['state']['user']
    A.store().revoke_all(u['id'])
    clear_auth_cookies(request, response, keep_csrf=True)
    return dict(ok=True)


@router.get('/api/auth/me')
@min_role('viewer')
def me(request: Request):
    return A.store().public_user(request.scope['state']['user'])


@router.post('/api/auth/password')
@min_role('viewer')
def change_password(request: Request, response: Response, current_password: str = Body(...), new_password: str = Body(...)):
    st = A.store(); u = request.scope['state']['user']
    if not st.verify_password(u, current_password): raise HTTPException(400, 'The current password is not right.')
    if current_password == new_password: raise HTTPException(400, 'Choose a password different from the current one.')
    try: st.set_password(u['id'], new_password)
    except A.AuthError as e: _err(e)
    st.revoke_all(u['id'])                          # every other device signs in again; this one gets a fresh session
    log.info('password changed (user id %s)', u['id'])
    return _login_response(request, response, st.user(u['id']))


@router.get('/api/auth/sessions')
@min_role('viewer')
def my_sessions(request: Request):
    u = request.scope['state']['user']; cur = request.scope['state']['session']['sid']
    return [dict(s, current=s['sid'] == cur) for s in A.store().list_sessions(u['id'])]


@router.delete('/api/auth/sessions/{sid}')
@min_role('viewer')
def revoke_my_session(request: Request, sid: str):
    A.store().revoke(sid, request.scope['state']['user']['id'])
    return dict(ok=True)


@router.post('/api/auth/totp/setup')
@min_role('viewer')
def totp_setup(request: Request, password: str = Body(..., embed=True)):
    st = A.store(); u = request.scope['state']['user']
    if not st.verify_password(u, password): raise HTTPException(400, 'The password is not right.')
    try: sec, uri = st.totp_begin(u['id'])
    except A.AuthError as e: _err(e)
    return dict(secret=sec, uri=uri)


@router.post('/api/auth/totp/confirm')
@min_role('viewer')
def totp_confirm(request: Request, code: str = Body(..., embed=True)):
    try: A.store().totp_confirm(request.scope['state']['user']['id'], code)
    except A.AuthError as e: _err(e)
    log.info('two-factor enabled (user id %s)', request.scope['state']['user']['id'])
    return dict(ok=True)


@router.post('/api/auth/totp/disable')
@min_role('viewer')
def totp_disable(request: Request, password: str = Body(..., embed=True)):
    st = A.store(); u = request.scope['state']['user']
    if not st.verify_password(u, password): raise HTTPException(400, 'The password is not right.')
    st.totp_disable(u['id'])
    log.info('two-factor disabled (user id %s)', u['id'])
    return dict(ok=True)
