"""
Track rows and sequences once you go past the 3+3 default.

The row helpers read a module-level NUM_VIDEO_TRACKS, so adding a
fourth video track put every clip on the wrong row; and the drop slot
was clamped against the video count, so a fourth audio track could
never be dropped on. Saving kept only the open sequence.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import effects  # noqa: F401

from core.project import Project
from core.track import Track, TrackType, SequenceSettings
from core.project_io import save_project, load_project
from ui.constants import (video_row, audio_row, row_is_video,
                          row_to_track_index)


# ── row maths with a non-default track count ──────────────────

def test_rows_on_the_default_timeline():
    assert [video_row(i, 3) for i in (0, 1, 2)] == [2, 1, 0]
    assert [audio_row(i, 3) for i in (0, 1, 2)] == [3, 4, 5]


def test_rows_after_adding_a_fourth_video_track():
    """V1 is the bottom video row, so every row shifts down by one."""
    assert [video_row(i, 4) for i in (0, 1, 2, 3)] == [3, 2, 1, 0]
    assert [audio_row(i, 4) for i in (0, 1, 2)] == [4, 5, 6]


def test_rows_round_trip_to_track_indices():
    for n_video in (3, 4, 6):
        for index in range(n_video):
            row = video_row(index, n_video)
            assert row_is_video(row, n_video)
            assert row_to_track_index(row, n_video) == ('video', index)
        for index in range(3):
            row = audio_row(index, n_video)
            assert not row_is_video(row, n_video)
            assert row_to_track_index(row, n_video) == ('audio', index)


# ── dropping onto extra tracks ────────────────────────────────

def project_with(n_video=3, n_audio=3):
    p = Project()
    seq = p.active_sequence
    while len(seq.video_tracks) < n_video:
        seq.video_tracks.append(
            Track(TrackType.VIDEO, len(seq.video_tracks)))
    while len(seq.audio_tracks) < n_audio:
        seq.audio_tracks.append(
            Track(TrackType.AUDIO, len(seq.audio_tracks)))
    item = p.import_media('cam1.mp4')
    item.source_frames = 600
    return p, item


def drop(p, item, row):
    p.clips.clear()
    return p.add_linked_clips(
        item, drop_row=row, start_frame=0,
        stream_info={'video_count': 1, 'audio_count': 1})


def test_a_fourth_audio_track_can_be_dropped_on():
    """Row 6 is A4. The slot was clamped to the video count, so it
    landed on A3 instead."""
    p, item = project_with(n_video=3, n_audio=4)
    made = drop(p, item, 6)
    audio = next(c for c in made if c.has_audio)
    assert audio.track == 3          # A4


def test_every_audio_row_lands_on_its_own_track():
    p, item = project_with(n_video=3, n_audio=5)
    for row, expected in ((3, 0), (4, 1), (5, 2), (6, 3), (7, 4)):
        made = drop(p, item, row)
        audio = next(c for c in made if c.has_audio)
        assert audio.track == expected, f"row {row}"


def test_video_rows_still_map_to_video_tracks():
    p, item = project_with(n_video=4, n_audio=3)
    for row, expected in ((0, 3), (1, 2), (2, 1), (3, 0)):
        made = drop(p, item, row)
        video = next(c for c in made if c.has_video)
        assert video.track == expected, f"row {row}"


def test_a_video_clip_never_lands_on_a_track_that_is_not_there():
    """Dropping low down on a timeline with more audio tracks than
    video ones must not invent a video track to land on."""
    p, item = project_with(n_audio=6)
    seq = p.active_sequence
    n_video = len(seq.video_tracks)        # 3 by default, not removable
    assert len(seq.audio_tracks) > n_video
    for row in range(n_video + len(seq.audio_tracks)):
        made = drop(p, item, row)
        video = next((c for c in made if c.has_video), None)
        if video is not None:
            assert video.track < n_video, f"row {row}"


# ── sequences survive a save ──────────────────────────────────

def test_a_new_project_has_exactly_one_sequence():
    assert len(Project().sequences) == 1


def test_every_sequence_survives_a_round_trip(tmp_path):
    p = Project(name='Concert')
    p.active_sequence.name = 'Night 1'
    second = p.add_sequence(
        name='Night 2',
        settings=SequenceSettings(width=3840, height=2160))
    p.active_sequence = second

    path = str(tmp_path / 'multi.veproj')
    assert save_project(p, path)
    back = load_project(path)

    assert sorted(s.name for s in back.sequences.values()) == [
        'Night 1', 'Night 2']
    assert len(back.sequences) == 2        # no orphan from Project()
    assert back.active_sequence.name == 'Night 2'
    assert (back.active_sequence.settings.width,
            back.active_sequence.settings.height) == (3840, 2160)


def test_added_tracks_survive_a_round_trip(tmp_path):
    p, _item = project_with(n_video=5, n_audio=4)
    p.active_sequence.video_tracks[4].locked = True
    p.active_sequence.audio_tracks[3].muted = True

    path = str(tmp_path / 'tracks.veproj')
    assert save_project(p, path)
    seq = load_project(path).active_sequence

    assert len(seq.video_tracks) == 5
    assert len(seq.audio_tracks) == 4
    assert seq.video_tracks[4].locked is True
    assert seq.audio_tracks[3].muted is True


def test_a_single_sequence_file_still_loads(tmp_path):
    """Files written before sequences were plural."""
    import json
    p = Project(name='Old')
    p.active_sequence.name = 'Only One'
    path = str(tmp_path / 'old.veproj')
    assert save_project(p, path)

    raw = json.load(open(path))
    del raw['sequences']
    del raw['active_sequence_id']
    json.dump(raw, open(path, 'w'))

    back = load_project(path)
    assert len(back.sequences) == 1
    assert back.active_sequence.name == 'Only One'
