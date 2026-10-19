"""
What a click on a clip means.

A 40px row packs four targets into the same few pixels: a trim zone at
each edge, keyframe markers, and the opacity rubber band. The trim
zones were a fixed 10px tested left-first, so on a clip drawn narrower
than 20px every click read as a left trim and trying to stretch a short
clip moved it instead. The rubber band runs the full width and sits
about a quarter down, so it crossed both zones and took the click first.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # noqa: F401

from core.clip import Clip, ClipType

pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtWidgets import QApplication, QGraphicsScene  # noqa: E402
from PySide6.QtCore import QPointF, QRectF                  # noqa: E402

from ui.app_state import AppState                           # noqa: E402
from ui.widgets.clip_item import ClipItem                   # noqa: E402

VIEW_W = 1200.0


@pytest.fixture(scope='module')
def qapp():
    yield QApplication.instance() or QApplication([])


def make_item(qapp, width_px):
    """A ClipItem drawn `width_px` wide, in a live scene."""
    state = AppState()
    state.set_view_width(VIEW_W)
    state.total_frames = 5400
    frames = max(1, int(round(width_px / state.px_per_frame)))
    clip = Clip(filepath='slide.png', clip_type=ClipType.IMAGE,
                has_video=True, has_audio=False,
                source_frames=frames * 4, source_fps=29.97,
                track=0, start_frame=0, in_point=0, out_point=frames)
    scene = QGraphicsScene()
    scene.setSceneRect(QRectF(0, 0, VIEW_W, 40))
    item = ClipItem(clip, state, VIEW_W)
    scene.addItem(item)
    item.update_geometry_flat()
    return item, scene, state       # callers must hold all three


@pytest.fixture
def wide(qapp):
    item, scene, state = make_item(qapp, 400.0)
    yield item


@pytest.fixture
def narrow(qapp):
    item, scene, state = make_item(qapp, 12.0)
    yield item


def test_a_wide_clip_has_edges_and_a_middle(wide):
    rect = wide.rect()
    assert wide._trim_edge_at(QPointF(rect.left() + 2, 20)) == 'left'
    assert wide._trim_edge_at(QPointF(rect.right() - 2, 20)) == 'right'
    assert wide._trim_edge_at(QPointF(rect.center().x(), 20)) is None


def test_a_narrow_clip_keeps_a_middle_to_drag_by(narrow):
    """Every click used to read as 'left'."""
    rect = narrow.rect()
    assert rect.width() < 20          # narrower than two fixed zones
    assert narrow._trim_edge_at(QPointF(rect.center().x(), 20)) is None


def test_the_right_edge_of_a_narrow_clip_is_reachable(narrow):
    rect = narrow.rect()
    assert narrow._trim_edge_at(QPointF(rect.right() - 0.5, 20)) == 'right'
    assert narrow._trim_edge_at(QPointF(rect.left() + 0.5, 20)) == 'left'


def test_the_zone_never_takes_more_than_a_third(wide, narrow):
    """Measured against boundingRect, which is what the hit test
    compares against (it carries the pen width)."""
    for item in (wide, narrow):
        third = item.boundingRect().width() / 3.0
        assert item._trim_zone_width() <= third + 1e-6
        assert item._trim_zone_width() <= item.TRIM_ZONE


def test_the_rubber_band_does_not_steal_an_edge_click(wide):
    """The band's y crosses the trim zones; the edge must win."""
    rect  = wide.rect()
    env_y = wide._envelope_y(rect)
    assert wide._near_envelope(QPointF(rect.center().x(), env_y)) is True
    assert wide._near_envelope(QPointF(rect.left() + 2, env_y)) is False
    assert wide._near_envelope(QPointF(rect.right() - 2, env_y)) is False


def test_the_rubber_band_still_works_across_the_body(wide):
    rect  = wide.rect()
    env_y = wide._envelope_y(rect)
    for frac in (0.25, 0.5, 0.75):
        x = rect.left() + rect.width() * frac
        assert wide._near_envelope(QPointF(x, env_y)) is True


def test_audio_clips_have_no_opacity_band(qapp):
    state = AppState()
    state.set_view_width(VIEW_W)
    clip = Clip(filepath='a.wav', clip_type=ClipType.AUDIO,
                has_video=False, has_audio=True,
                source_frames=600, source_fps=29.97,
                track=0, start_frame=0, out_point=600)
    scene = QGraphicsScene()
    item = ClipItem(clip, state, VIEW_W)
    scene.addItem(item)
    assert item._near_envelope(QPointF(10, 20)) is False
