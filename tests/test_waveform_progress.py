"""
The percentage reported while a waveform is computed.

Two faults, which together meant a long file showed no useful
progress at all:

  - the canvas handed the queue a progress callback naming a method
    that had been removed, so every progress signal raised
    AttributeError and the status bar never changed. Covered in
    test_waveform_streams.py;

  - the percentage was computed against stream.frames, which is 0
    for WAV and anything the container does not count, falling back
    to a flat 1000 frames. A short file never got past 42%, and an
    hour-long one reported 90% within its first ninety seconds and
    sat there — which reads as a hang. It is now measured in
    samples against the stream duration.
"""

import fractions
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import numpy as np
import av

from media.waveform import compute_peaks, get_cache_path

RATE    = 48000
SECONDS = 40
CHUNK   = 1024


@pytest.fixture(scope='module')
def wav_without_a_frame_count(tmp_path_factory):
    """A WAV long enough to report progress several times. WAV
    carries no frame count, which is the case that was broken."""
    path = str(tmp_path_factory.mktemp('media') / 'long.wav')
    samples = (np.sin(2 * np.pi * 220
                      * np.arange(RATE * SECONDS) / RATE)
               * 0.8 * 32767).astype(np.int16)
    with av.open(path, mode='w') as container:
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
    return path


@pytest.fixture(autouse=True)
def no_cache(wav_without_a_frame_count):
    """A cache hit returns before reporting anything."""
    from pathlib import Path
    for index in (0, 1):
        cache = get_cache_path(wav_without_a_frame_count, index)
        for candidate in (cache, Path(str(cache) + '.npy')):
            Path(candidate).unlink(missing_ok=True)
    yield


def reported(path):
    seen = []
    peaks = compute_peaks(path, num_peaks=4000,
                          progress_callback=lambda pct: seen.append(pct))
    assert peaks is not None
    return seen


def test_the_file_really_has_no_frame_count(wav_without_a_frame_count):
    """Guard the premise: if PyAV starts counting WAV frames this
    test stops testing the broken path."""
    with av.open(wav_without_a_frame_count) as container:
        stream = next(s for s in container.streams if s.type == 'audio')
        assert not stream.frames
        assert stream.duration                  # but duration is there


def test_progress_is_reported_more_than_once(wav_without_a_frame_count):
    assert len(reported(wav_without_a_frame_count)) > 2


def test_progress_gets_most_of_the_way_before_the_end(
        wav_without_a_frame_count):
    """It used to stop at 42% on a file this length, then jump."""
    during = [p for p in reported(wav_without_a_frame_count) if p <= 90]
    assert during, 'nothing reported during the decode'
    assert max(during) >= 80, max(during)


def test_progress_never_goes_backwards(wav_without_a_frame_count):
    seen = reported(wav_without_a_frame_count)
    assert seen == sorted(seen), seen


def test_progress_stays_in_range(wav_without_a_frame_count):
    seen = reported(wav_without_a_frame_count)
    assert all(0 <= p <= 100 for p in seen), seen
    assert seen[-1] == 100


def test_the_decode_itself_never_claims_to_be_finished(
        wav_without_a_frame_count):
    """90 is the cap while decoding; 95 and 100 come after."""
    seen = reported(wav_without_a_frame_count)
    assert seen[-2:] == [95, 100]
    assert all(p <= 90 for p in seen[:-2])
