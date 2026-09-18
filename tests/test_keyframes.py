"""
Tests for effect parameter keyframes.

Keyframes live in clip.envelopes under "<effect_id>.<param>" and are
always evaluated at the clip-local frame, so animation travels with a
clip when it is moved along the timeline.

No files, no GPU, no UI needed.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

try:                       # Qt is present on the dev machine, not in CI
    import PySide6.QtCore  # noqa: F401
    HAVE_QT = True
except Exception:          # missing module, or missing system libraries
    HAVE_QT = False

requires_qt = pytest.mark.skipif(
    not HAVE_QT, reason="core.undo imports PySide6")

import effects  # trigger registrations
from core.clip import Clip
from core.clip_renderer import ClipRenderer


def make_clip(**kwargs) -> Clip:
    defaults = dict(
        filepath='test.mp4',
        has_video=True,
        has_audio=False,
        source_frames=1000,
        source_fps=30.0,
        source_width=1920,
        source_height=1080,
    )
    defaults.update(kwargs)
    return Clip(**defaults)


def test_param_starts_static():
    clip = make_clip()
    assert not clip.is_param_animated('motion', 'scale')
    assert clip.get_param_at('motion', 'scale', 0) == 100.0


def test_keyframe_interpolates():
    clip = make_clip()
    clip.set_param_keyframe('motion', 'scale', 0, 100.0)
    clip.set_param_keyframe('motion', 'scale', 10, 200.0)

    assert clip.is_param_animated('motion', 'scale')
    assert clip.get_param_at('motion', 'scale', 0) == 100.0
    assert clip.get_param_at('motion', 'scale', 5) == 150.0
    assert clip.get_param_at('motion', 'scale', 10) == 200.0


def test_value_holds_outside_keyframe_range():
    clip = make_clip()
    clip.set_param_keyframe('motion', 'position_x', 10, 500.0)
    clip.set_param_keyframe('motion', 'position_x', 20, 900.0)

    assert clip.get_param_at('motion', 'position_x', 0) == 500.0
    assert clip.get_param_at('motion', 'position_x', 99) == 900.0


def test_has_keyframe_at():
    clip = make_clip()
    clip.set_param_keyframe('motion', 'rotation', 7, 45.0)

    assert clip.has_keyframe_at('motion', 'rotation', 7)
    assert not clip.has_keyframe_at('motion', 'rotation', 8)


def test_removing_last_keyframe_restores_static_value():
    clip = make_clip()
    motion = clip.get_effect('motion')
    motion.set('scale', 80.0)

    clip.set_param_keyframe('motion', 'scale', 5, 150.0)
    assert clip.get_param_at('motion', 'scale', 5) == 150.0

    clip.remove_param_keyframe('motion', 'scale', 5)
    assert not clip.is_param_animated('motion', 'scale')
    assert clip.get_param_at('motion', 'scale', 5) == 80.0
    # the envelope itself is gone, not left empty
    assert 'motion.scale' not in clip.envelopes


def test_keyframe_on_same_frame_replaces():
    clip = make_clip()
    clip.set_param_keyframe('motion', 'scale', 3, 120.0)
    clip.set_param_keyframe('motion', 'scale', 3, 140.0)

    env = clip.envelopes['motion.scale']
    assert len(env.keyframes) == 1
    assert clip.get_param_at('motion', 'scale', 3) == 140.0


def test_renderer_reports_animated_motion():
    clip = make_clip(start_frame=100)
    clip.set_param_keyframe('motion', 'scale', 0, 100.0)
    clip.set_param_keyframe('motion', 'scale', 10, 200.0)
    r = ClipRenderer(clip)

    # keyframes are clip-local: timeline 105 is local frame 5
    assert r.get_motion_at(100)['scale'] == 100.0
    assert r.get_motion_at(105)['scale'] == 150.0
    assert r.get_motion_at(110)['scale'] == 200.0


def test_animation_travels_with_the_clip():
    clip = make_clip(start_frame=0)
    clip.set_param_keyframe('motion', 'scale', 0, 100.0)
    clip.set_param_keyframe('motion', 'scale', 10, 200.0)
    r = ClipRenderer(clip)
    before = r.get_motion_at(5)['scale']

    clip.start_frame = 500
    after = ClipRenderer(clip).get_motion_at(505)['scale']

    assert before == after == 150.0


def test_static_params_still_returned():
    clip = make_clip()
    motion = clip.get_effect('motion')
    motion.set('rotation', -2.0)
    motion.set('uniform_scale', False)
    motion.set('scale_x', 150.0)
    r = ClipRenderer(clip)

    m = r.get_motion_at(0)
    assert m['rotation'] == -2.0
    assert m['scale_x'] == 150.0
    assert m['uniform_scale'] is False   # switches are never keyframed


def test_keyframes_survive_a_save_load_round_trip(tmp_path):
    from core.project import Project
    from core.project_io import save_project, load_project

    project = Project()
    clip = make_clip()
    clip.set_param_keyframe('motion', 'scale', 0, 100.0)
    clip.set_param_keyframe('motion', 'scale', 12, 175.0)
    project.clips[clip.id] = clip

    path = str(tmp_path / 'kf.veproj')
    assert save_project(project, path)

    loaded = load_project(path)
    reloaded = loaded.clips[clip.id]
    assert reloaded.is_param_animated('motion', 'scale')
    assert reloaded.get_param_at('motion', 'scale', 6) == 137.5


# ── dragging markers on the timeline ──────────────────────────────

def test_keyframe_frames_lists_every_animated_param():
    clip = make_clip()
    clip.set_param_keyframe('motion', 'scale', 0, 100.0)
    clip.set_param_keyframe('motion', 'position_x', 0, 960.0)
    clip.set_param_keyframe('motion', 'scale', 20, 150.0)

    # frame 0 carries two parameters but is one marker
    assert clip.keyframe_frames('motion') == [0, 20]


def test_move_keyframes_retimes_every_param_on_that_frame():
    clip = make_clip()
    clip.set_param_keyframe('motion', 'scale', 10, 150.0)
    clip.set_param_keyframe('motion', 'rotation', 10, 30.0)
    clip.set_param_keyframe('motion', 'scale', 40, 200.0)

    overwritten = clip.move_keyframes(10, 25, 'motion')

    assert overwritten == {}
    assert clip.keyframe_frames('motion') == [25, 40]
    assert clip.get_param_at('motion', 'scale', 25) == 150.0
    assert clip.get_param_at('motion', 'rotation', 25) == 30.0


def test_move_onto_another_keyframe_reports_what_it_replaced():
    clip = make_clip()
    clip.set_param_keyframe('motion', 'scale', 5, 120.0)
    clip.set_param_keyframe('motion', 'scale', 30, 180.0)

    overwritten = clip.move_keyframes(5, 30, 'motion')

    assert overwritten == {'motion.scale': 180.0}
    assert clip.keyframe_frames('motion') == [30]
    assert clip.get_param_at('motion', 'scale', 30) == 120.0


@requires_qt
def test_move_keyframes_undo_restores_position_and_overwritten():
    from core.undo import MoveKeyframesCommand
    clip = make_clip()
    clip.set_param_keyframe('motion', 'scale', 5, 120.0)
    clip.set_param_keyframe('motion', 'scale', 30, 180.0)

    cmd = MoveKeyframesCommand(clip, 'motion', 5, 30, {})
    cmd.redo()
    assert clip.keyframe_frames('motion') == [30]

    cmd.undo()
    assert clip.keyframe_frames('motion') == [5, 30]
    assert clip.get_param_at('motion', 'scale', 5) == 120.0
    assert clip.get_param_at('motion', 'scale', 30) == 180.0


@requires_qt
def test_push_can_record_a_change_already_made():
    from core.undo import UndoStack, MoveKeyframesCommand
    clip = make_clip()
    clip.set_param_keyframe('motion', 'scale', 5, 120.0)
    stack = UndoStack()

    # what a live drag does: move first, make it undoable afterwards
    overwritten = clip.move_keyframes(5, 18, 'motion')
    stack.push(MoveKeyframesCommand(clip, 'motion', 5, 18, overwritten),
               execute=False)
    assert clip.keyframe_frames('motion') == [18]

    stack.undo()
    assert clip.keyframe_frames('motion') == [5]


# ── opacity / volume / pan keyframes (envelope units differ) ──────

def test_opacity_keyframes_convert_percent_to_envelope_units():
    clip = make_clip()
    clip.set_param_keyframe('opacity', 'opacity', 0, 100.0)
    clip.set_param_keyframe('opacity', 'opacity', 10, 0.0)

    # panel units coming back out
    assert clip.get_param_at('opacity', 'opacity', 5) == 50.0
    # renderer units going in
    assert clip.get_opacity_at(0) == 1.0
    assert clip.get_opacity_at(5) == 0.5
    assert clip.get_opacity_at(10) == 0.0


def test_volume_keyframes_convert_db_to_linear():
    from effects.audio.volume import db_to_linear
    clip = make_clip(has_audio=True)
    clip.set_param_keyframe('volume', 'volume_db', 0, 0.0)
    clip.set_param_keyframe('volume', 'volume_db', 10, -6.0)

    assert clip.get_volume_at(0) == 1.0
    assert abs(clip.get_volume_at(10) - db_to_linear(-6.0)) < 1e-9
    assert abs(clip.get_param_at('volume', 'volume_db', 10) + 6.0) < 1e-9


def test_pan_keyframes_convert_percent_to_unit_range():
    clip = make_clip(has_audio=True)
    clip.set_param_keyframe('pan', 'pan', 0, -100.0)
    clip.set_param_keyframe('pan', 'pan', 10, 100.0)

    r = ClipRenderer(clip)
    assert r.get_pan_at(0) == -1.0
    assert r.get_pan_at(5) == 0.0
    assert clip.get_param_at('pan', 'pan', 10) == 100.0


def test_removing_a_legacy_keyframe_keeps_its_flat_envelope():
    clip = make_clip()
    clip.set_param_keyframe('opacity', 'opacity', 4, 50.0)
    clip.remove_param_keyframe('opacity', 'opacity', 4)

    # the envelope carries the clip's flat opacity, so it must survive
    assert 'opacity' in clip.envelopes
    assert not clip.is_param_animated('opacity', 'opacity')
    assert clip.get_opacity_at(4) == 1.0


def test_markers_cover_every_parameter():
    clip = make_clip(has_audio=True)
    clip.set_param_keyframe('motion', 'scale', 5, 120.0)
    clip.set_param_keyframe('opacity', 'opacity', 30, 0.0)
    clip.set_param_keyframe('volume', 'volume_db', 30, -6.0)

    assert clip.keyframe_frames() == [5, 30]
    assert clip.keyframe_frames('motion') == [5]
    assert clip.keyframe_frames('opacity') == [30]


def test_dragging_a_marker_moves_mixed_parameters_together():
    clip = make_clip(has_audio=True)
    clip.set_param_keyframe('motion', 'scale', 12, 150.0)
    clip.set_param_keyframe('opacity', 'opacity', 12, 25.0)

    clip.move_keyframes(12, 40)

    assert clip.keyframe_frames() == [40]
    assert clip.get_param_at('motion', 'scale', 40) == 150.0
    assert clip.get_param_at('opacity', 'opacity', 40) == 25.0
