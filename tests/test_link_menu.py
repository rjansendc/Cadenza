"""
What the clip's right-click menu offers for linking.

It decided between Link and Unlink by asking whether the clicked clip
carried a link group id — not whether it was linked to anything. A
clip in a group of one therefore offered Unlink. So after unlinking a
movie, deleting its audio and bringing another WAV up to the video,
right-clicking the audio said Unlink and right-clicking the video
said Link: neither offered what was wanted, and the two could not be
linked to each other.

The decision is a plain function of the clips on the timeline and the
selection, so it is tested as one — no menu, no window.
"""

import os
import sys
import types
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # noqa: F401

QtWidgets = pytest.importorskip('PySide6.QtWidgets')
from ui.widgets.clip_item import ClipItem           # noqa: E402


def clip(clip_id, group=None, has_audio=False):
    return types.SimpleNamespace(id=clip_id, link_group_id=group,
                                 has_audio=has_audio, has_video=not has_audio)


def timeline(*clips):
    """all_items: clip id -> its timeline item."""
    return {c.id: types.SimpleNamespace(clip=c) for c in clips}


def choice(clicked, clips, selection):
    """The menu's decision, called unbound — no Qt object needed."""
    return ClipItem._link_menu_choice(
        types.SimpleNamespace(clip=clicked), timeline(*clips), selection)


# ── the reported case ─────────────────────────────────────────

def test_a_lone_wav_in_a_group_of_one_does_not_offer_unlink():
    """The WAV brought up to the video. Every drop used to be given a
    group id, so a single-clip drop looked linked."""
    wav = clip('wav', group='group-of-one', has_audio=True)
    assert choice(wav, [wav], ['wav']) is None


def test_the_video_and_the_wav_both_offer_link():
    """One said Link and the other said Unlink."""
    video = clip('video')
    wav   = clip('wav', group='group-of-one', has_audio=True)
    both  = ['video', 'wav']
    assert choice(video, [video, wav], both) == 'link'
    assert choice(wav,   [video, wav], both) == 'link'


def test_both_offer_unlink_once_they_are_linked():
    video = clip('video', group='together')
    wav   = clip('wav', group='together', has_audio=True)
    both  = ['video', 'wav']
    assert choice(video, [video, wav], both) == 'unlink'
    assert choice(wav,   [video, wav], both) == 'unlink'


# ── a real group still unlinks ────────────────────────────────

def test_a_dropped_movie_offers_unlink():
    video = clip('v', group='take')
    audio = clip('a', group='take', has_audio=True)
    assert choice(video, [video, audio], ['v']) == 'unlink'


def test_a_multitrack_take_offers_unlink():
    members = [clip('v', group='take')] + [
        clip(f'a{i}', group='take', has_audio=True) for i in range(4)]
    assert choice(members[0], members, ['v']) == 'unlink'


def test_a_group_left_with_one_member_does_not_offer_unlink():
    """Whatever emptied it — an unlink, a delete, an old project
    saved that way — the clip left behind is linked to nothing."""
    survivor = clip('v', group='take')
    assert choice(survivor, [survivor], ['v']) is None


def test_a_clip_is_not_its_own_partner():
    alone = clip('v', group='take')
    other = clip('w', group='other')
    assert choice(alone, [alone, other], ['v', 'w']) == 'link'


# ── nothing to offer ──────────────────────────────────────────

def test_one_unlinked_clip_selected_offers_neither():
    only = clip('v')
    assert choice(only, [only], ['v']) is None


def test_a_selection_of_one_offers_neither_even_beside_others():
    video = clip('video')
    wav   = clip('wav', has_audio=True)
    assert choice(video, [video, wav], ['video']) is None


def test_clips_already_in_one_group_offer_neither_link():
    """Selecting a linked pair and right-clicking gives Unlink, not
    Link — but a third clip in the selection means Link."""
    video = clip('v', group='take')
    audio = clip('a', group='take', has_audio=True)
    third = clip('t', has_audio=True)
    assert choice(third, [video, audio, third],
                  ['v', 'a', 't']) == 'link'


def test_a_selection_naming_clips_that_are_gone_is_ignored():
    only = clip('v')
    assert choice(only, [only], ['v', 'deleted', 'also-gone']) is None
