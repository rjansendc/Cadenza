"""
TimelinePanel — new unified track architecture.

Each track is a TrackRow:
  TrackHeader (controls, left) + TrackCanvas (clips, right)

Layout:
  ┌─────────────────────────────────────────┐
  │  Ruler (fixed height)                   │
  ├─────────────────────────────────────────┤
  │  QScrollArea                            │
  │    TrackStack                           │
  │      TrackRow: V3                       │
  │      TrackRow: V2                       │
  │      TrackRow: V1                       │
  │      TrackRow: A1                       │
  │      TrackRow: A2                       │
  │      TrackRow: A3                       │
  ├─────────────────────────────────────────┤
  │  ZoomBar (fixed height)                 │
  └─────────────────────────────────────────┘

Alignment is guaranteed — header and canvas are
siblings in the same TrackRow widget.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QSizePolicy, QLabel, QRubberBand
)
from PySide6.QtCore import Qt, QRectF, QRect, QPoint, Signal
from PySide6.QtGui import QColor, QPen, QBrush, QPainter

from core.project import Project
from core.track import Sequence, TrackType
from ui.app_state import AppState
from ui.widgets.ruler import Ruler
from ui.widgets.track_header import TrackRow
from ui.widgets.zoom_bar import ZoomBar
from ui.constants import (
    TRACK_HEADER_WIDTH, compute_track_layout
)


class TrackStack(QWidget):
    """
    Container for all TrackRow widgets.
    Lives inside the QScrollArea.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed
        )

    def add_row(self, row: TrackRow):
        self._layout.addWidget(row)

    def total_height(self) -> int:
        h = 0
        for i in range(self._layout.count()):
            w = self._layout.itemAt(i).widget()
            if w:
                h += w.height()
        return h


