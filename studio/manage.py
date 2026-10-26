"""Admin command line for things the web UI cannot do (run on the server / inside the container).

    python studio/manage.py list-users
    python studio/manage.py create-admin you@example.com          # asks for the password
    python studio/manage.py reset-password you@example.com        # prints a one-time temporary password
    python studio/manage.py unlock you@example.com                # clears a login lockout
    python studio/manage.py disable-2fa you@example.com
    python studio/manage.py rotate-secret-key                     # re-encrypt secrets with STUDIO_SECRET_KEY
                                                                  # (old key(s) in STUDIO_SECRET_KEY_OLD)
Docker:  docker compose exec studio python studio/manage.py reset-password you@example.com
"""
import argparse
import getpass
import json
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import CONFIG  # noqa: E402


def store():
    from security import auth as A
    from storage.settings import _fernet
    if not CONFIG.secret_key:
        f = CONFIG.config_dir / 'secret.key'
        if f.exists(): CONFIG.secret_key = f.read_text().strip()
    fer = _fernet(CONFIG.secret_key, os.environ.get('STUDIO_SECRET_KEY_OLD', '')) if CONFIG.secret_key else None
    return A.AuthStore(CONFIG.config_dir / 'studio.db', CONFIG.session_idle_minutes, CONFIG.session_max_hours, fer), A


def main():
    ap = argparse.ArgumentParser(description='Kawaii Chaos Studio admin commands')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list-users')
    for c in ('create-admin', 'reset-password', 'unlock', 'disable-2fa'):
        sub.add_parser(c).add_argument('email')
    sub.add_parser('rotate-secret-key')
    a = ap.parse_args()
    st, A = store()
    if a.cmd == 'list-users':
        for u in st.list_users():
            print(f"{u['id']:>3}  {u['role']:<7} {'off' if u['disabled'] else 'on ':<4} {'2FA' if u['totp_enabled'] else '   '}  {u['email']}  {u['name']}")
        return
    if a.cmd == 'rotate-secret-key':
        from storage.settings import StorageSettings
        if not CONFIG.secret_key: sys.exit('Set STUDIO_SECRET_KEY (new key) and STUDIO_SECRET_KEY_OLD (old key) first.')
        ss = StorageSettings(CONFIG.config_dir, CONFIG.secret_key, os.environ.get('STUDIO_SECRET_KEY_OLD', ''))
        raw = ss.stored(); n = 0
        for k, v in list(raw.items()):
            if k.endswith('_enc') and v:
                raw[k] = ss.encrypt(ss.decrypt(v)); n += 1
        if n: ss._write_file(raw)
        m = 0
        for r in st._x('SELECT id, totp_secret FROM users WHERE totp_secret IS NOT NULL'):
            st._x('UPDATE users SET totp_secret=? WHERE id=?', (st.fernet.rotate(r[1].encode()).decode(), r[0])); m += 1
        print(f'Re-encrypted {n} storage secret(s) and {m} two-factor secret(s) with the new key. '
              'You can now remove STUDIO_SECRET_KEY_OLD.')
        return
    u = st.user_by_email(a.email)
    if a.cmd == 'create-admin':
        if u: sys.exit('That user already exists (use reset-password).')
        pw = getpass.getpass('Password (10+ characters): ')
        if pw != getpass.getpass('Again: '): sys.exit('The passwords are different.')
        try: st.create_user(a.email, pw, 'admin', 'Admin')
        except A.AuthError as e: sys.exit(str(e))
        print('Admin created.'); return
    if not u: sys.exit('No such user.')
    if a.cmd == 'reset-password':
        pw = secrets.token_urlsafe(12)
        st.set_password(u['id'], pw, must_change=True); st.revoke_all(u['id'])
        print(json.dumps({'email': u['email'], 'temporary_password': pw}))
        print('They must choose a new password at the next sign-in.', file=sys.stderr)
    elif a.cmd == 'unlock':
        st._x('UPDATE users SET failed_count=0, locked_until=0 WHERE id=?', (u['id'],)); print('Unlocked.')
    elif a.cmd == 'disable-2fa':
        st.totp_disable(u['id']); print('Two-factor sign-in turned off.')


if __name__ == '__main__':
    main()
