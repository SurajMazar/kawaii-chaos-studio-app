"""Test fixtures: a throw-away data folder (local backend), config dir and cache — never the real repo content."""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(STUDIO))

_TMP = Path(tempfile.mkdtemp(prefix='kcs_test_'))
DATA = _TMP / 'data'
os.environ.update({
    'STUDIO_ENV': 'development', 'STUDIO_CONFIG_DIR': str(_TMP / 'config'), 'STUDIO_CACHE_DIR': str(_TMP / 'cache'),
    'STUDIO_DATA_DIR': str(DATA), 'STUDIO_WORKDIR': str(_TMP / 'work'), 'STUDIO_NO_AUTOAPP': '1',
    'STUDIO_SECRET_KEY': 'test-secret-key-for-unit-tests-only', 'STUDIO_LOG_LEVEL': 'WARNING',
    'STUDIO_JOB_STARTS_PER_MINUTE': '1000', 'STUDIO_MAX_JOBS_PER_USER': '50', 'STUDIO_ALLOWED_HOSTS': 'localhost,127.0.0.1,testserver',
})
for k in ('STORAGE_BACKEND', 'S3_BUCKET', 'S3_ENDPOINT', 'S3_ACCESS_KEY_ID', 'S3_SECRET_ACCESS_KEY', 'STUDIO_ADMIN_EMAIL', 'STUDIO_ADMIN_PASSWORD'):
    os.environ.pop(k, None)

PID = '001_test_strip'
MVID = '01_test_mv'


def png_bytes(w=64, h=80, color=(240, 200, 210)):
    from PIL import Image
    b = io.BytesIO(); Image.new('RGB', (w, h), color).save(b, 'PNG'); return b.getvalue()


def make_data(root: Path):
    p = root / 'projects' / PID; (p / 'raw').mkdir(parents=True); (p / 'layout').mkdir()
    (p / 'synopsis.md').write_text('# test_strip — "Testing" (Subaru x Rem)\n\n1. one\n2. two\n\n**Caption:**\n\nhi\n')
    (p / 'strip.png').write_bytes(png_bytes(300, 375))
    (p / 'raw' / 'draft1.png').write_bytes(png_bytes(30, 30))
    (p / 'qa.md').write_text('# QA\n')
    m = root / 'music_videos' / MVID; (m / 'edit_frames').mkdir(parents=True)
    (m / 'synopsis.md').write_text('# test mv\n')
    (m / 'frame1.png').write_bytes(png_bytes(108, 192))
    (m / 'lyric_edit.json').write_text(json.dumps(dict(output='lyric_edit.mp4', size=[1080, 1920], fps=30, start=0.0, lines=[
        dict(start=0.0, end=2.0, text='*HELLO* / there', style='block', y=0.15, shots=[dict(image='frame1.png')])]), indent=1))
    (root / 'upload').mkdir(); (root / 'references').mkdir(); (root / 'fonts').mkdir()
    (root / 'references' / 'style_ref.png').write_bytes(png_bytes(200, 120))
    (root / 'captions.json').write_text('{}\n'); (root / 'posting_log.json').write_text(json.dumps({'account': {}, 'posts': []}, indent=1) + '\n')
    (root / 'qa_rules.md').write_text('**A. Story.** clear\n**B. Faces.** fine\n')
    for n in ('songs.md', 'couples.md', 'style.md', 'README.md'): (root / n).write_text('# x\n')
    # something secret OUTSIDE the data root, to prove traversal never reaches it
    (root.parent / 'outside_secret.txt').write_text('TOP SECRET')


make_data(DATA)

import server  # noqa: E402

APP = server.create_app()


@pytest.fixture(scope='session')
def app():
    return APP


class Client:
    """TestClient wrapper that keeps cookies and sends the CSRF header like the web app does."""
    def __init__(self, app):
        from fastapi.testclient import TestClient
        self.c = TestClient(app, base_url='http://testserver')
        self.csrf = self.c.get('/api/auth/state').json()['csrf']

    def _h(self, kw):
        h = dict(kw.pop('headers', {}) or {})
        if 'x-csrf-token' not in {k.lower() for k in h}: h['x-csrf-token'] = self.csrf
        return h

    def get(self, url, **kw): return self.c.get(url, **kw)
    def post(self, url, **kw): return self.c.post(url, headers=self._h(kw), **kw)
    def put(self, url, **kw): return self.c.put(url, headers=self._h(kw), **kw)
    def patch(self, url, **kw): return self.c.patch(url, headers=self._h(kw), **kw)
    def delete(self, url, **kw): return self.c.request('DELETE', url, headers=self._h(kw), **kw)

    def login(self, email, password):
        r = self.post('/api/auth/login', json=dict(email=email, password=password))
        assert r.status_code == 200, r.text
        self.csrf = r.json()['csrf']
        return r


ADMIN = ('admin@example.com', 'Admin-Password-123')
EDITOR = ('editor@example.com', 'Editor-Password-123')
VIEWER = ('viewer@example.com', 'Viewer-Password-123')


@pytest.fixture(scope='session')
def users(app):
    from security import auth as A
    st = A.store()
    if not st.count_users():
        c = Client(app)
        r = c.post('/api/auth/setup', json=dict(email=ADMIN[0], password=ADMIN[1], name='Admin'))
        assert r.status_code == 200, r.text
        st.create_user(EDITOR[0], EDITOR[1], 'editor', 'Ed')
        st.create_user(VIEWER[0], VIEWER[1], 'viewer', 'Vi')
    return dict(admin=ADMIN, editor=EDITOR, viewer=VIEWER)


@pytest.fixture
def anon(app):
    return Client(app)


@pytest.fixture
def admin(app, users):
    c = Client(app); c.login(*ADMIN); return c


@pytest.fixture
def editor(app, users):
    c = Client(app); c.login(*EDITOR); return c


@pytest.fixture
def viewer(app, users):
    c = Client(app); c.login(*VIEWER); return c
