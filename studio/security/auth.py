"""User accounts and server-side sessions (SQLite in the config dir).

* passwords: argon2id (argon2-cffi defaults), rehashed when the parameters change;
* sessions: 256-bit random opaque token in an HttpOnly cookie; only its SHA-256 is stored; idle + absolute expiry;
  a new token on every login (no fixation); per-session CSRF token;
* login throttling: per account (lockout with exponential backoff, stored in the DB) and per client IP (in memory);
  generic error messages and a dummy hash check for unknown accounts (no user enumeration by timing);
* optional TOTP 2FA (pyotp), secrets encrypted with STUDIO_SECRET_KEY.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .context import ROLES

log = logging.getLogger('studio.auth')
_ph = PasswordHasher()
_DUMMY = _ph.hash('not-a-real-password-' + secrets.token_hex(8))
EMAIL_RE = re.compile(r'^[^@\s]{1,64}@[^@\s]{1,190}$')
ACCOUNT_FREE_FAILS = 5          # then 30 s, 60 s, 120 s … (max 1 h)
IP_WINDOW = 15 * 60
IP_MAX_FAILS = 30


class AuthError(Exception):
    def __init__(self, msg, status=400, code=None):
        super().__init__(msg); self.status = status; self.code = code


def now() -> float:
    return time.time()


def token_hash(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


def check_password_policy(pw: str, email: str = ''):
    if not isinstance(pw, str) or len(pw) < 10: raise AuthError('Use at least 10 characters for the password.')
    if len(pw) > 256: raise AuthError('That password is too long (max 256 characters).')
    if len(set(pw)) < 4: raise AuthError('That password is too simple.')
    if email and pw.lower() == email.lower(): raise AuthError('The password cannot be your email address.')
    if pw.lower() in ('password123', 'qwertyuiop', '1234567890', 'kawaiichaos', 'kawaiichaos1'): raise AuthError('That password is too common.')


def norm_email(e: str) -> str:
    e = (e or '').strip().lower()
    if not EMAIL_RE.match(e): raise AuthError('Enter a valid email address.')
    return e


class _Res:
    def __init__(self, rows, lastrowid):
        self.rows = rows; self.lastrowid = lastrowid

    def fetchone(self): return self.rows[0] if self.rows else None
    def fetchall(self): return self.rows
    def __iter__(self): return iter(self.rows)


class AuthStore:
    def __init__(self, db_path: Path, idle_minutes: int = 720, max_hours: int = 336, fernet=None):
        self.path = Path(db_path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.idle = idle_minutes * 60; self.maxage = max_hours * 3600
        self.fernet = fernet
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        try: self.path.chmod(0o600)
        except OSError: pass
        self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL DEFAULT '',
          password_hash TEXT NOT NULL, role TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0,
          must_change_password INTEGER NOT NULL DEFAULT 0, totp_secret TEXT, totp_enabled INTEGER NOT NULL DEFAULT 0,
          failed_count INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0,
          created_at REAL NOT NULL, updated_at REAL NOT NULL, last_login_at REAL, last_login_ip TEXT);
        CREATE TABLE IF NOT EXISTS sessions (
          sid TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          csrf TEXT NOT NULL, created_at REAL NOT NULL, last_seen REAL NOT NULL, expires_at REAL NOT NULL,
          ip TEXT, user_agent TEXT);
        CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
        ''')
        self._ip_fails: dict[str, deque] = {}

    def _x(self, sql, args=()):
        """Execute AND fetch while holding the lock: the connection is shared by request threads, so a cursor must
        never be read outside the lock (concurrent requests would otherwise see each other's rows)."""
        with self._lock:
            cur = self.db.execute(sql, args)
            return _Res(cur.fetchall() if cur.description else [], cur.lastrowid)

    # ---------------- users ----------------
    def count_users(self) -> int:
        return self._x('SELECT COUNT(*) FROM users').fetchone()[0]

    def count_admins(self, exclude_id: int | None = None) -> int:
        return self._x("SELECT COUNT(*) FROM users WHERE role='admin' AND disabled=0 AND id IS NOT ?", (exclude_id,)).fetchone()[0]

    def user(self, uid: int) -> dict | None:
        r = self._x('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
        return dict(r) if r else None

    def user_by_email(self, email: str) -> dict | None:
        r = self._x('SELECT * FROM users WHERE email=?', ((email or '').strip().lower(),)).fetchone()
        return dict(r) if r else None

    @staticmethod
    def public_user(u: dict) -> dict:
        return dict(id=u['id'], email=u['email'], name=u['name'], role=u['role'], disabled=bool(u['disabled']),
                    must_change_password=bool(u['must_change_password']), totp_enabled=bool(u['totp_enabled']),
                    created_at=u['created_at'], last_login_at=u.get('last_login_at'), last_login_ip=u.get('last_login_ip'),
                    locked=u['locked_until'] > now())

    def list_users(self) -> list[dict]:
        return [self.public_user(dict(r)) for r in self._x('SELECT * FROM users ORDER BY id')]

    def create_user(self, email: str, password: str, role: str = 'editor', name: str = '', must_change: bool = False,
                    only_if_empty: bool = False) -> dict:
        email = norm_email(email)
        if role not in ROLES: raise AuthError('Unknown role.')
        check_password_policy(password, email)
        h = _ph.hash(password); t = now()
        with self._lock:
            try:
                self._x('BEGIN IMMEDIATE')
                if only_if_empty and self._x('SELECT COUNT(*) FROM users').fetchone()[0]:
                    self._x('ROLLBACK'); raise AuthError('Setup is already done — sign in instead.', 409)
                cur = self._x('INSERT INTO users (email, name, password_hash, role, must_change_password, created_at, updated_at) VALUES (?,?,?,?,?,?,?)',
                                      (email, (name or '').strip()[:80], h, role, int(must_change), t, t))
                self._x('COMMIT')
            except sqlite3.IntegrityError:
                self._x('ROLLBACK'); raise AuthError('A user with this email already exists.', 409)
            except AuthError: raise
            except Exception:
                try: self._x('ROLLBACK')
                except sqlite3.Error: pass
                raise
        return self.user(cur.lastrowid)

    def update_user(self, uid: int, *, role: str | None = None, disabled: bool | None = None, name: str | None = None) -> dict:
        u = self.user(uid)
        if not u: raise AuthError('No such user.', 404)
        with self._lock:
            if role is not None:
                if role not in ROLES: raise AuthError('Unknown role.')
                if u['role'] == 'admin' and role != 'admin' and self.count_admins(exclude_id=uid) == 0:
                    raise AuthError('This is the last admin — make someone else admin first.', 409)
                self._x('UPDATE users SET role=?, updated_at=? WHERE id=?', (role, now(), uid))
            if disabled is not None:
                if disabled and u['role'] == 'admin' and self.count_admins(exclude_id=uid) == 0:
                    raise AuthError('This is the last admin — it cannot be disabled.', 409)
                self._x('UPDATE users SET disabled=?, updated_at=? WHERE id=?', (int(disabled), now(), uid))
                if disabled: self.revoke_all(uid)
            if name is not None:
                self._x('UPDATE users SET name=?, updated_at=? WHERE id=?', (name.strip()[:80], now(), uid))
        return self.user(uid)

    def delete_user(self, uid: int):
        u = self.user(uid)
        if not u: raise AuthError('No such user.', 404)
        if u['role'] == 'admin' and self.count_admins(exclude_id=uid) == 0: raise AuthError('The last admin cannot be deleted.', 409)
        with self._lock: self._x('DELETE FROM users WHERE id=?', (uid,))

    def set_password(self, uid: int, password: str, must_change: bool = False):
        u = self.user(uid)
        if not u: raise AuthError('No such user.', 404)
        check_password_policy(password, u['email'])
        with self._lock:
            self._x('UPDATE users SET password_hash=?, must_change_password=?, failed_count=0, locked_until=0, updated_at=? WHERE id=?',
                            (_ph.hash(password), int(must_change), now(), uid))

    def verify_password(self, u: dict, password: str) -> bool:
        try:
            ok = _ph.verify(u['password_hash'], password or '')
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
        if ok and _ph.check_needs_rehash(u['password_hash']):
            with self._lock: self._x('UPDATE users SET password_hash=? WHERE id=?', (_ph.hash(password), u['id']))
        return ok

    # ---------------- login throttling ----------------
    def ip_blocked(self, ip: str) -> bool:
        q = self._ip_fails.get(ip)
        if not q: return False
        while q and q[0] < now() - IP_WINDOW: q.popleft()
        return len(q) >= IP_MAX_FAILS

    def _ip_fail(self, ip: str):
        self._ip_fails.setdefault(ip, deque()).append(now())
        if len(self._ip_fails) > 10000:                      # bound memory
            for k in list(self._ip_fails)[:5000]: self._ip_fails.pop(k, None)

    def authenticate(self, email: str, password: str, ip: str, totp: str | None = None) -> dict:
        """Returns the user or raises AuthError with a generic message."""
        generic = AuthError('Wrong email or password.', 401, 'bad_credentials')
        if self.ip_blocked(ip):
            raise AuthError('Too many failed sign-ins from this network. Try again in 15 minutes.', 429, 'rate_limited')
        u = self.user_by_email((email or '').strip().lower())
        if not u:
            try: _ph.verify(_DUMMY, password or '')            # same cost as a real check
            except Exception: pass  # nosec B110 - timing equaliser only
            self._ip_fail(ip); raise generic
        if u['locked_until'] > now():
            self._ip_fail(ip)
            wait = int(u['locked_until'] - now()) + 1
            raise AuthError(f'Too many failed sign-ins for this account. Try again in {wait} s.', 429, 'locked')
        if not self.verify_password(u, password):
            n = u['failed_count'] + 1
            lock = now() + min(3600, 30 * 2 ** (n - ACCOUNT_FREE_FAILS)) if n >= ACCOUNT_FREE_FAILS else 0
            with self._lock: self._x('UPDATE users SET failed_count=?, locked_until=? WHERE id=?', (n, lock, u['id']))
            self._ip_fail(ip)
            if lock: log.warning('account locked after %d failures (user id %s)', n, u['id'])
            raise generic
        if u['disabled']:
            self._ip_fail(ip); raise generic
        if u['totp_enabled']:
            if not totp: raise AuthError('Enter the 6-digit code from your authenticator app.', 401, 'totp_required')
            if not self.verify_totp(u, totp):
                n = u['failed_count'] + 1
                lock = now() + min(3600, 30 * 2 ** (n - ACCOUNT_FREE_FAILS)) if n >= ACCOUNT_FREE_FAILS else 0
                with self._lock: self._x('UPDATE users SET failed_count=?, locked_until=? WHERE id=?', (n, lock, u['id']))
                self._ip_fail(ip)
                raise AuthError('That code is not right (or expired).', 401, 'totp_bad')
        with self._lock:
            self._x('UPDATE users SET failed_count=0, locked_until=0, last_login_at=?, last_login_ip=? WHERE id=?', (now(), ip, u['id']))
        return self.user(u['id'])

    # ---------------- TOTP ----------------
    def _enc(self, s: str) -> str:
        if not self.fernet: raise AuthError('Two-factor sign-in needs STUDIO_SECRET_KEY to be set on the server.', 409)
        return self.fernet.encrypt(s.encode()).decode()

    def _dec(self, s: str) -> str:
        if not self.fernet: raise AuthError('STUDIO_SECRET_KEY is not set.', 409)
        return self.fernet.decrypt(s.encode()).decode()

    def totp_begin(self, uid: int) -> tuple[str, str]:
        import pyotp
        u = self.user(uid)
        sec = pyotp.random_base32()
        with self._lock: self._x('UPDATE users SET totp_secret=?, totp_enabled=0 WHERE id=?', (self._enc(sec), uid))
        uri = pyotp.TOTP(sec).provisioning_uri(name=u['email'], issuer_name='Kawaii Chaos Studio')
        return sec, uri

    def verify_totp(self, u: dict, code: str) -> bool:
        import pyotp
        if not u.get('totp_secret'): return False
        code = re.sub(r'\s', '', code or '')
        if not re.fullmatch(r'\d{6}', code): return False
        return pyotp.TOTP(self._dec(u['totp_secret'])).verify(code, valid_window=1)

    def totp_confirm(self, uid: int, code: str):
        u = self.user(uid)
        if not u or not u.get('totp_secret'): raise AuthError('Start the two-factor setup first.')
        if not self.verify_totp(u, code): raise AuthError('That code is not right — check the time on your phone and try again.')
        with self._lock: self._x('UPDATE users SET totp_enabled=1 WHERE id=?', (uid,))

    def totp_disable(self, uid: int):
        with self._lock: self._x('UPDATE users SET totp_enabled=0, totp_secret=NULL WHERE id=?', (uid,))

    # ---------------- sessions ----------------
    def create_session(self, uid: int, ip: str, ua: str) -> tuple[str, dict]:
        tok = secrets.token_urlsafe(32); sid = secrets.token_hex(8); csrf = secrets.token_urlsafe(24); t = now()
        with self._lock:
            self._x('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)',
                            (sid, token_hash(tok), uid, csrf, t, t, t + self.maxage, (ip or '')[:64], (ua or '')[:200]))
            # keep at most 20 sessions per user
            olds = self._x('SELECT sid FROM sessions WHERE user_id=? ORDER BY last_seen DESC LIMIT -1 OFFSET 20', (uid,)).fetchall()
            for r in olds: self._x('DELETE FROM sessions WHERE sid=?', (r[0],))
        return tok, dict(sid=sid, csrf=csrf, user_id=uid)

    def session(self, tok: str | None) -> tuple[dict, dict] | None:
        """(session, user) for a valid token, else None (expired sessions are deleted)."""
        if not tok or len(tok) > 200: return None
        r = self._x('SELECT * FROM sessions WHERE token_hash=?', (token_hash(tok),)).fetchone()
        if not r: return None
        s = dict(r); t = now()
        if s['expires_at'] < t or s['last_seen'] + self.idle < t:
            with self._lock: self._x('DELETE FROM sessions WHERE sid=?', (s['sid'],))
            return None
        u = self.user(s['user_id'])
        if not u or u['disabled']: return None
        if t - s['last_seen'] > 60:
            with self._lock: self._x('UPDATE sessions SET last_seen=? WHERE sid=?', (t, s['sid']))
        return s, u

    def list_sessions(self, uid: int) -> list[dict]:
        return [dict(sid=r['sid'], created_at=r['created_at'], last_seen=r['last_seen'], expires_at=r['expires_at'], ip=r['ip'], user_agent=r['user_agent'])
                for r in self._x('SELECT * FROM sessions WHERE user_id=? ORDER BY last_seen DESC', (uid,))]

    def revoke(self, sid: str, uid: int | None = None):
        with self._lock:
            if uid is None: self._x('DELETE FROM sessions WHERE sid=?', (sid,))
            else: self._x('DELETE FROM sessions WHERE sid=? AND user_id=?', (sid, uid))

    def revoke_all(self, uid: int, except_sid: str | None = None):
        with self._lock: self._x('DELETE FROM sessions WHERE user_id=? AND sid IS NOT ?', (uid, except_sid))

    def purge_expired(self):
        t = now()
        with self._lock: self._x('DELETE FROM sessions WHERE expires_at<? OR last_seen<?', (t, t - self.idle))


def consteq(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(str(a).encode(), str(b).encode())


_STORE: AuthStore | None = None


def set_store(s: AuthStore):
    global _STORE
    _STORE = s


def store() -> AuthStore:
    if _STORE is None: raise RuntimeError('auth store not initialised')
    return _STORE
