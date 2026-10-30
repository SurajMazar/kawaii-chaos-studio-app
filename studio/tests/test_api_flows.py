"""Real API flows on the throw-away data folder (local backend) and on an S3 backend (moto)."""
import json
import time

import pytest

from conftest import DATA, MVID, PID, png_bytes


def wait_job(c, jid, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = c.get(f'/api/jobs/{jid}').json()
        if j['state'] not in ('queued', 'running'): return j
        time.sleep(0.3)
    raise AssertionError('job timed out')


def test_text_save_keeps_history(editor):
    url = f'/api/p/strip/{PID}/text?name=synopsis.md'
    before = editor.get(url).json()['text']
    assert editor.put(url, json={'text': before + 'more\n'}).status_code == 200
    assert editor.get(url).json()['text'].endswith('more\n')
    hist = list((DATA / 'projects' / PID / '.studio_history').glob('synopsis_*.md'))
    assert hist and any(h.read_text() == before for h in hist)


def test_new_project_and_layout(editor):
    r = editor.post('/api/new', json=dict(kind='strip', name='flow_test', couple='Subaru x Rem', tag='', premise='p', panels=3, seed=7,
                                          layout=True, mood='', lines='', start=0))
    assert r.status_code == 200, r.text
    pid = r.json()['id']
    assert pid.startswith('002_') and (DATA / 'projects' / pid / 'layout' / 'layout.png').exists()
    assert editor.post('/api/new', json=dict(kind='strip', name='flow_test', couple='', tag='', premise='', panels=3, seed=None,
                                             layout=False, mood='', lines='', start=0)).status_code == 409


def test_lyric_preview_render_job(editor):
    edit = editor.get(f'/api/lyric/{MVID}/edit?file=lyric_edit.json').json()
    edit['size'] = [216, 384]
    r = editor.post(f'/api/lyric/{MVID}/render', json=dict(edit=edit, file='lyric_edit.json', quality='preview', bake_audio=False))
    assert r.status_code == 200, r.text
    j = wait_job(editor, r.json()['id'])
    assert j['state'] == 'done', j
    assert (DATA / 'music_videos' / MVID / 'lyric_edit_preview.mp4').stat().st_size > 1000


def test_job_cancel_only_owner_or_admin(app, editor, viewer, admin):
    edit = editor.get(f'/api/lyric/{MVID}/edit?file=lyric_edit.json').json()
    edit['size'] = [216, 384]
    jid = editor.post(f'/api/lyric/{MVID}/render', json=dict(edit=edit, file='lyric_edit.json', quality='preview', bake_audio=False)).json()['id']
    assert viewer.post(f'/api/jobs/{jid}/cancel').status_code == 403
    assert admin.post(f'/api/jobs/{jid}/cancel').status_code == 200
    wait_job(editor, jid)


def test_qa_pass_and_caption(editor):
    qa = editor.get(f'/api/p/strip/{PID}/qa').json()
    checks = {c['key']: True for c in qa['checklist']}
    r = editor.post(f'/api/p/strip/{PID}/qa/pass', json=dict(file='strip.png', checks=checks, notes={}, stranger='ok'))
    assert r.status_code == 200, r.text
    assert f"PASS {r.json()['sha']} strip.png" in (DATA / 'projects' / PID / 'qa.md').read_text()
    assert editor.put(f'/api/p/strip/{PID}/caption', json=dict(caption='Cute!', pinned='')).status_code == 200
    assert json.loads((DATA / 'captions.json').read_text())[PID] == 'Cute!'


def test_upload_and_file_download(editor):
    r = editor.post(f'/api/p/strip/{PID}/upload', files={'file': ('my pic.png', png_bytes(), 'image/png')}, data={'dest': 'raw'})
    assert r.status_code == 200 and r.json()['path'] == 'raw/my_pic.png'
    f = editor.get(f"/api/p/strip/{PID}/file/raw/my_pic.png?download=1")
    assert f.status_code == 200 and f.content == png_bytes() and 'attachment' in f.headers['content-disposition']



def test_share_uses_the_mac_app_hook(viewer, monkeypatch):
    from api import native
    assert viewer.post(f'/api/p/strip/{PID}/share', json={'rel': 'strip.png'}).status_code == 404   # servers: no share menu
    got = []
    monkeypatch.setattr(native, 'share', lambda p, rect: got.append((p, rect)))
    r = viewer.post(f'/api/p/strip/{PID}/share', json={'rel': 'strip.png', 'rect': [10, 20, 30, 40]})
    assert r.status_code == 200 and [(p.resolve(), rect) for p, rect in got] == [((DATA / 'projects' / PID / 'strip.png').resolve(), (10, 20, 30, 40))]
    assert viewer.post(f'/api/p/strip/{PID}/share', json={'rel': '../../outside_secret.txt'}).status_code in (400, 404)
    assert viewer.post(f'/api/p/strip/{PID}/share', json={'rel': 'nope.png'}).status_code == 404 and len(got) == 1

# ---------------- the same app on an S3 bucket (moto) ----------------
@pytest.fixture
def s3_ws(monkeypatch, tmp_path):
    moto = pytest.importorskip('moto')
    for k in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY'): monkeypatch.setenv(k, 'testing')
    with moto.mock_aws():
        import boto3
        from storage import Workspace, get_ws, set_workspace
        from storage.local import LocalStorage
        from storage.s3 import S3Storage
        from api.integrations import _copy_one, content_entries
        boto3.client('s3', region_name='us-east-1').create_bucket(Bucket='kcs-app')
        s3 = S3Storage(bucket='kcs-app', region='us-east-1', access_key_id='testing', secret_access_key='testing')
        src = LocalStorage(DATA)
        for k in content_entries(src): _copy_one(src, s3, k)
        old = get_ws()
        from config import CODE_ROOT
        set_workspace(Workspace(s3, workdir=tmp_path / 'work', start_refresher=False, code_root=CODE_ROOT))
        from api.library import invalidate; invalidate()
        yield s3
        set_workspace(old); invalidate()


def test_app_on_s3(s3_ws, editor):
    s3 = s3_ws
    lib = editor.get('/api/library').json()
    assert any(i['id'] == PID for i in lib['items'])
    assert editor.get(f'/api/p/strip/{PID}/thumb/strip.png?w=120').status_code == 200
    # write-through
    url = f'/api/p/strip/{PID}/text?name=synopsis.md'
    t = editor.get(url).json()['text']
    assert editor.put(url, json={'text': t + 's3 edit\n'}).status_code == 200
    assert s3.read_bytes(f'projects/{PID}/synopsis.md').decode().endswith('s3 edit\n')
    assert any('.studio_history/synopsis_' in e.key for e in s3.list(f'projects/{PID}'))
    # upload lands in the bucket
    r = editor.post(f'/api/p/strip/{PID}/upload', files={'file': ('s3pic.png', png_bytes(), 'image/png')}, data={'dest': 'raw'})
    assert r.status_code == 200 and s3.stat(f'projects/{PID}/raw/s3pic.png')
    # a job: lyric preview render -> output pushed to the bucket
    edit = editor.get(f'/api/lyric/{MVID}/edit?file=lyric_edit.json').json(); edit['size'] = [216, 384]
    j = wait_job(editor, editor.post(f'/api/lyric/{MVID}/render', json=dict(edit=edit, file='lyric_edit.json', quality='preview', bake_audio=False)).json()['id'])
    assert j['state'] == 'done', j
    assert s3.stat(f'music_videos/{MVID}/lyric_edit_preview.mp4').size > 1000
    # subprocess job: layout script runs in the work cache, output pushed
    r = editor.post(f'/api/p/strip/{PID}/layout', json=dict(panels=2, seed=3, punch=True))
    assert r.status_code == 200, r.text
    assert s3.stat(f'projects/{PID}/layout/layout.png')
    # new project numbering from the bucket listing
    r = editor.post('/api/new', json=dict(kind='mv', name='s3_mv', couple='', tag='', premise='', panels=4, seed=None, layout=False, mood='', lines='', start=0))
    assert r.status_code == 200 and s3.stat(f"music_videos/{r.json()['id']}/synopsis.md")
