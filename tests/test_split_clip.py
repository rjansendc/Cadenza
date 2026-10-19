"""
A razor cut keeps both halves looking the same.

split_clip used to rebuild the right half's effect stack from defaults,
so every cut silently reset the grade, motion and keyframes on the
right-hand clip.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import effects  # noqa: F401

from core.project import Project


def project_with_graded_clip(frames=600):
    p = Project(name='T')
    item = p.import_media('cam1.mp4')
    item.source_frames = frames
    item.has_video = item.has_audio = True
    clip = p.add_clip(item, track=0, start_frame=0)
    lum = clip.get_effect('lumetri_color')
    lum.set('exposure', 1.25)
    lum.set('contrast', -0.4)
    motion = clip.get_effect('motion')
    motion.set('scale', 80.0)
    return p, clip


def test_right_half_keeps_the_grade():
    p, clip = project_with_graded_clip()
    right = p.split_clip(clip.id, 300)[0]
    lum = right.get_effect('lumetri_color')
    assert lum.get('exposure') == 1.25
    assert lum.get('contrast') == -0.4
    assert right.get_effect('motion').get('scale') == 80.0


def test_left_half_keeps_the_grade_too():
    p, clip = project_with_graded_clip()
    p.split_clip(clip.id, 300)
    assert clip.get_effect('lumetri_color').get('exposure') == 1.25


def test_the_halves_are_independent():
    """Copies, not shared references — grading one must not move the
    other."""
    p, clip = project_with_graded_clip()
    right = p.split_clip(clip.id, 300)[0]
    right.get_effect('lumetri_color').set('exposure', -2.0)
    assert clip.get_effect('lumetri_color').get('exposure') == 1.25
    assert right.get_effect('lumetri_color').get('exposure') == -2.0


def test_disabled_effects_stay_disabled():
    p, clip = project_with_graded_clip()
    clip.get_effect('lumetri_color').enabled = False
    right = p.split_clip(clip.id, 300)[0]
    assert right.get_effect('lumetri_color').enabled is False


def test_keyframes_are_retimed_onto_the_right_half():
    """Envelopes read at clip-local frames, so the right half's
    keyframes shift by however far in the cut fell."""
    p, clip = project_with_graded_clip()
    clip.set_param_keyframe('opacity', 'opacity', 100, 100.0)
    clip.set_param_keyframe('opacity', 'opacity', 400, 0.0)

    right = p.split_clip(clip.id, 300)[0]
    frames = sorted(kf.frame for kf in right.envelopes['opacity'].keyframes)
    # 100 and 400 in the original become -200 and 100 on the right half
    assert frames == [-200, 100]

    # the left half is untouched
    assert sorted(kf.frame for kf in
                  clip.envelopes['opacity'].keyframes) == [100, 400]


def test_a_fade_across_the_cut_stays_continuous():
    """The value either side of the cut must match, or the picture
    jumps at the join."""
    p, clip = project_with_graded_clip()
    clip.set_param_keyframe('opacity', 'opacity', 0,   100.0)
    clip.set_param_keyframe('opacity', 'opacity', 600,   0.0)

    cut = 300
    right = p.split_clip(clip.id, cut)[0]
    # clip-local frame of the cut, on each half
    left_at_cut  = clip.envelopes['opacity'].value_at(cut)
    right_at_cut = right.envelopes['opacity'].value_at(0)
    assert abs(left_at_cut - right_at_cut) < 1e-9
    # and halfway down the fade, as expected
    assert abs(left_at_cut - 0.5) < 1e-6


def test_envelopes_are_independent():
    p, clip = project_with_graded_clip()
    clip.set_param_keyframe('opacity', 'opacity', 100, 50.0)
    right = p.split_clip(clip.id, 300)[0]
    right.envelopes['opacity'].add_keyframe(10, 0.25)
    assert len(clip.envelopes['opacity'].keyframes) == 1


def test_a_linked_pair_both_split():
    p = Project(name='T')
    item = p.import_media('cam1.mp4')
    item.source_frames = 600
    clips = p.add_linked_clips(
        item, drop_row=2, start_frame=0,
        stream_info={'video_count': 1, 'audio_count': 1})
    assert len(clips) == 2
    made = p.split_clip(clips[0].id, 300)
    assert len(made) == 2
    assert {c.has_video for c in made} == {True, False}
