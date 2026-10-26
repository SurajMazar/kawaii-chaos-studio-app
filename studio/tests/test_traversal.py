"""Path traversal, symlink escapes, absolute paths, NUL bytes, render-document paths, uploads."""
import os

import pytest

from conftest import DATA, MVID, PID, png_bytes

EVIL = ['../../outside_secret.txt', '..%2f..%2foutside_secret.txt', '%2e%2e/%2e%2e/outside_secret.txt', '/etc/passwd',
        '..\\..\\outside_secret.txt', 'raw/../../../outside_secret.txt', 'synopsis.md%00.png', '....//....//outside_secret.txt',
        '%252e%252e/%252e%252e/outside_secret.txt', 'raw/%2e%2e/%2e%2e/%2e%2e/outside_secret.txt']


@pytest.mark.parametrize('rel', EVIL)
def test_file_endpoints_reject_traversal(editor, rel):
    for url in (f'/api/p/strip/{PID}/file/{rel}', f'/api/p/strip/{PID}/thumb/{rel}', f'/api/root/upload/{rel}', f'/api/rthumb/upload/{rel}',
                f'/api/p/strip/{PID}/files?dir={rel}'):
        r = editor.get(url)
        assert r.status_code in (400, 404), (url, r.status_code)
        assert b'TOP SECRET' not in r.content


def test_bad_project_ids(editor):
    for pid in ('..', '../projects', '001_test_strip/../..', 'x' * 300, '001_te%00st'):
        r = editor.get(f'/api/p/strip/{pid}')
        assert r.status_code in (400, 404, 422)


def test_symlink_escape_is_blocked(editor):
    link = DATA / 'projects' / PID / 'escape.txt'
    if not link.exists(): os.symlink(DATA.parent / 'outside_secret.txt', link)
    try:
        r = editor.get(f'/api/p/strip/{PID}/file/escape.txt')
        assert r.status_code in (400, 404) and b'TOP SECRET' not in r.content
        listing = editor.get(f'/api/p/strip/{PID}/files?dir=').json()
        assert all(e['name'] != 'escape.txt' for e in listing['entries'])
    finally:
        link.unlink()


def test_text_names_are_allowlisted(editor):
    assert editor.put(f'/api/p/strip/{PID}/text?name=../../evil.md', json={'text': 'x'}).status_code == 400
    assert editor.put(f'/api/p/strip/{PID}/text?name=/tmp/evil.md', json={'text': 'x'}).status_code == 400


def test_set_role_and_reject_paths(editor):
    assert editor.post(f'/api/p/strip/{PID}/set-role', json=dict(src='../../outside_secret.txt', role='strip')).status_code == 400
    assert editor.post(f'/api/p/strip/{PID}/reject', json=dict(src='../../../captions.json', reason='x')).status_code == 400


def test_lyric_edit_paths_validated(editor):
    base = editor.get(f'/api/lyric/{MVID}/edit?file=lyric_edit.json').json()
    for bad in ({'output': '../../evil.mp4'}, {'audio': '/etc/passwd'}, {'fonts': {'heavy': '/etc/passwd'}},
                {'lines': [dict(start=0, end=1, text='x', shots=[dict(image='../../../outside_secret.txt')])]},
                {'lines': [dict(start=0, end=1, text='x', shots=[dict(image='http://169.254.169.254/latest')])]},
                {'size': [100000, 100000]}):
        e = dict(base, **bad)
        r = editor.put(f'/api/lyric/{MVID}/edit?file=lyric_edit.json', json=e)
        assert r.status_code == 400, (bad, r.text)
        r = editor.post(f'/api/lyric/{MVID}/render', json=dict(edit=e, file='lyric_edit.json', quality='final', bake_audio=False))
        assert r.status_code == 400, (bad, r.text)
    assert editor.put(f'/api/lyric/{MVID}/edit?file=../x.json', json=base).status_code == 400


def test_storyboard_paths_validated(editor):
    sb = {'output': {'file': '/tmp/pwn.mp4', 'width': 1080, 'height': 1920}, 'shots': [{'id': 's1', 'image': 'panel1.png', 'start': 0, 'end': 2}]}
    r = editor.put(f'/api/reel/{PID}/storyboard', json={'storyboard': sb})
    assert r.status_code == 400
    sb['output']['file'] = 'strip_reel.mp4'; sb['shots'][0]['image'] = '../../../outside_secret.txt'
    assert editor.put(f'/api/reel/{PID}/storyboard', json={'storyboard': sb}).status_code == 400


def test_upload_type_validation(editor):
    files = {'file': ('evil.png', b'<?php system($_GET[1]); ?>', 'image/png')}
    assert editor.post(f'/api/p/strip/{PID}/upload', files=files, data={'dest': 'raw'}).status_code == 400
    files = {'file': ('evil.html', b'<script>alert(1)</script>', 'text/html')}
    assert editor.post(f'/api/p/strip/{PID}/upload', files=files, data={'dest': 'raw'}).status_code == 400
    files = {'file': ('../../../escape.png', png_bytes(), 'image/png')}
    r = editor.post(f'/api/p/strip/{PID}/upload', files=files, data={'dest': 'raw'})
    assert r.status_code == 200 and r.json()['path'] == 'raw/escape.png'
    assert editor.post(f'/api/p/strip/{PID}/upload', files={'file': ('a.png', png_bytes(), 'image/png')}, data={'dest': '../..'}).status_code == 400


def test_decompression_bomb_rejected(editor):
    import io
    from PIL import Image
    big = Image.new('1', (12000, 12000))                 # 144 Mpx, tiny file
    b = io.BytesIO(); big.save(b, 'PNG')
    r = editor.post(f'/api/p/strip/{PID}/upload', files={'file': ('bomb.png', b.getvalue(), 'image/png')}, data={'dest': 'raw'})
    assert r.status_code == 400


def test_font_upload_validation(editor):
    assert editor.post('/api/fonts', files={'file': ('x.ttf', b'not a font at all', 'font/ttf')}).status_code == 400
    assert editor.get('/api/fonts/sample?path=../../outside_secret.txt').status_code == 404


def test_tool_args_validated(admin):
    assert admin.post('/api/tools/make_pdf/run', json={'args': {'out': '../../evil.pdf'}}).status_code == 400
    assert admin.post('/api/tools/style_check/run', json={'args': {'image': '/etc/passwd'}}).status_code == 400
    assert admin.post('/api/tools/upload_encode/run', json={'args': {'projects': '--help; rm -rf /'}}).status_code == 400


def test_settings_validation(admin):
    assert admin.put('/api/settings', json={'chatgpt_url': 'javascript:alert(1)'}).status_code == 400
    assert admin.put('/api/settings', json={'python': '/bin/sh'}).status_code == 400
    assert admin.put('/api/settings', json={'style_ref': '../../x.png'}).status_code == 400
