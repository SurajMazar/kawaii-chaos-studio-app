"""Sessions, CSRF, lockout, setup, password change, headers."""
import time

from conftest import ADMIN, EDITOR, PID, Client


def test_setup_only_once(app, users, anon):
    r = anon.post('/api/auth/setup', json=dict(email='evil@example.com', password='Another-Password-1'))
    assert r.status_code == 409


def test_csrf_missing_or_wrong(app, editor):
    url = f'/api/p/strip/{PID}/text?name=synopsis.md'
    r = editor.c.put(url, json={'text': 'x'})                           # no header
    assert r.status_code == 403 and r.json()['code'] == 'csrf'
    r = editor.c.put(url, json={'text': 'x'}, headers={'x-csrf-token': 'wrong'})
    assert r.status_code == 403
    r = editor.put(url, json={'text': 'x'}, headers={'origin': 'https://evil.example'})
    assert r.status_code == 403 and r.json()['code'] == 'bad_origin'


def test_login_generic_errors_and_lockout(app, users):
    from security import auth as A
    A.store().create_user('lock@example.com', 'Lockable-Pass-1', 'viewer') if not A.store().user_by_email('lock@example.com') else None
    c = Client(app)
    r1 = c.post('/api/auth/login', json=dict(email='nobody@example.com', password='whatever-123'))
    r2 = c.post('/api/auth/login', json=dict(email='lock@example.com', password='wrong-password'))
    assert r1.status_code == r2.status_code == 401
    assert r1.json()['detail']['message'] == r2.json()['detail']['message'] == 'Wrong email or password.'
    for _ in range(5): c.post('/api/auth/login', json=dict(email='lock@example.com', password='wrong-password'))
    r = c.post('/api/auth/login', json=dict(email='lock@example.com', password='Lockable-Pass-1'))
    assert r.status_code == 429                                          # locked even with the right password
    A.store()._x('UPDATE users SET locked_until=0, failed_count=0 WHERE email=?', ('lock@example.com',))
    assert c.post('/api/auth/login', json=dict(email='lock@example.com', password='Lockable-Pass-1')).status_code == 200


def test_ip_rate_limit(app, users):
    from security import auth as A
    st = A.store()
    ip = 'testclient'
    st._ip_fails.pop(ip, None)
    for _ in range(A.IP_MAX_FAILS): st._ip_fail(ip)
    c = Client(app)
    r = c.post('/api/auth/login', json=dict(email=ADMIN[0], password=ADMIN[1]))
    assert r.status_code == 429
    st._ip_fails.pop(ip, None)


def test_session_rotation_and_logout(app, users):
    c = Client(app); c.login(*EDITOR)
    tok1 = c.c.cookies.get('kcs_session')
    c.login(*EDITOR)
    tok2 = c.c.cookies.get('kcs_session')
    assert tok1 and tok2 and tok1 != tok2
    from security import auth as A
    assert A.store().session(tok1) is None                               # old session revoked on re-login (no fixation)
    assert c.get('/api/auth/me').status_code == 200
    assert c.post('/api/auth/logout').status_code == 200
    assert c.get('/api/auth/me').status_code == 401


def test_logout_everywhere(app, users):
    a = Client(app); a.login(*EDITOR); b = Client(app); b.login(*EDITOR)
    assert a.post('/api/auth/logout-all').status_code == 200
    assert b.get('/api/auth/me').status_code == 401


def test_cookie_flags(app, users):
    c = Client(app); r = c.login(*EDITOR)
    sc = [v for k, v in r.headers.multi_items() if k == 'set-cookie']
    sess = next(x for x in sc if x.startswith('kcs_session='))
    assert 'HttpOnly' in sess and 'SameSite=lax' in sess.replace('Lax', 'lax')


def test_idle_expiry(app, users):
    from security import auth as A
    st = A.store()
    c = Client(app); c.login(*EDITOR)
    tok = c.c.cookies.get('kcs_session')
    st._x('UPDATE sessions SET last_seen=? WHERE token_hash=?', (time.time() - st.idle - 5, A.token_hash(tok)))
    assert c.get('/api/auth/me').status_code == 401


def test_password_change_revokes_other_sessions(app, users):
    from security import auth as A
    if not A.store().user_by_email('pw@example.com'): A.store().create_user('pw@example.com', 'First-Password-1', 'editor')
    a = Client(app); a.login('pw@example.com', 'First-Password-1')
    b = Client(app); b.login('pw@example.com', 'First-Password-1')
    r = a.post('/api/auth/password', json=dict(current_password='First-Password-1', new_password='Second-Password-2'))
    assert r.status_code == 200, r.text
    a.csrf = r.json()['csrf']
    assert a.get('/api/auth/me').status_code == 200
    assert b.get('/api/auth/me').status_code == 401
    assert a.post('/api/auth/password', json=dict(current_password='nope', new_password='Third-Password-3')).status_code == 400


def test_weak_password_rejected(admin):
    r = admin.post('/api/users', json=dict(email='weak@example.com', password='short', role='viewer'))
    assert r.status_code == 400


