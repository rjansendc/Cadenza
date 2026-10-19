"""
Audio sync.

Three faults, all present since the first commit, which together made
Sync Refine useless on ordinary material:

  - the correlation envelope was built by point decimation,
    search_corr[::100], and the ±1s refine searched only around the
    peak that found. A correlation peak is a spike a few samples
    wide, so decimation kept it only when it happened to land on a
    boundary. Dense music and speech survived this — their
    correlation has a broad pedestal around the true lag that is
    still visible at one sample in a hundred, which is why concert
    footage synced correctly and this went unnoticed. Sharp
    transients have no such pedestal, and the envelope then peaked
    wherever noise put it: a clip two frames out was corrected by
    +158 frames, five seconds the wrong way.

  - the caller subtracted the analysis window from the end of the
    search region and the scan loop subtracted it again, so a scan
    only ran when the usable overlap was more than twice the window.
    With the window capped at 120s that meant nothing under four
    minutes could sync at all — it reported "no alignment found"
    however well the clips lined up;

  - the measured offset was converted to frames with int(), which
    truncates toward zero. The correlation lag is quantised to the
    analysis sample rate, so an exact 45 frame offset measures as
    -1.50150s against an exact -1.501502s, and the whole frame was
    thrown away. Every result came back one frame short.
"""

import fractions
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import numpy as np
import av

import effects  # noqa: F401

from core.clip import Clip, ClipType
from sync.sync import sync_clips_to_reference

FPS = 29.97
RATE = 48000
SECONDS = 50          # well under the four minutes that used to be needed
# How far out an eyeball alignment plausibly is. Nobody drops a clip
# five seconds off; the fine correction only has to beat that.
BY_EYE = 150          # 5 seconds
CHUNK = 1024          # small packets, as a real recording has


@pytest.fixture(scope='module')
def click_track(tmp_path_factory):
    """
    Sharp transients at irregular times over quiet noise.

    Speech and music correlate well; stationary noise does not, and a
    pure tone repeats. Clicks give one unambiguous peak.
    """
    rng = np.random.default_rng(5)
    samples = rng.normal(0, 0.02, RATE * SECONDS)
    for start in rng.choice(RATE * SECONDS - RATE, size=70, replace=False):
        length = int(rng.integers(400, 1600))
        decay = np.exp(-np.linspace(0, 6, length))
        tone = np.sin(2 * np.pi * int(rng.integers(200, 2000))
                      * np.arange(length) / RATE)
        samples[start:start + length] += tone * decay
    samples = (samples / np.abs(samples).max() * 0.8 * 32767).astype(np.int16)

    path = str(tmp_path_factory.mktemp('media') / 'clicks.wav')
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


def clip_at(path, start_frame):
    frames = int(SECONDS * FPS)
    return Clip(filepath=path, clip_type=ClipType.AUDIO,
                has_video=False, has_audio=True,
                source_fps=FPS, source_frames=frames, track=0,
                start_frame=start_frame, in_point=0, out_point=frames,
                stream_index=1)


def correction(click_track, placed, capsys=None):
    offsets = sync_clips_to_reference(
        clip_at(click_track, 0), [clip_at(click_track, placed)],
        fps=FPS, show_plot=False)
    if not offsets:
        return None
    return list(offsets.values())[0]


# ── an alignment is found at all ──────────────────────────────

def test_a_short_pair_can_sync(click_track):
    """40 seconds. This returned nothing at all before: the scan
    needed over four minutes of overlap to run once."""
    assert correction(click_track, 45) is not None


def test_identical_clips_need_no_correction(click_track):
    assert correction(click_track, 0) == 0


# ── and it is the right number ────────────────────────────────

@pytest.mark.parametrize('placed', [1, 15, 30, 45, 90, 150])
def test_the_offset_is_exact(click_track, placed):
    """Anything an editor could line up by eye lands exactly. The
    decimated envelope put 30 frames at +38 and 45 at +115 — not
    merely imprecise, the wrong direction."""
    assert correction(click_track, placed) == -placed


@pytest.mark.parametrize('placed', [2, 3, 5, 7, 11])
def test_a_peak_between_pool_boundaries_is_still_found(click_track, placed):
    """One frame at 29.97fps is 266.9 samples at the 8kHz analysis
    rate, so these lags land all over a 100 sample pool. Decimation
    found them only when the spike happened to sit on a boundary:
    2 frames came back as +158 and 5 frames as -122."""
    assert correction(click_track, placed) == -placed


def test_no_systematic_bias(click_track):
    """The old error was always +1, never -1 and never 0 — the sign of
    truncation rather than noise."""
    errors = [correction(click_track, p) + p
              for p in (15, 45, 90, BY_EYE)]
    assert errors == [0, 0, 0, 0]


# ── the conversion itself ─────────────────────────────────────

@pytest.mark.parametrize('frames', [15, 45, 150, 300, 601])
def test_rounding_survives_the_frame_rate(frames):
    """29.97 makes an exact frame count land a hair under the integer
    once it has been through seconds."""
    seconds = -frames / FPS
    assert int(round(seconds * FPS)) == -frames
    # what it used to do, for the cases where they differ
    truncated = int(seconds * FPS)
    assert truncated in (-frames, -frames + 1)
