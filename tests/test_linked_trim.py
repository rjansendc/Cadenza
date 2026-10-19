"""
Trimming one clip of a link group trims the whole take.

Moving a linked clip carried its partners, and a razor cut split them
all, but trimming only ever touched the clip under the mouse — so
trimming a camera angle left its audio at the old length.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # noqa: F401

from core.clip import Clip, ClipType

QtWidgets = pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtWidgets import QApplication, QGraphicsScene  # noqa: E402
from PySide6.QtCore import QRectF  # noqa: E402

from ui.app_state import AppState          # noqa: E402
from ui.widgets.clip_item import ClipItem  # noqa: E402

GROUP = 'take-1'
VIEW_W = 1200.0


@pytest.fixture(scope='module')
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def take(qapp):
    """A linked video+audio pair as ClipItems in one scene."""
    state = AppState()
    state.set_view_width(VIEW_W)
    state.total_frames = 3000

    def clip(has_video):
        return Clip(
            filepath='cam1.mp4',
            clip_type=ClipType.VIDEO if has_video else ClipType.AUDIO,
            has_video=has_video, has_audio=not has_video,
            source_frames=3000, source_fps=29.97,
            track=0, start_frame=0, in_point=0, out_point=3000,
            link_group_id=GROUP,
        )

    scene = QGraphicsScene()
    scene.setSceneRect(QRectF(0, 0, VIEW_W, 40))
    video = ClipItem(clip(True),  state, VIEW_W)
    audio = ClipItem(clip(False), state, VIEW_W)
    scene.addItem(video)
    scene.addItem(audio)
    # yield, not return: the scene and state are locals, and Qt deletes
    # the items the moment the scene is collected
    yield video, audio


def start_trim(item, edge):
    """Put the item into the state a press on that edge leaves it."""
    item._trim_edge       = edge
    item._trim_orig_in    = item.clip.in_point
    item._trim_orig_out   = item.clip.out_point
    item._trim_orig_start = item.clip.start_frame
    for other in item._all_linked_items():
        other._trim_orig_in    = other.clip.in_point
        other._trim_orig_out   = other.clip.out_point
        other._trim_orig_start = other.clip.start_frame


def test_the_pair_can_see_each_other(take):
    video, audio = take
    assert [i.clip.id for i in video._all_linked_items()] == [audio.clip.id]
    assert [i.clip.id for i in audio._all_linked_items()] == [video.clip.id]


def test_unlinked_clips_see_nobody(take):
    video, audio = take
    video.clip.link_group_id = None
    assert video._all_linked_items() == []


def test_right_trim_shortens_the_audio_too(take):
    video, audio = take
    start_trim(video, 'right')
    video.clip.out_point = 2400          # what the drag does
    video._apply_trim_to_linked()
    assert audio.clip.out_point == 2400
    assert audio.clip.duration == video.clip.duration


def test_right_trim_from_the_audio_side_too(take):
    """Either half of the take may be the one grabbed."""
    video, audio = take
    start_trim(audio, 'right')
    audio.clip.out_point = 1800
    audio._apply_trim_to_linked()
    assert video.clip.out_point == 1800


def test_left_trim_moves_both_clips_together(take):
    video, audio = take
    start_trim(video, 'left')
    video.clip.in_point    = 300         # what the drag does
    video.clip.start_frame = 300
    video._apply_trim_to_linked()
    assert audio.clip.in_point == 300
    assert audio.clip.start_frame == 300
    assert audio.clip.duration == video.clip.duration


def test_a_shorter_source_stops_where_it_must(take):
    """Each clip is clamped by its own media, so a stream that runs
    out first stops rather than claiming frames it hasn't got."""
    video, audio = take
    audio.clip.source_frames = 2000
    start_trim(video, 'right')
    video.clip.out_point = 2800
    video._apply_trim_to_linked()
    assert audio.clip.out_point == 2000
    assert video.clip.out_point == 2800


def test_one_undo_step_covers_the_group(take):
    from core.undo import CompoundCommand
    video, audio = take
    start_trim(video, 'right')
    video.clip.out_point = 2400
    video._apply_trim_to_linked()

    items = [video] + video._all_linked_items()
    cmds = [c for c in (video._trim_command_for(i) for i in items)
            if c is not None]
    assert len(cmds) == 2

    group = CompoundCommand('Trim Clips')
    for cmd in cmds:
        group.add(cmd)
    group.undo()
    assert video.clip.out_point == 3000
    assert audio.clip.out_point == 3000
    group.redo()
    assert video.clip.out_point == 2400
    assert audio.clip.out_point == 2400


def test_a_clip_that_did_not_move_gets_no_command(take):
    video, _audio = take
    start_trim(video, 'right')
    assert video._trim_command_for(video) is None
