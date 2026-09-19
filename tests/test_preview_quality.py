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


# ── skipping effects that are doing nothing ──────────────────────

def test_fresh_effect_is_at_defaults():
    import effects
    from core.effects import EffectRegistry
    for eff_cls in EffectRegistry.all():
        eff = eff_cls()
        assert eff.is_at_defaults(), f"{eff.id} not default on creation"


def test_changed_effect_is_not_at_defaults():
    from core.effects import EffectRegistry
    lumetri = EffectRegistry.get('lumetri_color')()
    assert lumetri.is_at_defaults()
    lumetri.set('exposure', 0.5)
    assert not lumetri.is_at_defaults()


def test_setting_a_value_back_returns_to_default():
    from core.effects import EffectRegistry
    motion = EffectRegistry.get('motion')()
    default = motion.get('scale')
    motion.set('scale', 150.0)
    assert not motion.is_at_defaults()
    motion.set('scale', default)
    assert motion.is_at_defaults()


# ── anchor point ──────────────────────────────────────────────────

def anchor_offset(orig_w, anchor_x, user_scale, geom_scale=1.0,
                   src_scale=1.0):
    """The placement maths from Compositor._apply_motion."""
    scale_w = user_scale * geom_scale * src_scale
    return (orig_w / 2.0 - anchor_x) * (scale_w / src_scale)


def test_centre_anchor_does_not_move_the_picture():
    assert anchor_offset(1920, 960, 1.0) == 0.0
    assert anchor_offset(3840, 1920, 0.5) == 0.0


def test_anchor_left_edge_pushes_the_picture_right():
    # anchoring the left edge at Position puts the whole image to its
    # right, so the centre moves right by half the scaled width
    assert anchor_offset(1920, 0, 1.0) == 960.0
    assert anchor_offset(1920, 0, 0.5) == 480.0


def test_anchor_is_unaffected_by_proxy_scale():
    """A proxy frame stands in for the source; framing must not change."""
    full  = anchor_offset(3840, 1000, 0.5, src_scale=1.0)
    proxy = anchor_offset(3840, 1000, 0.5, src_scale=4.0)
    assert abs(full - proxy) < 1e-9


def test_anchor_follows_preview_quality():
    full = anchor_offset(1920, 0, 1.0, geom_scale=1.0)
    half = anchor_offset(1920, 0, 1.0, geom_scale=0.5)
    assert abs(half * 2 - full) < 1e-9


def test_motion_centres_the_anchor_for_its_source():
    from core.effects import EffectRegistry
    motion = EffectRegistry.get('motion')()
    motion.centre_anchor(3840, 2160)
    assert motion.get('anchor_x') == 1920.0
    assert motion.get('anchor_y') == 1080.0


def test_scale_to_frame_also_centres_the_anchor():
    from core.clip import Clip, ClipType
    clip = Clip(filepath='x.mp4', clip_type=ClipType.VIDEO,
                source_width=3840, source_height=2160)
    clip.scale_to_frame(1920, 1080)
    motion = clip.get_effect('motion')
    assert motion.get('scale') == 50.0
    assert (motion.get('anchor_x'), motion.get('anchor_y')) == (1920.0, 1080.0)


def test_anchor_migration_fixes_4k_clips():
    from core.clip import Clip, ClipType
    clip = Clip(filepath='x.mp4', clip_type=ClipType.VIDEO,
                source_width=3840, source_height=2160)
    motion = clip.get_effect('motion')
    motion.set('anchor_x', 960.0)      # the old default
    motion.set('anchor_y', 540.0)

    clip.migrate_anchor()
    assert (motion.get('anchor_x'), motion.get('anchor_y')) == (1920.0, 1080.0)


def test_migration_leaves_1080p_clips_alone():
    from core.clip import Clip, ClipType
    clip = Clip(filepath='x.mp4', clip_type=ClipType.VIDEO,
                source_width=1920, source_height=1080)
    motion = clip.get_effect('motion')
    clip.migrate_anchor()
    assert (motion.get('anchor_x'), motion.get('anchor_y')) == (960.0, 540.0)


def test_migration_respects_a_deliberate_anchor():
    from core.clip import Clip, ClipType
    clip = Clip(filepath='x.mp4', clip_type=ClipType.VIDEO,
                source_width=3840, source_height=2160)
    motion = clip.get_effect('motion')
    motion.set('anchor_x', 100.0)
    motion.set('anchor_y', 200.0)
    clip.migrate_anchor()
    assert (motion.get('anchor_x'), motion.get('anchor_y')) == (100.0, 200.0)


def test_changing_one_axis_does_not_move_the_other():
    """The bug: editing Anchor X also shifted the picture vertically."""
    from core.clip import Clip, ClipType
    clip = Clip(filepath='x.mp4', clip_type=ClipType.VIDEO,
                source_width=3840, source_height=2160)
    clip.scale_to_frame(1920, 1080)
    motion = clip.get_effect('motion')

    before_y = motion.get('anchor_y')
    motion.set('anchor_x', 0.0)
    assert motion.get('anchor_y') == before_y == 1080.0
    # and the vertical offset stays zero
    assert anchor_offset(2160, motion.get('anchor_y'), 0.5) == 0.0
