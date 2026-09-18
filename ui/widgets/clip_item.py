from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsItem
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QColor, QPen, QPainter, QBrush, QFont, QPolygonF
)
from core.clip import Clip
from ui.app_state import AppState
from ui.constants import (
    TRACK_HEIGHT, CLIP_PADDING,
    video_row, audio_row, row_to_y,
    y_to_row, snap_row_for_clip,
    NUM_VIDEO_TRACKS
)

SNAP_THRESHOLD_PX = 5    # pixels within which snap fires

VIDEO_COLORS = [
    ('#1a5a7a', '#2a8ab0'),   # V1
    ('#1a5a3a', '#2a8a5a'),   # V2
    ('#5a3a7a', '#8a5ab0'),   # V3
]
AUDIO_COLORS = [
    ('#1a4a2a', '#2a7a4a'),   # A1
    ('#1a3a4a', '#2a6a7a'),   # A2
    ('#3a3a1a', '#6a6a2a'),   # A3
]


class ClipItem(QGraphicsRectItem):
    """
    A single clip block on the timeline.
    Snaps to track rows and frames.
    Overlap-aware drag.
    """

    def __init__(self, clip: Clip,
                 app_state: AppState,
                 view_width: float,
                 track_y=None,    # NEW
                 track_h=None,
                 parent=None):
        super().__init__(parent)
        self.clip       = clip
        self.app_state  = app_state
        self.view_width = view_width

        self._is_selected     = False
        self._is_hovered      = False
        self._drag_start      = None
        self._drag_orig_frame = 0
        self._drag_orig_track = 0
        self._drag_orig_row   = 0

        # trim state
        self._trim_edge      = None  # 'left' or 'right'
        self._trim_start_x   = 0.0
        self._trim_orig_in   = 0
        self._trim_orig_out  = -1
        self._trim_orig_start = 0
        self.TRIM_ZONE       = 10  # px from edge
        self._colors          = self._get_colors()
        self.track_y = track_y   # set by timeline
        self.track_h = track_h   # set by timeline

        # keyframe marker drag state
        self._kf_drag_frame    = None   # frame being dragged
        self._kf_drag_orig     = None   # where it started
        self._kf_overwritten   = {}     # keyframes it landed on

        # opacity envelope drag state
        self._env_dragging     = False
        self._env_drag_start_y = 0.0
        self._env_start_val    = 1.0

        self.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(10)

        self.update_geometry()

    # =========================================================
    # Colors
    # =========================================================

    def _get_colors(self):
        idx = self.clip.track % 3
        if self.clip.has_video:
            return VIDEO_COLORS[idx]
        return AUDIO_COLORS[idx]

    def _refresh_colors(self):
        self._colors = self._get_colors()

    # =========================================================
    # Geometry
    # =========================================================

    def update_geometry(self, sequence=None):
        """Recalculate position from zoom and track height."""
        total = self.app_state.total_frames
        if total <= 0:
            return

        x1 = self.app_state.frame_to_pixel(
            self.clip.start_frame, self.view_width
        )
        x2 = self.app_state.frame_to_pixel(
            self.clip.start_frame + self.clip.duration,
            self.view_width
        )
        w = max(x2 - x1, 4.0)

        # get y and height from sequence if available
        if sequence is not None:
            from ui.constants import get_clip_row
            row = get_clip_row(sequence, self.clip)
            if row:
                y_pos    = row['y']
                track_h  = row['height']
            else:
                y_pos   = 0
                track_h = TRACK_HEIGHT
        else:
            # fallback to fixed layout
            if self.clip.has_video:
                row_idx = video_row(self.clip.track)
            else:
                row_idx = audio_row(self.clip.track)
            y_pos   = row_to_y(row_idx)
            track_h = TRACK_HEIGHT

        self.setRect(QRectF(
            x1,
            y_pos + CLIP_PADDING,
            w,
            track_h - CLIP_PADDING * 2
        ))


    def update_geometry_flat(self):
        """
        Geometry for new TrackCanvas architecture.
        y always starts at 0 — each canvas = one track.
        """
        total = self.app_state.total_frames
        if total <= 0:
            return

        # use actual widget width if view_width not set
        w_px = self.view_width
        if w_px <= 0 and self.scene():
            views = self.scene().views()
            if views:
                w_px = float(views[0].width())
        if w_px <= 0:
            return

        x1 = self.app_state.frame_to_pixel(
            self.clip.start_frame, w_px
        )
        x2 = self.app_state.frame_to_pixel(
            self.clip.start_frame + self.clip.duration,
            w_px
        )
        cw = max(x2 - x1, 4.0)

        # height from scene (= track height)
        if self.scene():
            track_h = self.scene().sceneRect().height()
        else:
            track_h = TRACK_HEIGHT
        track_h = max(track_h, 20)

        self.setRect(QRectF(
            x1, CLIP_PADDING,
            cw, track_h - CLIP_PADDING * 2
        ))

    # =========================================================
    # Paint
    # =========================================================

    def paint(self, painter: QPainter,
              option, widget=None):
        rect   = self.rect()
        fill   = QColor(self._colors[0])
        border = QColor(self._colors[1])

        if self._is_selected:
            fill   = fill.lighter(130)
            border = QColor('#ffffff')  # white border
        elif self._is_hovered:
            fill = fill.lighter(110)

        # main body
        painter.setBrush(QBrush(fill))
        border_w = 2 if self._is_selected else 1
        painter.setPen(QPen(border, border_w))
        painter.drawRoundedRect(rect, 2, 2)

        # left accent bar
        painter.setBrush(QBrush(border))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(QRectF(
            rect.x(), rect.y() + 1,
            3, rect.height() - 2
        ))

        # clip name
        if rect.width() > 30:
            painter.setPen(
                QPen(QColor('#e0e0e0'), 1)
            )
            font = QFont('Segoe UI', 9)
            painter.setFont(font)
            painter.drawText(
                rect.adjusted(8, 2, -4, -2),
                Qt.AlignmentFlag.AlignLeft |
                Qt.AlignmentFlag.AlignVCenter,
                self.clip.name
            )

        # fx badge
        if rect.width() > 60:
            painter.setPen(
                QPen(QColor('#aaaaaa'), 1)
            )
            font = QFont('Segoe UI', 7)
            painter.setFont(font)
            painter.drawText(
                rect.adjusted(
                    rect.width() - 22, 2, -4, -2
                ),
                Qt.AlignmentFlag.AlignRight |
                Qt.AlignmentFlag.AlignVCenter,
                'fx'
            )

        # link indicator — small chain icon
        if self.clip.link_group_id and rect.width() > 40:
            painter.setPen(
                QPen(QColor('#88ccff'), 1)
            )
            font2 = QFont('Segoe UI', 7)
            painter.setFont(font2)
            painter.drawText(
                rect.adjusted(8, rect.height()-14, -4, -2),
                Qt.AlignmentFlag.AlignLeft |
                Qt.AlignmentFlag.AlignBottom,
                '⛓'
            )

        # disabled overlay
        if not self.clip.enabled:
            painter.setBrush(
                QBrush(QColor(0, 0, 0, 120))
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect, 2, 2)
            painter.setPen(
                QPen(QColor('#888888'), 1)
            )
            painter.drawLine(
                rect.topLeft(), rect.bottomRight()
            )

        # opacity envelope line — video clips only
        if self.clip.has_video:
            self._draw_opacity_envelope(painter, rect)
            self._draw_keyframe_markers(painter, rect)

    # =========================================================
    # Effect keyframes
    # =========================================================

    KF_HALF_H = 4.5        # taller than wide, easier to see
    KF_HALF_W = 3.25
    KF_GRAB   = 6.0        # px either side counts as a hit

    def _keyframe_marker_x(self, rect, frame: int) -> float:
        """Screen x of a marker, nudged clear of the clip's edges."""
        duration = max(1, self.clip.duration)
        x = rect.left() + frame * (rect.width() / duration)
        return min(max(x, rect.left() + self.KF_HALF_W + 2),
                   rect.right() - self.KF_HALF_W - 1)

    def _keyframe_marker_y(self, rect) -> float:
        return rect.bottom() - self.KF_HALF_H - 1.5

    def _keyframe_at_pos(self, pos):
        """Local frame of the marker under the cursor, or None."""
        if not self.clip.has_video:
            return None
        rect = self.rect()
        if rect.width() < 20:
            return None
        y = self._keyframe_marker_y(rect)
        if abs(pos.y() - y) > self.KF_HALF_H + 3:
            return None
        best, best_dx = None, self.KF_GRAB
        for f in self.clip.keyframe_frames('motion'):
            dx = abs(pos.x() - self._keyframe_marker_x(rect, f))
            if dx <= best_dx:
                best, best_dx = f, dx
        return best

    def _frame_at_x(self, x: float) -> int:
        """Clip-local frame under a screen x, clamped to the clip."""
        rect = self.rect()
        duration = max(1, self.clip.duration)
        if rect.width() <= 0:
            return 0
        frame = round((x - rect.left()) / rect.width() * duration)
        return int(max(0, min(duration, frame)))

    def _draw_keyframe_markers(self, painter, rect):
        """
        Small diamonds along the bottom of the clip, one per frame
        that carries a Motion keyframe. Drag one to retime every
        parameter keyframed at that frame; values are edited in
        Effect Controls.
        """
        duration = max(1, self.clip.duration)
        if rect.width() < 20:
            return

        frames = [f for f in self.clip.keyframe_frames('motion')
                  if 0 <= f <= duration]
        if not frames:
            return

        half_h = self.KF_HALF_H
        half_w = self.KF_HALF_W
        y = self._keyframe_marker_y(rect)

        painter.setPen(QPen(QColor('#e0e0e0'), 0.8))   # light edge to lift
        for f in frames:                  # off black clip colours
            # the one being dragged reads back from Effect Controls blue
            painter.setBrush(QColor(
                '#4a9de0' if f == self._kf_drag_frame else '#000000'))
            x = self._keyframe_marker_x(rect, f)
            painter.drawPolygon(QPolygonF([
                QPointF(x, y - half_h),
                QPointF(x + half_w, y),
                QPointF(x, y + half_h),
                QPointF(x - half_w, y),
            ]))

    # =========================================================
    # Opacity envelope
    # =========================================================

    def _draw_opacity_envelope(self, painter, rect):
        env = self.clip.envelopes.get('opacity')
        if env is None:
            return
        val = max(0.0, min(1.0, env.default_value))
        h   = rect.height()
        y   = rect.top() + h * (0.75 - val * 0.50)
        painter.setPen(QPen(QColor('#dddddd'), 1.5))
        painter.drawLine(
            int(rect.left()),  int(y),
            int(rect.right()), int(y)
        )
        
        # Only show dot if value is not default (1.0) or has keyframes
        show_dot = False
        if hasattr(env, 'keyframes') and len(env.keyframes) > 0:
            show_dot = True
        elif abs(val - 1.0) > 0.01:  # Not at 100% opacity
            show_dot = True
            
        if show_dot:
            cx = rect.left() + rect.width() / 2
            painter.setBrush(QColor('#dddddd'))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(cx, y), 4, 4)

    def _envelope_y(self, rect) -> float:
        env = self.clip.envelopes.get('opacity')
        val = env.default_value if env else 1.0
        val = max(0.0, min(1.0, val))
        return rect.top() + rect.height() * (0.75 - val * 0.50)

    def _trim_edge_at(self, pos: QPointF):
        """Return 'left', 'right', or None."""
        rect = self.boundingRect()
        if pos.x() <= rect.left() + self.TRIM_ZONE:
            return 'left'
        if pos.x() >= rect.right() - self.TRIM_ZONE:
            return 'right'
        return None

    def _near_envelope(self, pos: QPointF) -> bool:
        if not self.clip.has_video:
            return False
        rect  = self.boundingRect()
        env_y = self._envelope_y(rect)
        return abs(pos.y() - env_y) <= 6

    # =========================================================
    # Drag — snapped to frames and track rows
    # =========================================================


    def mouseDoubleClickEvent(self, event):
        """Double-click loads clip in source monitor."""
        main = self._get_main_window()
        if main and hasattr(main, 'source_monitor'):
            main.source_monitor.load_clip(self.clip)
        event.accept()

    def contextMenuEvent(self, event):
        """Right-click context menu."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #2a2a2a;
                color: #cccccc;
                border: 1px solid #444444;
            }
            QMenu::item:selected {
                background-color: #3a6a9a;
            }
            QMenu::separator {
                background-color: #444444;
                height: 1px;
            }
            QMenu::item:disabled {
                color: #555555;
            }
        """)

        is_enabled  = self.clip.enabled
        sel_ids     = list(
            self.app_state.selected_clip_ids
        )
        multi_sel   = len(sel_ids) > 1

        # check if ALL selected clips share a link group
        panel = self._get_panel()
        all_items = {}
        if panel:
            for row in panel._rows.values():
                all_items.update(
                    row.canvas._clip_items
                )
        sel_clips = [
            all_items[i].clip
            for i in sel_ids
            if i in all_items
        ]
        # all selected clips in same link group?
        groups = set(
            c.link_group_id for c in sel_clips
            if c.link_group_id
        )
        all_same_group = (
            len(groups) == 1 and
            all(c.link_group_id for c in sel_clips)
        )

        # show Unlink if right-clicked clip is linked
        # show Link if multiple selected and not all same group
        # never show both
        if self.clip.link_group_id:
            show_unlink = True
            show_link   = False
        elif multi_sel and not all_same_group:
            show_unlink = False
            show_link   = True
        else:
            show_unlink = False
            show_link   = False

        # Delete
        act_delete = menu.addAction('Delete')

        menu.addSeparator()

        act_link   = None
        act_unlink = None
        if show_link:
            act_link = menu.addAction('Link')
        elif show_unlink:
            act_unlink = menu.addAction('Unlink')
        else:
            a = menu.addAction(
                'Link (select multiple clips)'
            )
            a.setEnabled(False)

        menu.addSeparator()

        # Scale to Frame Size — video clips only
        act_scale = None
        if self.clip.has_video:
            act_scale = menu.addAction(
                'Scale to Frame Size'
            )

        menu.addSeparator()

        # Synchronize — only when 2+ audio clips selected
        act_sync = None
        audio_selected = sum(
            1 for c in sel_clips if c.has_audio
        )
        if audio_selected >= 2:
            menu.addSeparator()
            act_sync = menu.addAction('Sync Refine (eyeball first, ±90s)')
        elif multi_sel:
            menu.addSeparator()
            a = menu.addAction('Sync Refine (eyeball first, ±90s)')
            a.setEnabled(False)

        # Enable / Disable
        toggle_label = (
            'Disable' if is_enabled else 'Enable'
        )
        act_toggle = menu.addAction(toggle_label)

        # show menu
        from PySide6.QtCore import QPoint
        sp = event.screenPos()
        action = menu.exec(
            QPoint(int(sp.x()), int(sp.y()))
        )

        if action is None:
            return

        main = self._get_main_window()
        if not main:
            return

        if action == act_delete:
            main._on_delete_clip()

        elif act_link and action == act_link:
            # link all selected clips together
            ids = list(
                self.app_state.selected_clip_ids
            )
            main.project.link_clips(ids)
            self._refresh_linked_visuals()
            main.status_label.setText(
                f'Linked {len(ids)} clips'
            )

        elif act_unlink and action == act_unlink:
            # unlink entire group
            main.project.unlink_group(
                self.clip.id
            )
            self._refresh_linked_visuals()
            main.status_label.setText('Unlinked')

        elif act_scale and action == act_scale:
            seq = main.project.active_sequence
            if seq:
                self.clip.scale_to_frame(
                    seq.settings.width,
                    seq.settings.height
                )
                main.status_label.setText(
                    'Scaled to frame size'
                )
                main._playback._compositor\
                    .invalidate_cache()
                main._scrub_to_playhead()

        elif act_sync and action == act_sync:
            main._on_synchronize()

        elif action == act_toggle:
            self.clip.enabled = not self.clip.enabled
            self.update()
            # dim disabled clips
            main._update_playback_clips()
            main.status_label.setText(
                f'Clip '
                f'{"enabled" if self.clip.enabled else "disabled"}'
            )

    def _track_is_locked(self) -> bool:
        """Check if the track this clip is on is locked."""
        try:
            canvas = self._get_my_canvas()
            if canvas:
                return canvas.track.locked
        except Exception:
            pass
        return False

    def _get_my_canvas(self):
        """Return the TrackCanvas this item lives in."""
        try:
            from ui.widgets.track_header import TrackCanvas
            views = self.scene().views()
            if views and isinstance(views[0], TrackCanvas):
                return views[0]
        except Exception:
            pass
        return None

    def _track_is_locked(self) -> bool:
        """Check if the track this clip is on is locked."""
        try:
            canvas = self._get_my_canvas()
            if canvas:
                return canvas.track.locked
        except Exception:
            pass
        return False

    def _get_panel(self):
        """Walk up to TimelinePanel."""
        try:
            views = self.scene().views()
            if not views:
                return None
            w = views[0]
            while w:
                from ui.panels.timeline import TimelinePanel
                if isinstance(w, TimelinePanel):
                    return w
                w = w.parent() if hasattr(w, 'parent') else None
        except Exception:
            pass
        return None

    def _get_main_window(self):
        """Walk up to MainWindow."""
        try:
            w = self.scene().views()[0]
            while w:
                # MainWindow has project attribute
                if hasattr(w, 'project') and hasattr(
                    w, '_on_delete_clip'
                ):
                    return w
                w = w.parent() if hasattr(
                    w, 'parent'
                ) else None
        except Exception:
            pass
        return None

    def _refresh_linked_visuals(self):
        """Repaint all clips in the link group."""
        panel = self._get_panel()
        if not panel:
            return
        for row in panel._rows.values():
            for item in row.canvas._clip_items.values():
                item.update()

    def mousePressEvent(self, event):
        # block all interaction on locked tracks
        if self._track_is_locked():
            event.ignore()
            return

        # check trim edge first
        tool = getattr(
            self.app_state, 'active_tool', 'select'
        )
        if (tool == 'select' and
                event.button() ==
                Qt.MouseButton.LeftButton):
            edge = self._trim_edge_at(event.pos())
            if edge:
                self._trim_edge      = edge
                self._trim_start_x   = (
                    event.scenePos().x()
                )
                self._trim_orig_in   = self.clip.in_point
                self._trim_orig_out  = self.clip.out_point
                self._trim_orig_start = (
                    self.clip.start_frame
                )
                # grab mouse so we get all move events
                self.grabMouse()
                event.accept()
                return

        if (tool == 'select' and
                event.button() == Qt.MouseButton.LeftButton):
            kf = self._keyframe_at_pos(event.pos())
            if kf is not None:
                self._kf_drag_frame  = kf
                self._kf_drag_orig   = kf
                self._kf_overwritten = {}
                self.grabMouse()
                self.update()
                event.accept()
                return

        if (event.button() == Qt.MouseButton.LeftButton
                and self._near_envelope(event.pos())):
            self._env_dragging     = True
            self._env_drag_start_y = event.pos().y()
            env = self.clip.envelopes.get('opacity')
            self._env_start_val = (
                env.default_value if env else 1.0
            )
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            mods = event.modifiers()
            add = bool(mods & (
                Qt.KeyboardModifier.ControlModifier |
                Qt.KeyboardModifier.ShiftModifier
            ))
            # If clip is already selected and no modifier,
            # keep the existing selection for multi-clip drag
            # BUT still update primary_clip_id so effects panel
            # reflects the clicked clip
            already_selected = self.app_state.is_selected(
                self.clip.id)
            if already_selected and not add:
                # Update primary so effects panel shows this clip
                self.app_state._primary_clip_id = self.clip.id
                self.app_state.selection_changed.emit(
                    self.app_state.selected_clip_ids)
                self.set_selected(True)
            else:
                # Collect this clip + all linked clip IDs
                ids_to_select = [self.clip.id]
                if self.clip.link_group_id:
                    try:
                        w = self.scene().views()[0].parent()
                        while w:
                            from ui.panels.timeline import TimelinePanel
                            if isinstance(w, TimelinePanel):
                                for row in w._rows.values():
                                    for cid, item in row.canvas._clip_items.items():
                                        if (item.clip.link_group_id ==
                                                self.clip.link_group_id
                                                and cid != self.clip.id):
                                            ids_to_select.append(cid)
                                break
                            w = w.parent() if hasattr(w, 'parent') else None
                    except Exception:
                        pass
                # Select all at once with single emission
                self.app_state.select_clips(ids_to_select,
                                             add_to_selection=add)
                self.set_selected(True)

            self._drag_start      = event.scenePos()
            self._drag_orig_frame = self.clip.start_frame
            self._drag_orig_track = self.clip.track

            if self.clip.has_video:
                self._drag_orig_row = video_row(
                    self.clip.track
                )
            else:
                self._drag_orig_row = audio_row(
                    self.clip.track
                )

            # store orig on linked items (same canvas)
            for item in self._get_linked_items():
                item._drag_orig_frame = (
                    item.clip.start_frame
                )
                item._drag_orig_track = item.clip.track
            # store orig on linked items (other canvases)
            self._store_linked_orig_frames()
            # store orig on ALL other selected clips
            panel = self._get_panel()
            if panel:
                selected = set(self.app_state.selected_clip_ids)
                for row in panel._rows.values():
                    for cid, item in row.canvas._clip_items.items():
                        if cid in selected:
                            item._drag_orig_frame = (
                                item.clip.start_frame)
                            item._drag_orig_track = (
                                item.clip.track)

        event.accept()



    def mouseMoveEvent(self, event):
        # keyframe marker drag
        if self._kf_drag_frame is not None:
            target = self._frame_at_x(event.pos().x())
            if target != self._kf_drag_frame:
                hit = self.clip.move_keyframes(
                    self._kf_drag_frame, target, 'motion')
                # keep the first set we displaced; later moves in the
                # same drag would otherwise overwrite the record
                for param, value in hit.items():
                    self._kf_overwritten.setdefault(param, value)
                self._kf_drag_frame = target
                self.update()
            event.accept()
            return

        # trim handle drag
        if self._trim_edge is not None:
            delta_px = (
                event.scenePos().x() -
                self._trim_start_x
            )
            delta_f = self._px_to_frame_delta(
                delta_px
            )
            if self._trim_edge == 'left':
                # left trim: move in_point and start_frame
                new_in = max(
                    0,
                    self._trim_orig_in + delta_f
                )
                # can't trim past out point
                if self.clip.out_point != -1:
                    new_in = min(
                        new_in,
                        self.clip.out_point - 1
                    )
                frame_delta = (
                    new_in - self._trim_orig_in
                )
                self.clip.in_point   = new_in
                self.clip.start_frame = (
                    self._trim_orig_start + frame_delta
                )
            else:
                # right trim: move out_point
                # Images have no real source limit — allow any length
                import os
                ext = os.path.splitext(
                    self.clip.filepath)[1].lower()
                is_image = ext in ('.jpg', '.jpeg', '.png',
                                    '.bmp', '.tiff', '.tif')
                max_out = (self.app_state.total_frames
                           if is_image
                           else self.clip.source_frames)
                if self._trim_orig_out == -1:
                    orig_out = self.clip.source_frames
                else:
                    orig_out = self._trim_orig_out
                new_out = max(
                    self.clip.in_point + 1,
                    min(
                        max_out,
                        orig_out + delta_f
                    )
                )
                self.clip.out_point = new_out
            self.update_geometry_flat()
            self.update()
            if self.scene():
                self.scene().update()
            event.accept()
            return

        if self._env_dragging:
            rect    = self.boundingRect()
            h       = rect.height()
            delta_y = event.pos().y() - self._env_drag_start_y
            # 50% of track height = 0→1 range
            delta_val = -(delta_y / (h * 0.50))
            new_val   = max(0.0, min(1.0,
                self._env_start_val + delta_val
            ))
            env = self.clip.envelopes.get('opacity')
            if env:
                old_val = self._env_start_val
                env.default_value = new_val
                # Push to undo stack (merges rapid drags into one step)
                from core.undo import undo_stack, SetOpacityCommand
                undo_stack.push(SetOpacityCommand(
                    self.clip, old_val, new_val
                ))
            self.update()
            # Notify effects panel so Opacity spinbox stays in sync
            self.app_state.clip_modified.emit(self.clip.id)
            event.accept()
            return

        if (self._drag_start is None or
                event.buttons() !=
                Qt.MouseButton.LeftButton):
            return

        delta = event.scenePos() - self._drag_start

        # horizontal only — in new arch clips stay
        # on their track (cross-track drag = future)
        # Use actual scene width for accuracy
        w_px = self.view_width
        if w_px <= 0 and self.scene() and self.scene().views():
            w_px = float(self.scene().views()[0].width())

        orig_px = self.app_state.frame_to_pixel(
            self._drag_orig_frame, w_px
        )
        new_px    = orig_px + delta.x()
        new_frame = self.app_state.pixel_to_frame(
            new_px, w_px
        )

        new_frame = max(0, new_frame)
        # snap to adjacent clip edges (hold Shift to disable)
        mods = event.modifiers()
        if not (mods & Qt.KeyboardModifier.ShiftModifier):
            new_frame = self._snap_frame(
                new_frame, self.clip.id, w_px
            )
        frame_delta = new_frame - self._drag_orig_frame

        # ── cross-track detection ──────────────────────
        panel = self._get_panel()
        target_row = None
        if panel:
            gpos = event.screenPos()
            target_row = panel.row_at_global_pos(
                gpos
            )

        # determine new track
        new_track = self.clip.track
        if (target_row and
                target_row.track.track_type ==
                self.track_type() and
                target_row.track.index != new_track):
            new_track = target_row.track.index

        if self._would_overlap(new_frame, new_track):
            return

        # ── cross-track move ───────────────────────────
        if (panel and target_row and
                new_track != self.clip.track):
            cur_canvas = self._get_my_canvas()
            if cur_canvas:
                panel.move_clip_to_track(
                    self.clip, cur_canvas, target_row
                )
                # also move linked clips to
                # corresponding tracks
                self._move_linked_to_offset(
                    panel,
                    new_track - self._drag_orig_track
                )

        # ── horizontal move ────────────────────────────
        # Clamp frame_delta so NO clip goes before frame 0
        panel = self._get_panel()
        if frame_delta < 0 and panel:
            selected = set(self.app_state.selected_clip_ids)
            for row in panel._rows.values():
                for cid, item in row.canvas._clip_items.items():
                    if cid in selected:
                        min_allowed = -item._drag_orig_frame
                        frame_delta = max(frame_delta, min_allowed)
            # Also clamp primary clip
            frame_delta = max(frame_delta, -self._drag_orig_frame)
            new_frame = max(0, self._drag_orig_frame + frame_delta)

        self.clip.start_frame = new_frame
        self.update_geometry_flat()

        self._sync_linked_in_other_canvases(frame_delta)

        # Also move all other selected clips by same frame_delta
        if frame_delta != 0:
            if panel:
                selected = set(self.app_state.selected_clip_ids)
                moved = {self.clip.id}
                for row in panel._rows.values():
                    for cid, item in row.canvas._clip_items.items():
                        if cid in selected and cid not in moved:
                            orig = item._drag_orig_frame
                            item.clip.start_frame = max(
                                0, orig + frame_delta)
                            item.update_geometry_flat()
                            item.update()
                            moved.add(cid)

        self.update()
        event.accept()

    def _px_to_frame_delta(self, dx: float) -> int:
        """Convert scene pixel delta to frame delta."""
        w = self.view_width
        if w <= 0:
            views = self.scene().views()
            w = float(views[0].width()) if views else 1000.0
        total   = self.app_state.total_frames or 1
        visible = self.app_state.visible_range
        frames_per_px = (total * visible) / w
        return int(dx * frames_per_px)

    def _snap_frame(self, frame: int,
                    exclude_id: str,
                    w_px: float = 0.0) -> int:
        """
        Snap frame to nearest clip edge if within
        SNAP_THRESHOLD_PX pixels.
        Checks all clips in all canvases.
        """
        w = w_px if w_px > 0 else self.view_width
        if w <= 0 and self.scene() and self.scene().views():
            w = float(self.scene().views()[0].width())
        if w <= 0:
            return frame

        # collect candidate snap points
        snap_frames = [0]  # always snap to start

        # get all clips from all canvases via panel
        try:
            view = self.scene().views()[0]
            p = view.parent()
            while p:
                from ui.panels.timeline import TimelinePanel
                if isinstance(p, TimelinePanel):
                    for row in p._rows.values():
                        for cid, item in (
                            row.canvas._clip_items.items()
                        ):
                            if cid == exclude_id:
                                continue
                            c = item.clip
                            snap_frames.append(
                                c.start_frame
                            )
                            snap_frames.append(
                                c.start_frame + c.duration
                            )
                    break
                p = p.parent() if hasattr(p, 'parent') else None
        except Exception:
            pass

        # find nearest snap point
        # Use visible frames (not total) so threshold stays
        # proportional to what's actually shown on screen
        visible_frames = (self.app_state.total_frames *
                          self.app_state.visible_range)
        threshold = max(
            1,
            int(SNAP_THRESHOLD_PX * visible_frames / w)
        )

        best      = frame
        best_dist = threshold + 1

        for sf in snap_frames:
            dist = abs(frame - sf)
            if dist < best_dist:
                best_dist = dist
                best      = sf

        return best

    def track_type(self):
        """Return TrackType for this clip."""
        from core.track import TrackType
        if self.clip.has_video:
            return TrackType.VIDEO
        return TrackType.AUDIO

    def _move_linked_to_offset(
            self, panel, track_delta: int):
        """
        Move linked clips by track_delta.
        Video clips move by delta, audio clips
        move by same delta on audio tracks.
        """
        if not self.clip.link_group_id:
            return
        from core.track import TrackType
        for row in panel._rows.values():
            for cid, item in list(
                row.canvas._clip_items.items()
            ):
                if (item is self or
                        item.clip.link_group_id !=
                        self.clip.link_group_id):
                    continue
                new_idx = (
                    item._drag_orig_track + track_delta
                )
                new_idx = max(0, new_idx)
                # find target row for linked clip
                tt = (TrackType.VIDEO
                      if item.clip.has_video
                      else TrackType.AUDIO)
                target = None
                for r in panel._rows.values():
                    if (r.track.track_type == tt and
                            r.track.index == new_idx):
                        target = r
                        break
                if target and target.track.index != (
                    item.clip.track
                ):
                    panel.move_clip_to_track(
                        item.clip, row.canvas, target
                    )

    def _store_linked_orig_frames(self):
        """Store _drag_orig_frame on all linked items."""
        if not self.clip.link_group_id:
            return
        w = self.scene().views()[0].parent()
        while w:
            try:
                from ui.panels.timeline import (
                    TimelinePanel
                )
                if isinstance(w, TimelinePanel):
                    for row in w._rows.values():
                        for cid, item in (
                            row.canvas._clip_items.items()
                        ):
                            if (item.clip.link_group_id
                                    == self.clip.link_group_id
                                    and item is not self):
                                item._drag_orig_frame = (
                                    item.clip.start_frame
                                )
                    break
            except Exception:
                pass
            w = w.parent() if hasattr(w, 'parent') else None

    def _sync_linked_in_other_canvases(
            self, frame_delta: int):
        """
        Find linked clips in other TrackCanvas scenes
        and update their start_frame.
        """
        if not self.clip.link_group_id:
            return

        # walk up to TimelinePanel
        panel = None
        w = self.scene().views()[0].parent()
        while w:
            try:
                from ui.panels.timeline import (
                    TimelinePanel
                )
                if isinstance(w, TimelinePanel):
                    panel = w
                    break
            except Exception:
                pass
            w = w.parent() if hasattr(w, 'parent') else None

        if panel is None:
            return

        for row in panel._rows.values():
            for cid, item in (
                row.canvas._clip_items.items()
            ):
                if item is self:
                    continue
                if (item.clip.link_group_id ==
                        self.clip.link_group_id):
                    item.clip.start_frame = (
                        item._drag_orig_frame
                        + frame_delta
                    )
                    item.update_geometry_flat()

    def _get_linked_items(self) -> list:
        """
        Find all other ClipItems in the same 
        link group from the scene.
        """
        if not self.clip.link_group_id:
            return []
        result = []
        for item in self.scene().items():
            if not isinstance(item, ClipItem):
                continue
            if item.clip.id == self.clip.id:
                continue
            if (item.clip.link_group_id ==
                    self.clip.link_group_id):
                result.append(item)
        return result



    def mouseReleaseEvent(self, event):
        # keyframe marker drag
        if self._kf_drag_frame is not None:
            self.ungrabMouse()
            start, end = self._kf_drag_orig, self._kf_drag_frame
            overwritten = self._kf_overwritten
            self._kf_drag_frame  = None
            self._kf_drag_orig   = None
            self._kf_overwritten = {}
            if end != start:
                from core.undo import undo_stack, MoveKeyframesCommand
                cmd = MoveKeyframesCommand(
                    self.clip, 'motion', start, end, overwritten)
                # the move already happened during the drag
                undo_stack.push(cmd, execute=False)
                self.app_state.clip_modified.emit(self.clip.id)
            self.update()
            event.accept()
            return

        self._env_dragging = False
        if self._trim_edge is not None:
            self.ungrabMouse()
        self._trim_edge = None

        # Push undo for drag if position changed
        moved_clips = []
        panel = self._get_panel()
        if self._drag_start is not None:
            from core.undo import undo_stack, MoveClipCommand, CompoundCommand
            selected = set(self.app_state.selected_clip_ids)

            # Collect all clips that moved
            if panel:
                for row in panel._rows.values():
                    for cid, item in row.canvas._clip_items.items():
                        if cid in selected:
                            old_f = getattr(item, '_drag_orig_frame',
                                            item.clip.start_frame)
                            old_t = getattr(item, '_drag_orig_track',
                                            item.clip.track)
                            if item.clip.start_frame != old_f or                                     item.clip.track != old_t:
                                moved_clips.append(
                                    (item.clip, old_f,
                                     item.clip.start_frame,
                                     old_t, item.clip.track))

            if moved_clips:
                if len(moved_clips) == 1:
                    clip, old_f, new_f, old_t, new_t = moved_clips[0]
                    undo_stack.push(
                        MoveClipCommand(clip, old_f, new_f, old_t, new_t))
                else:
                    cmd = CompoundCommand('Move Clips')
                    for clip, old_f, new_f, old_t, new_t in moved_clips:
                        cmd.add(MoveClipCommand(
                            clip, old_f, new_f, old_t, new_t))
                    undo_stack.push(cmd)

        self._drag_start = None
        # Recalculate total_frames after move
        if moved_clips and panel:
            project = None
            w = panel.window()
            if hasattr(w, 'project') and hasattr(w, 'app_state'):
                if w.project.clips:
                    w.app_state.total_frames = max(
                        c.start_frame + c.duration
                        for c in w.project.clips.values()
                    )
        event.accept()

    def _would_overlap(self, new_frame: int,
                        new_track: int) -> bool:
        """
        Returns True if placing this clip at
        new_frame on new_track overlaps any
        other clip on that track.
        """
        duration = self.clip.duration
        new_end  = new_frame + duration

        for item in self.scene().items():
            if not isinstance(item, ClipItem):
                continue
            if item.clip.id == self.clip.id:
                continue
            if item.clip.track != new_track:
                continue
            # only compare same stream type
            if item.clip.has_video != self.clip.has_video:
                continue
            other_start = item.clip.start_frame
            other_end   = (other_start +
                           item.clip.duration)
            # overlap if ranges intersect
            if not (new_end <= other_start or
                    new_frame >= other_end):
                return True
        return False

    # =========================================================
    # Selection / Hover
    # =========================================================

    def set_selected(self, selected: bool):
        self._is_selected = selected
        self.update()
        # highlight all linked clips too
        self._set_linked_selected(selected)

    def _set_linked_selected(self, selected: bool):
        """Apply selection state to all linked clips."""
        if not self.clip.link_group_id:
            return
        # same canvas
        for item in self._get_linked_items():
            item._is_selected = selected
            item.update()
        # other canvases
        try:
            w = self.scene().views()[0].parent()
            while w:
                from ui.panels.timeline import TimelinePanel
                if isinstance(w, TimelinePanel):
                    for row in w._rows.values():
                        for cid, item in (
                            row.canvas._clip_items.items()
                        ):
                            if (item is not self and
                                    item.clip.link_group_id
                                    == self.clip.link_group_id):
                                item._is_selected = selected
                                item.update()
                    break
                w = w.parent() if hasattr(w, 'parent') else None
        except Exception:
            pass

    def hoverMoveEvent(self, event):
        tool = getattr(
            self.app_state, 'active_tool', 'select'
        )
        if tool != 'select':
            return
        edge = self._trim_edge_at(event.pos())
        if edge:
            self.setCursor(
                Qt.CursorShape.SizeHorCursor
            )
        elif self._keyframe_at_pos(event.pos()) is not None:
            self.setCursor(
                Qt.CursorShape.SizeHorCursor
            )
        elif self._near_envelope(event.pos()):
            self.setCursor(
                Qt.CursorShape.SizeVerCursor
            )
        else:
            self.setCursor(
                Qt.CursorShape.ArrowCursor
            )

    def hoverEnterEvent(self, event):
        self._is_hovered = True
        tool = getattr(
            self.app_state, 'active_tool', 'select'
        )
        if tool == 'razor':
            # can cut — no red slash
            from ui.widgets.track_header import TrackCanvas
            self.setCursor(
                TrackCanvas._make_razor_cursor(
                    outside=False
                )
            )
        self.update()

    def hoverLeaveEvent(self, event):
        self._is_hovered = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()