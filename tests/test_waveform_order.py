"""
Which waveform gets decoded first, and saying when one is waiting.

The cost of a waveform is the walk across its container, so a 10 MB
WAV is done in moments while a 4K movie holds a slot for as long as
it takes to read the whole file. Two slots, taken in the order they
were asked for, meant a WAV dropped after a movie drew nothing until
the movie finished.

And nothing said it was waiting. The drop message is set after the
clips are drawn, so it replaced the status the canvas had just put
there: the status bar read "Added: a.wav -> 0V + 1A clips linked" and
then stayed that way, looking as though waveforms had stopped working
altogether.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # noqa: F401

QtWidgets = pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtWidgets import QApplication        # noqa: E402

from media.waveform_worker import _WaveformQueue   # noqa: E402


@pytest.fixture(scope='module')
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def files(tmp_path):
    """Three files of very different sizes."""
    sizes = {'movie.mp4': 400_000, 'take.wav': 1_000, 'other.mkv': 90_000}
    made = {}
    for name, size in sizes.items():
        path = tmp_path / name
        path.write_bytes(b'\0' * size)
        made[name] = str(path)
    return made


@pytest.fixture
def queue(qapp):
    q = _WaveformQueue()
    q.pause()               # hold everything in the pending list
    yield q
    q.shutdown()


# ── order ─────────────────────────────────────────────────────

def test_the_smallest_file_is_taken_first(queue, files):
    queue.submit(files['movie.mp4'])
    queue.submit(files['take.wav'])
    queue.submit(files['other.mkv'])
    queue._pending.sort(key=queue._weight)
    assert queue._pending[0] == files['take.wav']


def test_order_asked_for_does_not_decide_it(queue, files):
    """The WAV went in last and still goes first."""
    for name in ('movie.mp4', 'other.mkv', 'take.wav'):
        queue.submit(files[name])
    queue._pending.sort(key=queue._weight)
    assert [os.path.basename(p) for p in queue._pending] == [
        'take.wav', 'other.mkv', 'movie.mp4']


def test_a_missing_file_does_not_break_the_sort(queue, files):
    queue.submit('/nonexistent/gone.wav')
    queue.submit(files['movie.mp4'])
    queue._pending.sort(key=queue._weight)       # must not raise
    assert len(queue._pending) == 2


def test_a_file_is_only_queued_once(queue, files):
    queue.submit(files['take.wav'], 0)
    queue.submit(files['take.wav'], 1)
    queue.submit(files['take.wav'], 2)
    assert queue._pending.count(files['take.wav']) == 1


# ── knowing a job is waiting ──────────────────────────────────

def test_a_held_submission_reports_as_waiting(queue, files):
    queue.submit(files['take.wav'])
    assert queue.is_waiting(files['take.wav'])
    assert not queue.is_running(files['take.wav'])


def test_a_file_never_asked_for_is_neither(queue, files):
    assert not queue.is_waiting(files['movie.mp4'])
    assert not queue.is_running(files['movie.mp4'])


def test_a_started_job_reports_as_running_not_waiting(qapp, files):
    q = _WaveformQueue()
    try:
        q.submit(files['take.wav'])          # starts at once
        assert q.is_running(files['take.wav'])
        assert not q.is_waiting(files['take.wav'])
    finally:
        q.shutdown()


def test_work_beyond_the_slots_waits(qapp, files, tmp_path):
    """Two at a time: the third waits, and says so."""
    q = _WaveformQueue()
    try:
        extra = tmp_path / 'fourth.wav'
        extra.write_bytes(b'\0' * 2_000)
        for path in (files['movie.mp4'], files['other.mkv'],
                     files['take.wav'], str(extra)):
            q.submit(path)
        assert len(q._workers) == q.MAX_CONCURRENT
        assert any(q.is_waiting(p) for p in
                   (files['movie.mp4'], files['other.mkv'],
                    files['take.wav'], str(extra)))
    finally:
        q.shutdown()
