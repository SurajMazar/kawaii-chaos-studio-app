"""Voiced strip reels: voiceover.json validation, clip upload, ElevenLabs (mocked — never the real API), mix job, key safety."""
import io
import json
import subprocess
import urllib.error

import pytest

from conftest import DATA, PID
from test_api_flows import wait_job

URL = f'/api/p/strip/{PID}/voiceover'


def audio_bytes(sec=0.6, fmt='wav', freq=440):
    return subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'sine=frequency={freq}:duration={sec}', '-f', fmt, '-'],
                          capture_output=True, check=True).stdout


@pytest.fixture(scope='module', autouse=True)
def silent_reel():
    up = DATA / 'upload' / f'{PID}_strip_reel.mp4'
    if not up.exists():
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=pink:s=108x192:d=3:r=30', '-pix_fmt', 'yuv420p', str(up)], check=True)
    yield


def cfg(**kw):
    c = dict(video=f'upload/{PID}_strip_reel.mp4', lines=[dict(id='l1', character='Stark', text='Take my scarf.', at=0.4, clip='')],
             music=dict(file='', gain_db=-10), loudness=-16, model='eleven_v3')
    c.update(kw); return c


def test_defaults_and_save(editor, viewer):
    r = viewer.get(URL); assert r.status_code == 200, r.text
    assert r.json()['config']['output'] == f'upload/{PID}_strip_reel_voiceover.mp4' and r.json()['video']['duration'] == pytest.approx(3, abs=0.1)
    assert viewer.put(URL, json=dict(config=cfg())).status_code == 403
    r = editor.put(URL, json=dict(config=cfg())); assert r.status_code == 200, r.text
    assert json.loads((DATA / 'projects' / PID / 'voiceover' / 'voiceover.json').read_text())['lines'][0]['character'] == 'Stark'


@pytest.mark.parametrize('bad', [
    dict(video='../outside_secret.txt'), dict(video='projects/other/x.mp4'), dict(output='projects/001_test_strip/x.mp4'),
    dict(output=f'upload/{PID}_strip_reel.mp4'), dict(lines=[dict(clip='../../x.wav')]), dict(lines=[dict(clip='a/b.wav')]),
    dict(lines=[dict(clip='x.sh')]), dict(music=dict(file='/etc/passwd')), dict(lines=[dict(at=9999)]),
    dict(lines=[dict(text='x' * 1001)]), dict(lines=[dict(voice_id='bad id!')]),
])
def test_rejects_bad_config(editor, bad):
    assert editor.put(URL, json=dict(config=cfg(**bad))).status_code == 400


def test_upload_clip_and_mix_job(editor):
    r = editor.post(f'{URL}/clip', files={'file': ('stark1.wav', io.BytesIO(audio_bytes()), 'audio/wav')}); assert r.status_code == 200, r.text
    name = r.json()['name']; assert r.json()['duration'] == pytest.approx(0.6, abs=0.05)
    assert editor.post(f'{URL}/clip', files={'file': ('evil.wav', io.BytesIO(b'#!/bin/sh\necho hi'), 'audio/wav')}).status_code == 400
    r = editor.post(f'{URL}/clip', files={'file': ('bed.mp3', io.BytesIO(audio_bytes(4, 'mp3', 220)), 'audio/mpeg')}); assert r.status_code == 200
    c = cfg(lines=[dict(id='l1', character='Stark', text='Take my scarf.', at=0.4, clip=name)], music=dict(file=r.json()['name'], gain_db=-10))
    r = editor.post(f'{URL}/mix', json=dict(config=c)); assert r.status_code == 200, r.text
    j = wait_job(editor, r.json()['id']); assert j['state'] == 'done', j
    out = DATA / 'upload' / f'{PID}_strip_reel_voiceover.mp4'
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', str(out)], capture_output=True, text=True).stdout
    assert 'video' in probe and 'audio' in probe
    assert editor.get('/api/library').json() and editor.get(f'/api/p/strip/{PID}').json()['status']['voiceover'] is True


def test_mix_refuses_missing_clip(editor):
    r = editor.post(f'{URL}/mix', json=dict(config=cfg(lines=[dict(id='l1', at=0, clip='nope.wav')])))
    assert r.status_code == 409 and 'nope.wav' in r.text


