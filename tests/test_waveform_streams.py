"""
One waveform per audio stream, not per file.

A multitrack concert recording carries one audio stream per feed.
compute_peaks took whichever audio stream came first and the cache was
keyed on the filename alone, so every track of such a file drew the
same waveform while playing its own audio — measured on a four-stream
file, streams at peak 0.4, 0.7 and 1.0 all drew stream one's 0.1.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import numpy as np
import av

from media.waveform import compute_peaks, get_cache_path, load_peaks

# peak amplitude written into each stream, deliberately far apart
LEVELS = (0.1, 0.4, 0.7, 1.0)
RATE   = 48000


@pytest.fixture(scope='module')
def multitrack(tmp_path_factory):
    """A file with four mono audio streams at different levels."""
    path = str(tmp_path_factory.mktemp('media') / 'multitrack.mkv')
    container = av.open(path, mode='w')
    streams = [container.add_stream('pcm_s16le', rate=RATE)
               for _ in LEVELS]
    for stream in streams:
        stream.codec_context.layout = 'mono'

    t = np.arange(RATE) / RATE          # one second
    for index, (stream, level) in enumerate(zip(streams, LEVELS)):
        tone = (np.sin(2 * np.pi * 220 * (index + 1) * t)
                * level * 32767).astype(np.int16)
        frame = av.AudioFrame.from_ndarray(
            tone.reshape(1, -1), format='s16', layout='mono')
        frame.sample_rate = RATE
        frame.pts = 0
        for packet in stream.encode(frame):
            container.mux(packet)
    for stream in streams:
        for packet in stream.encode():
            container.mux(packet)
    container.close()
    return path


@pytest.fixture(autouse=True)
def clean_cache(multitrack):
    """Peaks are cached on disk; start each test from nothing."""
    from pathlib import Path
    for index in range(len(LEVELS) + 2):
        for candidate in (get_cache_path(multitrack, index),
                          Path(str(get_cache_path(multitrack, index))
                               + '.npy')):
            Path(candidate).unlink(missing_ok=True)
    yield


def drawn_peak(path, audio_index):
    """The loudest point the waveform would draw."""
    peaks = compute_peaks(path, num_peaks=200, audio_index=audio_index)
    assert peaks is not None
    return float(peaks[1].max())        # L_max row


# ── the streams are told apart ────────────────────────────────

def test_each_stream_draws_its_own_level(multitrack):
    drawn = [drawn_peak(multitrack, i) for i in range(len(LEVELS))]
    # rising, in the same order as what was written. The smallest
    # step is 0.7 -> 1.0, so a ratio of 1.43 is as close as they get.
    assert drawn == sorted(drawn)
    for quiet, loud in zip(drawn, drawn[1:]):
        assert loud > quiet * 1.3
    assert drawn[-1] > drawn[0] * 5


def test_they_are_not_all_the_first_stream(multitrack):
    """The bug: every track showed stream one."""
    first = drawn_peak(multitrack, 0)
    for index in range(1, len(LEVELS)):
        assert drawn_peak(multitrack, index) != pytest.approx(
            first, rel=0.05)


def test_the_drawn_level_tracks_what_was_written(multitrack):
    """Mono is spread to stereo on the way through, which costs a
    consistent 3dB, so compare the ratios rather than the values."""
    drawn = [drawn_peak(multitrack, i) for i in range(len(LEVELS))]
    for index in range(1, len(LEVELS)):
        written_ratio = LEVELS[index] / LEVELS[0]
        drawn_ratio   = drawn[index] / drawn[0]
        assert drawn_ratio == pytest.approx(written_ratio, rel=0.05)


def test_asking_past_the_last_stream_is_not_a_crash(multitrack):
    assert compute_peaks(multitrack, num_peaks=200,
                         audio_index=len(LEVELS)) is None


# ── each stream caches separately ─────────────────────────────

def test_every_stream_gets_its_own_cache_file(multitrack):
    paths = {get_cache_path(multitrack, i) for i in range(len(LEVELS))}
    assert len(paths) == len(LEVELS)


def test_the_first_stream_keeps_the_original_cache_path(multitrack):
    """Caches written before this change hold stream one's peaks,
    which is still the right answer for stream one."""
    assert get_cache_path(multitrack, 0) == get_cache_path(multitrack)


def test_a_cached_stream_comes_back_as_itself(multitrack):
    fresh = drawn_peak(multitrack, 2)
    cached = load_peaks(multitrack, 2)
    assert cached is not None
    assert float(cached[1].max()) == pytest.approx(fresh)
    # and stream 2's cache is not stream 0's
    assert load_peaks(multitrack, 0) is None


# ── the clip's stream reaches the decoder ─────────────────────

def test_a_clip_asks_for_its_own_stream(monkeypatch, multitrack):
    """stream_index counts every stream including video; the waveform
    code wants the position among the audio ones."""
    pytest.importorskip('PySide6.QtWidgets')
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    from core.clip import Clip, ClipType
    from core.track import Track, TrackType
    from ui.app_state import AppState
    from ui.widgets.track_header import TrackCanvas
    import media.waveform_worker as worker_module

    asked = []
    monkeypatch.setattr(
        worker_module.waveform_queue, 'submit',
        lambda fp, audio_index=0, **kw: asked.append(audio_index))

    canvas = TrackCanvas(Track(TrackType.AUDIO, 0), AppState())
    for stream_index, expected in ((1, 0), (2, 1), (3, 2), (0, 0)):
        asked.clear()
        clip = Clip(filepath=multitrack, clip_type=ClipType.AUDIO,
                    has_video=False, has_audio=True,
                    source_frames=300, source_fps=29.97,
                    track=0, start_frame=0, out_point=300,
                    stream_index=stream_index)
        canvas._start_waveform_worker(clip)
        assert asked == [expected], f'stream_index {stream_index}'
    canvas.detach()


def test_the_canvas_handles_progress_and_completion(monkeypatch,
                                                    multitrack):
    """
    The queue reports progress while it decodes, and reports again
    when done. The stub above never calls either of those back, so a
    canvas missing a handler still passed it — and decoding a real
    file raised on the first progress signal:

        AttributeError: 'TrackCanvas' object has no attribute
        '_on_waveform_progress'

    once per signal, for every stream, until the thread was torn down.
    """
    pytest.importorskip('PySide6.QtWidgets')
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    from core.clip import Clip, ClipType
    from core.track import Track, TrackType
    from ui.app_state import AppState
    from ui.widgets.track_header import TrackCanvas
    import media.waveform as waveform_module
    import media.waveform_worker as worker_module

    # no cache, so the queue is actually used
    monkeypatch.setattr(waveform_module, 'load_peaks',
                        lambda fp, audio_index=0: None)

    called = []

    def fake_submit(fp, audio_index=0, completed=None, progress=None):
        for pct in (0, 37, 100):
            progress(fp, pct)
            called.append(('progress', pct))
        completed(fp, np.zeros((2, 16), dtype=np.float32))
        called.append(('completed', audio_index))

    monkeypatch.setattr(worker_module.waveform_queue, 'submit',
                        fake_submit)

    canvas = TrackCanvas(Track(TrackType.AUDIO, 0), AppState())
    clip = Clip(filepath=multitrack, clip_type=ClipType.AUDIO,
                has_video=False, has_audio=True,
                source_frames=300, source_fps=29.97,
                track=0, start_frame=0, out_point=300,
                stream_index=2)
    canvas._start_waveform_worker(clip)       # must not raise
    canvas.detach()

    assert called == [('progress', 0), ('progress', 37),
                      ('progress', 100), ('completed', 1)]


def test_every_callback_the_canvas_hands_out_is_one_it_has():
    """Cheap guard on the same class of mistake: the request path
    names its handlers in lambdas, which are not checked until they
    run."""
    pytest.importorskip('PySide6.QtWidgets')
    from ui.widgets.track_header import TrackCanvas
    for name in ('_on_waveform_ready', '_on_waveform_progress',
                 '_on_waveform_done'):
        assert callable(getattr(TrackCanvas, name, None)), name
