"""Storage drivers + workspace: local semantics, S3 driver (moto), remote workspace sync, settings encryption, SSRF."""
import json
import time
from pathlib import Path

import pytest

from storage.base import BadKey, norm_key
from storage.local import LocalStorage
from storage.workspace import Workspace, pattern_re


# ---------------- keys ----------------
@pytest.mark.parametrize('k', ['../x', 'a/../../b', '/etc/passwd', 'a\\b', 'a\x00b', 'a//b', './a', 'C:/x', 'a/./b', '', 'a/\n'])
def test_bad_keys(k):
    with pytest.raises(BadKey): norm_key(k)


def test_good_keys():
    assert norm_key('projects/001_x/strip.png') == 'projects/001_x/strip.png'
    assert norm_key('projects/x/') == 'projects/x'


def test_patterns():
    assert pattern_re('projects/*/strip.png').match('projects/001_a/strip.png')
    assert not pattern_re('projects/*/strip.png').match('projects/001_a/raw/strip.png')
    assert pattern_re('projects/001_a/**').match('projects/001_a/raw/x/y.png')


# ---------------- local workspace keeps the old semantics ----------------
def test_local_write_history(tmp_path):
    (tmp_path / 'projects' / '001_a').mkdir(parents=True)
    ws = Workspace(LocalStorage(tmp_path))
    k = 'projects/001_a/synopsis.md'
    ws.write(k, 'v1\n'); ws.write(k, 'v2\n')
    assert (tmp_path / k).read_text() == 'v2\n'
    hist = list((tmp_path / 'projects/001_a/.studio_history').iterdir())
    assert len(hist) == 1 and hist[0].read_text() == 'v1\n' and hist[0].name.startswith('synopsis_2')
    for i in range(60): ws.write(k, f'v{i}\n')
    assert len(list((tmp_path / 'projects/001_a/.studio_history').iterdir())) == 50
    assert oct((tmp_path / k).stat().st_mode & 0o777) == '0o644'


def test_local_refuses_non_content(tmp_path):
    ws = Workspace(LocalStorage(tmp_path))
    with pytest.raises(BadKey): ws.write('studio/.config/storage.json', b'x')
    with pytest.raises(BadKey): ws.write('.git/config', b'x')


# ---------------- S3 driver (moto) ----------------
@pytest.fixture
def s3(monkeypatch):
    moto = pytest.importorskip('moto')
    for k in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY'): monkeypatch.setenv(k, 'testing')
    monkeypatch.setenv('AWS_DEFAULT_REGION', 'us-east-1')
    with moto.mock_aws():
        import boto3
        boto3.client('s3', region_name='us-east-1').create_bucket(Bucket='kcs-test')
        from storage.s3 import S3Storage
        yield S3Storage(bucket='kcs-test', prefix='studio', region='us-east-1', access_key_id='testing', secret_access_key='testing')


def test_s3_driver_basics(s3):
    e = s3.write_bytes('projects/001_a/synopsis.md', b'hello')
    assert e.etag and e.size == 5
    assert s3.read_bytes('projects/001_a/synopsis.md') == b'hello'
    assert s3.stat('projects/001_a/synopsis.md').size == 5
    assert s3.stat('nope/x') is None
    s3.copy('projects/001_a/synopsis.md', 'projects/001_a/copy.md')
    keys = sorted(x.key for x in s3.list('projects'))
    assert keys == ['projects/001_a/copy.md', 'projects/001_a/synopsis.md']
    top = list(s3.list('', recursive=False))
    assert any(x.is_dir and x.key == 'projects' for x in top)
    chunks, ent = s3.open_range('projects/001_a/synopsis.md', 1, 3)
    assert b''.join(chunks) == b'ell' and ent.size == 5
    url = s3.presigned_url('projects/001_a/synopsis.md', 60, 'syn.md')
    assert 'X-Amz-Signature' in url and 'studio/projects' in url
    s3.delete('projects/001_a/copy.md'); assert s3.stat('projects/001_a/copy.md') is None
    assert s3.probe()['ok']
    with pytest.raises(BadKey): s3.read_bytes('../x')


