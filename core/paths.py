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


def _writable(path: Path) -> bool:
    """Can we actually create and write here?"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / '.write-test'
        probe.write_bytes(b'')
        probe.unlink()
        return True
    except OSError:
        return False


def cache_root() -> Path:
    """
    The cache directory, made if missing.

    A frozen build keeps it beside Cadenza.exe, so it travels with the
    application folder and is easy to find or clear. If that folder is
    read-only — the app unpacked into Program Files, say — it falls
    back to the user's own data directory, and to temp after that, so a
    cache location never stops the app from opening.

    Source runs keep it beside the code, as before.
    """
    if is_frozen():
        candidates = [Path(sys.executable).parent / 'cache']
        base = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
        if base:
            candidates.append(Path(base) / 'Cadenza' / 'cache')
        else:
            candidates.append(Path.home() / '.cache' / 'cadenza')
    else:
        candidates = [Path(__file__).resolve().parent.parent / 'cache']

    import tempfile
    candidates.append(Path(tempfile.gettempdir()) / 'cadenza-cache')

    for candidate in candidates:
        if _writable(candidate):
            return candidate
    return candidates[-1]


def cache_dir(name: str) -> Path:
    """A named subdirectory of the cache, e.g. 'waveforms', 'proxies'."""
    path = cache_root() / name
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return path
