"""
The drag itself, through a real window: release a clip over another
and it settles on a track with room instead of on top of it.

This covers the wiring — that the release handler resolves the track,
rebuilds the rows, and records the track it actually settled on so
undo puts it back. The search itself is in test_no_stacked_clips.py.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # noqa: F401

QtWidgets = pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtWidgets import QApplication        # noqa: E402
from PySide6.QtGui import QImage, QColor          # noqa: E402
from PySide6.QtCore import QPointF, Qt            # noqa: E402

V1_ROW = 2


@pytest.fixture(scope='module')
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(scope='module')
def stills(tmp_path_factory, qapp):
    folder = tmp_path_factory.mktemp('media')
    paths = []
    for i in range(2):
        image = QImage(640, 360, QImage.Format.Format_RGB888)
        image.fill(QColor(60 * i, 100, 160))
        path = folder / f'slide{i}.png'
        image.save(str(path))
        paths.append(str(path))
    return paths


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


class Release:
    """Only accept() and modifiers() are reached on the drag path."""
    def accept(self):
        pass

    def modifiers(self):
        return Qt.KeyboardModifier.NoModifier


def drop(window, index, start_frame, row=V1_ROW):
    ids = list(window.project.media_pool)
    window._on_media_dropped(ids[index], row, start_frame)
    QApplication.processEvents()


def item_for(window, clip_id):
    for row in window.timeline._rows.values():
        if clip_id in row.canvas._clip_items:
            return row.canvas._clip_items[clip_id]
    return None


def drag_to(window, clip, new_start):
    """Move a clip the way the mouse does, then release it."""
    item = item_for(window, clip.id)
    assert item is not None, 'clip has no timeline item'
    item._drag_start      = QPointF(0.0, 0.0)
    item._drag_orig_frame = clip.start_frame
    item._drag_orig_track = clip.track
    window.app_state.select_clip(clip.id)
    clip.start_frame = new_start          # the live part of the drag
    item.mouseReleaseEvent(Release())
    QApplication.processEvents()


def video(window):
    return sorted((c for c in window.project.clips.values() if c.has_video),
                  key=lambda c: (c.track, c.start_frame))


def two_clips(window):
    drop(window, 0, 0)
    length = next(iter(window.project.clips.values())).duration
    drop(window, 1, length * 3)
    first, second = video(window)[:2]
    if first.start_frame > second.start_frame:
        first, second = second, first
    return first, second, length


def stacked(window):
    """Any two clips of a kind holding the same frames on one track."""
    for a in window.project.clips.values():
        for b in window.project.clips.values():
            if a.id >= b.id or a.track != b.track:
                continue
            if bool(a.has_audio) != bool(b.has_audio):
                continue
            if (a.start_frame < b.start_frame + b.duration and
                    b.start_frame < a.start_frame + a.duration):
                return True
    return False


# ── it settles somewhere with room ────────────────────────────

def test_a_clip_released_over_another_moves_to_the_next_track(window):
    under, over, length = two_clips(window)
    drag_to(window, over, length // 2)
    assert over.track == 1                     # V2
    assert over.start_frame == length // 2     # the time it was put at
    assert under.track == 0 and under.start_frame == 0


def test_nothing_is_ever_stacked(window):
    under, over, length = two_clips(window)
    drag_to(window, over, length // 2)
    assert not stacked(window)


def test_the_clip_underneath_is_not_touched(window):
    under, over, length = two_clips(window)
    before = (under.start_frame, under.duration, under.in_point)
    drag_to(window, over, 0)
    assert (under.start_frame, under.duration, under.in_point) == before


def test_landing_clear_of_everything_keeps_the_track(window):
    under, over, length = two_clips(window)
    drag_to(window, over, length * 5)
    assert over.track == 0
    assert over.start_frame == length * 5


def test_a_move_within_a_free_stretch_of_its_own_track_is_normal(window):
    under, over, length = two_clips(window)
    drag_to(window, over, length + 5)
    assert over.track == 0


# ── undo remembers the track it settled on ────────────────────

def test_undo_returns_the_clip_to_its_own_track_and_frame(window):
    under, over, length = two_clips(window)
    origin = (over.track, over.start_frame)
    drag_to(window, over, length // 2)
    assert (over.track, over.start_frame) != origin
    window._on_undo()
    QApplication.processEvents()
    assert (over.track, over.start_frame) == origin


def test_redo_puts_it_back_on_the_track_it_settled_on(window):
    under, over, length = two_clips(window)
    drag_to(window, over, length // 2)
    settled = (over.track, over.start_frame)
    window._on_undo()
    QApplication.processEvents()
    window._on_redo()
    QApplication.processEvents()
    assert (over.track, over.start_frame) == settled


# ── no free track at all ──────────────────────────────────────

def test_with_every_track_busy_the_clip_goes_home(window):
    under, over, length = two_clips(window)
    seq = window.project.active_sequence
    del seq.video_tracks[1:]              # one video track only
    window.timeline.refresh()
    origin = (over.track, over.start_frame)
    drag_to(window, over, length // 2)
    assert (over.track, over.start_frame) == origin
    assert not stacked(window)


# ── the rows show what the project holds ──────────────────────

def test_the_timeline_items_match_the_project_after_a_nudge(window):
    under, over, length = two_clips(window)
    drag_to(window, over, length // 2)
    shown = set()
    for row in window.timeline._rows.values():
        shown |= set(row.canvas._clip_items)
    assert shown == set(window.project.clips)


def test_the_moved_clip_is_drawn_on_its_new_row(window):
    under, over, length = two_clips(window)
    drag_to(window, over, length // 2)
    item = item_for(window, over.id)
    assert item is not None
    assert item.clip.track == over.track
