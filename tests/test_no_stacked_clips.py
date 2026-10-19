"""
Two clips never hold the same frames on one track.

A clip dropped or dragged onto occupied timeline moves to the nearest
track with room, keeping the time it was put at. Stacking them is
only recoverable by undo, and nothing on screen says which of the two
is being heard or seen.

What used to happen: the refusal consulted self.scene().items(), and
the timeline gives each row its own QGraphicsScene. So it compared the
destination track number against clips in the *source* row, matched
nothing, and let the clip land on top. Same-track drags were refused;
cross-track drags were never checked at all.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # noqa: F401

from core.project import Project
from core.track import Track, TrackType


def project(n_video=3, n_audio=3):
    p = Project()
    seq = p.active_sequence
    for kind, want, tracks in (
            (TrackType.VIDEO, n_video, seq.video_tracks),
            (TrackType.AUDIO, n_audio, seq.audio_tracks)):
        while len(tracks) < want:
            tracks.append(Track(kind, len(tracks)))
        del tracks[want:]
    return p


def place(p, name, track, start, frames, audio=False):
    item = p.import_media(name)
    item.source_frames = frames
    return p.add_clip(item, track=track, start_frame=start,
                      has_video=not audio, has_audio=audio)


def free(p, preferred, start, end, audio=False, exclude=()):
    return p.nearest_free_track(preferred, start, end,
                                is_audio=audio, exclude_ids=exclude)


# ── the search ────────────────────────────────────────────────

def test_an_empty_track_is_used_as_asked():
    p = project()
    assert free(p, 0, 0, 300) == 0


def test_an_occupied_track_sends_the_clip_to_the_next_one():
    p = project()
    place(p, 'a.mp4', 0, 0, 300)
    assert free(p, 0, 0, 300) == 1


def test_the_nearest_track_wins_not_the_first():
    """Dropped on V3 with V3 busy, V2 is nearer than V1."""
    p = project()
    place(p, 'a.mp4', 2, 0, 300)
    assert free(p, 2, 0, 300) == 1


def test_a_tie_goes_to_the_higher_numbered_track():
    """Dropped on V2 with V2 busy: V1 and V3 are both one away, and
    the clip slides away from V1 rather than onto it."""
    p = project()
    place(p, 'a.mp4', 1, 0, 300)
    assert free(p, 1, 0, 300) == 2


def test_the_search_skips_several_busy_tracks():
    p = project(n_video=4)
    for track in (0, 1, 2):
        place(p, f'a{track}.mp4', track, 0, 300)
    assert free(p, 0, 0, 300) == 3


def test_every_track_busy_gives_no_answer():
    p = project(n_video=2)
    place(p, 'a.mp4', 0, 0, 300)
    place(p, 'b.mp4', 1, 0, 300)
    assert free(p, 0, 0, 300) is None


# ── free means free at this time ──────────────────────────────

def test_a_track_busy_elsewhere_in_time_is_still_free_here():
    p = project()
    place(p, 'a.mp4', 0, 0, 300)
    assert free(p, 0, 500, 800) == 0


def test_touching_end_to_end_is_not_a_collision():
    p = project()
    place(p, 'a.mp4', 0, 0, 300)
    assert free(p, 0, 300, 600) == 0


def test_one_frame_of_overlap_is_a_collision():
    p = project()
    place(p, 'a.mp4', 0, 0, 300)
    assert free(p, 0, 299, 600) == 1


# ── kinds do not collide with each other ──────────────────────

def test_audio_does_not_block_video_on_the_same_index():
    """V1 and A1 clips both have track == 0."""
    p = project()
    place(p, 'take.wav', 0, 0, 300, audio=True)
    assert free(p, 0, 0, 300, audio=False) == 0


def test_video_does_not_block_audio_on_the_same_index():
    p = project()
    place(p, 'cam.mp4', 0, 0, 300)
    assert free(p, 0, 0, 300, audio=True) == 0


def test_audio_and_video_track_counts_are_read_separately():
    p = project(n_video=2, n_audio=5)
    for track in range(5):
        place(p, f'a{track}.wav', track, 0, 300, audio=True)
    assert free(p, 0, 0, 300, audio=True) is None
    assert free(p, 0, 0, 300, audio=False) == 0


# ── a clip being moved does not block itself ──────────────────

def test_a_clip_does_not_collide_with_itself():
    p = project()
    moving = place(p, 'a.mp4', 0, 0, 300)
    assert free(p, 0, 0, 300, exclude=(moving.id,)) == 0


def test_two_clips_moving_together_do_not_block_each_other():
    p = project()
    a = place(p, 'a.mp4', 0, 0, 300)
    b = place(p, 'b.mp4', 1, 0, 300)
    assert free(p, 0, 0, 300, exclude=(a.id, b.id)) == 0


# ── dropping from the bin ─────────────────────────────────────

def drop(p, item, row, start=0, video=1, audio=1):
    return p.add_linked_clips(
        item, drop_row=row, start_frame=start,
        stream_info={'video_count': video, 'audio_count': audio})


def media(p, name, frames=300):
    item = p.import_media(name)
    item.source_frames = frames
    return item


def v1_row(p):
    """V1 is the bottom video row, so its row number moves as video
    tracks are added — and these drops add them."""
    from ui.constants import video_row
    return video_row(0, len(p.active_sequence.video_tracks))


def test_a_bin_drop_onto_an_occupied_video_track_moves_down():
    p = project()
    place(p, 'first.mp4', 0, 0, 300)
    made = drop(p, media(p, 'second.mp4'), v1_row(p))
    assert next(c for c in made if c.has_video).track == 1


def test_a_bin_drop_with_every_video_track_busy_grows_the_sequence():
    """New material has to go somewhere: six angles stacked at one
    timecode need six video tracks. Moving a clip that already has a
    home does not grow anything — see test_drag_to_free_track.py."""
    p = project(n_video=2)
    place(p, 'a.mp4', 0, 0, 300)
    place(p, 'b.mp4', 1, 0, 300)
    made = drop(p, media(p, 'c.mp4'), v1_row(p))
    assert next(c for c in made if c.has_video).track == 2
    assert len(p.active_sequence.video_tracks) == 3


def test_a_run_of_stacked_angles_grows_both_kinds_of_track():
    p = project(n_video=2, n_audio=2)
    for i in range(5):
        drop(p, media(p, f'cam{i}.mp4'), v1_row(p))
    seq = p.active_sequence
    assert len(seq.video_tracks) == 5
    assert len(seq.audio_tracks) == 5
    assert [t.name for t in seq.video_tracks] == ['V1', 'V2', 'V3', 'V4', 'V5']


def test_a_bin_drop_clear_of_everything_is_untouched():
    p = project()
    place(p, 'first.mp4', 0, 0, 300)
    made = drop(p, media(p, 'second.mp4'), v1_row(p), start=400)
    assert next(c for c in made if c.has_video).track == 0


def test_no_two_clips_share_frames_after_a_run_of_drops():
    """The invariant itself, over a sequence of drops."""
    p = project(n_video=4, n_audio=4)
    for i in range(4):
        drop(p, media(p, f'cam{i}.mp4'), v1_row(p))
    seen = {}
    for clip in p.clips.values():
        key = (clip.track, bool(clip.has_audio))
        for other in seen.get(key, []):
            assert (clip.start_frame >= other[1] or
                    other[0] >= clip.start_frame + clip.duration), \
                f'stacked on {key}'
        seen.setdefault(key, []).append(
            (clip.start_frame, clip.start_frame + clip.duration))
