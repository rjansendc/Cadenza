"""
Linking an audio clip to a video clip.

A link group needs something to link. Every drop was given a fresh
group id and handed it to whatever it created, so a WAV dropped by
itself ended up in a group of one — and a group id on its own reads
as "linked" everywhere it is asked.

So after unlinking a movie and deleting its audio, moving a separate
WAV up to the video gave two clips that could not be linked to each
other: right-clicking the video offered Link, right-clicking the WAV
offered Unlink, and neither did what was wanted. The same thing is
left behind by an unlink or a delete that empties a group down to one
member.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # noqa: F401

from core.project import Project


def project():
    return Project()


def drop(p, name, row, start=0, video=1, audio=1, frames=300):
    item = p.import_media(name)
    item.source_frames = frames
    return p.add_linked_clips(
        item, drop_row=row, start_frame=start,
        stream_info={'video_count': video, 'audio_count': audio})


V1, A1, A2 = 2, 3, 4


# ── a single clip is not a group ──────────────────────────────

def test_a_wav_dropped_alone_is_not_linked():
    p = project()
    made = drop(p, 'take.wav', A1, video=0, audio=1)
    assert len(made) == 1
    assert made[0].link_group_id is None


def test_a_video_with_no_audio_is_not_linked():
    p = project()
    made = drop(p, 'silent.mp4', V1, video=1, audio=0)
    assert len(made) == 1
    assert made[0].link_group_id is None


def test_a_video_with_audio_is_linked():
    p = project()
    made = drop(p, 'cam.mp4', V1, video=1, audio=1)
    assert len(made) == 2
    groups = {c.link_group_id for c in made}
    assert len(groups) == 1
    assert None not in groups


def test_a_multitrack_take_is_one_group():
    p = project()
    made = drop(p, 'four.mkv', V1, video=1, audio=4)
    assert len(made) == 5
    assert len({c.link_group_id for c in made}) == 1


def test_a_lone_clip_reports_no_partners():
    p = project()
    wav = drop(p, 'take.wav', A1, video=0, audio=1)[0]
    assert p.get_linked_clips(wav.id) == []
    assert p.get_link_group(wav.id) == [wav]


# ── the user's sequence ───────────────────────────────────────

def test_a_separate_wav_can_be_linked_to_a_bare_video():
    """Unlink a movie, delete its audio, bring up another WAV."""
    p = project()
    pair = drop(p, 'movie.mp4', V1, video=1, audio=1)
    video = next(c for c in pair if c.has_video)
    audio = next(c for c in pair if c.has_audio)

    p.unlink_group(video.id)
    p.remove_clip(audio.id)
    assert video.link_group_id is None

    wav = drop(p, 'take.wav', A1, video=0, audio=1)[0]
    assert wav.link_group_id is None          # not a group of one

    p.link_clips([video.id, wav.id])
    assert video.link_group_id is not None
    assert video.link_group_id == wav.link_group_id
    assert p.get_linked_clips(video.id) == [wav]
    assert p.get_linked_clips(wav.id) == [video]


# ── groups that fall to one member let go ─────────────────────

def test_deleting_one_of_a_pair_unlinks_the_other():
    p = project()
    pair = drop(p, 'movie.mp4', V1, video=1, audio=1)
    video = next(c for c in pair if c.has_video)
    audio = next(c for c in pair if c.has_audio)
    p.remove_clip(audio.id)
    assert video.link_group_id is None


def test_deleting_one_of_three_leaves_the_rest_linked():
    p = project()
    made = drop(p, 'three.mkv', V1, video=1, audio=2)
    assert len(made) == 3
    p.remove_clip(made[-1].id)
    rest = [c for c in made[:-1]]
    assert all(c.link_group_id for c in rest)
    assert len({c.link_group_id for c in rest}) == 1


def test_unlinking_one_of_a_pair_unlinks_both():
    p = project()
    pair = drop(p, 'movie.mp4', V1, video=1, audio=1)
    p.unlink_clip(pair[0].id)
    assert all(c.link_group_id is None for c in pair)


def test_unlinking_one_of_three_leaves_the_other_two_linked():
    p = project()
    made = drop(p, 'three.mkv', V1, video=1, audio=2)
    p.unlink_clip(made[0].id)
    assert made[0].link_group_id is None
    rest = made[1:]
    assert all(c.link_group_id for c in rest)
    assert len({c.link_group_id for c in rest}) == 1


# ── linking needs two ─────────────────────────────────────────

def test_linking_one_clip_does_nothing():
    p = project()
    wav = drop(p, 'take.wav', A1, video=0, audio=1)[0]
    p.link_clips([wav.id])
    assert wav.link_group_id is None


def test_linking_nothing_does_nothing():
    p = project()
    p.link_clips([])            # must not raise
    p.link_clips(['no-such-id'])


def test_linking_regroups_clips_that_were_linked_elsewhere():
    p = project()
    first  = drop(p, 'a.mp4', V1, video=1, audio=1)
    second = drop(p, 'b.wav', A2, video=0, audio=1, start=900)
    video = next(c for c in first if c.has_video)
    p.link_clips([video.id, second[0].id])
    assert video.link_group_id == second[0].link_group_id