def test_s3_prefix_isolation(s3):
    s3.client.put_object(Bucket='kcs-test', Key='other/secret.txt', Body=b'x')
    assert all(not e.key.startswith('other') for e in s3.list(''))


def test_remote_workspace_sync(s3, tmp_path):
    s3.write_bytes('projects/001_a/strip.png', b'PNGDATA')
    s3.write_bytes('projects/001_a/qa.md', b'# QA\n')
    s3.write_bytes('captions.json', b'{}\n')
    ws = Workspace(s3, workdir=tmp_path / 'work', start_refresher=False)
    assert ws.remote and ws.exists('projects/001_a/strip.png') and ws.is_dir('projects/001_a')
    assert {e.name for e in ws.listdir('projects/001_a')} == {'strip.png', 'qa.md'}
    p = ws.local('projects/001_a/strip.png'); assert p.read_bytes() == b'PNGDATA'
    # write-through + history object in the bucket
    ws.write('projects/001_a/qa.md', b'# QA v2\n')
    assert s3.read_bytes('projects/001_a/qa.md') == b'# QA v2\n'
    hist = [e.key for e in s3.list('projects/001_a/.studio_history')]
    assert len(hist) == 1 and s3.read_bytes(hist[0]) == b'# QA\n'
    assert (tmp_path / 'work/projects/001_a/qa.md').read_bytes() == b'# QA v2\n'
    # sha1 cached per etag
    import hashlib
    assert ws.sha1('projects/001_a/strip.png') == hashlib.sha1(b'PNGDATA').hexdigest()
    # a job: pull, create + change + delete files, push
    with ws.job_sync(pull=['projects/001_a/**'], push=['projects/001_a/**', 'upload/001_a_strip.png'], scope='projects/001_a') as root:
        (root / 'projects/001_a/strip_reel').mkdir()
        (root / 'projects/001_a/strip_reel/panel1.png').write_bytes(b'P1')
        (root / 'upload').mkdir(exist_ok=True); (root / 'upload/001_a_strip.png').write_bytes(b'UP')
        time.sleep(0.01); (root / 'projects/001_a/qa.md').write_bytes(b'# QA by job\n')
        (root / 'projects/001_a/strip.png').unlink()
    assert s3.read_bytes('projects/001_a/strip_reel/panel1.png') == b'P1'
    assert s3.read_bytes('upload/001_a_strip.png') == b'UP'
    assert s3.read_bytes('projects/001_a/qa.md') == b'# QA by job\n'
    assert s3.stat('projects/001_a/strip.png') is None
    # remote change -> pulled again
    s3.write_bytes('projects/001_a/qa.md', b'# changed elsewhere\n'); ws.refresh_index()
    ws.pull(['projects/001_a/*'])
    assert (tmp_path / 'work/projects/001_a/qa.md').read_bytes() == b'# changed elsewhere\n'
    # remote delete -> local copy removed on pull; unknown local files left alone
    (tmp_path / 'work/projects/001_a/untracked.tmpfile').write_bytes(b'x')
    s3.delete('projects/001_a/qa.md'); ws.refresh_index(); ws.pull(['projects/001_a/*'])
    assert not (tmp_path / 'work/projects/001_a/qa.md').exists()
    assert (tmp_path / 'work/projects/001_a/untracked.tmpfile').exists()


def test_remote_response_range(s3, tmp_path):
    from storage import workspace as W
    data = bytes(range(256)) * 100
    s3.write_bytes('upload/big.mp4', data)
    ws = Workspace(s3, workdir=tmp_path / 'w', start_refresher=False)
    old = W.INLINE_MAX; W.INLINE_MAX = 10
    try:
        class Req:
            headers = {'range': 'bytes=100-199'}
        r = ws.response('upload/big.mp4', Req())
        assert r.status_code == 206 and r.headers['content-range'] == f'bytes 100-199/{len(data)}'
    finally:
        W.INLINE_MAX = old


