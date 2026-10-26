"""Every API route: 401 without a session, 403 for roles below the route's minimum (deny by default)."""
import re

import pytest
from fastapi.routing import APIRoute

from conftest import MVID, PID

PARAMS = {'kind': 'strip', 'pid': PID, 'rel': 'synopsis.md', 'jid': 'nojob', 'uid': '999', 'sid': 'nosession', 'key': 'make_pdf'}
PUBLIC = {'/api/health', '/api/ready', '/api/auth/state', '/api/auth/login', '/api/auth/setup', '/api/auth/logout'}


def routes(app):
    import server
    out = []
    for r in server.api_routes(app):
        if isinstance(r, APIRoute):
            for m in r.methods:
                if m == 'HEAD': continue
                url = re.sub(r'\{(\w+)(?::path)?\}', lambda mm: PARAMS.get(mm.group(1), 'x'), r.path)
                if '{pid}' in r.path and '/lyric/' in r.path: url = url.replace(PID, MVID)
                out.append((m, r.path, url, r))
    return out


def required(r, method):
    from api.deps import required_role
    return required_role(r, method)


def call(c, m, url):
    if m == 'GET': return c.get(url)
    return getattr(c, m.lower())(url, json={})


def test_every_route_is_guarded(app):
    from api.deps import authorize
    rs = routes(app)
    assert len(rs) > 60
    for m, path, url, r in rs:
        assert any(d.call is authorize for d in r.dependant.dependencies), path
        need = required(r, m)
        if path in PUBLIC: assert need is None, path
        else: assert need in ('viewer', 'editor', 'admin'), path


def test_unauthenticated_gets_401(app, anon):
    for m, path, url, r in routes(app):
        if path in PUBLIC: continue
        res = call(anon, m, url)
        assert res.status_code == 401, (m, url, res.status_code, res.text[:200])


@pytest.mark.parametrize('who,level', [('viewer', 0), ('editor', 1)])
def test_roles_below_minimum_get_403(app, request, who, level):
    c = request.getfixturevalue(who)
    lv = {'viewer': 0, 'editor': 1, 'admin': 2}
    checked = 0
    for m, path, url, r in routes(app):
        need = required(r, m)
        if need is None or lv[need] <= level: continue
        res = call(c, m, url)
        assert res.status_code == 403, (who, m, url, res.status_code, res.text[:200])
        checked += 1
    assert checked > 10


def test_viewer_can_read(viewer):
    assert viewer.get('/api/library').status_code == 200
    assert viewer.get(f'/api/p/strip/{PID}').status_code == 200
    assert viewer.put(f'/api/p/strip/{PID}/text?name=synopsis.md', json={'text': 'x'}).status_code == 403


def test_editor_cannot_admin(editor):
    assert editor.get('/api/users').status_code == 403
    assert editor.get('/api/integrations/storage').status_code == 403
    assert editor.post('/api/tools/make_pdf/run', json={'args': {}}).status_code == 403
    assert editor.put('/api/settings', json={'handle': '@x'}).status_code == 403


def test_static_and_health_are_public(anon):
    assert anon.get('/api/health').json()['ok'] is True
    assert anon.get('/api/ready').status_code in (200, 503)
