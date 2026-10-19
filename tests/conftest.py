"""
Shared test setup.

Only one thing here: make `sounddevice` importable. ui/audio_output.py
imports it at module scope, so MainWindow cannot be built without it,
and a machine with no PortAudio (a container, or CI) would be unable
to test any of the window behaviour.

On a real machine with PortAudio installed this does nothing at all.
"""

import sys
import types

import pytest


def _audio_is_importable() -> bool:
    try:
        import sounddevice  # noqa: F401
        return True
    except Exception:
        return False


@pytest.fixture(scope='session', autouse=True)
def audio_output_available():
    """Stand in for sounddevice when the real one cannot load."""
    if _audio_is_importable():
        yield False          # nothing to do
        return

    stub = types.ModuleType('sounddevice')

    class _Stream:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

    stub.OutputStream = _Stream
    stub.query_devices = lambda *a, **k: []
    stub.default = types.SimpleNamespace(
        device=(None, None), samplerate=48000)
    stub.PortAudioError = RuntimeError
    sys.modules['sounddevice'] = stub
    yield True
    sys.modules.pop('sounddevice', None)
