"""
Where a dropped file's audio lands.

The drop row used to decide the audio track outright: V1 meant A1,
whatever was already on A1. Pulling a camera angle into V1 while A1
held a WAV put the angle's audio on top of it — two clips on one
track across the same frames, playing over each other. The row is
now where the search starts, and each stream takes the first track
from there with room over the clip's own span.

And when a file had more audio streams than the sequence had tracks,
the loop simply stopped. A four-stream recording dropped into the
default three-track sequence lost its fourth stream with nothing
said anywhere.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # noqa: F401

from core.project import Project
from core.track import Track, TrackType


SPAN = 600          # frames in every test file


def project(n_audio=3):
    p = Project()
    seq = p.active_sequence
    while len(seq.audio_tracks) < n_audio:
        seq.audio_tracks.append(
            Track(TrackType.AUDIO, len(seq.audio_tracks)))
    return p


def media(p, name, frames=SPAN):
    item = p.import_media(name)
    item.source_frames = frames
    return item


def drop(p, item, row, start=0, video=1, audio=1):
    return p.add_linked_clips(
        item, drop_row=row, start_frame=start,
        stream_info={'video_count': video, 'audio_count': audio})


def audio_tracks_of(clips):
    return sorted(c.track for c in clips if c.has_audio)


V1, A1, A2, A3 = 2, 3, 4, 5      # rows, on a 3-video timeline


# ── the reported case ─────────────────────────────────────────

def test_a_video_dropped_on_v1_does_not_land_on_occupied_audio():
    """Two WAVs on A1 and A2, then Test_36.mp4 into V1. Its audio
    went onto A1, on top of the WAV."""
    p = project()
    drop(p, media(p, 'take.wav'), A1, video=0, audio=1)
    drop(p, media(p, 'room.wav'), A2, video=0, audio=1)

    made = drop(p, media(p, 'Test_36.mp4'), V1)
    assert audio_tracks_of(made) == [2]          # A3, the first free one
    assert next(c for c in made if c.has_video).track == 0   # V1 as asked


def test_the_video_track_is_still_exactly_what_was_dropped_on():
    """Only the audio track is inferred, so only it may move."""
    p = project()
    drop(p, media(p, 'take.wav'), A1, video=0, audio=1)
    made = drop(p, media(p, 'cam.mp4'), V1)
    assert next(c for c in made if c.has_video).track == 0


def test_an_empty_timeline_still_uses_the_matching_track():
    """Nothing in the way, nothing clever: V1 means A1."""
    p = project()
    made = drop(p, media(p, 'cam.mp4'), V1)
    assert audio_tracks_of(made) == [0]


def test_each_angle_gets_its_own_track_in_turn():
    """Six camera angles dropped one after another, as a multicam
    cut is built: each stacks at the same timecode on its own pair of
    tracks."""
    from ui.constants import video_row
    p = project(n_audio=6)
    while len(p.active_sequence.video_tracks) < 6:
        p.active_sequence.video_tracks.append(
            Track(TrackType.VIDEO, len(p.active_sequence.video_tracks)))
    # V1 is the bottom video row, so which row number means V1
    # depends on how many video tracks there are
    row = video_row(0, 6)
    for i in range(6):
        made = drop(p, media(p, f'cam{i}.mp4'), row)
        assert audio_tracks_of(made) == [i], f'angle {i}'


# ── free means free at this time, not empty ───────────────────

def test_a_clip_later_in_time_reuses_the_track():
    """A1 busy at the head does not make A1 unusable at 0:40."""
    p = project()
    drop(p, media(p, 'take.wav'), A1, video=0, audio=1)   # 0..600
    made = drop(p, media(p, 'cam.mp4'), V1, start=SPAN + 10)
    assert audio_tracks_of(made) == [0]


def test_touching_end_to_end_is_not_a_collision():
    """A clip starting exactly where another ends fits."""
    p = project()
    drop(p, media(p, 'take.wav'), A1, video=0, audio=1)   # 0..600
    made = drop(p, media(p, 'cam.mp4'), V1, start=SPAN)
    assert audio_tracks_of(made) == [0]


def test_one_frame_of_overlap_is_a_collision():
    p = project()
    drop(p, media(p, 'take.wav'), A1, video=0, audio=1)
    made = drop(p, media(p, 'cam.mp4'), V1, start=SPAN - 1)
    assert audio_tracks_of(made) == [1]


# ── multi-stream files ────────────────────────────────────────

def test_streams_spread_across_consecutive_free_tracks():
    p = project(n_audio=4)
    made = drop(p, media(p, 'multitrack.mkv'), V1, audio=4)
    assert audio_tracks_of(made) == [0, 1, 2, 3]


def test_streams_step_over_what_is_already_down():
    p = project(n_audio=6)
    drop(p, media(p, 'room.wav'), A2, video=0, audio=1)    # A2 busy
    made = drop(p, media(p, 'multitrack.mkv'), V1, audio=3)
    assert audio_tracks_of(made) == [0, 2, 3]              # A2 skipped


def test_running_out_of_tracks_grows_the_sequence():
    """This used to `break`, losing the remaining streams silently."""
    p = project(n_audio=3)
    made = drop(p, media(p, 'seven.mkv'), V1, audio=7)
    assert audio_tracks_of(made) == [0, 1, 2, 3, 4, 5, 6]
    assert len(p.active_sequence.audio_tracks) == 7


def test_every_stream_becomes_a_clip():
    p = project(n_audio=3)
    made = drop(p, media(p, 'seven.mkv'), V1, audio=7)
    assert len([c for c in made if c.has_audio]) == 7


def test_grown_tracks_are_named_in_order():
    p = project(n_audio=3)
    drop(p, media(p, 'seven.mkv'), V1, audio=7)
    names = [t.name for t in p.active_sequence.audio_tracks]
    assert names == ['A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'A7']
    assert [t.index for t in p.active_sequence.audio_tracks] == list(range(7))


def test_a_grown_track_gets_its_own_z_order():
    """Audio z_order is AUDIO_Z_BASE + index; a duplicate would make
    two tracks render as one."""
    p = project(n_audio=3)
    drop(p, media(p, 'seven.mkv'), V1, audio=7)
    z = [t.z_order for t in p.active_sequence.audio_tracks]
    assert len(set(z)) == len(z)
    assert z == sorted(z)


# ── a drop on an audio row starts there ───────────────────────

def test_dropping_on_an_audio_row_uses_that_track_when_it_is_free():
    p = project()
    made = drop(p, media(p, 'take.wav'), A2, video=0, audio=1)
    assert audio_tracks_of(made) == [1]


def test_dropping_on_a_busy_audio_row_moves_down():
    """The row is where the search starts, not where the clip has to
    land — two clips must never hold the same frames on one track."""
    p = project()
    drop(p, media(p, 'take.wav'), A1, video=0, audio=1)
    made = drop(p, media(p, 'other.wav'), A1, video=0, audio=1)
    assert audio_tracks_of(made) == [1]


def test_streams_of_an_audio_row_drop_step_over_what_is_down():
    p = project(n_audio=6)
    drop(p, media(p, 'room.wav'), A2, video=0, audio=1)    # A2 busy
    made = drop(p, media(p, 'pair.wav'), A1, video=0, audio=2)
    assert audio_tracks_of(made) == [0, 2]                 # A2 skipped


# ── the predicate on its own ──────────────────────────────────

def test_busy_predicate_ignores_video_clips_on_the_same_index():
    """Video and audio tracks are both 0-based, so V1 and A1 clips
    both have track == 0."""
    p = project()
    drop(p, media(p, 'cam.mp4'), V1, video=1, audio=0)
    assert not p.audio_track_is_busy(0, 0, SPAN)


def test_busy_predicate_reports_an_occupied_span():
    p = project()
    drop(p, media(p, 'take.wav'), A1, video=0, audio=1)
    assert p.audio_track_is_busy(0, 0, SPAN)
    assert p.audio_track_is_busy(0, SPAN - 1, SPAN + 100)
    assert not p.audio_track_is_busy(0, SPAN, SPAN + 100)
    assert not p.audio_track_is_busy(1, 0, SPAN)
