"""
Tests for ClipRenderer — the temporal mapping layer.

These tests verify the core equation:
  source_time = (in_point + local_frame * speed) / fps

No files, no GPU, no UI needed.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import effects  # trigger registrations
from core.clip import Clip
from core.clip_renderer import ClipRenderer


def make_clip(**kwargs) -> Clip:
    """Helper to create a test clip."""
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


# =========================================================
# Activity
# =========================================================

def test_is_active_basic():
    clip = make_clip(start_frame=100, source_frames=200)
    clip.out_point = -1   # full clip = 200 frames
    r = ClipRenderer(clip)
    assert not r.is_active_at(99)
    assert r.is_active_at(100)
    assert r.is_active_at(299)
    assert not r.is_active_at(300)


def test_is_active_disabled():
    clip = make_clip(start_frame=0, source_frames=100)
    clip.enabled = False
    r = ClipRenderer(clip)
    assert not r.is_active_at(0)


# =========================================================
# Core mapping — no in_point, no speed
# =========================================================

def test_mapping_simple():
    """
    Simple clip: start=0, in_point=0, speed=1.0
    timeline frame N → source frame N
    """
    clip = make_clip(start_frame=0, source_frames=300)
    clip.in_point = 0
    r = ClipRenderer(clip)

    assert r.timeline_to_source_frame(0)   == 0
    assert r.timeline_to_source_frame(30)  == 30
    assert r.timeline_to_source_frame(100) == 100


def test_mapping_with_start_frame():
    """
    Clip placed at timeline frame 100.
    timeline 100 → source 0
    timeline 130 → source 30
    """
    clip = make_clip(start_frame=100, source_frames=300)
    clip.in_point = 0
    r = ClipRenderer(clip)

    assert r.timeline_to_source_frame(100) == 0
    assert r.timeline_to_source_frame(130) == 30
    assert r.timeline_to_source_frame(200) == 100


def test_mapping_with_in_point():
    """
    Clip razor-cut: in_point=50
    timeline 0 → source 50
    timeline 30 → source 80
    """
    clip = make_clip(start_frame=0, source_frames=300)
    clip.in_point  = 50
    clip.out_point = 150   # duration = 100
    r = ClipRenderer(clip)

    assert r.timeline_to_source_frame(0)  == 50
    assert r.timeline_to_source_frame(30) == 80
    assert r.timeline_to_source_frame(99) == 149


def test_mapping_after_razor_right_half():
    """
    After razor at frame 300:
    Right clip: start_frame=300, in_point=300
    timeline 300 → source 300
    timeline 350 → source 350
    """
    clip = make_clip(
        start_frame=300,
        source_frames=1000
    )
    clip.in_point  = 300
    clip.out_point = -1
    r = ClipRenderer(clip)

    assert r.timeline_to_source_frame(300) == 300
    assert r.timeline_to_source_frame(350) == 350


def test_mapping_moved_after_razor():
    """
    Right clip moved to timeline frame 500.
    in_point still 300 (from razor).
    timeline 500 → source 300
    timeline 550 → source 350
    """
    clip = make_clip(
        start_frame=500,
        source_frames=1000
    )
    clip.in_point  = 300
    clip.out_point = -1
    r = ClipRenderer(clip)

    assert r.timeline_to_source_frame(500) == 300
    assert r.timeline_to_source_frame(550) == 350


# =========================================================
# Local frame
# =========================================================

def test_local_frame():
    clip = make_clip(start_frame=200, source_frames=300)
    r = ClipRenderer(clip)

    assert r.local_frame(200) == 0
    assert r.local_frame(230) == 30
    assert r.local_frame(100) == 0   # clamps to 0


# =========================================================
# Volume envelope — local frame evaluation
# =========================================================

def test_volume_flat():
    clip = make_clip(start_frame=0, source_frames=300)
    clip.volume = 0.8
    r = ClipRenderer(clip)
    assert r.get_volume_at(0)   == 0.8
    assert r.get_volume_at(100) == 0.8


def test_volume_muted():
    clip = make_clip(start_frame=0, source_frames=300)
    clip.muted  = True
    clip.volume = 1.0
    r = ClipRenderer(clip)
    assert r.get_volume_at(0) == 0.0


def test_volume_envelope_uses_local_frame():
    """
    Volume envelope should evaluate at LOCAL frame,
    not timeline frame. Two clips from the same source
    placed at different timeline positions should both
    fade in at the same rate.
    """
    from core.envelope import Envelope, Keyframe

    clip1 = make_clip(start_frame=0,   source_frames=300)
    clip2 = make_clip(start_frame=500, source_frames=300)

    # add fade-in envelope: 0→1 over frames 0-30
    for clip in [clip1, clip2]:
        env = Envelope(param='volume', default_value=1.0)
        env.add_keyframe(0,  0.0)
        env.add_keyframe(30, 1.0)
        clip.envelopes['volume'] = env

    r1 = ClipRenderer(clip1)
    r2 = ClipRenderer(clip2)

    # both should have same volume at local frame 15
    # clip1: timeline 15 = local 15
    # clip2: timeline 515 = local 15
    assert abs(r1.get_volume_at(15)  -
               r2.get_volume_at(515)) < 0.01


# =========================================================
# Source time precision
# =========================================================

def test_source_time_precision():
    """
    Verify source_time is precise enough for audio.
    Audio needs sample-accurate positioning.
    """
    clip = make_clip(start_frame=0, source_frames=10000)
    clip.in_point   = 0
    clip.source_fps = 29.97
    r = ClipRenderer(clip)

    # frame 1 at 29.97fps = 0.03337 seconds
    t = r.timeline_to_source_time(1)
    assert abs(t - 1/29.97) < 0.001


def test_source_frame_clamped():
    """Source frame should never exceed source_frames."""
    clip = make_clip(start_frame=0, source_frames=100)
    clip.in_point  = 0
    clip.out_point = -1
    r = ClipRenderer(clip)

    # requesting frame 200 on a 100-frame clip
    frame = r.timeline_to_source_frame(200)
    assert frame <= 99


if __name__ == '__main__':
    tests = [
        test_is_active_basic,
        test_is_active_disabled,
        test_mapping_simple,
        test_mapping_with_start_frame,
        test_mapping_with_in_point,
        test_mapping_after_razor_right_half,
        test_mapping_moved_after_razor,
        test_local_frame,
        test_volume_flat,
        test_volume_muted,
        test_volume_envelope_uses_local_frame,
        test_source_time_precision,
        test_source_frame_clamped,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f'  PASS  {t.__name__}')
            passed += 1
        except Exception as e:
            print(f'  FAIL  {t.__name__}: {e}')
            failed += 1
    print(f'\n{passed} passed, {failed} failed')