# ---------------- settings: secrets encrypted, never shown, env overrides ----------------
def test_storage_settings_secrets(tmp_path, monkeypatch):
    from storage.settings import StorageSettings
    from storage.base import StorageError
    for k in ('STORAGE_BACKEND', 'S3_BUCKET', 'S3_SECRET_ACCESS_KEY', 'S3_ENDPOINT', 'STUDIO_DATA_DIR'): monkeypatch.delenv(k, raising=False)
    st = StorageSettings(tmp_path, secret_key='k1')
    cfg = dict(backend='r2', account_id='a' * 32, bucket='kcs', access_key_id='AKIAEXAMPLE1234', secret_access_key='SUPERSECRET')
    st.save(cfg)
    raw = (tmp_path / 'storage.json').read_text()
    assert 'SUPERSECRET' not in raw and 'secret_access_key_enc' in raw
    assert oct((tmp_path / 'storage.json').stat().st_mode & 0o777) == '0o600'
    pub = st.public_view()
    assert pub['secret_access_key'] == {'set': True} and 'SUPERSECRET' not in json.dumps(pub)
    assert st.effective()['secret_access_key'] == 'SUPERSECRET'
    # blank secret keeps the stored one
    st.save(dict(cfg, secret_access_key='')); assert st.effective()['secret_access_key'] == 'SUPERSECRET'
    # without the key: refuse to store secrets
    with pytest.raises(StorageError): StorageSettings(tmp_path / 'b', secret_key='').save(cfg)
    # wrong key cannot decrypt
    with pytest.raises(StorageError): StorageSettings(tmp_path, secret_key='other').effective()
    # rotation: old key still decrypts
    assert StorageSettings(tmp_path, secret_key='k2', old_keys='k1').effective()['secret_access_key'] == 'SUPERSECRET'
    # env overrides + locked
    monkeypatch.setenv('S3_BUCKET', 'from-env')
    assert st.effective()['bucket'] == 'from-env' and 'bucket' in st.public_view()['locked']


@pytest.mark.parametrize('url,ok', [
    ('https://abc.r2.cloudflarestorage.com', True), ('https://s3.us-east-1.amazonaws.com', True),
    ('http://s3.amazonaws.com', False), ('https://169.254.169.254', False), ('https://[fe80::1]', False),
    ('https://127.0.0.1:9000', False), ('https://10.0.0.5', False), ('ftp://x.com', False), ('file:///etc/passwd', False),
    ('https://user:pw@s3.amazonaws.com', False), ('https://s3.amazonaws.com/path?x=1', False), ('https://100.100.100.200', False)])
def test_ssrf_endpoint_validation(url, ok):
    from storage.s3 import validate_endpoint
    from storage.base import StorageError
    if ok:
        assert validate_endpoint(url, resolve=False)
    else:
        with pytest.raises(StorageError): validate_endpoint(url, resolve=True)


def test_insecure_flag_allows_local_minio_but_never_metadata():
    from storage.s3 import validate_endpoint
    from storage.base import StorageError
    assert validate_endpoint('http://127.0.0.1:9000', allow_insecure=True)
    with pytest.raises(StorageError): validate_endpoint('http://169.254.169.254', allow_insecure=True)


def test_migrate_local_to_s3(s3, tmp_path):
    from api.integrations import _copy_one, _same, content_entries
    (tmp_path / 'projects/001_a').mkdir(parents=True)
    (tmp_path / 'projects/001_a/strip.png').write_bytes(b'abc'); (tmp_path / 'captions.json').write_text('{}')
    (tmp_path / 'studio').mkdir(); (tmp_path / 'studio/secret.txt').write_text('no')
    src = LocalStorage(tmp_path)
    ents = content_entries(src)
    assert set(ents) == {'projects/001_a/strip.png', 'captions.json'}          # code / config never migrated
    for k in ents: _copy_one(src, s3, k)
    dst = content_entries(s3)
    assert all(_same(src, s3, ents[k], dst.get(k)) for k in ents)
    assert Path(tmp_path / 'projects/001_a/strip.png').exists()                # source untouched
