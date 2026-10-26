"""Runtime configuration from environment variables (12-factor), with defaults that keep the owner's local setup
(`studio/run.sh` on a Mac, data in the repo) working unchanged. Every variable is documented in `.env.example`."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

STUDIO = Path(__file__).resolve().parent
CODE_ROOT = STUDIO.parent                      # repo root: scripts/, studio/, default fonts/


def env(name: str, default: str = '') -> str:
    v = os.environ.get(name)
    return default if v is None or v.strip() == '' else v.strip()


def env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None or v.strip() == '': return default
    return v.strip().lower() in ('1', 'true', 'yes', 'on')


def env_int(name: str, default: int) -> int:
    try: return int(env(name, str(default)))
    except ValueError: return default


def env_float(name: str, default: float) -> float:
    try: return float(env(name, str(default)))
    except ValueError: return default


@dataclass
class Config:
    env: str = 'development'
    host: str = '127.0.0.1'
    port: int = 8770
    config_dir: Path = STUDIO / '.config'
    cache_dir: Path = STUDIO / '.cache'
    data_dir: Path = CODE_ROOT / 'data'
    workdir: Path = STUDIO / '.workcache'
    secret_key: str = ''
    cookie_secure: str = 'auto'                 # auto | true | false
    session_idle_minutes: int = 12 * 60
    session_max_hours: int = 14 * 24
    allowed_origins: list[str] = field(default_factory=list)
    allowed_hosts: list[str] = field(default_factory=lambda: ['*'])
    trusted_proxies: str = '127.0.0.1'
    max_upload_mb: int = 200
    max_json_mb: int = 8
    max_import_mb: int = 4096
    max_jobs: int = 3
    max_jobs_per_user: int = 4
    job_starts_per_minute: int = 30
    allow_insecure_endpoints: bool = False
    local_features: bool = True                  # Downloads import, export folder, script-python setting
    log_format: str = 'text'
    log_level: str = 'INFO'
    admin_email: str = ''
    admin_password: str = ''
    index_ttl: float = 30.0
    cache_max_gb: float = 20.0
    hsts: bool = False
    image_max_pixels: int = 80_000_000

    @property
    def production(self) -> bool:
        return self.env == 'production'

    def cookie_is_secure(self, scheme: str) -> bool:
        if self.cookie_secure == 'true': return True
        if self.cookie_secure == 'false': return False
        return scheme == 'https' or self.production


def load() -> Config:
    e = env('STUDIO_ENV', 'development').lower()
    prod = e == 'production'
    cfg_dir = Path(env('STUDIO_CONFIG_DIR', str(STUDIO / '.config'))).expanduser()
    c = Config(
        env=e,
        host=env('STUDIO_HOST', '0.0.0.0' if prod else '127.0.0.1'),  # nosec B104 - containers listen on all interfaces
        port=env_int('PORT', env_int('STUDIO_PORT', 8770)),
        config_dir=cfg_dir,
        cache_dir=Path(env('STUDIO_CACHE_DIR', str(STUDIO / '.cache'))).expanduser(),
        data_dir=Path(env('STUDIO_DATA_DIR', str(CODE_ROOT / 'data'))).expanduser(),
        workdir=Path(env('STUDIO_WORKDIR', str(STUDIO / '.workcache'))).expanduser(),
        secret_key=env('STUDIO_SECRET_KEY'),
        cookie_secure=env('STUDIO_COOKIE_SECURE', 'auto').lower(),
        session_idle_minutes=env_int('STUDIO_SESSION_IDLE_MINUTES', 12 * 60),
        session_max_hours=env_int('STUDIO_SESSION_MAX_HOURS', 14 * 24),
        allowed_origins=[o.strip().rstrip('/') for o in env('STUDIO_ALLOWED_ORIGINS').split(',') if o.strip()],
        # Host header allowlist (DNS-rebinding guard). Local default: localhost names only; production default "*" —
        # set it to your domain, e.g. studio.example.com
        allowed_hosts=[h.strip().lower() for h in env('STUDIO_ALLOWED_HOSTS', '*' if prod else 'localhost,127.0.0.1,::1,*.localhost').split(',') if h.strip()],
        trusted_proxies=env('STUDIO_TRUSTED_PROXIES', '127.0.0.1'),
        max_upload_mb=env_int('STUDIO_MAX_UPLOAD_MB', 200),
        max_json_mb=env_int('STUDIO_MAX_JSON_MB', 8),
        max_import_mb=env_int('STUDIO_MAX_IMPORT_MB', 4096),
        max_jobs=max(1, env_int('STUDIO_MAX_JOBS', 3)),
        max_jobs_per_user=max(1, env_int('STUDIO_MAX_JOBS_PER_USER', 4)),
        job_starts_per_minute=max(1, env_int('STUDIO_JOB_STARTS_PER_MINUTE', 30)),
        allow_insecure_endpoints=env_bool('STUDIO_ALLOW_INSECURE_ENDPOINTS', False),
        local_features=env_bool('STUDIO_LOCAL_FEATURES', not prod),
        log_format=env('STUDIO_LOG_FORMAT', 'json' if prod else 'text').lower(),
        log_level=env('STUDIO_LOG_LEVEL', 'INFO').upper(),
        admin_email=env('STUDIO_ADMIN_EMAIL'),
        admin_password=os.environ.get('STUDIO_ADMIN_PASSWORD', ''),
        index_ttl=max(2.0, env_float('STUDIO_INDEX_TTL', 30.0)),
        cache_max_gb=max(0.5, env_float('STUDIO_CACHE_MAX_GB', 20.0)),
        hsts=env_bool('STUDIO_HSTS', prod),
        image_max_pixels=env_int('STUDIO_IMAGE_MAX_PIXELS', 80_000_000),
    )
    return c


CONFIG = load()


def reload() -> Config:
    """Tests change env vars and call this."""
    global CONFIG
    new = load()
    CONFIG.__dict__.update(new.__dict__)
    return CONFIG
