"""Storage backends (local folder, S3, Cloudflare R2, S3-compatible) + the workspace/work-cache layer."""
from .base import BadKey, Entry, NotFound, Storage, StorageError, norm_key  # noqa: F401
from .local import LocalStorage  # noqa: F401
from .workspace import ROOT, SPath, Workspace, get_ws, set_workspace  # noqa: F401
