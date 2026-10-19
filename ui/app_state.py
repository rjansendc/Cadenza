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
        # True while the playhead is being dragged: frames are drawn
        # from the nearest keyframe so the picture follows the mouse
        self.scrubbing: bool = False

        # --- selection ---
        self._selected_clip_ids: List[str] = []
        self._primary_clip_id:   str       = None

        # --- timeline scale ---
        # Absolute: pixels per frame. Nothing about the content changes
        # it, so dropping, stretching or deleting a clip leaves the
        # ruler and every other clip exactly where they were.
        # None means "not zoomed yet" — the span then stays at
        # DEFAULT_VISIBLE_FRAMES however wide the window is.
        self._px_per_frame: float = None
        self._scroll_frame: float = 0.0    # leftmost visible frame
        self._view_width:   float = 1000.0 # canvas width, kept in sync

        # --- tools ---
        self._active_tool: str = 'select'
        # tools: 'select', 'razor', 'trim'

        # --- total project duration ---
        # The content extent. It sets how far the timeline scrolls; it
        # no longer has any say in the scale.
        self._total_frames: int = 0

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

    # --- content extent ---

    @property
    def total_frames(self) -> int:
        """Frame the last clip ends on. Sets the scroll range only."""
        return self._total_frames

    @total_frames.setter
    def total_frames(self, frames: int):
        frames = max(0, int(frames))
        if frames == self._total_frames:
            return
        self._total_frames = frames
        # The scroll range moved, so the zoom bar and ruler need a
        # repaint. Clip geometry does not depend on this any more, but
        # this used to be a plain attribute — changing it rescaled the
        # whole timeline with nothing telling the widgets to re-lay out.
        self._clamp_scroll()
        self.zoom_changed.emit(self.view_start, self.view_end)

    # --- scale ---

    @property
    def px_per_frame(self) -> float:
        """Pixels one frame occupies. The zoom, absolutely."""
        from ui.constants import DEFAULT_VISIBLE_FRAMES
        if self._px_per_frame and self._px_per_frame > 0:
            return self._px_per_frame
        return self._view_width / DEFAULT_VISIBLE_FRAMES

    @property
    def visible_frames(self) -> float:
        """How much time the window shows."""
        ppf = self.px_per_frame
        return self._view_width / ppf if ppf > 0 else 0.0

    @property
    def scroll_frames(self) -> float:
        """
        How far the timeline scrolls: the content plus empty room past
        it, never less than the default span. This is what the zoom
        bar's full width stands for.
        """
        from ui.constants import (DEFAULT_VISIBLE_FRAMES,
                                   SCROLL_PAD_FRAMES)
        return float(max(self._total_frames + SCROLL_PAD_FRAMES,
                         DEFAULT_VISIBLE_FRAMES))

    @property
    def view_width(self) -> float:
        return self._view_width

    def set_view_width(self, width: float):
        """
        Tell the state how wide the timeline canvases are.

        A window resize keeps the zoom and reveals more time, which is
        what an absolute scale means. Before the first zoom there is no
        scale to keep, so the default span holds instead.
        """
        width = float(width)
        if width <= 0 or abs(width - self._view_width) < 0.5:
            return
        self._view_width = width
        self._clamp_scroll()
        self.zoom_changed.emit(self.view_start, self.view_end)

    # --- zoom, as the normalized window the overview widgets want ---

    @property
    def view_start(self) -> float:
        sf = self.scroll_frames
        return self._scroll_frame / sf if sf > 0 else 0.0

    @property
    def view_end(self) -> float:
        sf = self.scroll_frames
        if sf <= 0:
            return 1.0
        return min(1.0, (self._scroll_frame + self.visible_frames) / sf)

    @property
    def visible_range(self) -> float:
        return self.view_end - self.view_start

    @property
    def zoom_level(self) -> float:
        r = self.visible_range
        return 1.0 / r if r > 0 else 1.0

    @property
    def scroll_frame(self) -> float:
        """Leftmost visible frame."""
        return self._scroll_frame

    def _clamp_scroll(self):
        """Keep the window inside the scrollable range."""
        limit = max(0.0, self.scroll_frames - self.visible_frames)
        self._scroll_frame = max(0.0, min(self._scroll_frame, limit))

    def _apply_scale(self, px_per_frame: float, scroll_frame: float):
        """Set zoom and scroll together, clamped, and emit once."""
        from ui.constants import MIN_VISIBLE_FRAMES
        w  = self._view_width
        sf = self.scroll_frames
        # fully zoomed out shows the whole scroll range; fully in,
        # MIN_VISIBLE_FRAMES across the window
        lo = w / sf if sf > 0 else px_per_frame
        hi = w / MIN_VISIBLE_FRAMES
        new_ppf = max(lo, min(float(px_per_frame), hi))

        old = (self._px_per_frame, self._scroll_frame)
        self._px_per_frame = new_ppf
        self._scroll_frame = scroll_frame
        self._clamp_scroll()
        if (self._px_per_frame, self._scroll_frame) != old:
            self.zoom_changed.emit(self.view_start, self.view_end)

    def set_view(self, start: float, end: float):
        """Set the visible window as a fraction of the scroll range."""
        from ui.constants import MIN_VISIBLE_FRAMES
        sf    = self.scroll_frames
        start = max(0.0, min(start, 1.0))
        end   = max(0.0, min(end,   1.0))
        if end <= start:
            end = min(1.0, start + MIN_VISIBLE_FRAMES / sf)
        visible = max(MIN_VISIBLE_FRAMES, (end - start) * sf)
        self._apply_scale(self._view_width / visible, start * sf)

    def zoom_in_at_position(self,
                             norm_pos: float,
                             factor: float = 0.75):
        """
        Zoom in keeping norm_pos (0.0-1.0) fixed on screen.
        Called on scroll wheel up — factor < 1.0 shows less time.
        """
        from ui.constants import MIN_VISIBLE_FRAMES
        visible = self.visible_frames
        anchor  = norm_pos * self.scroll_frames
        # where the anchor sits across the window right now
        frac = ((anchor - self._scroll_frame) / visible
                if visible > 0 else 0.5)
        frac = max(0.0, min(frac, 1.0))
        new_visible = max(MIN_VISIBLE_FRAMES, visible * factor)
        self._apply_scale(self._view_width / new_visible,
                          anchor - frac * new_visible)

    def zoom_out_at_position(self,
                              norm_pos: float,
                              factor: float = 1.33):
        self.zoom_in_at_position(norm_pos, factor)

    def pan_by(self, delta_norm: float):
        """Pan timeline by a normalized delta."""
        self._apply_scale(self.px_per_frame,
                          self._scroll_frame +
                          delta_norm * self.scroll_frames)

    def zoom_to_fit(self, first_frame: int, last_frame: int,
                    margin: float = 0.05):
        """Fit a frame range to the window — only ever on request."""
        from ui.constants import MIN_VISIBLE_FRAMES
        span = max(1.0, float(last_frame - first_frame))
        pad  = span * margin
        visible = max(MIN_VISIBLE_FRAMES, span + pad * 2)
        self._apply_scale(self._view_width / visible,
                          first_frame - pad)

    # --- frame/pixel conversion ---

    def frame_to_norm(self, frame: int) -> float:
        """Convert frame number to normalized scroll-range position."""
        sf = self.scroll_frames
        return frame / sf if sf > 0 else 0.0

    def norm_to_frame(self, norm: float) -> int:
        """Convert normalized scroll-range position to frame number."""
        return int(round(norm * self.scroll_frames))

    def pixel_to_norm(self,
                       pixel: float,
                       view_width: float) -> float:
        """
        Convert a pixel x position in the timeline view
        to a normalized timeline position.
        """
        return self.frame_to_norm(
            self.pixel_to_frame(pixel, view_width))

    def norm_to_pixel(self,
                       norm: float,
                       view_width: float) -> float:
        """Convert normalized position to pixel x in timeline."""
        return self.frame_to_pixel(
            norm * self.scroll_frames, view_width)

    def frame_to_pixel(self,
                        frame: int,
                        view_width: float) -> float:
        """
        Frame → pixel x in the timeline.

        view_width is accepted for call compatibility and ignored: the
        scale is absolute, so it cannot depend on how wide the window
        happens to be.
        """
        return (frame - self._scroll_frame) * self.px_per_frame

    def pixel_to_frame(self,
                        pixel: float,
                        view_width: float) -> int:
        """Pixel x in the timeline → frame. view_width is ignored."""
        ppf = self.px_per_frame
        if ppf <= 0:
            return 0
        return int(round(self._scroll_frame + pixel / ppf))

    def frames_per_pixel(self) -> float:
        """How many frames one pixel of drag covers."""
        ppf = self.px_per_frame
        return 1.0 / ppf if ppf > 0 else 0.0

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