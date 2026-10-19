"""
Setting a clip's level moves its whole automation curve.

Envelope.set_default computed its delta *after* overwriting
default_value, so the delta was always zero and keyframes never moved.
Nothing called it either — every writer poked default_value directly,
which value_at ignores once keyframes exist, so dragging the rubber
band on a keyframed clip did nothing at all.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # noqa: F401

from core.clip import Clip, ClipType
from core.envelope import Envelope, PARAM_RANGES


def curve(param='opacity', default=1.0, points=((0, 0.2), (100, 0.6))):
    env = Envelope(param=param, default_value=default)
    for frame, value in points:
        env.add_keyframe(frame, value)
    return env


def test_flat_envelope_just_takes_the_value():
    env = Envelope(param='opacity', default_value=1.0)
    env.set_default(0.4)
    assert env.default_value == 0.4


def test_keyframes_move_with_the_level():
    env = curve(default=0.5)
    env.set_default(0.7)           # +0.2
    assert [kf.value for kf in env.keyframes] == pytest.approx([0.4, 0.8])
    assert env.default_value == 0.7


def test_the_curve_keeps_its_shape():
    env = curve(default=0.5, points=((0, 0.2), (50, 0.9), (100, 0.4)))
    before = [kf.value for kf in env.keyframes]
    spread_before = max(before) - min(before)
    env.set_default(0.55)
    after = [kf.value for kf in env.keyframes]
    assert abs((max(after) - min(after)) - spread_before) < 1e-9


def test_a_shift_that_would_overflow_is_limited_not_flattened():
    """Clamping each keyframe on its own would pile them on the limit
    and the shape would never come back."""
    env = curve(default=0.5, points=((0, 0.2), (100, 0.9)))
    env.set_default(1.0)           # +0.5 would push 0.9 to 1.4
    values = [kf.value for kf in env.keyframes]
    assert max(values) == 1.0                      # stopped at the top
    assert abs((values[1] - values[0]) - 0.7) < 1e-9   # shape intact


def test_shift_down_stops_at_the_floor():
    env = curve(default=0.5, points=((0, 0.2), (100, 0.9)))
    env.set_default(0.0)
    values = [kf.value for kf in env.keyframes]
    assert min(values) == 0.0
    assert abs((values[1] - values[0]) - 0.7) < 1e-9


def test_pan_may_go_negative():
    """The old clamp was 0..2 for everything, which pinned pan to the
    right-hand half."""
    assert PARAM_RANGES['pan'] == (-1.0, 1.0)
    env = curve(param='pan', default=0.0, points=((0, 0.0), (50, 0.5)))
    env.set_default(-0.5)
    assert [kf.value for kf in env.keyframes] == pytest.approx([-0.5, 0.0])
    assert env.default_value == -0.5


def test_volume_reaches_its_ceiling_not_opacitys():
    assert PARAM_RANGES['volume'] == (0.0, 2.0)
    env = Envelope(param='volume', default_value=1.0)
    env.set_default(1.8)
    assert env.default_value == 1.8


def test_effect_envelopes_are_not_clamped():
    """motion.scale is a percentage; it has no business being capped
    at 1.0."""
    env = Envelope(param='motion.scale', default_value=100.0)
    assert env.value_range == (None, None)
    env.set_default(250.0)
    assert env.default_value == 250.0


def video_audio_clip():
    return Clip(filepath='cam1.mp4', clip_type=ClipType.VIDEO_AUDIO,
                has_video=True, has_audio=True,
                source_frames=600, source_fps=29.97)


def test_clip_set_opacity_moves_the_curve():
    clip = video_audio_clip()
    clip.set_param_keyframe('opacity', 'opacity', 0,   100.0)
    clip.set_param_keyframe('opacity', 'opacity', 100,  50.0)
    clip.set_opacity(0.8)          # rubber band dragged down
    values = [kf.value for kf in clip.envelopes['opacity'].keyframes]
    assert values == pytest.approx([0.8, 0.3])


def test_clip_set_volume_moves_the_curve():
    clip = video_audio_clip()
    env = clip.envelopes['volume']
    env.add_keyframe(0,  0.5)
    env.add_keyframe(50, 1.0)
    clip.set_volume(1.25)
    assert [kf.value for kf in env.keyframes] == pytest.approx([0.75, 1.25])


def test_the_level_drag_is_undoable_and_restores_the_curve():
    from core.undo import UndoStack, SetOpacityCommand
    clip = video_audio_clip()
    clip.set_param_keyframe('opacity', 'opacity', 0,   80.0)
    clip.set_param_keyframe('opacity', 'opacity', 100, 40.0)
    before = [kf.value for kf in clip.envelopes['opacity'].keyframes]

    stack = UndoStack()
    stack.push(SetOpacityCommand(clip, 1.0, 0.6))      # executes
    moved = [kf.value for kf in clip.envelopes['opacity'].keyframes]
    assert moved != before

    stack.undo()
    back = [kf.value for kf in clip.envelopes['opacity'].keyframes]
    assert back == pytest.approx(before)
