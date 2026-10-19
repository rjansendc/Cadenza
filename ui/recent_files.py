"""
Where you were last, and what you had open.

Every file dialog opened on '' — whatever directory the app happened
to be launched from — so reaching the footage meant navigating there
again each time, and there was no way back to a recent project.

Stored with QSettings, which puts it in the registry on Windows and a
config file elsewhere. Nothing here is part of a project file.
"""

from PySide6.QtCore import QSettings

from core.version import APP_NAME

MAX_RECENT = 10

# which folder to reopen for which kind of dialog: projects and
# footage usually live nowhere near each other
PROJECTS = 'projects'
MEDIA    = 'media'
XML      = 'xml'
EXPORTS  = 'exports'


def settings() -> QSettings:
    """
    The settings store. Tests replace this with a temporary one so a
    test run never touches the real preferences.
    """
    return QSettings(APP_NAME, APP_NAME)


# ── last directory ────────────────────────────────────────────

def last_dir(kind: str = PROJECTS) -> str:
    """The folder a dialog of this kind should open in, '' if none."""
    import os
    value = settings().value(f'paths/last_{kind}', '', type=str)
    return value if value and os.path.isdir(value) else ''


def remember_dir(kind: str, path: str):
    """Remember the folder a file was chosen from or saved to."""
    import os
    if not path:
        return
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    if folder:
        settings().setValue(f'paths/last_{kind}', folder)


# ── recent projects ───────────────────────────────────────────

def recent_projects() -> list:
    """Most recently opened or saved first, missing files dropped."""
    import os
    stored = settings().value('recent/projects', [], type=list) or []
    return [p for p in stored if p and os.path.exists(p)]


def add_recent(path: str):
    """Put a project at the top of the list."""
    if not path:
        return
    import os
    path = os.path.abspath(path)
    items = [p for p in (settings().value('recent/projects', [], type=list)
                         or []) if p and os.path.abspath(p) != path]
    items.insert(0, path)
    settings().setValue('recent/projects', items[:MAX_RECENT])
    remember_dir(PROJECTS, path)


def clear_recent():
    settings().setValue('recent/projects', [])
