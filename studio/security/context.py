"""Request-scoped user + role helpers shared by the routers."""
from contextvars import ContextVar

ROLES = ('viewer', 'editor', 'admin')
LEVEL = {r: i for i, r in enumerate(ROLES)}

current_user: ContextVar[dict | None] = ContextVar('current_user', default=None)
request_id: ContextVar[str] = ContextVar('request_id', default='-')


def min_role(role: str):
    """Mark an endpoint with the minimum role it needs. Without a mark: GET/HEAD = viewer, anything else = editor.
    Put it *below* the @router.<method>(...) decorator."""
    if role not in LEVEL: raise ValueError(role)

    def deco(fn):
        fn._min_role = role
        return fn
    return deco


def public_route(fn):
    """Mark an endpoint that needs no login (auth endpoints, health)."""
    fn._public = True
    return fn


def has_role(user: dict | None, role: str) -> bool:
    return bool(user) and LEVEL.get(user.get('role'), -1) >= LEVEL[role]
