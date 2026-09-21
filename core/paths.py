"""
Where Cadenza keeps things on disk.

Modules used to build cache paths from Path(__file__).parent.parent,
which is the project root when running from source — but inside
_internal/ in a PyInstaller build, because that is where the bundled
module lives. Caches then landed inside the application folder: hidden
from the user, wiped by every reinstall, and unwritable if the app sits
somewhere protected.

Frozen builds therefore use a per-user location instead, and
everything shares one root so there is a single place to clear.
"""

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, 'frozen', False))


def app_root() -> Path:
    """The project root when running from source, else the exe's folder."""
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def cache_root() -> Path:
    """
    The cache directory, made if missing.

    Source runs keep it beside the code, as before. A frozen build puts
    it under the user's own data directory, so it survives reinstalls
    and never needs write access to the install location.
    """
    if is_frozen():
        base = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
        if base:
            root = Path(base) / 'Cadenza' / 'cache'
        else:                              # macOS / Linux builds
            root = Path.home() / '.cache' / 'cadenza'
    else:
        root = Path(__file__).resolve().parent.parent / 'cache'

    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        # last resort: the system temp directory, so a cache failure
        # never stops the app from opening
        import tempfile
        root = Path(tempfile.gettempdir()) / 'cadenza-cache'
        root.mkdir(parents=True, exist_ok=True)
    return root


def cache_dir(name: str) -> Path:
    """A named subdirectory of the cache, e.g. 'waveforms', 'proxies'."""
    path = cache_root() / name
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path
