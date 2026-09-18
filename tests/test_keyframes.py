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
