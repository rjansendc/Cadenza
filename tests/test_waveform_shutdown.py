"""
Closing the window while waveforms are still decoding.

Nothing stopped the waveform queue on the way out, so Qt tore down
threads that were still reading audio:

    QThread: Destroyed while thread '' is still running

A waveform is disposable — it is recomputed or read from cache next
time — so the decode is abandoned rather than waited out.
"""

import fractions
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import numpy as np
import av

from media.waveform import compute_peaks

RATE  = 48000
CHUNK = 1024          # small packets, so progress is reported often


@pytest.fixture(scope='module')
def long_audio(tmp_path_factory):
    """Enough audio frames that the decode loop reports progress."""
    path = str(tmp_path_factory.mktemp('media') / 'long.wav')
    samples = (np.sin(2 * np.pi * 220
                      * np.arange(RATE * 4) / RATE)
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
def no_cache(long_audio):
    from pathlib import Path
    from media.waveform import get_cache_path
    for index in (0, 1):
        for candidate in (get_cache_path(long_audio, index),
                          Path(str(get_cache_path(long_audio, index))
                               + '.npy')):
            Path(candidate).unlink(missing_ok=True)
    yield


# ── the decode can be abandoned ───────────────────────────────

def test_cancel_is_asked_more_often_than_progress_is_reported(long_audio):
    """Why cancelling cannot ride on the progress callback: progress
    is reported every 50 audio frames, and this four-second file
    decodes as fewer frames than that — PyAV hands back large frames,
    so the decode loop reports nothing at all. Overloading progress
    meant the cancel was never seen."""
    progress, asked = [], []
    compute_peaks(long_audio, num_peaks=200,
                  progress_callback=lambda pct: progress.append(pct),
                  cancel_callback=lambda: asked.append(1) and False)
    assert len(asked) > len(progress)


def test_a_truthy_cancel_abandons_the_decode(long_audio):
    """The signal the worker uses to stop."""
    assert compute_peaks(long_audio, num_peaks=200,
                         cancel_callback=lambda: True) is None


def test_a_falsy_cancel_decodes_as_normal(long_audio):
    peaks = compute_peaks(long_audio, num_peaks=200,
                          cancel_callback=lambda: False)
    assert peaks is not None
    assert peaks.shape == (4, 200)


def test_no_cancel_callback_at_all_still_works(long_audio):
    """Every existing caller passes only progress."""
    peaks = compute_peaks(long_audio, num_peaks=200,
                          progress_callback=lambda pct: None)
    assert peaks is not None


def test_abandoning_writes_no_cache(long_audio):
    """A half-read file must not be cached as the whole waveform."""
    from media.waveform import load_peaks
    compute_peaks(long_audio, num_peaks=200,
                  cancel_callback=lambda: True)
    assert load_peaks(long_audio, 0) is None


# ── the queue lets go on shutdown ─────────────────────────────

def test_shutdown_drops_work_that_had_not_started(long_audio):
    pytest.importorskip('PySide6.QtWidgets')
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from media.waveform_worker import _WaveformQueue

    queue = _WaveformQueue()
    queue.pause()                       # nothing starts
    queue.submit(long_audio, 0)
    queue.submit(long_audio, 1)
    assert queue.busy
    queue.shutdown()
    assert not queue.busy


def test_shutdown_waits_for_a_running_decode(long_audio):
    pytest.importorskip('PySide6.QtWidgets')
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from media.waveform_worker import _WaveformQueue

    queue = _WaveformQueue()
    queue.submit(long_audio, 0)
    workers = list(queue._workers.values())
    assert workers, 'nothing started'
    queue.shutdown()
    # no thread is left running and unreferenced — the condition Qt
    # complains about
    for worker in workers:
        assert worker.isFinished() or worker in queue._retired.values()


def test_a_cancelled_worker_reports_no_peaks(long_audio):
    """It must not deliver a half-read waveform as a finished one."""
    pytest.importorskip('PySide6.QtWidgets')
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from media.waveform_worker import WaveformWorker

    worker = WaveformWorker(long_audio)
    delivered = []
    worker.completed.connect(
        lambda f, results: delivered.append(results))
    worker.cancel()                     # before it even starts
    worker.start()
    worker.wait(10000)
    QApplication.processEvents()
    assert delivered == []


def test_an_uncancelled_worker_still_delivers(long_audio):
    pytest.importorskip('PySide6.QtWidgets')
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from media.waveform_worker import WaveformWorker

    worker = WaveformWorker(long_audio)
    delivered = []
    worker.completed.connect(
        lambda f, results: delivered.append(results))
    worker.start()
    worker.wait(20000)
    QApplication.processEvents()
    assert len(delivered) == 1
    assert delivered[0].get(0) is not None     # the file's one stream
