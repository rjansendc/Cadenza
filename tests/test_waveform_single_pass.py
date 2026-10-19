"""
Every audio stream of a file is read in one pass.

Decoding a stream makes the demuxer walk the whole container, past
every video packet, so the cost tracks the file's size and not its
audio: the same 30 seconds of audio took 20x longer to read from
inside a 1941 MB 1080p file than from a 0.5 MB audio file. Computing
one stream at a time meant a four-stream recording was read four
times over — for a 4K movie, four passes across tens of gigabytes.

The pass also folds samples into their buckets as they arrive. The
whole decoded stream used to be held in memory, 115 MB per five
minutes, so reading four streams together would otherwise have held
four times about 2.8 GB on a two-hour concert.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import numpy as np
import av

from media.waveform import (compute_peaks, compute_peaks_all,
                            get_cache_path, load_peaks, _Envelope)

LEVELS = (0.1, 0.4, 0.7, 1.0)
RATE   = 48000
CHUNK  = 1024


@pytest.fixture(scope='module')
def multitrack(tmp_path_factory):
    """Four mono streams at different levels, in small packets."""
    path = str(tmp_path_factory.mktemp('media') / 'four.mkv')
    container = av.open(path, mode='w')
    streams = [container.add_stream('pcm_s16le', rate=RATE)
               for _ in LEVELS]
    for stream in streams:
        stream.codec_context.layout = 'mono'
    seconds = 3
    t = np.arange(RATE * seconds) / RATE
    tones = [(np.sin(2 * np.pi * 220 * (i + 1) * t) * level * 32767
              ).astype(np.int16)
             for i, level in enumerate(LEVELS)]
    pts = 0
    for start in range(0, len(t) - CHUNK, CHUNK):
        for stream, tone in zip(streams, tones):
            frame = av.AudioFrame.from_ndarray(
                tone[start:start + CHUNK].reshape(1, -1),
                format='s16', layout='mono')
            frame.sample_rate = RATE
            frame.pts = pts
            for packet in stream.encode(frame):
                container.mux(packet)
        pts += CHUNK
    for stream in streams:
        for packet in stream.encode():
            container.mux(packet)
    container.close()
    return path


@pytest.fixture(autouse=True)
def clean_cache(multitrack):
    from pathlib import Path
    for index in range(len(LEVELS) + 2):
        cache = get_cache_path(multitrack, index)
        for candidate in (cache, Path(str(cache) + '.npy')):
            Path(candidate).unlink(missing_ok=True)
    yield


def opens_counted(monkeypatch):
    """Count how many times the file is opened for reading."""
    import media.waveform as waveform
    opened = []
    real = av.open

    def counting_open(path, *a, **kw):
        if kw.get('mode') != 'w':
            opened.append(path)
        return real(path, *a, **kw)

    monkeypatch.setattr(av, 'open', counting_open)
    return opened


# ── one pass, every stream ────────────────────────────────────

def test_all_four_streams_come_back(multitrack):
    results = compute_peaks_all(multitrack, num_peaks=200)
    assert sorted(results) == [0, 1, 2, 3]
    assert all(results[i] is not None for i in results)


def test_each_stream_keeps_its_own_level(multitrack):
    """Mono is spread to stereo on the way through, which costs a
    consistent 3dB, so compare the ratios rather than the values."""
    results = compute_peaks_all(multitrack, num_peaks=200)
    drawn = [float(results[i][1].max()) for i in range(4)]
    assert drawn == sorted(drawn)        # and not all the first one
    for index in range(1, len(LEVELS)):
        assert (drawn[index] / drawn[0]) == pytest.approx(
            LEVELS[index] / LEVELS[0], rel=0.05), drawn


def test_the_file_is_opened_once_for_all_streams(monkeypatch, multitrack):
    opened = opens_counted(monkeypatch)
    compute_peaks_all(multitrack, num_peaks=200)
    assert len(opened) == 1, opened


def test_one_stream_at_a_time_opens_the_file_once_per_stream(
        monkeypatch, multitrack):
    """What the old code did on every drop, and the reason the queue
    now asks per file instead of per stream: compute_peaks is still
    free to fetch a single stream, and still pays a whole walk of the
    container to do it."""
    opened = opens_counted(monkeypatch)
    for index in range(4):
        compute_peaks(multitrack, num_peaks=200, audio_index=index)
    assert len(opened) == 4, opened


def test_every_stream_is_cached_by_the_one_pass(multitrack):
    compute_peaks_all(multitrack, num_peaks=200)
    for index in range(4):
        assert load_peaks(multitrack, index) is not None, index


def test_named_streams_that_are_cached_do_not_open_the_file(
        monkeypatch, multitrack):
    compute_peaks_all(multitrack, num_peaks=200)
    opened = opens_counted(monkeypatch)
    results = compute_peaks_all(multitrack, num_peaks=200,
                                audio_indices=[0, 1, 2, 3])
    assert len(opened) == 0, opened
    assert sorted(results) == [0, 1, 2, 3]


def test_a_cached_single_stream_does_not_open_the_file(
        monkeypatch, multitrack):
    compute_peaks(multitrack, num_peaks=200, audio_index=1)
    opened = opens_counted(monkeypatch)
    assert compute_peaks(multitrack, num_peaks=200,
                         audio_index=1) is not None
    assert len(opened) == 0, opened


def test_asking_for_every_stream_without_naming_them_opens_once(
        monkeypatch, multitrack):
    """Enumerating the streams means opening the file, even when the
    answers are all cached — one header read, no decode."""
    compute_peaks_all(multitrack, num_peaks=200)
    opened = opens_counted(monkeypatch)
    compute_peaks_all(multitrack, num_peaks=200)
    assert len(opened) == 1, opened


def test_a_partly_cached_file_fills_in_the_rest(multitrack):
    compute_peaks(multitrack, num_peaks=200, audio_index=0)
    cached = load_peaks(multitrack, 0)
    results = compute_peaks_all(multitrack, num_peaks=200)
    assert sorted(results) == [0, 1, 2, 3]
    # the cached one comes back untouched, the others are computed
    assert np.array_equal(results[0], cached)
    drawn = [float(results[i][1].max()) for i in range(4)]
    assert drawn == sorted(drawn), drawn


# ── the one-stream wrapper still behaves ──────────────────────

def test_one_stream_still_returns_an_array(multitrack):
    peaks = compute_peaks(multitrack, num_peaks=200, audio_index=1)
    assert peaks is not None
    assert peaks.shape == (4, 200)


def test_asking_past_the_last_stream_is_not_a_crash(multitrack):
    assert compute_peaks(multitrack, num_peaks=200, audio_index=9) is None
    results = compute_peaks_all(multitrack, num_peaks=200,
                                audio_indices=[0, 9])
    assert results[9] is None
    assert results[0] is not None


def test_a_file_with_no_audio_returns_nothing(tmp_path):
    import av as _av
    path = str(tmp_path / 'silent.mp4')
    with _av.open(path, mode='w') as container:
        stream = container.add_stream('libx264', rate=30)
        stream.width, stream.height = 160, 120
        stream.pix_fmt = 'yuv420p'
        for i in range(10):
            frame = _av.VideoFrame.from_ndarray(
                np.zeros((120, 160, 3), dtype=np.uint8), format='rgb24')
            frame.pts = i
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    assert compute_peaks_all(path, num_peaks=200) == {}
    assert compute_peaks(path, num_peaks=200) is None


# ── the accumulator ───────────────────────────────────────────

def test_the_envelope_holds_only_its_buckets():
    """Memory is the bucket count, not the recording length."""
    env = _Envelope(100, 48000 * 3600)       # an hour
    block = np.linspace(-1, 1, 4096).astype(np.float32)
    for _ in range(200):
        env.add(block)
    assert env.mins.size == 100 and env.maxs.size == 100
    assert env.held is None


def test_the_envelope_finds_the_extremes_in_each_bucket():
    env = _Envelope(4, 400)
    for start in range(0, 400, 100):
        block = np.full(100, float(start) / 100, dtype=np.float32)
        env.add(block)
    mins, maxs = env.finish()
    assert list(maxs) == [0.0, 1.0, 2.0, 3.0]
    assert list(mins) == [0.0, 1.0, 2.0, 3.0]


def test_a_peak_is_not_lost_across_a_block_boundary():
    """Blocks arrive at whatever size the decoder hands over, which
    has nothing to do with bucket boundaries."""
    env = _Envelope(2, 200)
    env.add(np.concatenate([np.zeros(99, np.float32),
                            np.array([0.9], np.float32)]))   # 0..99
    env.add(np.concatenate([np.array([-0.8], np.float32),
                            np.zeros(99, np.float32)]))      # 100..199
    mins, maxs = env.finish()
    assert float(maxs[0]) == pytest.approx(0.9)
    assert float(mins[1]) == pytest.approx(-0.8)


def test_a_stream_shorter_than_its_duration_still_spans_the_width():
    """A container's duration can run a little long; the waveform
    must not stop short of the clip."""
    env = _Envelope(10, 1000)
    env.add(np.full(500, 0.5, dtype=np.float32))      # only half
    mins, maxs = env.finish()
    assert all(v == pytest.approx(0.5) for v in maxs), list(maxs)


def test_an_unknown_duration_falls_back_to_holding_the_samples():
    """Guessing a length would fold the whole stream into one
    bucket, so this case buckets at the end instead."""
    env = _Envelope(4, 0)
    assert env.unknown
    for value in (0.1, 0.2, 0.3, 0.4):
        env.add(np.full(100, value, dtype=np.float32))
    mins, maxs = env.finish()
    assert [round(float(v), 2) for v in maxs] == [0.1, 0.2, 0.3, 0.4]
