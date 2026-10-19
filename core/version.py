"""
What this build of Cadenza is.

One place, so the About box, the saved project files and anything else
that wants to say which version it is all agree. The version used to
be a literal inside an f-string in the About handler.
"""

__version__ = '1.2.0'

APP_NAME = 'Cadenza'


def version_string() -> str:
    return f'{APP_NAME} {__version__}'


def environment() -> dict:
    """
    The versions underneath, for the About box and bug reports.

    Everything is probed defensively: a missing or broken optional
    package should make one line read "unavailable", not stop the
    dialog from opening.
    """
    info = {'Cadenza': __version__}

    import sys
    info['Python'] = sys.version.split()[0]

    try:
        import PySide6
        info['PySide6'] = PySide6.__version__
    except Exception:
        info['PySide6'] = 'unavailable'

    try:
        import torch
        if torch.cuda.is_available():
            info['PyTorch'] = f'{torch.__version__} (CUDA {torch.version.cuda})'
            info['GPU'] = torch.cuda.get_device_name(0)
        else:
            info['PyTorch'] = f'{torch.__version__} (CPU only)'
            info['GPU'] = 'none detected (CPU rendering)'
    except Exception:
        info['PyTorch'] = 'unavailable'

    try:
        import av
        info['PyAV'] = av.__version__
    except Exception:
        info['PyAV'] = 'unavailable'

    try:
        from core.project_io import PROJECT_VERSION
        info['Project format'] = str(PROJECT_VERSION)
    except Exception:
        pass

    try:
        from core.paths import cache_root
        info['Cache'] = str(cache_root())
    except Exception:
        pass

    return info
