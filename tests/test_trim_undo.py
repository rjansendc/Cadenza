"""
Trimming an edge is one undo step.

A stretch used to leave nothing on the undo stack, so Ctrl+Z after one
reached past it and undid whatever came before.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import effects  # noqa: F401

from core.clip import Clip, ClipType
from core.undo import TrimClipCommand, UndoStack


def image_clip(start=0, source_frames=299):
    """A still, imported as a 10 second clip at 29.97."""
    return Clip(filepath='slide1.png', clip_type=ClipType.IMAGE,
                has_video=True, has_audio=False,
                source_width=1920, source_height=1080,
                source_fps=29.97, source_frames=source_frames,
                track=0, start_frame=start)


def test_stretch_right_edge_undoes():
    clip = image_clip()
    assert clip.out_point == -1          # untrimmed
    assert clip.duration == 299

    # the drag already happened; the command records it
    cmd = TrimClipCommand(clip, 0, -1, 0, 0, 534, 0)
    clip.out_point = 534                 # what the drag did
    stack = UndoStack()
    stack.push(cmd, execute=False)

    assert stack.can_undo
    assert stack.undo_description == 'Trim Clip'

    stack.undo()
    assert clip.out_point == -1
    assert clip.duration == 299

    stack.redo()
    assert clip.out_point == 534
    assert clip.duration == 534


def test_left_trim_restores_start_frame_too():
    """A left trim moves start_frame with in_point; undo returns both."""
    clip = image_clip(start=300)
    clip.out_point = 299

    cmd = TrimClipCommand(clip, 0, 299, 300, 60, 299, 360)
    clip.in_point, clip.start_frame = 60, 360
    stack = UndoStack()
    stack.push(cmd, execute=False)

    assert clip.duration == 239
    stack.undo()
    assert (clip.in_point, clip.start_frame) == (0, 300)
    assert clip.duration == 299


def test_push_does_not_reapply_the_drag():
    """execute=False: pushing must not move the edge a second time."""
    clip = image_clip()
    clip.out_point = 400
    stack = UndoStack()
    stack.push(TrimClipCommand(clip, 0, -1, 0, 0, 400, 0),
               execute=False)
    assert clip.out_point == 400
