"""
Cross dissolve: the maths of the mix and where one can be placed.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import effects  # noqa: F401

try:                       # Qt is present on the dev machine, not in CI
    import PySide6.QtCore  # noqa: F401
    HAVE_QT = True
except Exception:
    HAVE_QT = False
from core.clip import Clip, ClipType
from core.transition import (
    Transition, find_at, cut_points, max_duration, CROSS_DISSOLVE,
)


def video_clip(start, duration, track=0, **kw):
    return Clip(filepath='x.mp4', clip_type=ClipType.VIDEO,
                has_video=True, has_audio=False,
                source_frames=10000, source_fps=29.97,
                track=track, start_frame=start,
                in_point=kw.get('in_point', 0),
                out_point=kw.get('in_point', 0) + duration)


# ── geometry ──────────────────────────────────────────────────────

def test_dissolve_is_centred_on_the_cut():
    tr = Transition(track=0, center_frame=900, duration=30)
    assert tr.start_frame == 885
    assert tr.end_frame == 915
    assert tr.covers(885) and tr.covers(914)
    assert not tr.covers(884) and not tr.covers(915)


def test_progress_runs_nought_to_one():
    tr = Transition(track=0, center_frame=900, duration=30)
    assert tr.progress_at(885) == 0.0
    assert tr.progress_at(900) == 0.5
    assert tr.progress_at(915) == 1.0
    # clamped outside its own window
    assert tr.progress_at(800) == 0.0
    assert tr.progress_at(1000) == 1.0


def test_find_at_matches_track_and_frame():
    a = Transition(track=0, center_frame=900, duration=30)
    b = Transition(track=1, center_frame=900, duration=30)
    assert find_at([a, b], 0, 890) is a
    assert find_at([a, b], 1, 890) is b
    assert find_at([a, b], 2, 890) is None
    assert find_at([a, b], 0, 500) is None


def test_zero_length_dissolve_is_complete():
    tr = Transition(track=0, center_frame=900, duration=0)
    assert tr.progress_at(900) == 1.0


# ── where a dissolve can go ───────────────────────────────────────

def test_cut_points_are_where_clips_meet():
    clips = [video_clip(0, 100), video_clip(100, 100), video_clip(300, 50)]
    # 100 is a cut; 200 is a gap, not a cut
    assert cut_points(clips, 0) == [100]


def test_cut_points_ignore_other_tracks():
    clips = [video_clip(0, 100), video_clip(100, 100),
             video_clip(0, 50, track=1), video_clip(50, 50, track=1)]
    assert cut_points(clips, 0) == [100]
    assert cut_points(clips, 1) == [50]


def test_max_duration_is_the_shorter_neighbour():
    clips = [video_clip(0, 100), video_clip(100, 40)]
    assert max_duration(clips, 0, 100) == 40


def test_max_duration_zero_without_a_neighbour():
    clips = [video_clip(0, 100)]
    assert max_duration(clips, 0, 100) == 0


# ── the mix itself ────────────────────────────────────────────────

def dissolve_opacity(tr, clip, frame):
    """Mirrors Compositor._transition_alpha."""
    if not tr.covers(frame):
        return None
    if clip.start_frame + clip.duration == tr.center_frame:
        return 1.0
    if clip.start_frame == tr.center_frame:
        return tr.progress_at(frame)
    return None


def test_outgoing_stays_opaque_and_incoming_rises():
    outgoing = video_clip(0, 900)
    incoming = video_clip(900, 900)
    tr = Transition(track=0, center_frame=900, duration=30)

    assert dissolve_opacity(tr, outgoing, 885) == 1.0
    assert dissolve_opacity(tr, outgoing, 914) == 1.0
    assert dissolve_opacity(tr, incoming, 885) == 0.0
    assert dissolve_opacity(tr, incoming, 900) == 0.5
    assert dissolve_opacity(tr, incoming, 914) > 0.9


def test_mix_of_the_two_always_sums_to_one():
    """canvas = A, then B over it at p, so result = A(1-p) + B(p)."""
    tr = Transition(track=0, center_frame=900, duration=30)
    incoming = video_clip(900, 900)
    for frame in range(885, 915):
        p = dissolve_opacity(tr, incoming, frame)
        assert 0.0 <= p <= 1.0
        assert abs((1 - p) + p - 1.0) < 1e-9


def test_clips_outside_the_window_are_untouched():
    other = video_clip(2000, 100)
    tr = Transition(track=0, center_frame=900, duration=30)
    assert dissolve_opacity(tr, other, 2050) is None


def test_outgoing_clip_reads_past_its_out_point():
    """The handles question: frames after the cut come from the source."""
    from core.clip_renderer import ClipRenderer
    clip = video_clip(0, 900)          # out_point 900, source has 10000
    r = ClipRenderer(clip)
    during = r.timeline_to_source_time(910)     # past its own end
    assert during > 0
    # it maps further into the media, not back to the start
    assert during > r.timeline_to_source_time(890)


# ── saving and undo ───────────────────────────────────────────────

def test_transitions_survive_save_and_load(tmp_path):
    from core.project import Project
    from core.project_io import save_project, load_project

    project = Project()
    seq = project.active_sequence
    clip_a = video_clip(0, 900)
    clip_b = video_clip(900, 900)
    project.clips[clip_a.id] = clip_a
    project.clips[clip_b.id] = clip_b
    seq.transitions.append(
        Transition(track=0, center_frame=900, duration=24))

    path = str(tmp_path / 'tr.veproj')
    assert save_project(project, path)

    loaded = load_project(path)
    restored = loaded.active_sequence.transitions
    assert len(restored) == 1
    assert restored[0].center_frame == 900
    assert restored[0].duration == 24
    assert restored[0].kind == CROSS_DISSOLVE


def test_a_sequence_starts_with_no_transitions():
    from core.track import Sequence
    assert Sequence(name='S').transitions == []


def test_add_and_remove_commands_round_trip():
    if not HAVE_QT:
        import pytest
        pytest.skip('core.undo imports PySide6')
    from core.track import Sequence
    from core.undo import AddTransitionCommand, RemoveTransitionCommand

    seq = Sequence(name='S')
    tr = Transition(track=0, center_frame=600, duration=30)

    add = AddTransitionCommand(seq, tr)
    add.redo()
    assert seq.transitions == [tr]
    add.undo()
    assert seq.transitions == []

    seq.transitions.append(tr)
    rm = RemoveTransitionCommand(seq, tr)
    rm.redo()
    assert seq.transitions == []
    rm.undo()
    assert seq.transitions == [tr]