class TimelinePanel(QWidget):
    """
    Full timeline panel with unified TrackRow architecture.
    """

    def __init__(self, project: Project,
                 app_state: AppState,
                 parent=None):
        super().__init__(parent)
        self.project   = project
        self.app_state = app_state

        # track_id → TrackRow
        self._rows: dict = {}

        self.setMinimumHeight(180)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        seq = self.project.active_sequence
        fps = seq.settings.fps if seq else 29.97

        # ── Ruler row ────────────────────────────────────
        ruler_row = QHBoxLayout()
        ruler_row.setContentsMargins(0, 0, 0, 0)
        ruler_row.setSpacing(0)

        corner = QWidget()
        corner.setFixedSize(TRACK_HEADER_WIDTH,
                            Ruler.HEIGHT)
        corner.setStyleSheet(
            'background-color:#141414;'
            'border-right:1px solid #333;'
            'border-bottom:1px solid #333;'
        )
        ruler_row.addWidget(corner)

        self.ruler = Ruler(self.app_state, fps)
        ruler_row.addWidget(self.ruler)
        layout.addLayout(ruler_row)

        # ── Scroll area ───────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(
            QScrollArea.Shape.NoFrame
        )
        self._scroll.setStyleSheet(
            'QScrollArea { background: #111111; '
            'border: none; }'
        )

        self._track_stack = TrackStack()
        self._scroll.setWidget(self._track_stack)
        layout.addWidget(self._scroll)

        # Rubber band state — installed on canvases after rows built
        self._rubber_active  = False
        self._rubber_origin  = None  # in viewport coords
        self._rubber_current = None
        self._rubber_mods    = Qt.KeyboardModifier.NoModifier
        self._rubber_band    = QRubberBand(
            QRubberBand.Shape.Rectangle,
            self._scroll.viewport()
        )

        # build track rows
        if seq:
            self._build_rows(seq)
            self._install_rubber_filters()

        # outside-track razor cursor
        self.app_state.tool_changed.connect(
            self._on_tool_changed
        )

        # ── Zoom bar ─────────────────────────────────────
        zoom_row = QHBoxLayout()
        zoom_row.setContentsMargins(0, 0, 0, 0)
        zoom_row.setSpacing(0)
        spacer = QWidget()
        spacer.setFixedWidth(TRACK_HEADER_WIDTH)
        spacer.setStyleSheet('background:#141414;')
        zoom_row.addWidget(spacer)
        zoom_row.addWidget(ZoomBar(self.app_state))
        layout.addLayout(zoom_row)

    def eventFilter(self, obj, event):
        """Handle rubber band on each canvas viewport."""
        from PySide6.QtCore import QEvent, QPointF

        # Only handle canvas viewports
        canvas = None
        for row in self._rows.values():
            if obj is row.canvas.viewport():
                canvas = row.canvas
                break
        if canvas is None:
            return False

        t = event.type()

        if t == QEvent.Type.MouseButtonPress:
            if event.button() != Qt.MouseButton.LeftButton:
                return False
            # Convert to scroll viewport coordinates
            vp_pos = self._scroll.viewport().mapFromGlobal(
                canvas.viewport().mapToGlobal(event.pos())
            )
            if self._clip_at_viewport(vp_pos):
                return False  # let canvas handle normally
            # Start rubber band
            self._rubber_active  = True
            self._rubber_origin  = QPointF(vp_pos)
            self._rubber_current = QPointF(vp_pos)
            self._rubber_mods    = event.modifiers()
            if not (self._rubber_mods &
                    Qt.KeyboardModifier.ShiftModifier):
                self.app_state.deselect_all()
            self._rubber_band.setGeometry(QRect(vp_pos, vp_pos))
            self._rubber_band.show()
            return True

        elif t == QEvent.Type.MouseMove:
            if not self._rubber_active:
                return False
            vp_pos = self._scroll.viewport().mapFromGlobal(
                canvas.viewport().mapToGlobal(event.pos())
            )
            self._rubber_current = QPointF(vp_pos)
            self._rubber_band.setGeometry(
                QRect(self._rubber_origin.toPoint(),
                      vp_pos).normalized())
            return False  # don't block canvas move events

        elif t == QEvent.Type.MouseButtonRelease:
            if not self._rubber_active:
                return False
            if event.button() != Qt.MouseButton.LeftButton:
                return False
            self._rubber_active = False
            self._rubber_band.hide()
            self._select_clips_in_rubber_band()
            self._rubber_origin  = None
            self._rubber_current = None
            return True

        return False

    def _clip_at_viewport(self, pos):
        """Return True if a ClipItem is under viewport pos."""
        from PySide6.QtCore import QPoint
        from ui.constants import TRACK_HEADER_WIDTH
        from ui.widgets.clip_item import ClipItem
        stack = self._track_stack
        vp    = self._scroll.viewport()
        stack_pos = stack.mapFrom(vp, pos)
        if stack_pos.x() < TRACK_HEADER_WIDTH:
            return True
        for row in self._rows.values():
            canvas = row.canvas
            canvas_pos = canvas.mapFrom(stack, stack_pos)
            scene_pos  = canvas.mapToScene(canvas_pos)
            for item in canvas._scene.items(scene_pos):
                if isinstance(item, ClipItem):
                    return True
        return False

    def _select_clips_in_rubber_band(self):
        from PySide6.QtCore import QRectF
        from ui.widgets.clip_item import ClipItem
        if self._rubber_origin is None:
            return
        band = QRectF(
            self._rubber_origin, self._rubber_current
        ).normalized()
        stack = self._track_stack
        vp    = self._scroll.viewport()
        ids   = []
        for row in self._rows.values():
            canvas = row.canvas
            def vp_to_scene(pt):
                sp = stack.mapFrom(vp, pt.toPoint())
                cp = canvas.mapFrom(stack, sp)
                return canvas.mapToScene(cp)
            tl = vp_to_scene(band.topLeft())
            br = vp_to_scene(band.bottomRight())
            sr = QRectF(tl, br).normalized()
            for item in canvas._scene.items(sr):
                if isinstance(item, ClipItem):
                    if item.clip.id not in ids:
                        ids.append(item.clip.id)
                    if item.clip.link_group_id:
                        for cid, other in                                 canvas._clip_items.items():
                            if (other.clip.link_group_id ==
                                    item.clip.link_group_id
                                    and cid not in ids):
                                ids.append(cid)
        if ids:
            add = bool(self._rubber_mods &
                       Qt.KeyboardModifier.ShiftModifier)
            self.app_state.select_clips(ids,
                                         add_to_selection=add)
            # refresh visuals
            selected = set(self.app_state.selected_clip_ids)
            for row in self._rows.values():
                for cid, item in row.canvas._clip_items.items():
                    item._is_selected = cid in selected
                    item.update()

    def _on_tool_changed(self, tool: str):
        """Set outside-track cursor on panel."""
        if tool == 'razor':
            from ui.widgets.track_header import TrackCanvas
            self.setCursor(
                TrackCanvas._make_razor_cursor(
                    outside=True
                )
            )
            self._scroll.setCursor(
                TrackCanvas._make_razor_cursor(
                    outside=True
                )
            )
        else:
            self.setCursor(
                Qt.CursorShape.ArrowCursor
            )
            self._scroll.setCursor(
                Qt.CursorShape.ArrowCursor
            )

    def _install_rubber_filters(self):
        """Install eventFilter on every canvas viewport."""
        for row in self._rows.values():
            vp = row.canvas.viewport()
            vp.installEventFilter(self)
            vp.setMouseTracking(True)

    def _build_rows(self, sequence: Sequence):
        """Create one TrackRow per track."""
        # V3 first (top), V1 last, then A1-A3
        for track in reversed(sequence.video_tracks):
            self._add_row(track)
        for track in sequence.audio_tracks:
            self._add_row(track)

    def _add_row(self, track):
        row = TrackRow(track, self.app_state)
        row.height_changed.connect(
            self._on_track_height_changed
        )
        row.clip_dropped.connect(
            self._on_clip_dropped
        )
        self._rows[track.id] = row
        self._track_stack.add_row(row)
        # install rubber band filter on new canvas
        row.canvas.viewport().installEventFilter(self)
        row.canvas.viewport().setMouseTracking(True)

    # =========================================================
    # Public API — called from mainwindow
    # =========================================================

    def add_clip(self, clip):
        """Add clip visual to correct TrackRow canvas."""
        seq = self.project.active_sequence
        if not seq:
            return

        # find which track this clip belongs to
        if clip.has_video:
            tracks = seq.video_tracks
        else:
            tracks = seq.audio_tracks

        if clip.track >= len(tracks):
            return

        track    = tracks[clip.track]
        row      = self._rows.get(track.id)
        if row:
            row.canvas.add_clip(clip)

    def remove_clip(self, clip_id: str):
        """Remove clip from whichever canvas owns it."""
        for row in self._rows.values():
            if clip_id in row.canvas._clip_items:
                row.canvas.remove_clip(clip_id)
                return

    def refresh(self):
        """
        Reload all clips from project.
        Also rebuilds track rows if sequence changed.
        """
        # clear all existing rows
        for row in list(self._rows.values()):
            row.canvas._clip_items.clear()
            row.canvas._waveform_items.clear()
            row.canvas._scene.clear()
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        # rebuild rows from current sequence
        seq = self.project.active_sequence
        if seq:
            self._build_rows(seq)

        # reload clips
        for clip in self.project.clips.values():
            self.add_clip(clip)

         
        # update total_frames to match actual clip extent
        if self.project.clips:
            max_end = max(
                c.start_frame + c.duration
                for c in self.project.clips.values()
            )
            old_total = self.app_state.total_frames
            self.app_state.total_frames = max_end
            # If total shrank significantly, reset view
            if max_end < old_total * 0.9:
                self.app_state.set_view(0.0, 1.0)

    def get_all_clip_items(self):
        """Return all ClipItem objects across all canvases."""
        items = {}
        for row in self._rows.values():
            items.update(row.canvas._clip_items)
        return items

    def get_canvas_for_track(self, track_id: str):
        row = self._rows.get(track_id)
        return row.canvas if row else None

    # =========================================================
    # Signals
    # =========================================================

    def _on_track_height_changed(self,
                                  track_id: str,
                                  new_height: int):
        """Track resized — TrackRow handles its own height."""
        # update scene width if needed
        row = self._rows.get(track_id)
        if row:
            row.canvas.update_height(new_height)

    def _on_clip_dropped(self, track_id: str,
                          item_id: str,
                          start_frame: int):
        """
        Media dropped onto a TrackCanvas.
        Find the track and emit to mainwindow.
        """
        seq = self.project.active_sequence
        if not seq:
            return

        # find row number for this track
        row_idx = self._track_id_to_row(
            track_id, seq
        )
        if row_idx < 0:
            return

        # emit to mainwindow via media_dropped
        # reuse existing mainwindow handler
        self._emit_media_dropped(
            item_id, row_idx, start_frame
        )

    def _track_id_to_row(self, track_id: str,
                          seq: Sequence) -> int:
        """Convert track_id to row index (0=V3 top)."""
        layout = compute_track_layout(seq)
        for i, row in enumerate(layout['rows']):
            if row['track'].id == track_id:
                return i
        return -1

    def _emit_media_dropped(self, item_id, row, frame):
        """
        Find mainwindow and call its drop handler.
        Keeps mainwindow as the single coordinator.
        """
        main = self.window()
        if hasattr(main, '_on_media_dropped'):
            main._on_media_dropped(
                item_id, row, frame
            )

    # =========================================================
    # Razor tool support
    # =========================================================

    def get_clip_item(self, clip_id: str):
        """Find a ClipItem by clip_id across all canvases."""
        for row in self._rows.values():
            item = row.canvas._clip_items.get(clip_id)
            if item:
                return item
        return None

    def add_clip_item_to_canvas(self, clip,
                                 canvas_override=None):
        """Add new clip visual after razor cut."""
        self.add_clip(clip)

    def update_all_playheads(self):
        for row in self._rows.values():
            row.canvas._update_playhead()

    # =========================================================
    # Razor tool
    # =========================================================

    def row_at_global_pos(self, global_pos):
        """
        Find the TrackRow under a global screen position.
        Returns TrackRow or None.
        """
        for row in self._rows.values():
            # map global pos to row local coords
            from PySide6.QtCore import QPoint
            gp = global_pos
            local = row.mapFromGlobal(
                QPoint(int(gp.x()), int(gp.y()))
            )
            if row.rect().contains(local):
                return row
        return None

    def move_clip_to_track(self, clip,
                            from_canvas,
                            to_row):
        """
        Move a clip from one canvas to another.
        Updates clip.track, refreshes colors,
        repositions geometry.
        """
        clip_id = clip.id

        # get the item from old canvas
        item = from_canvas._clip_items.pop(
            clip_id, None
        )
        if item is None:
            return

        # remove from old scene
        from_canvas._scene.removeItem(item)

        # also move waveform item if exists
        wf = from_canvas._waveform_items.pop(
            clip_id, None
        )

        # update clip track index
        clip.track = to_row.track.index

        # refresh clip color for new track
        item._refresh_colors()

        # add to new canvas
        to_canvas = to_row.canvas
        to_canvas._scene.addItem(item)
        to_canvas._clip_items[clip_id] = item
        item.update_geometry_flat()

        # re-parent waveform if it existed
        if wf is not None:
            to_canvas._waveform_items[clip_id] = wf

    def do_razor_cut(self, frame: int,
                     clicked_clip_id: str = None,
                     cut_all: bool = False):
        """
        Cut clips at frame.
        - If clicked_clip_id given and not cut_all:
          cut only that clip + its linked partners.
        - If cut_all or no clicked_clip_id:
          cut all clips spanning frame.
        Shift key = cut_all.
        """
        main = self.window()
        if not hasattr(main, 'project'):
            return

        seen_groups = set()
        to_cut = []

        if clicked_clip_id and not cut_all:
            # Only cut the clicked clip's link group
            clicked = main.project.clips.get(clicked_clip_id)
            if clicked:
                key = clicked.link_group_id or clicked.id
                seen_groups.add(key)
                to_cut.append(clicked_clip_id)
        else:
            # Cut all clips spanning this frame
            for row in self._rows.values():
                for clip_id, item in list(
                    row.canvas._clip_items.items()
                ):
                    c = item.clip
                    if not (c.start_frame <= frame <
                            c.start_frame + c.duration):
                        continue
                    key = c.link_group_id or c.id
                    if key in seen_groups:
                        continue
                    seen_groups.add(key)
                    to_cut.append(clip_id)

        if not to_cut:
            return

        from core.undo import undo_stack, RazorCutCommand

        for clip_id in to_cut:
            # Capture left-half clips and their current out_points
            # BEFORE split_clip modifies them
            group = main.project.get_link_group(clip_id)
            if not group:
                c = main.project.clips.get(clip_id)
                group = [c] if c else []

            left_clips = [
                c for c in group
                if c.start_frame < frame <
                   c.start_frame + c.duration
            ]
            original_out_points = {
                c.id: c.out_point for c in left_clips
            }

            # split_clip handles entire link group
            new_clips = main.project.split_clip(
                clip_id, frame
            )
            if not new_clips:
                continue

            # Record undo command (action already done by split_clip)
            cmd = RazorCutCommand(
                project=main.project,
                frame=frame,
                left_clips=left_clips,
                original_out_points=original_out_points,
                right_clips=new_clips,
                timeline_refresh_fn=self.refresh,
                update_playback_fn=main._update_playback_clips,
                app_state=self.app_state,
            )
            # Push without re-executing (split_clip already ran)
            undo_stack._stack = undo_stack._stack[
                :undo_stack._index + 1
            ]
            if len(undo_stack._stack) >= undo_stack._max:
                undo_stack._stack.pop(0)
            else:
                undo_stack._index += 1
            undo_stack._stack.append(cmd)
            undo_stack.changed.emit()

            # update geometry of left halves
            for row in self._rows.values():
                for cid, item in (
                    row.canvas._clip_items.items()
                ):
                    item.update_geometry_flat()

            # add right halves to correct canvases
            for new_clip in new_clips:
                self.add_clip(new_clip)

        main._update_playback_clips()
        if hasattr(main, '_update_undo_actions'):
            main._update_undo_actions()
        tc = self.app_state.frame_to_timecode(frame)
        main.status_label.setText(
            f'Cut at {tc}'
        )
