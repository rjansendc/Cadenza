"""
The waveform queue is held while playback runs, and let go afterwards.

Waveform decoding is disk-bound, so the drives belong to video decode
while playing. The hold was applied and released in the play button's
handler — but playback stops by routes that button never sees:
reaching the end of the timeline calls pause() straight from the
video tick, and so does starting an export.

So playing once to the end left the queue paused for the rest of the
session. Every waveform asked for afterwards sat in the pending list
and never started: dropping a WAV reported "Added a.wav -> 0V + 1A
clips linked" and then drew nothing at all, with no message to say
why. The hold now lives in the engine, which sees every stop.
"""

import os
import sys
import types
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

# PortAudio has no device here and audio_output imports sounddevice at
# module level, which blocks MainWindow construction
if 'sounddevice' not in sys.modules:
    _stub = types.ModuleType('sounddevice')
    _stub.OutputStream = lambda *a, **k: types.SimpleNamespace(
        start=lambda: None, stop=lambda: None, close=lambda: None,
        write=lambda *a: None, active=False)
    _stub.query_devices = lambda *a, **k: []
    _stub.default = types.SimpleNamespace(device=(None, None),
                                          samplerate=48000)
    sys.modules['sounddevice'] = _stub

import effects  # noqa: F401

QtWidgets = pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtWidgets import QApplication        # noqa: E402

from media.waveform_worker import waveform_queue   # noqa: E402


@pytest.fixture(scope='module')
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def engine(qapp):
    from ui.mainwindow import MainWindow
    win = MainWindow()
    QApplication.processEvents()
    assert win._playback is not None, 'no playback engine'
    yield win._playback
    waveform_queue.resume()
    win.project.is_dirty = False
    win.close()


# ── every stop releases the hold ──────────────────────────────

def test_pause_releases_the_queue(engine):
    """The end of the timeline calls pause() from the tick — this is
    the path that used to strand it."""
    waveform_queue.pause()
    engine._playing = True                 # as if playing
    engine.pause()
    assert not waveform_queue._paused


def test_stop_releases_the_queue(engine):
    waveform_queue.pause()
    engine._playing = True
    engine.stop()
    assert not waveform_queue._paused


def test_a_pause_while_already_stopped_leaves_it_running(engine):
    waveform_queue.resume()
    engine._playing = False
    engine.pause()                         # early-returns
    assert not waveform_queue._paused


def test_the_hold_itself_pauses_and_resumes(engine):
    engine._hold_waveforms(True)
    assert waveform_queue._paused
    engine._hold_waveforms(False)
    assert not waveform_queue._paused


def test_the_hold_never_raises_at_playback(engine, monkeypatch):
    """Playback must not fail because of a waveform concern."""
    import media.waveform_worker as module

    def boom():
        raise RuntimeError('no')

    monkeypatch.setattr(module.waveform_queue, 'resume', boom)
    engine._hold_waveforms(False)          # must not propagate


# ── a request after a stop actually starts ────────────────────

def test_a_submission_after_playback_ends_is_not_stranded(engine):
    """The symptom, at the level it was seen: a request made after
    playback stopped must leave the pending list."""
    waveform_queue.pause()
    engine._playing = True
    engine.pause()                         # as the tick does at the end

    started = []
    original = waveform_queue._drain

    def watch():
        started.append(True)
        return original()

    waveform_queue._drain = watch
    try:
        waveform_queue.submit('/nonexistent/after.wav', 0)
    finally:
        waveform_queue._drain = original
    assert started, 'the queue was not drained'
    assert not waveform_queue._paused


# ── closing a window does not strand the singleton ────────────

def test_shutdown_leaves_the_queue_usable():
    """The queue is a module-level singleton that outlives the window
    which closed. Shutting it down cancels the work; it must not also
    leave the object permanently paused."""
    waveform_queue.submit('/nonexistent/x.wav', 0)
    waveform_queue.shutdown()
    assert not waveform_queue._paused
    assert not waveform_queue.busy
