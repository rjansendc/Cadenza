"""
Importing audio starts its waveform.

Peaks were computed only when a clip was placed on an audio track, so
dropping a file into the media bin did nothing at all — no work
started and nothing was said — and the wait landed later, on the
edit. Importing is the moment to pay for it: by the time a clip is
placed the peaks are cached and draw at once.
"""

import fractions
import os
import sys
import types
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import numpy as np
import av

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
from PySide6.QtWidgets import QApplication          # noqa: E402
from PySide6.QtGui import QImage, QColor            # noqa: E402

RATE  = 48000
CHUNK = 1024


@pytest.fixture(scope='module')
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(scope='module')
def media(tmp_path_factory, qapp):
    folder = tmp_path_factory.mktemp('media')
    made = {}

    for name, seconds in (('one.wav', 2), ('two.wav', 3)):
        path = folder / name
        samples = (np.sin(2 * np.pi * 220 * np.arange(RATE * seconds)
                          / RATE) * 0.8 * 32767).astype(np.int16)
        with av.open(str(path), mode='w') as container:
            stream = container.add_stream('pcm_s16le', rate=RATE)
            stream.codec_context.layout = 'mono'
            stream.codec_context.time_base = fractions.Fraction(1, RATE)
            pts = 0
            for i in range(0, len(samples) - CHUNK, CHUNK):
                frame = av.AudioFrame.from_ndarray(
                    samples[i:i + CHUNK].reshape(1, -1),
                    format='s16', layout='mono')
                frame.sample_rate = RATE
                frame.pts = pts
                frame.time_base = fractions.Fraction(1, RATE)
                pts += CHUNK
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
        made[name] = str(path)

    image = QImage(320, 240, QImage.Format.Format_RGB888)
    image.fill(QColor(80, 120, 160))
    still = folder / 'still.png'
    image.save(str(still))
    made['still.png'] = str(still)
    return made


@pytest.fixture(autouse=True)
def cold_cache(media):
    from pathlib import Path
    from media.waveform import get_cache_path
    for path in media.values():
        for index in (0, 1):
            cache = get_cache_path(path, index)
            for candidate in (cache, Path(str(cache) + '.npy')):
                Path(candidate).unlink(missing_ok=True)
    yield


@pytest.fixture
def window(qapp):
    from ui.mainwindow import MainWindow
    from media.waveform_worker import waveform_queue
    win = MainWindow()
    QApplication.processEvents()
    yield win
    waveform_queue.shutdown()
    win.project.is_dirty = False
    win.close()


def submissions(monkeypatch):
    """Record what is asked for without doing the work."""
    import media.waveform_worker as module
    asked = []
    monkeypatch.setattr(
        module.waveform_queue, 'submit',
        lambda fp, audio_index=0, **kw: asked.append(
            (os.path.basename(fp), audio_index)))
    return asked


# ── importing asks for the work ───────────────────────────────

def test_importing_audio_asks_for_its_waveform(window, media, monkeypatch):
    asked = submissions(monkeypatch)
    window._on_import_paths([media['one.wav']])
    QApplication.processEvents()
    assert asked == [('one.wav', 0)]


def test_nothing_is_placed_on_the_timeline_by_importing(window, media,
                                                        monkeypatch):
    submissions(monkeypatch)
    window._on_import_paths([media['one.wav']])
    QApplication.processEvents()
    assert len(window.project.clips) == 0


def test_every_imported_audio_file_is_asked_for(window, media,
                                                monkeypatch):
    asked = submissions(monkeypatch)
    window._on_import_paths([media['one.wav'], media['two.wav']])
    QApplication.processEvents()
    assert sorted(asked) == [('one.wav', 0), ('two.wav', 0)]


def test_one_request_per_file_not_per_stream(window, media, monkeypatch):
    """The queue reads every audio stream of a file in one pass, so
    asking for the first asks for all of them."""
    asked = submissions(monkeypatch)
    window._on_import_paths([media['one.wav']])
    QApplication.processEvents()
    assert len(asked) == 1


def test_a_still_image_is_not_asked_for(window, media, monkeypatch):
    asked = submissions(monkeypatch)
    window._on_import_paths([media['still.png']])
    QApplication.processEvents()
    assert asked == []


def test_a_file_already_cached_is_not_asked_for_again(window, media,
                                                      monkeypatch):
    from media.waveform import compute_peaks
    compute_peaks(media['one.wav'], num_peaks=4000)
    asked = submissions(monkeypatch)
    window._on_import_paths([media['one.wav']])
    QApplication.processEvents()
    assert asked == []


# ── and the work actually happens ─────────────────────────────

def test_the_peaks_are_on_disk_without_placing_a_clip(window, media):
    import time
    from media.waveform import load_peaks
    from media.waveform_worker import waveform_queue

    window._on_import_paths([media['one.wav']])
    QApplication.processEvents()
    deadline = time.time() + 30
    while waveform_queue.busy and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()

    assert len(window.project.clips) == 0
    assert load_peaks(media['one.wav'], 0) is not None


def test_the_status_bar_reports_the_work(window, media):
    import time
    from media.waveform_worker import waveform_queue

    seen = []
    original = window.status_label.setText
    window.status_label.setText = lambda text: (seen.append(text),
                                                original(text))[1]
    window._on_import_paths([media['one.wav']])
    QApplication.processEvents()
    deadline = time.time() + 30
    while waveform_queue.busy and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()

    assert any(t.startswith('Imported') for t in seen), seen[:3]
    assert any('Waveform' in t for t in seen), seen[-3:]


def test_placing_a_clip_afterwards_needs_no_decode(window, media,
                                                   monkeypatch):
    """The point of doing it at import: the peaks are already there."""
    import time
    from media.waveform_worker import waveform_queue

    window._on_import_paths([media['one.wav']])
    QApplication.processEvents()
    deadline = time.time() + 30
    while waveform_queue.busy and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()

    asked = submissions(monkeypatch)
    item_id = next(iter(window.project.media_pool))
    window._on_media_dropped(item_id, 3, 0)
    QApplication.processEvents()
    assert asked == [], 'the clip asked for a decode it did not need'
    drawn = [wf for row in window.timeline._rows.values()
             for wf in row.canvas._waveform_items.values()]
    assert drawn, 'no waveform item was made'
    assert any(getattr(wf, '_peaks', None) is not None for wf in drawn)
