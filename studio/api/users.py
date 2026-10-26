"""User management (admins only): create/invite, roles, password reset, disable, delete, sessions."""
import logging
import secrets

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from .deps import authorize

from security import auth as A
from security.context import min_role

router = APIRouter(dependencies=[Depends(authorize)])   # deny by default (api/deps.py)
log = logging.getLogger('studio.audit')


def _err(e: A.AuthError):
    raise HTTPException(e.status, str(e))


def temp_password() -> str:
    return secrets.token_urlsafe(12)


def _actor(request: Request):
    return request.scope['state']['user']['id']


@router.get('/api/users')
@min_role('admin')
def list_users():
    return A.store().list_users()


@router.post('/api/users')
@min_role('admin')
def create_user(request: Request, email: str = Body(...), name: str = Body(''), role: str = Body('editor'), password: str = Body('')):
    """Without a password a temporary one is generated and returned ONCE; the user must change it at first sign-in."""
    pw = password or temp_password()
    try: u = A.store().create_user(email, pw, role, name, must_change=not password)
    except A.AuthError as e: _err(e)
    log.info('user %s created with role %s by %s', u['id'], role, _actor(request))
    return dict(user=A.store().public_user(u), temporary_password=None if password else pw)


@router.patch('/api/users/{uid}')
@min_role('admin')
def update_user(request: Request, uid: int, role: str | None = Body(None), disabled: bool | None = Body(None), name: str | None = Body(None)):
    if uid == _actor(request) and (disabled or (role and role != 'admin')):
        raise HTTPException(409, 'You cannot disable yourself or remove your own admin role.')
    try: u = A.store().update_user(uid, role=role, disabled=disabled, name=name)
    except A.AuthError as e: _err(e)
    log.info('user %s updated by %s (role=%s disabled=%s)', uid, _actor(request), role, disabled)
    return A.store().public_user(u)


@router.post('/api/users/{uid}/reset-password')
@min_role('admin')
def reset_password(request: Request, uid: int):
    pw = temp_password()
    try: A.store().set_password(uid, pw, must_change=True)
    except A.AuthError as e: _err(e)
    A.store().revoke_all(uid)
    log.info('password of user %s reset by %s', uid, _actor(request))
    return dict(temporary_password=pw)


@router.post('/api/users/{uid}/disable-2fa')
@min_role('admin')
def disable_2fa(request: Request, uid: int):
    if not A.store().user(uid): raise HTTPException(404, 'No such user.')
    A.store().totp_disable(uid)
    log.info('two-factor of user %s turned off by %s', uid, _actor(request))
    return dict(ok=True)


@router.delete('/api/users/{uid}')
@min_role('admin')
def delete_user(request: Request, uid: int):
    if uid == _actor(request): raise HTTPException(409, 'You cannot delete yourself.')
    try: A.store().delete_user(uid)
    except A.AuthError as e: _err(e)
    log.info('user %s deleted by %s', uid, _actor(request))
    return dict(ok=True)


@router.get('/api/users/{uid}/sessions')
@min_role('admin')
def user_sessions(uid: int):
    return A.store().list_sessions(uid)


@router.delete('/api/users/{uid}/sessions/{sid}')
@min_role('admin')
def revoke_session(request: Request, uid: int, sid: str):
    A.store().revoke(sid, uid)
    log.info('session of user %s revoked by %s', uid, _actor(request))
    return dict(ok=True)


@router.delete('/api/users/{uid}/sessions')
@min_role('admin')
def revoke_all_sessions(request: Request, uid: int):
    A.store().revoke_all(uid)
    log.info('all sessions of user %s revoked by %s', uid, _actor(request))
    return dict(ok=True)
