"""
Undo/Redo system — Command Pattern.

Usage:
    # Wrap every undoable action:
    stack.push(SetOpacityCommand(clip, old=1.0, new=0.5))

    # Undo/Redo:
    stack.undo()
    stack.redo()

    # Compound (multiple clips moved together):
    with stack.compound("Move clips"):
        stack.push(MoveClipCommand(clip_a, ...))
        stack.push(MoveClipCommand(clip_b, ...))
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional
from PySide6.QtCore import QObject, Signal


# ─────────────────────────────────────────────────────────────
# Base command
# ─────────────────────────────────────────────────────────────

class UndoCommand(ABC):
    """Base class for all undoable actions."""

    def __init__(self, description: str = ""):
        self.description = description

    @abstractmethod
    def redo(self):
        """Apply (or re-apply) the action."""

    @abstractmethod
    def undo(self):
        """Reverse the action."""

    def try_merge(self, other: UndoCommand) -> bool:
        """
        Try to merge `other` (newer) into self.
        Return True if merged — other will be discarded.
        Used to coalesce rapid drag events into one undo step.
        """
        return False


# ─────────────────────────────────────────────────────────────
# Compound command — groups multiple commands into one undo step
# ─────────────────────────────────────────────────────────────

class CompoundCommand(UndoCommand):
    def __init__(self, description: str = ""):
        super().__init__(description)
        self._children: List[UndoCommand] = []

    def add(self, cmd: UndoCommand):
        self._children.append(cmd)

    def redo(self):
        for cmd in self._children:
            cmd.redo()

    def undo(self):
        for cmd in reversed(self._children):
            cmd.undo()

    def __len__(self):
        return len(self._children)


# ─────────────────────────────────────────────────────────────
# Undo stack
# ─────────────────────────────────────────────────────────────

class UndoStack(QObject):
    """
    Session-long undo/redo stack.
    Emits signals so menu items can enable/disable themselves.
    """

    changed = Signal()          # emitted whenever stack state changes

    def __init__(self, max_steps: int = 200, parent=None):
        super().__init__(parent)
        self._stack:   List[UndoCommand] = []
        self._index:   int = -1          # points to last applied command
        self._max:     int = max_steps
        self._compound: Optional[CompoundCommand] = None
        self._compound_depth: int = 0

    # ── public API ──────────────────────────────────────────

    def push(self, cmd: UndoCommand):
        """
        Execute cmd and push it onto the stack.
        If a compound is open, adds to it instead.
        Tries to merge with the previous command first.
        """
        cmd.redo()   # execute immediately

        if self._compound is not None:
            self._compound.add(cmd)
            return

        # Try to merge with top of stack (e.g. opacity drag)
        if (self._index >= 0 and
                self._stack[self._index].try_merge(cmd)):
            self.changed.emit()
            return

        # Discard any redo history above current index
        self._stack = self._stack[:self._index + 1]

        # Enforce max size
        if len(self._stack) >= self._max:
            self._stack.pop(0)
        else:
            self._index += 1

        self._stack.append(cmd)
        self.changed.emit()

    def undo(self):
        if not self.can_undo:
            return
        self._stack[self._index].undo()
        self._index -= 1
        self.changed.emit()

    def redo(self):
        if not self.can_redo:
            return
        self._index += 1
        self._stack[self._index].redo()
        self.changed.emit()

    def compound(self, description: str = "") -> _CompoundContext:
        """Context manager for grouping commands."""
        return _CompoundContext(self, description)

    def clear(self):
        self._stack.clear()
        self._index = -1
        self.changed.emit()

    # ── state queries ────────────────────────────────────────

    @property
    def can_undo(self) -> bool:
        return self._index >= 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._stack) - 1

    @property
    def undo_description(self) -> str:
        if not self.can_undo:
            return ""
        return self._stack[self._index].description

    @property
    def redo_description(self) -> str:
        if not self.can_redo:
            return ""
        return self._stack[self._index + 1].description

    # ── internal ─────────────────────────────────────────────

    def _begin_compound(self, description: str):
        self._compound_depth += 1
        if self._compound_depth == 1:
            self._compound = CompoundCommand(description)

    def _end_compound(self):
        self._compound_depth -= 1
        if self._compound_depth == 0 and self._compound is not None:
            compound = self._compound
            self._compound = None
            if len(compound) > 0:
                # Push without re-executing (already done)
                self._stack = self._stack[:self._index + 1]
                if len(self._stack) >= self._max:
                    self._stack.pop(0)
                else:
                    self._index += 1
                self._stack.append(compound)
                self.changed.emit()


class _CompoundContext:
    def __init__(self, stack: UndoStack, description: str):
        self._stack = stack
        self._description = description

    def __enter__(self):
        self._stack._begin_compound(self._description)
        return self

    def __exit__(self, *_):
        self._stack._end_compound()


# ─────────────────────────────────────────────────────────────
# Concrete commands
# ─────────────────────────────────────────────────────────────

class SetOpacityCommand(UndoCommand):
    def __init__(self, clip, old_val: float, new_val: float):
        super().__init__(f"Set Opacity")
        self.clip    = clip
        self.old_val = old_val
        self.new_val = new_val

    def redo(self):
        self.clip.set_opacity(self.new_val)

    def undo(self):
        self.clip.set_opacity(self.old_val)

    def try_merge(self, other: UndoCommand) -> bool:
        # Coalesce rapid opacity drags — keep first old, last new
        if (isinstance(other, SetOpacityCommand) and
                other.clip is self.clip):
            self.new_val = other.new_val
            return True
        return False


class SetVolumeCommand(UndoCommand):
    def __init__(self, clip, old_val: float, new_val: float):
        super().__init__("Set Volume")
        self.clip    = clip
        self.old_val = old_val
        self.new_val = new_val

    def redo(self):
        self.clip.set_volume(self.new_val)

    def undo(self):
        self.clip.set_volume(self.old_val)

    def try_merge(self, other: UndoCommand) -> bool:
        if (isinstance(other, SetVolumeCommand) and
                other.clip is self.clip):
            self.new_val = other.new_val
            return True
        return False


class SetMutedCommand(UndoCommand):
    def __init__(self, clip, old_val: bool, new_val: bool):
        super().__init__("Mute" if new_val else "Unmute")
        self.clip    = clip
        self.old_val = old_val
        self.new_val = new_val

    def redo(self):
        self.clip.muted = self.new_val

    def undo(self):
        self.clip.muted = self.old_val


class MoveClipCommand(UndoCommand):
    def __init__(self, clip, old_frame: int, new_frame: int,
                 old_track: int, new_track: int):
        super().__init__("Move Clip")
        self.clip      = clip
        self.old_frame = old_frame
        self.new_frame = new_frame
        self.old_track = old_track
        self.new_track = new_track

    def redo(self):
        self.clip.start_frame = self.new_frame
        self.clip.track       = self.new_track

    def undo(self):
        self.clip.start_frame = self.old_frame
        self.clip.track       = self.old_track


class AddClipCommand(UndoCommand):
    def __init__(self, project, clip, timeline_add_fn,
                 timeline_remove_fn):
        super().__init__("Add Clip")
        self.project           = project
        self.clip              = clip
        self.timeline_add_fn   = timeline_add_fn
        self.timeline_remove_fn = timeline_remove_fn

    def redo(self):
        self.project.clips[self.clip.id] = self.clip
        self.timeline_add_fn(self.clip)

    def undo(self):
        del self.project.clips[self.clip.id]
        self.timeline_remove_fn(self.clip.id)


class DeleteClipCommand(UndoCommand):
    def __init__(self, project, clip, timeline_add_fn,
                 timeline_remove_fn):
        super().__init__("Delete Clip")
        self.project            = project
        self.clip               = clip
        self.timeline_add_fn    = timeline_add_fn
        self.timeline_remove_fn = timeline_remove_fn

    def redo(self):
        del self.project.clips[self.clip.id]
        self.timeline_remove_fn(self.clip.id)

    def undo(self):
        self.project.clips[self.clip.id] = self.clip
        self.timeline_add_fn(self.clip)


class RazorCutCommand(UndoCommand):
    def __init__(self, project, original_clip, left_clip,
                 right_clip, timeline_add_fn, timeline_remove_fn):
        super().__init__("Razor Cut")
        self.project            = project
        self.original_clip      = original_clip
        self.left_clip          = left_clip
        self.right_clip         = right_clip
        self.timeline_add_fn    = timeline_add_fn
        self.timeline_remove_fn = timeline_remove_fn

    def redo(self):
        del self.project.clips[self.original_clip.id]
        self.timeline_remove_fn(self.original_clip.id)
        self.project.clips[self.left_clip.id]  = self.left_clip
        self.project.clips[self.right_clip.id] = self.right_clip
        self.timeline_add_fn(self.left_clip)
        self.timeline_add_fn(self.right_clip)

    def undo(self):
        del self.project.clips[self.left_clip.id]
        del self.project.clips[self.right_clip.id]
        self.timeline_remove_fn(self.left_clip.id)
        self.timeline_remove_fn(self.right_clip.id)
        self.project.clips[self.original_clip.id] = self.original_clip
        self.timeline_add_fn(self.original_clip)


class SetEffectParamCommand(UndoCommand):
    def __init__(self, clip, effect_id: str,
                 param: str, old_val, new_val):
        super().__init__(f"Set {param}")
        self.clip      = clip
        self.effect_id = effect_id
        self.param     = param
        self.old_val   = old_val
        self.new_val   = new_val

    def redo(self):
        fx = self.clip.get_effect(self.effect_id)
        if fx:
            fx.set(self.param, self.new_val)

    def undo(self):
        fx = self.clip.get_effect(self.effect_id)
        if fx:
            fx.set(self.param, self.old_val)

    def try_merge(self, other: UndoCommand) -> bool:
        if (isinstance(other, SetEffectParamCommand) and
                other.clip is self.clip and
                other.effect_id == self.effect_id and
                other.param == self.param):
            self.new_val = other.new_val
            return True
        return False


class RazorCutCommand(UndoCommand):
    """
    Undo a razor cut at a specific frame.

    Stores the original out_point of each left-half clip
    and the ids of the right-half clips created, so undo
    can cleanly reverse the split.

    Uses timeline.refresh() after undo/redo to avoid
    surgical item management that can leave stale visuals.
    """
    def __init__(self, project, frame: int,
                 left_clips: list,
                 original_out_points: dict,
                 right_clips: list,
                 timeline_refresh_fn,
                 update_playback_fn,
                 app_state=None):
        super().__init__("Razor Cut")
        self.project              = project
        self.frame                = frame
        self.left_clips           = left_clips
        self.original_out_points  = original_out_points
        self.right_clips          = right_clips
        self.timeline_refresh_fn  = timeline_refresh_fn
        self.update_playback_fn   = update_playback_fn
        self._app_state           = app_state

    def redo(self):
        # Trim left halves
        for c in self.left_clips:
            c.out_point = c.in_point + (self.frame - c.start_frame)
        # Re-add right halves to project
        for r in self.right_clips:
            self.project.clips[r.id] = r
        self._refresh_and_restore_tool()

    def _refresh_and_restore_tool(self):
        self.timeline_refresh_fn()
        self.update_playback_fn()
        # refresh() rebuilds canvases — re-emit tool so new
        # widgets pick up the current tool state
        if self._app_state is not None:
            tool = self._app_state.active_tool
            self._app_state.tool_changed.emit(tool)

    def undo(self):
        # Remove right halves from project
        for r in self.right_clips:
            self.project.clips.pop(r.id, None)
        # Restore left halves' original out_point
        for c in self.left_clips:
            c.out_point = self.original_out_points[c.id]
        self._refresh_and_restore_tool()


# Global singleton
undo_stack = UndoStack()