def test_generate_without_key_and_with_mock(editor, monkeypatch):
    from api import voiceover as V
    body = dict(text='Take my scarf.', voice_id='abcdefgh1234', character='Stark', model='eleven_v3')
    monkeypatch.delenv('ELEVENLABS_API_KEY', raising=False)
    assert editor.post(f'{URL}/generate', json=body).status_code == 409          # not connected
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'k' * 32)
    seen = {}

    def fake(method, path, body=None, query=None, audio=False, key=None, timeout=90):
        seen.update(method=method, path=path, body=body); return audio_bytes(0.5, 'mp3')
    monkeypatch.setattr(V, 'el', fake)
    r = editor.post(f'{URL}/generate', json=dict(body, stability=0.4)); assert r.status_code == 200, r.text
    assert r.json()['name'].startswith('stark_') and seen['path'] == '/v1/text-to-speech/abcdefgh1234'
    assert seen['body']['voice_settings']['stability'] == 0.5                       # v3 snaps to Natural
    assert editor.post(f'{URL}/generate', json=dict(body, voice_id='../../v1/user')).status_code == 400
    assert editor.post(f'{URL}/generate', json=dict(body, model='gpt')).status_code == 400


def test_elevenlabs_401_is_not_a_studio_401(editor, monkeypatch):
    from api import voiceover as V
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'k' * 32)

    def boom(*a, **k): raise urllib.error.HTTPError('https://api.elevenlabs.io', 401, 'no', {}, io.BytesIO(b'{"detail":{"message":"invalid_api_key"}}'))
    monkeypatch.setattr(V.urllib.request, 'urlopen', boom)
    r = editor.post(f'{URL}/generate', json=dict(text='hi', voice_id='abcdefgh1234', character='x', model='eleven_v3'))
    assert r.status_code == 400 and 'refused' in r.text and 'k' * 32 not in r.text


def test_key_admin_only_encrypted_never_returned(admin, editor, monkeypatch):
    from api import voiceover as V
    monkeypatch.delenv('ELEVENLABS_API_KEY', raising=False)
    monkeypatch.setattr(V, '_subscription', lambda key=None: dict(tier='free', used=1, limit=10000, resets=None))
    key = 'sk_' + 'a1' * 20
    assert editor.put('/api/integrations/elevenlabs', json=dict(api_key=key)).status_code == 403
    r = admin.put('/api/integrations/elevenlabs', json=dict(api_key=key)); assert r.status_code == 200, r.text
    assert key not in r.text and key not in admin.get('/api/integrations/elevenlabs').text
    from config import CONFIG
    raw = (CONFIG.config_dir / 'elevenlabs.json').read_text(); assert key not in raw
    assert V.api_key() == key
    assert admin.delete('/api/integrations/elevenlabs').json()['set'] is False and V.api_key() == ''


def test_cast_roundtrip_and_validation(editor, viewer):
    c = dict(model='eleven_v3', characters=[dict(name='Stark', series='Frieren', voice_name='Valf', voice_id='abcdefgh1234', notes='sarcastic')])
    assert viewer.put('/api/voice/cast', json=dict(cast=c)).status_code == 403
    r = editor.put('/api/voice/cast', json=dict(cast=c)); assert r.status_code == 200, r.text
    assert viewer.get('/api/voice/cast').json()['characters'][0]['voice_id'] == 'abcdefgh1234'
    assert (DATA / 'voices.json').exists()
    assert editor.put('/api/voice/cast', json=dict(cast=dict(characters=[dict(name='X', voice_id='../etc')]))).status_code == 400
    assert editor.put('/api/voice/cast', json=dict(cast=dict(characters=[dict(name='')]))).status_code == 400


def test_script_suggestions(editor):
    (DATA / 'projects' / PID / 'synopsis.md').write_text('# t\n\n1. Caption: "A freezing night." Stark: "Take my scarf."\n2. Frieren: "...I\'m also cold."\n')
    s = editor.get(URL).json()['suggestions']
    assert [(x['character'], x['text']) for x in s] == [('Narrator', 'A freezing night.'), ('Stark', 'Take my scarf.'), ('Frieren', "...I'm also cold.")]
    assert s[2]['at'] == pytest.approx(4.0)