def test_must_change_password_flow(app, admin):
    r = admin.post('/api/users', json=dict(email='new@example.com', role='editor'))
    assert r.status_code == 200
    tmp = r.json()['temporary_password']; assert tmp
    c = Client(app); c.login('new@example.com', tmp)
    assert c.get('/api/library').status_code == 403                      # must set a new password first
    r = c.post('/api/auth/password', json=dict(current_password=tmp, new_password='My-Own-Password-1'))
    assert r.status_code == 200; c.csrf = r.json()['csrf']
    assert c.get('/api/library').status_code == 200


def test_last_admin_protected(admin):
    me = admin.get('/api/auth/me').json()
    assert admin.patch(f"/api/users/{me['id']}", json=dict(role='viewer')).status_code == 409
    assert admin.delete(f"/api/users/{me['id']}").status_code == 409


def test_disable_user_kills_sessions(app, admin):
    from security import auth as A
    u = A.store().user_by_email('dis@example.com') or A.store().create_user('dis@example.com', 'Disable-Me-123', 'viewer')
    c = Client(app); c.login('dis@example.com', 'Disable-Me-123')
    assert admin.patch(f"/api/users/{u['id']}", json=dict(disabled=True)).status_code == 200
    assert c.get('/api/auth/me').status_code == 401
    r = Client(app).post('/api/auth/login', json=dict(email='dis@example.com', password='Disable-Me-123'))
    assert r.status_code == 401


def test_totp(app, users):
    import pyotp
    from security import auth as A
    if not A.store().user_by_email('totp@example.com'): A.store().create_user('totp@example.com', 'Totp-Password-1', 'admin')
    c = Client(app); c.login('totp@example.com', 'Totp-Password-1')
    r = c.post('/api/auth/totp/setup', json=dict(password='Totp-Password-1')); assert r.status_code == 200
    sec = r.json()['secret']
    assert c.post('/api/auth/totp/confirm', json=dict(code='000000')).status_code == 400
    assert c.post('/api/auth/totp/confirm', json=dict(code=pyotp.TOTP(sec).now())).status_code == 200
    d = Client(app)
    r = d.post('/api/auth/login', json=dict(email='totp@example.com', password='Totp-Password-1'))
    assert r.status_code == 401 and r.json()['detail']['code'] == 'totp_required'
    r = d.post('/api/auth/login', json=dict(email='totp@example.com', password='Totp-Password-1', totp=pyotp.TOTP(sec).now()))
    assert r.status_code == 200


def test_security_headers(anon):
    r = anon.get('/api/auth/state')
    h = r.headers
    assert h['x-content-type-options'] == 'nosniff'
    assert "frame-ancestors 'none'" in h['content-security-policy']
    assert h['x-frame-options'] == 'DENY'
    assert h['referrer-policy'] == 'same-origin'
    assert 'x-request-id' in h
    assert 'server' not in h


def test_no_stack_traces_in_production(app, admin, monkeypatch):
    from config import CONFIG
    monkeypatch.setattr(CONFIG, 'env', 'production')
    from api import library
    monkeypatch.setattr(library, 'build_library', lambda: 1 / 0)
    library.invalidate()
    r = admin.get('/api/library')
    assert r.status_code == 500
    assert 'ZeroDivision' not in r.text and 'Traceback' not in r.text and 'request_id' in r.json()
    library.invalidate()


def test_body_limits(admin, monkeypatch):
    from config import CONFIG
    monkeypatch.setattr(CONFIG, 'max_json_mb', 1)
    r = admin.put(f'/api/p/strip/{PID}/text?name=synopsis.md', content=b'{"text": "' + b'a' * (2 * 1024 * 1024) + b'"}',
                  headers={'content-type': 'application/json'})
    assert r.status_code == 413


def test_session_lookup_is_thread_safe(app, users):
    """Regression: the shared SQLite connection must never hand one request another request's rows."""
    from concurrent.futures import ThreadPoolExecutor
    from security import auth as A
    st = A.store()
    toks = [(st.create_session(st.user_by_email(e)['id'], 'x', 'y')[0], e) for e in (EDITOR[0], ADMIN[0])] * 50

    def check(t):
        s = st.session(t[0])
        return s is not None and s[1]['email'] == t[1] and s[1]['role'] in ('editor', 'admin')
    with ThreadPoolExecutor(max_workers=16) as ex:
        assert all(ex.map(check, toks))


def test_host_header_allowlist(anon):
    r = anon.get('/api/auth/state', headers={'host': 'evil.example'})
    assert r.status_code == 400
    assert anon.get('/api/auth/state', headers={'host': 'localhost:8770'}).status_code == 200


def test_still_rate_limit(editor):
    from security import ratelimit
    import pytest as _pt
    from fastapi import HTTPException
    k = 'test:still'
    for _ in range(40): ratelimit.hit(k, 40, 0.0001)
    with _pt.raises(HTTPException): ratelimit.hit(k, 40, 0.0001)


def test_active_content_downloads(editor):
    from conftest import DATA, PID
    (DATA / 'projects' / PID / 'x.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
    r = editor.get(f'/api/p/strip/{PID}/file/x.svg')
    assert r.status_code == 200 and r.headers['content-disposition'].startswith('attachment')


def test_health_ignores_host_allowlist(anon):
    assert anon.get('/api/health', headers={'host': '127.0.0.1:8770'}).status_code == 200
    assert anon.get('/api/health', headers={'host': 'internal-name'}).status_code == 200
