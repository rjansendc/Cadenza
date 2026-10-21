"""
The preview re-composites when the clip list changes.

It holds whatever was last composited, and nothing redrew it when
clips were added or removed. So dropping an image onto V2 while the
playhead already sat inside where it landed left the previous frame
on screen — the video on V1 below it — and the image looked as though
it had been ignored. Deleting a clip under the playhead left the
deleted clip showing.

Undo has always invalidated the cached frame and re-rendered; drop
and delete did not. The cache matters as much as the re-render: a
re-render alone hands back the same stale composite.
"""

import os
import sys
import types
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

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
from PySide6.QtWidgets import QApplication            # noqa: E402
from PySide6.QtGui import QImage, QColor              # noqa: E402

V1_ROW, V2_ROW = 2, 1


@pytest.fixture(scope='module')
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(scope='module')
def stills(tmp_path_factory, qapp):
    folder = tmp_path_factory.mktemp('media')
    made = []
    for name, colour in (('under.png', QColor(30, 30, 200)),
                         ('over.png', QColor(220, 30, 30))):
        image = QImage(640, 360, QImage.Format.Format_RGB888)
        image.fill(colour)
        path = folder / name
        image.save(str(path))
        made.append(str(path))
    return made


@pytest.fixture
def window(qapp, stills):
    from ui.mainwindow import MainWindow
    win = MainWindow()
    win.show()
    QApplication.processEvents()
    win._on_import_paths(stills)
    QApplication.processEvents()
    yield win
    win.project.is_dirty = False
    win.close()


def watch(window, monkeypatch):
    """Record the refresh calls an edit makes."""
    calls = []
    compositor = (window._playback._compositor
                  if window._playback else None)
    if compositor is not None:
        monkeypatch.setattr(
            compositor, 'invalidate_cache',
            lambda: calls.append('invalidate'))
    monkeypatch.setattr(
        window, '_scrub_to_playhead',
        lambda: calls.append('rerender'))
    return calls


def media_ids(window):
    return list(window.project.media_pool)


def test_dropping_a_clip_re_composites_the_preview(window, monkeypatch):
    """The reported case: the playhead sits where the new clip lands,
    so nothing else would ever redraw it."""
    ids = media_ids(window)
    window._on_media_dropped(ids[0], V1_ROW, 0)
    QApplication.processEvents()
    window.app_state.playhead_frame = 100

    calls = watch(window, monkeypatch)
    window._on_media_dropped(ids[1], V2_ROW, 0)
    QApplication.processEvents()
    assert 'rerender' in calls, calls
    assert 'invalidate' in calls, calls


def test_the_cached_frame_is_dropped_not_just_redrawn(window, monkeypatch):
    """A re-render on its own returns the same stale composite."""
    ids = media_ids(window)
    calls = watch(window, monkeypatch)
    window._on_media_dropped(ids[0], V1_ROW, 0)
    QApplication.processEvents()
    assert calls.index('invalidate') < calls.index('rerender'), calls


def test_deleting_a_clip_re_composites_the_preview(window, monkeypatch):
    """Otherwise the deleted clip stays on screen."""
    ids = media_ids(window)
    window._on_media_dropped(ids[0], V1_ROW, 0)
    QApplication.processEvents()
    clip = next(iter(window.project.clips.values()))
    window.app_state.select_clip(clip.id)

    calls = watch(window, monkeypatch)
    window._on_delete_clip()
    QApplication.processEvents()
    assert 'rerender' in calls, calls
    assert 'invalidate' in calls, calls


def test_a_refused_drop_does_not_redraw(window, monkeypatch):
    """Nothing was placed, so nothing needs re-compositing."""
    calls = watch(window, monkeypatch)
    window._on_media_dropped('no-such-item', V1_ROW, 0)
    QApplication.processEvents()
    assert calls == []


# ── and the frame really does change ──────────────────────────

def test_the_new_clip_is_in_the_composite(window):
    """End to end, without stubbing the refresh: the image on V2 is
    what comes back at the playhead."""
    from gpu.compositor import Compositor
    ids = media_ids(window)
    window._on_media_dropped(ids[0], V1_ROW, 0)      # blue under
    QApplication.processEvents()
    window.app_state.playhead_frame = 100
    window._on_media_dropped(ids[1], V2_ROW, 0)      # red over
    QApplication.processEvents()

    sequence = window.project.active_sequence
    compositor = Compositor(sequence)
    compositor.use_proxies = False
    out = compositor.composite_frame(
        list(window.project.clips.values()), 100, sequence=sequence)
    centre = [int(v) for v in out[out.shape[0] // 2, out.shape[1] // 2]]
    assert centre[0] > 150, centre      # red, not blue
