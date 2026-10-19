"""
Stretching a still from either edge.

A still has no source to run out of, so both its edges should move
freely. The left edge was treated like footage — clamped at in_point 0
— so a slide dropped at frame 600 could never be made to start
earlier; you had to move the clip and re-stretch the right side.

Footage keeps the old rule: it can only give back frames it has.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # noqa: F401

from core.clip import Clip, ClipType

pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtWidgets import (                        # noqa: E402
    QApplication, QGraphicsScene, QGraphicsSceneMouseEvent)
from PySide6.QtCore import Qt, QEvent, QPointF, QRectF  # noqa: E402

from ui.app_state import AppState                      # noqa: E402
from ui.widgets.clip_item import ClipItem              # noqa: E402

VIEW_W = 1200.0


@pytest.fixture(scope='module')
def qapp():
    yield QApplication.instance() or QApplication([])


def build(qapp, still: bool, start=600, duration=299, in_point=0):
    state = AppState()
    state.set_view_width(VIEW_W)
    state.total_frames = 3000
    clip = Clip(
        filepath='slide1.png' if still else 'cam1.mp4',
        clip_type=ClipType.IMAGE if still else ClipType.VIDEO,
        has_video=True, has_audio=False,
        source_width=1920, source_height=1080, source_fps=29.97,
        source_frames=3000,
        track=0, start_frame=start,
        in_point=in_point, out_point=in_point + duration,
    )
    scene = QGraphicsScene()
    scene.setSceneRect(QRectF(0, 0, VIEW_W, 40))
    item = ClipItem(clip, state, VIEW_W)
    scene.addItem(item)
    item.update_geometry_flat()
    return item, scene, state


def drag_edge(item, edge, dx):
    """Press that edge, move dx pixels, release."""
    rect = item.rect()
    x = rect.left() + 1 if edge == 'left' else rect.right() - 1
    for kind, at in (
        (QEvent.Type.GraphicsSceneMousePress,   x),
        (QEvent.Type.GraphicsSceneMouseMove,    x + dx),
        (QEvent.Type.GraphicsSceneMouseRelease, x + dx),
    ):
        ev = QGraphicsSceneMouseEvent(kind)
        ev.setPos(QPointF(at, 32))
        ev.setScenePos(QPointF(at, 32))
        ev.setButton(Qt.MouseButton.LeftButton)
        ev.setButtons(
            Qt.MouseButton.LeftButton
            if kind != QEvent.Type.GraphicsSceneMouseRelease
            else Qt.MouseButton.NoButton)
        {QEvent.Type.GraphicsSceneMousePress:   item.mousePressEvent,
         QEvent.Type.GraphicsSceneMouseMove:    item.mouseMoveEvent,
         QEvent.Type.GraphicsSceneMouseRelease: item.mouseReleaseEvent,
         }[kind](ev)


# ── stills ────────────────────────────────────────────────────

def test_a_still_extends_from_its_left_edge(qapp):
    item, _scene, _state = build(qapp, still=True)
    clip = item.clip
    end_before = clip.start_frame + clip.duration

    drag_edge(item, 'left', -60)

    assert clip.start_frame < 600          # it starts earlier now
    assert clip.duration > 299             # and runs longer
    assert clip.start_frame + clip.duration == end_before   # right edge held


def test_the_left_edge_stops_at_the_start_of_the_timeline(qapp):
    item, _scene, _state = build(qapp, still=True, start=100)
    clip = item.clip
    end_before = clip.start_frame + clip.duration

    drag_edge(item, 'left', -400)          # far past frame 0

    assert clip.start_frame == 0
    assert clip.start_frame + clip.duration == end_before


def test_dragging_the_left_edge_right_shortens_it(qapp):
    item, _scene, _state = build(qapp, still=True)
    clip = item.clip
    end_before = clip.start_frame + clip.duration

    drag_edge(item, 'left', 40)

    assert clip.start_frame > 600
    assert clip.duration < 299
    assert clip.start_frame + clip.duration == end_before


def test_a_still_never_collapses_to_nothing(qapp):
    item, _scene, _state = build(qapp, still=True)
    clip = item.clip
    drag_edge(item, 'left', 400)           # past its own right edge
    assert clip.duration >= 1


def test_the_right_edge_still_extends_freely(qapp):
    item, _scene, _state = build(qapp, still=True)
    clip = item.clip
    start_before = clip.start_frame
    drag_edge(item, 'right', 200)
    assert clip.duration > 299
    assert clip.start_frame == start_before


def test_extending_a_still_leftwards_is_one_undo_step(qapp):
    from core.undo import undo_stack
    item, _scene, _state = build(qapp, still=True)
    clip = item.clip
    before = (clip.start_frame, clip.duration)

    depth = len(undo_stack._stack)
    drag_edge(item, 'left', -60)
    assert len(undo_stack._stack) == depth + 1
    assert undo_stack.undo_description == 'Trim Clip'

    undo_stack.undo()
    assert (clip.start_frame, clip.duration) == before


# ── footage keeps the old rule ────────────────────────────────

def test_footage_cannot_be_extended_past_its_first_frame(qapp):
    """There is no source before frame 0 to reveal."""
    item, _scene, _state = build(qapp, still=False, in_point=0)
    clip = item.clip
    before = (clip.start_frame, clip.duration)

    drag_edge(item, 'left', -60)

    assert (clip.start_frame, clip.duration) == before


def test_footage_with_handles_gives_them_back(qapp):
    """Trimmed-in footage can be pulled back out to the left."""
    item, _scene, _state = build(qapp, still=False, in_point=500)
    clip = item.clip

    drag_edge(item, 'left', -60)

    assert clip.in_point < 500             # earlier into the source
    assert clip.start_frame < 600          # and earlier on the timeline
    assert clip.duration > 299
