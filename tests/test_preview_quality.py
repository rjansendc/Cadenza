"""
Preview quality composites at a smaller size.

Motion values are in sequence pixels, so the canvas and everything
placed on it must shrink together — otherwise a clip keeps its
full-size position on a small canvas and lands in the corner.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # trigger registrations
from core.track import Sequence, SequenceSettings

torch = pytest.importorskip('torch')
from gpu.compositor import Compositor   # noqa: E402  (needs torch)


def make_compositor(width=1920, height=1080):
    seq = Sequence(name='S', settings=SequenceSettings(
        width=width, height=height, fps=29.97))
    return Compositor(seq)


def test_starts_at_full_size():
    c = make_compositor()
    assert (c.width, c.height) == (1920, 1080)
    assert c.geom_scale == 1.0


def test_half_preview_halves_canvas_and_geometry():
    c = make_compositor()
    c.set_preview_size(960, 540)
    assert (c.width, c.height) == (960, 540)
    assert c.geom_scale == 0.5


def test_quarter_preview():
    c = make_compositor()
    c.set_preview_size(480, 270)
    assert c.geom_scale == 0.25


def test_blank_frame_follows_the_canvas():
    c = make_compositor()
    c.set_preview_size(960, 540)
    assert tuple(c._blank.shape) == (540, 960, 3)


def test_going_back_to_full_size_restores_scale():
    c = make_compositor()
    c.set_preview_size(480, 270)
    c.set_preview_size(1920, 1080)
    assert c.geom_scale == 1.0
    assert tuple(c._blank.shape) == (1080, 1920, 3)


def test_sequence_size_is_remembered_not_overwritten():
    """Export reads seq_width/height to restore full quality."""
    c = make_compositor()
    c.set_preview_size(480, 270)
    assert (c.seq_width, c.seq_height) == (1920, 1080)


def test_setting_the_same_size_twice_is_a_no_op():
    c = make_compositor()
    c.set_preview_size(960, 540)
    blank = c._blank
    c.set_preview_size(960, 540)
    assert c._blank is blank      # no needless reallocation


def test_tiny_sizes_are_clamped():
    c = make_compositor()
    c.set_preview_size(1, 1)
    assert c.width >= 16 and c.height >= 16


# ── occlusion: clips hidden behind an opaque full-frame clip ──────

class FakeClip:
    def __init__(self, w=1920, h=1080):
        self.source_width, self.source_height = w, h


class FakeRenderer:
    """Just enough of ClipRenderer for _covers_canvas."""
    def __init__(self, opacity=1.0, source=(1920, 1080), **motion):
        self._opacity = opacity
        self.clip = FakeClip(*source)
        self._motion = {
            'scale': 100.0, 'scale_x': 100.0, 'uniform_scale': True,
            'rotation': 0.0, 'position_x': 960.0, 'position_y': 540.0,
            'crop_left': 0.0, 'crop_right': 0.0,
            'crop_top': 0.0, 'crop_bottom': 0.0,
        }
        self._motion.update(motion)

    def get_opacity_at(self, frame):
        return self._opacity

    def get_motion_at(self, frame):
        return self._motion


def test_full_frame_opaque_clip_covers():
    c = make_compositor()
    assert c._covers_canvas(FakeRenderer(), 0)


def test_4k_source_at_half_scale_covers_1080p():
    c = make_compositor()
    r = FakeRenderer(source=(3840, 2160), scale=50.0)
    assert c._covers_canvas(r, 0)


def test_partly_transparent_does_not_cover():
    c = make_compositor()
    assert not c._covers_canvas(FakeRenderer(opacity=0.5), 0)


def test_scaled_down_clip_does_not_cover():
    c = make_compositor()
    assert not c._covers_canvas(FakeRenderer(scale=80.0), 0)


def test_moved_clip_does_not_cover():
    c = make_compositor()
    assert not c._covers_canvas(FakeRenderer(position_x=1200.0), 0)


def test_rotated_or_cropped_never_covers():
    c = make_compositor()
    assert not c._covers_canvas(FakeRenderer(rotation=5.0), 0)
    assert not c._covers_canvas(FakeRenderer(crop_left=10.0), 0)


def test_coverage_holds_at_preview_quality():
    """Canvas and geometry shrink together, so the answer is the same."""
    c = make_compositor()
    c.set_preview_size(960, 540)
    assert c._covers_canvas(FakeRenderer(), 0)
    assert not c._covers_canvas(FakeRenderer(scale=80.0), 0)
