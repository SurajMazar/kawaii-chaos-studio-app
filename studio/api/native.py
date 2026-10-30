"""Hooks the Mac app fills in when it starts (desktop/main.py). They stay None on servers and in run.sh."""
from pathlib import Path
from typing import Callable

# share(file, (x, y, w, h)): open the macOS share menu (AirDrop, Messages, Mail…) for a local file, next to that
# rectangle of the window (CSS pixels from the top-left of the page)
share: Callable[[Path, tuple[float, float, float, float]], None] | None = None
