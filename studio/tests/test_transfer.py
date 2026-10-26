"""Project export / import (.zip) and the couples list."""
import io
import json
import stat
import zipfile

import pytest

from conftest import DATA, PID, png_bytes


def export(c, **q):
    r = c.get(f'/api/p/strip/{PID}/export.zip', params=q)
    assert r.status_code == 200, r.text
    return zipfile.ZipFile(io.BytesIO(r.content))


def make_zip(files: dict, manifest=None, links=()):
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        if manifest is not False:
            z.writestr('kcs_project.json', json.dumps(manifest or dict(format='kawaii-chaos-studio/project', version=1, kind='strip', id='007_evil', name='evil')))
        for n, data in files.items(): z.writestr(n, data)
        for n in links:
            i = zipfile.ZipInfo(n); i.external_attr = (stat.S_IFLNK | 0o777) << 16; z.writestr(i, '/etc/passwd')
    return b.getvalue()


def imp(c, data, name='p.zip'):
    return c.post('/api/import', files={'file': (name, io.BytesIO(data), 'application/zip')})


def test_export_contents(viewer):
    (DATA / 'upload' / f'{PID}_strip.png').write_bytes(png_bytes(20, 25))
    z = export(viewer)
    names = z.namelist()
    man = json.loads(z.read('kcs_project.json'))
    assert man['format'] == 'kawaii-chaos-studio/project' and man['id'] == PID
    assert 'project/synopsis.md' in names and 'project/strip.png' in names and f'upload/{PID}_strip.png' in names
    assert not any('.studio_history' in n for n in names)


def test_roundtrip_import_makes_a_new_project(editor):
    r = editor.get(f'/api/p/strip/{PID}/export.zip'); data = r.content
    before = (DATA / 'projects' / PID / 'synopsis.md').read_text()
    r = imp(editor, data); assert r.status_code == 200, r.text
    new = r.json()['id']
    assert new != PID and new.endswith('_test_strip_2') and r.json()['renamed_from'] == PID
    assert (DATA / 'projects' / new / 'strip.png').read_bytes() == (DATA / 'projects' / PID / 'strip.png').read_bytes()
    assert (DATA / 'upload' / f'{new}_strip.png').exists()
    assert (DATA / 'projects' / PID / 'synopsis.md').read_text() == before            # the original is untouched
    assert editor.get(f'/api/p/strip/{new}').status_code == 200


def test_viewer_cannot_import(viewer, editor):
    assert imp(viewer, editor.get(f'/api/p/strip/{PID}/export.zip').content).status_code == 403


@pytest.mark.parametrize('files,links,manifest,why', [
    ({'project/../../evil.md': 'x'}, (), None, 'bad path'),
    ({'/abs/evil.md': 'x'}, (), None, 'bad path'),
    ({'project/run.sh': '#!/bin/sh'}, (), None, 'no project files'),
    ({'project/strip.png': b'not a png'}, (), None, 'does not look'),
    ({'project/x.md': 'hi'}, ('project/link.md',), None, 'link'),
    ({'project/x.md': 'hi'}, (), False, 'not exported'),
    ({'project/x.md': 'hi'}, (), dict(format='other'), 'not a Studio'),
    ({'other/x.md': 'hi'}, (), None, 'Unexpected'),
    ({'project/lyric_edit.json': json.dumps(dict(lines=[dict(shots=[dict(image='../../etc/passwd')])]))}, (), None, 'Bad'),
    ({'project/x.md': 'hi', 'upload/999_other_strip.png': png_bytes()}, (), None, 'Unexpected'),
])
def test_rejects_bad_zips(editor, files, links, manifest, why):
    before = sorted(p.name for p in (DATA / 'projects').iterdir())
    r = imp(editor, make_zip(files, manifest, links))
    assert r.status_code == 400 and why.lower() in r.text.lower(), r.text
    assert sorted(p.name for p in (DATA / 'projects').iterdir()) == before          # nothing written


def test_zip_bomb_and_not_a_zip(editor):
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('kcs_project.json', json.dumps(dict(format='kawaii-chaos-studio/project', kind='strip', id='007_x', name='x')))
        z.writestr('project/big.txt', '0' * (50 << 20))
    assert 'bomb' in imp(editor, b.getvalue()).text
    assert imp(editor, b'hello').status_code == 400


def test_couples_create_edit_and_parse(editor, viewer):
    r = editor.put('/api/couples', json=dict(couples=[dict(name='Hero x Heroine', tag='#HeroxHeroine', series='My Show', looks='red scarf | blue eyes', dynamic='')]))
    assert r.status_code == 200, r.text
    c = viewer.get('/api/couples').json()
    assert c[0]['name'] == 'Hero × Heroine' and c[0]['short'] == 'Hero x Heroine' and c[0]['tag'] == '#HeroxHeroine' and c[0]['series'] == 'My Show'
    assert '|' not in c[0]['looks']
    assert viewer.put('/api/couples', json=dict(couples=[])).status_code == 403
    assert editor.put('/api/couples', json=dict(couples=[dict(name='')])).status_code == 400
    assert editor.put('/api/couples', json=dict(couples=[dict(name='A x B', tag='not a tag')])).status_code == 400
    assert editor.put('/api/couples', json=dict(couples=[dict(name='A x B'), dict(name='a x b')])).status_code == 400
    assert editor.put('/api/couples', json=dict(couples=[])).json() == []


def test_unknown_files_are_skipped_drawing_files_kept(editor):
    r = imp(editor, make_zip({'project/synopsis.md': '# x\n', 'project/run.sh': '#!/bin/sh', 'project/logo.svg': '<svg/>', 'project/art/page1.kra': b'PK..'}))
    assert r.status_code == 200, r.text
    new = r.json()['id']
    assert sorted(r.json()['skipped']) == ['project/logo.svg', 'project/run.sh']
    assert (DATA / 'projects' / new / 'art' / 'page1.kra').exists() and not (DATA / 'projects' / new / 'run.sh').exists()
