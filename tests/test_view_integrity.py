"""
The view stays where it should.

Four ways it did not:

  - the zoom menu divided the playhead by total_frames while the view
    is measured against the scroll range, so it pulled towards a point
    well right of the playhead;
  - a left trim could give back more handles than there was room for
    and push a clip to a negative start frame;
  - the canvas scene is far wider than the viewport with the scrollbar
    hidden, so anything that scrolled the view shifted every clip away
    from the ruler with no way to see it or get back;
  - a refresh emptied each scene but left the canvas subscribed to
    app_state, so a signal arriving before collection reached deleted
    objects.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # noqa: F401

from core.clip import Clip, ClipType
from core.track import Track, TrackType

pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtWidgets import (                        # noqa: E402
    QApplication, QGraphicsScene, QGraphicsSceneMouseEvent)
from PySide6.QtCore import Qt, QEvent, QPointF, QRectF  # noqa: E402

from ui.app_state import AppState                      # noqa: E402
from ui.widgets.clip_item import ClipItem              # noqa: E402
from ui.widgets.track_header import TrackCanvas        # noqa: E402

VIEW_W = 1200.0


@pytest.fixture(scope='module')
def qapp():
    yield QApplication.instance() or QApplication([])


def state(total_frames=1794):
    st = AppState()
    st.set_view_width(VIEW_W)
    st.total_frames = total_frames
    return st


# ── the zoom anchor ───────────────────────────────────────────

class _Holder:
    """Just enough of MainWindow to call the method under test."""
    def __init__(self, app_state):
        self.app_state = app_state


def zoom_anchor(app_state):
    from ui.mainwindow import MainWindow
    return MainWindow._zoom_anchor(_Holder(app_state))


@pytest.mark.parametrize('playhead', [0, 300, 900, 1700])
def test_the_anchor_points_at_the_playhead(qapp, playhead):
    st = state()
    st.playhead_frame = playhead
    assert st.norm_to_frame(zoom_anchor(st)) == pytest.approx(
        playhead, abs=1)


def test_zooming_holds_the_playhead_still(qapp):
    """What the anchor is for."""
    st = state()
    st.playhead_frame = 900
    before = st.frame_to_pixel(900, VIEW_W)
    st.zoom_in_at_position(zoom_anchor(st), factor=0.5)
    after = st.frame_to_pixel(900, VIEW_W)
    assert abs(after - before) < 1.0


def test_the_old_denominator_really_was_wrong(qapp):
    """Guard the premise: total_frames and the scroll range differ."""
    st = state()
    st.playhead_frame = 900
    assert st.total_frames != st.scroll_frames
    old = 900 / st.total_frames
    assert abs(st.norm_to_frame(old) - 900) > 100


def test_a_playhead_off_screen_falls_back_to_the_middle(qapp):
    st = state()
    st.set_view(0.0, 0.1)
    st.playhead_frame = st.total_frames
    anchor = zoom_anchor(st)
    assert anchor == pytest.approx((st.view_start + st.view_end) / 2)


def test_an_empty_timeline_has_an_anchor(qapp):
    st = state(total_frames=0)
    assert 0.0 <= zoom_anchor(st) <= 1.0


# ── trimming at the front of the timeline ─────────────────────

def drag_left_edge(item, dx):
    rect = item.rect()
    x = rect.left() + 1
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


def footage(qapp, start_frame, in_point):
    st = state(3000)
    clip = Clip(filepath='cam1.mp4', clip_type=ClipType.VIDEO,
                has_video=True, has_audio=False,
                source_frames=3000, source_fps=29.97, track=0,
                start_frame=start_frame, in_point=in_point,
                out_point=in_point + 400)
    scene = QGraphicsScene()
    scene.setSceneRect(QRectF(0, 0, VIEW_W, 40))
    item = ClipItem(clip, st, VIEW_W)
    scene.addItem(item)
    item.update_geometry_flat()
    return item, scene, st


@pytest.mark.parametrize('start_frame,in_point', [
    (100, 500), (0, 500), (1000, 500), (50, 10), (5, 5000),
])
def test_a_left_trim_never_goes_before_zero(qapp, start_frame, in_point):
    item, _scene, _st = footage(qapp, start_frame, in_point)
    drag_left_edge(item, -600)
    assert item.clip.start_frame >= 0
    assert item.clip.in_point >= 0


def test_it_gives_back_exactly_the_room_available(qapp):
    """100 frames of timeline in front, 500 frames of handle: it may
    use 100 of them."""
    item, _scene, _st = footage(qapp, 100, 500)
    drag_left_edge(item, -600)
    assert item.clip.start_frame == 0
    assert item.clip.in_point == 400


def test_plenty_of_room_uses_all_the_handles(qapp):
    item, _scene, _st = footage(qapp, 1000, 500)
    drag_left_edge(item, -600)
    assert item.clip.in_point == 0
    assert item.clip.start_frame == 500


def test_a_clip_already_at_zero_cannot_move(qapp):
    item, _scene, _st = footage(qapp, 0, 500)
    drag_left_edge(item, -600)
    assert item.clip.start_frame == 0
    assert item.clip.in_point == 500


# ── the canvas stays put ──────────────────────────────────────

@pytest.fixture
def canvas(qapp):
    st = state()
    track = Track(TrackType.VIDEO, 0)
    view = TrackCanvas(track, st)
    view.resize(int(VIEW_W), 40)
    view.show()
    QApplication.processEvents()
    yield view
    view.detach()
    view.deleteLater()


def test_the_scene_is_wider_than_the_view(canvas):
    """Guard the premise — that is why scrolling was possible."""
    assert canvas._scene.sceneRect().width() > canvas.viewport().width()


def test_the_canvas_refuses_to_scroll_sideways(canvas):
    canvas.horizontalScrollBar().setValue(500)
    QApplication.processEvents()
    assert canvas.horizontalScrollBar().value() == 0


def test_set_h_offset_cannot_knock_it_out_of_line(canvas):
    canvas.set_h_offset(800)
    QApplication.processEvents()
    assert canvas.horizontalScrollBar().value() == 0


# ── letting go before teardown ────────────────────────────────

def test_detaching_stops_the_signals(canvas):
    canvas.detach()
    canvas._scene.clear()
    # these used to reach a canvas whose scene had been emptied
    canvas.app_state.playhead_frame = 123
    canvas.app_state.set_view(0.2, 0.4)
    QApplication.processEvents()
    assert canvas._playhead_line is None


def test_detaching_twice_is_harmless(canvas):
    canvas.detach()
    canvas.detach()


def test_refresh_detaches_every_row(qapp, tmp_path):
    """The panel tears rows down on refresh; each must let go first."""
    from core.project import Project
    from ui.panels.timeline import TimelinePanel

    st = state()
    panel = TimelinePanel(Project(), st)
    panel.resize(int(VIEW_W), 300)
    panel.show()
    QApplication.processEvents()

    old_canvases = [row.canvas for row in panel._rows.values()]
    assert old_canvases
    panel.refresh()
    QApplication.processEvents()

    for old in old_canvases:
        assert old._connected is False

    # signals now reach only the new rows
    st.playhead_frame = 77
    st.set_view(0.1, 0.5)
    QApplication.processEvents()
    panel.deleteLater()
