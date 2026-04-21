from dataclasses import dataclass, field
from typing import List, Optional
from PySide6.QtCore import QObject, Signal

class AppState(QObject):
    """
    Runtime state — never saved to disk.
    All UI panels read from this and connect to its signals.
    This is the switchboard between panels.
    """

    # --- signals --- panels connect to these
    playhead_changed      = Signal(int)        # frame number
    selection_changed     = Signal(list)       # list of clip ids
    zoom_changed          = Signal(float, float)  # view_start, view_end
    tool_changed          = Signal(str)        # tool name
    project_changed       = Signal()           # full refresh needed
    clip_modified         = Signal(str)        # clip_id — effect/property changed

    def __init__(self, parent=None):
        super().__init__(parent)

        # --- playhead ---
        self._playhead_frame: int = 0

        # --- selection ---
        self._selected_clip_ids: List[str] = []
        self._primary_clip_id:   str       = None

        # --- timeline zoom (normalized 0.0 to 1.0) ---
        self._view_start: float = 0.0
        self._view_end:   float = 1.0

        # --- tools ---
        self._active_tool: str = 'select'  
        # tools: 'select', 'razor', 'trim'

        # --- total project duration ---
        self.total_frames: int = 0

    # --- playhead ---

    @property
    def playhead_frame(self) -> int:
        return self._playhead_frame

    @playhead_frame.setter
    def playhead_frame(self, frame: int):
        frame = max(0, frame)
        if frame != self._playhead_frame:
            self._playhead_frame = frame
            self.playhead_changed.emit(frame)

    # --- selection ---

    @property
    def selected_clip_ids(self) -> List[str]:
        return list(self._selected_clip_ids)

    def select_clip(self, clip_id: str,
                    add_to_selection: bool = False,
                    emit: bool = True):
        if add_to_selection:
            if clip_id not in self._selected_clip_ids:
                self._selected_clip_ids.append(clip_id)
        else:
            self._selected_clip_ids = [clip_id]
            self._primary_clip_id = clip_id
        if emit:
            self.selection_changed.emit(self._selected_clip_ids)

    @property
    def primary_clip_id(self) -> str:
        return self._primary_clip_id

    def select_clips(self, clip_ids, add_to_selection: bool = False):
        """Select multiple clips, emitting only once.
        First clip in list is the primary (clicked) clip."""
        if not add_to_selection:
            self._selected_clip_ids = []
        for cid in clip_ids:
            if cid not in self._selected_clip_ids:
                self._selected_clip_ids.append(cid)
        # First clip is always the primary (the one clicked)
        if clip_ids:
            self._primary_clip_id = clip_ids[0]
        self.selection_changed.emit(self._selected_clip_ids)

    def deselect_all(self):
        if self._selected_clip_ids:
            self._selected_clip_ids = []
            self.selection_changed.emit([])

    def is_selected(self, clip_id: str) -> bool:
        return clip_id in self._selected_clip_ids

    # --- zoom ---

    @property
    def view_start(self) -> float:
        return self._view_start

    @property
    def view_end(self) -> float:
        return self._view_end

    @property
    def visible_range(self) -> float:
        return self._view_end - self._view_start

    @property
    def zoom_level(self) -> float:
        r = self.visible_range
        return 1.0 / r if r > 0 else 1.0

    def set_view(self, start: float, end: float):
        """Set zoom bar position directly — clamp and emit."""
        start = max(0.0, min(start, 1.0))
        end   = max(0.0, min(end,   1.0))
        # enforce minimum visible range (max zoom limit)
        MIN_RANGE = 0.005
        if end - start < MIN_RANGE:
            # keep center fixed, expand to minimum
            center = (start + end) / 2
            start  = center - MIN_RANGE / 2
            end    = center + MIN_RANGE / 2
            start  = max(0.0, start)
            end    = min(1.0, end)
        if (start != self._view_start or 
                end != self._view_end):
            self._view_start = start
            self._view_end   = end
            self.zoom_changed.emit(start, end)

    def zoom_in_at_position(self, 
                             norm_pos: float,
                             factor: float = 0.75):
        """
        Zoom in keeping norm_pos (0.0-1.0) fixed on screen.
        Called on scroll wheel up — factor < 1.0 shrinks range.
        norm_pos is the normalized timeline position 
        under the mouse cursor.
        """
        r         = self.visible_range
        new_range = max(r * factor, 0.005)
        # keep norm_pos at same screen fraction
        frac      = ((norm_pos - self._view_start) / r 
                     if r > 0 else 0.5)
        new_start = norm_pos - frac * new_range
        new_end   = new_start + new_range
        self.set_view(new_start, new_end)

    def zoom_out_at_position(self,
                              norm_pos: float,
                              factor: float = 1.33):
        self.zoom_in_at_position(norm_pos, factor)

    def pan_by(self, delta_norm: float):
        """Pan timeline by a normalized delta."""
        new_start = self._view_start + delta_norm
        new_end   = self._view_end   + delta_norm
        # clamp without changing range
        if new_start < 0.0:
            new_end   -= new_start
            new_start  = 0.0
        if new_end > 1.0:
            new_start -= (new_end - 1.0)
            new_end    = 1.0
        self.set_view(new_start, new_end)

    # --- frame/pixel conversion ---

    def frame_to_norm(self, frame: int) -> float:
        """Convert frame number to normalized 0.0-1.0 position."""
        if self.total_frames <= 0:
            return 0.0
        return frame / self.total_frames

    def norm_to_frame(self, norm: float) -> int:
        """Convert normalized position to frame number."""
        return int(norm * self.total_frames)

    def pixel_to_norm(self, 
                       pixel: float, 
                       view_width: float) -> float:
        """
        Convert a pixel x position in the timeline view
        to a normalized timeline position.
        """
        frac = pixel / view_width if view_width > 0 else 0.0
        return self._view_start + frac * self.visible_range

    def norm_to_pixel(self, 
                       norm: float, 
                       view_width: float) -> float:
        """Convert normalized position to pixel x in timeline."""
        frac = ((norm - self._view_start) / self.visible_range
                if self.visible_range > 0 else 0.0)
        return frac * view_width

    def frame_to_pixel(self, 
                        frame: int, 
                        view_width: float) -> float:
        """Direct frame → pixel conversion."""
        return self.norm_to_pixel(
            self.frame_to_norm(frame), view_width
        )

    def pixel_to_frame(self, 
                        pixel: float, 
                        view_width: float) -> int:
        """Direct pixel → frame conversion."""
        return self.norm_to_frame(
            self.pixel_to_norm(pixel, view_width)
        )

    # --- tool ---

    @property
    def active_tool(self) -> str:
        return self._active_tool

    @active_tool.setter
    def active_tool(self, tool: str):
        valid = ('select', 'razor', 'trim')
        if tool in valid and tool != self._active_tool:
            self._active_tool = tool
            self.tool_changed.emit(tool)

    # --- timecode helper ---

    def frame_to_timecode(self, 
                           frame: int, 
                           fps: float = 29.97) -> str:
        total_seconds = frame / fps
        h  = int(total_seconds // 3600)
        m  = int((total_seconds % 3600) // 60)
        s  = int(total_seconds % 60)
        f  = int((total_seconds % 1) * fps)
        return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"

    def __repr__(self):
        return (f"AppState(frame={self._playhead_frame} | "
                f"tool={self._active_tool} | "
                f"zoom={self.zoom_level:.2f}x | "
                f"selected={len(self._selected_clip_ids)})")