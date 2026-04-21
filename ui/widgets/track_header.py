"""
Track header widgets — new unified architecture.

TrackRow: one widget per track, full panel width.
  ├── TrackHeader (left, fixed width) — controls
  └── TrackCanvas (right, expanding) — clips/waveforms

Resize handle: full bottom edge of TrackRow.
Alignment guaranteed — header and canvas share same Y.
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QLabel,
    QGraphicsView, QGraphicsScene, QGraphicsItem,
    QSizePolicy
)
from PySide6.QtCore import (
    Qt, Signal, QRectF, QPointF
)
from PySide6.QtGui import (
    QColor, QPen, QBrush, QPainter, QFont
)
from PySide6.QtWidgets import QGraphicsRectItem

from core.clip import Clip
from core.track import Track, TrackType
from ui.app_state import AppState
from ui.constants import TRACK_HEADER_WIDTH, CLIP_PADDING

MIN_TRACK_HEIGHT = 28
MAX_TRACK_HEIGHT = 300
RESIZE_ZONE      = 6     # px from bottom edge


# ─────────────────────────────────────────────────────────────
# TrackHeader — left side controls
# ─────────────────────────────────────────────────────────────

class TrackHeader(QWidget):
    """
    Left-side controls for one track.
    Fixed width, same height as its TrackRow.
    """

    mute_toggled    = Signal(str, bool)
    solo_toggled    = Signal(str, bool)
    lock_toggled    = Signal(str, bool)
    visible_toggled = Signal(str, bool)

    VIDEO_ACCENT = '#2a6b8a'
    AUDIO_ACCENT = '#2a6b4a'
    INACTIVE_BG  = '#1a1a1a'

    def __init__(self, track: Track, parent=None):
        super().__init__(parent)
        self.track = track
        self.setFixedWidth(TRACK_HEADER_WIDTH)
        self._build_ui()

    def _build_ui(self):
        is_video = (self.track.track_type == TrackType.VIDEO)
        accent   = (self.VIDEO_ACCENT if is_video
                    else self.AUDIO_ACCENT)

        self.setStyleSheet(f"""
            QWidget {{
                background-color: {self.INACTIVE_BG};
                border-right: 2px solid {accent};
                padding: 0px; margin: 0px;
            }}
        """)

        row = QHBoxLayout(self)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(2)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # lock
        self.lock_btn = self._btn('🔒', 'Lock')
        self.lock_btn.setCheckable(True)
        self.lock_btn.clicked.connect(
            lambda c: self._on_lock(c)
        )
        row.addWidget(self.lock_btn)

        # name
        lbl = QLabel(self.track.name)
        lbl.setAlignment(
            Qt.AlignmentFlag.AlignCenter |
            Qt.AlignmentFlag.AlignVCenter
        )
        lbl.setStyleSheet(
            'color:#cccccc; font-size:10px; '
            'font-weight:bold; border:none; '
            'background:transparent;'
        )
        lbl.setFixedWidth(22)
        row.addWidget(lbl)

        if is_video:
            # VIDEO: eye only — no M/S/mic
            self.eye_btn = self._btn('', 'Toggle visibility')
            self.eye_btn.setCheckable(True)
            self.eye_btn.setChecked(True)
            # Load eye icon
            import os
            from PySide6.QtGui import QIcon
            from PySide6.QtCore import QSize
            eye_path = os.path.join(
                os.path.dirname(os.path.dirname(
                    os.path.dirname(__file__))),
                'icons', 'eye.ico'
            )
            if os.path.exists(eye_path):
                self.eye_btn.setIcon(QIcon(eye_path))
                self.eye_btn.setIconSize(QSize(20, 20))
            self.eye_btn.clicked.connect(
                lambda c: self._on_visible(c)
            )
            row.addWidget(self.eye_btn)
        else:
            # AUDIO: M, S, mic — no eye
            self.mute_btn = self._btn('M', 'Mute')
            self.mute_btn.setCheckable(True)
            self.mute_btn.clicked.connect(
                lambda c: self._on_mute(c)
            )
            row.addWidget(self.mute_btn)

            mic = self._btn('🎤', 'Record arm')
            mic.setEnabled(False)
            row.addWidget(mic)

        row.addStretch()

    def _btn(self, label, tip):
        b = QPushButton(label)
        b.setFixedSize(16, 16)
        b.setToolTip(tip)
        b.setStyleSheet("""
            QPushButton {
                background:#2a2a2a; color:#888;
                border:1px solid #383838;
                border-radius:2px; font-size:8px;
                padding:0px;
            }
            QPushButton:hover {
                background:#3a3a3a; color:#ccc;
            }
            QPushButton:checked {
                background:#4a9de0; color:#fff;
            }
            QPushButton:disabled {
                background:#1a1a1a; color:#444;
                border-color:#2a2a2a;
            }
        """)
        return b

    def _on_lock(self, c):
        self.track.locked = c
        self.lock_toggled.emit(self.track.id, c)

    def _on_solo(self, c):
        self.track.solo = c
        self.solo_toggled.emit(self.track.id, c)

    def _on_visible(self, c):
        self.track.visible = c
        self.visible_toggled.emit(self.track.id, c)
        # swap eye icon
        import os
        from PySide6.QtGui import QIcon
        icon_name = 'eye.ico' if c else 'eye_off.ico'
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.dirname(__file__))),
            'icons', icon_name
        )
        if os.path.exists(icon_path):
            self.eye_btn.setIcon(QIcon(icon_path))
        # dim canvas when hidden
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        row = self.parent()
        if hasattr(row, 'canvas'):
            if not c:
                eff = QGraphicsOpacityEffect()
                eff.setOpacity(0.3)
                row.canvas.setGraphicsEffect(eff)
            else:
                row.canvas.setGraphicsEffect(None)
        self._request_repaint()

    def _on_mute(self, c):
        self.track.muted = c
        self.mute_toggled.emit(self.track.id, c)
        self._request_repaint()

    def _request_repaint(self):
        """Invalidate cache and rescrub current frame."""
        w = self.window()
        # invalidate compositor cache first
        if (hasattr(w, '_playback') and
                w._playback and
                hasattr(w._playback, '_compositor') and
                w._playback._compositor):
            w._playback._compositor.invalidate_cache()
        if hasattr(w, '_scrub_to_playhead'):
            w._scrub_to_playhead()


# ─────────────────────────────────────────────────────────────
# TrackCanvas — right side clip area
# ─────────────────────────────────────────────────────────────

class TrackCanvas(QGraphicsView):
    """
    QGraphicsView for one track's clips.
    Horizontal position driven by app_state zoom.
    No scrollbars — pan/zoom controlled externally.
    """

    # emitted when media dropped onto this canvas
    clip_dropped = Signal(str, int)   # item_id, frame

    def __init__(self, track: Track,
                 app_state: AppState,
                 parent=None):
        super().__init__(parent)
        self.track     = track
        self.app_state = app_state

        self._clip_items:    dict = {}
        self._waveform_items: dict = {}
        self._waveform_workers: dict = {}
        self._playhead_line  = None
        self._razor_lines    = []
        self._razor_label    = None

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        is_video = (track.track_type == TrackType.VIDEO)
        if is_video:
            bg = QColor('#1a1a1a')
        else:
            bg = QColor('#141414')
        self.setBackgroundBrush(QBrush(bg))

        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setRenderHint(
            QPainter.RenderHint.Antialiasing, False
        )
        self.setAlignment(
            Qt.AlignmentFlag.AlignLeft |
            Qt.AlignmentFlag.AlignTop
        )
        self.setAcceptDrops(True)

        # playhead line
        self._init_scene()

        # connect signals
        self.app_state.zoom_changed.connect(
            self._on_zoom_changed
        )
        self.app_state.playhead_changed.connect(
            self._update_playhead
        )
        self.app_state.selection_changed.connect(
            self._on_selection_changed
        )
        self.app_state.tool_changed.connect(
            self._on_tool_changed
        )
        self._razor_active         = False
        self._razor_frame          = 0
        self._razor_cursor_outside = None
        self._razor_cursor_inside  = None
        self._razor_line_item      = None
        # override viewport cursor handling
        self.viewport().setMouseTracking(True)

    def _init_scene(self):
        w = max(4000, self.width())
        h = self.track.height
        self._scene.setSceneRect(QRectF(0, 0, w, h))

        # draw track background
        is_video = (
            self.track.track_type == TrackType.VIDEO
        )
        color = (QColor('#1e2a35') if is_video
                 else QColor('#1a2a1e'))
        bg = self._scene.addRect(
            0, 0, w, h,
            QPen(QColor('#2a2a2a'), 1),
            QBrush(color)
        )
        bg.setZValue(0)
        self._bg_rect = bg

        self._playhead_line = self._scene.addLine(
            0, 0, 0, h,
            QPen(QColor('#e8e820'), 1)
        )
        self._playhead_line.setZValue(100)

    def set_scene_width(self, w: int):
        h = self.track.height
        self._scene.setSceneRect(QRectF(0, 0, w, h))
        if hasattr(self, '_bg_rect') and self._bg_rect:
            self._bg_rect.setRect(QRectF(0, 0, w, h))
        if self._playhead_line:
            self._playhead_line.setLine(0, 0, 0, h)

    def update_height(self, h: int):
        """Called when track height changes."""
        w = self._scene.width()
        self._scene.setSceneRect(QRectF(0, 0, w, h))
        if hasattr(self, '_bg_rect') and self._bg_rect:
            self._bg_rect.setRect(QRectF(0, 0, w, h))
        if self._playhead_line:
            x = self._playhead_line.line().x1()
            self._playhead_line.setLine(x, 0, x, h)
        self._reposition_clips()

    def set_h_offset(self, pixel_offset: float):
        """
        Set horizontal scroll position.
        Called by TimelinePanel when zoom/pan changes.
        """
        self.horizontalScrollBar().setValue(
            int(pixel_offset)
        )

    # ── Clip management ──────────────────────────────────

    def add_clip(self, clip: Clip):
        from ui.widgets.clip_item import ClipItem
        w = float(self.width()) or 1000.0
        item = ClipItem(clip, self.app_state, w)
        self._scene.addItem(item)
        self._clip_items[clip.id] = item
        item.update_geometry_flat()

        if clip.has_audio and not clip.has_video:
            from ui.widgets.waveform_item import WaveformItem
            wf = WaveformItem(
                clip, self.app_state, parent=item
            )
            self._waveform_items[clip.id] = wf
            self._start_waveform_worker(clip)

    def remove_clip(self, clip_id: str):
        item = self._clip_items.pop(clip_id, None)
        if item:
            self._scene.removeItem(item)
        wf = self._waveform_items.pop(clip_id, None)

    def _reposition_clips(self):
        w = float(self.width())
        for item in self._clip_items.values():
            item.view_width = w
            item.update_geometry_flat()
        for wf in self._waveform_items.values():
            wf.prepareGeometryChange()
            wf.update()

    # ── Playhead ─────────────────────────────────────────

    def _update_playhead(self, frame=None):
        if self._playhead_line is None:
            return
        if frame is None:
            frame = self.app_state.playhead_frame
        px = self.app_state.frame_to_pixel(
            frame, float(self.width())
        )
        h  = self._scene.height()
        try:
            self._playhead_line.setLine(px, 0, px, h)
        except RuntimeError:
            # C++ object deleted after timeline refresh — recreate it
            from PySide6.QtGui import QPen, QColor
            from PySide6.QtCore import Qt
            self._playhead_line = self._scene.addLine(
                px, 0, px, h,
                QPen(QColor('#ff6b6b'), 2)
            )
            self._playhead_line.setZValue(100)

    # ── Zoom ─────────────────────────────────────────────

    def _on_zoom_changed(self, start, end):
        w = float(self.width())
        for item in self._clip_items.values():
            item.view_width = w
            item.update_geometry_flat()
        for wf in self._waveform_items.values():
            wf.prepareGeometryChange()
            wf.update()
        self._update_playhead()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._on_zoom_changed(
            self.app_state.view_start,
            self.app_state.view_end
        )

    # ── Selection ────────────────────────────────────────

    def _on_selection_changed(self, clip_ids):
        # Update visual state directly — don't use set_selected()
        # because that calls _set_linked_selected() which can
        # interfere with other canvases updating their own items.
        for cid, item in self._clip_items.items():
            item._is_selected = cid in clip_ids
            item.update()

    def wheelEvent(self, event):
        x = event.position().x()
        norm = self.app_state.pixel_to_norm(
            x, float(self.width())
        )
        if event.angleDelta().y() > 0:
            self.app_state.zoom_in_at_position(norm)
        else:
            self.app_state.zoom_out_at_position(norm)

    # ── Tool handling ────────────────────────────────────

    @staticmethod
    def _draw_razor_base(p, size):
        """Draw vertical line + blade onto painter."""
        from PySide6.QtGui import (
            QPen, QColor, QPolygon
        )
        from PySide6.QtCore import Qt as _Qt, QPoint

        # vertical dashed line at x=8
        pen = QPen(QColor('#ffffff'), 1)
        pen.setStyle(_Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(8, 0, 8, size)

        # razor blade
        blade = QPolygon([
            QPoint(9,  6),
            QPoint(22, 2),
            QPoint(24, 7),
            QPoint(22, 12),
            QPoint(9,  12),
        ])
        p.setPen(QPen(QColor('#dddddd'), 1))
        p.setBrush(QColor('#aaaaaa'))
        p.drawPolygon(blade)
        # edge highlight
        p.setPen(QPen(QColor('#ffffff'), 1))
        p.drawLine(9, 6, 22, 2)
        # score line
        p.setPen(QPen(QColor('#777777'), 1))
        p.drawLine(10, 9, 20, 9)

    @staticmethod
    def _make_razor_cursor(outside=False):
        """
        Build razor cursor from ICO file if available,
        otherwise fall back to hand-drawn cursor.
        outside=True = cut_off.ico (outside clip),
        outside=False = cutt.ico (over clip).
        """
        import os
        from PySide6.QtGui import QPixmap, QCursor
        from PySide6.QtCore import Qt as _Qt

        icon_name = 'cut_off.ico' if outside else 'cutt.ico'
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.dirname(__file__))),
            'icons', icon_name
        )
        if os.path.exists(icon_path):
            from PySide6.QtGui import QIcon
            icon = QIcon(icon_path)
            px = icon.pixmap(32, 32)
            # hotspot at x=2 to align with the dashed line on left
            return QCursor(px, 5, 0)

        # Fallback: hand-drawn cursor
        from PySide6.QtGui import QPainter, QPen, QColor
        size = 32
        px   = QPixmap(size, size)
        px.fill(_Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        TrackCanvas._draw_razor_base(p, size)
        if outside:
            pen = QPen(QColor('#ff3333'), 2)
            pen.setCapStyle(_Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(14, 16, 28, 30)
        p.end()
        return QCursor(px, 8, 0)

    def _on_tool_changed(self, tool: str):
        self._razor_active = (tool == 'razor')
        if self._razor_active:
            cur = self._make_razor_cursor(outside=True)
            self._razor_cursor_outside = cur
            self._razor_cursor_inside  = (
                self._make_razor_cursor(outside=False)
            )
            self.viewport().setCursor(cur)
            # disable clip items so razor gets all events
            self._set_clips_mouse_enabled(False)
        else:
            self._razor_cursor_outside = None
            self._razor_cursor_inside  = None
            self.viewport().unsetCursor()
            self._set_clips_mouse_enabled(True)
            self._clear_linked_razor_lines()
            self.clear_razor_line()
        self.setMouseTracking(True)

    def mouseMoveEvent(self, event):
        if self._razor_active:
            from ui.widgets.clip_item import ClipItem
            from ui.widgets.waveform_item import WaveformItem
            scene_x = self.mapToScene(
                event.pos()
            ).x()
            item = self.itemAt(event.pos())
            # WaveformItem is a child of ClipItem — use parent
            if isinstance(item, WaveformItem):
                item = item.parentItem()
            if isinstance(item, ClipItem):
                self.viewport().setCursor(
                    self._razor_cursor_inside
                )
                # draw line on this canvas AND linked canvases
                self.set_razor_line(scene_x)
                self._show_linked_razor_lines(
                    item.clip, scene_x
                )
            else:
                self.viewport().setCursor(
                    self._razor_cursor_outside
                )
                # clear lines on all canvases
                self.clear_razor_line()
                self._clear_linked_razor_lines()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._razor_active:
            self._clear_linked_razor_lines()
        super().leaveEvent(event)

    def _show_linked_razor_lines(self, clip, scene_x):
        """Draw vertical line on all linked canvases."""
        if not clip.link_group_id:
            return
        panel = self._get_panel()
        if not panel:
            return
        for row in panel._rows.values():
            canvas = row.canvas
            if canvas is self:
                continue
            # check if this canvas has a linked clip
            has_linked = any(
                i.clip.link_group_id == clip.link_group_id
                for i in canvas._clip_items.values()
            )
            if has_linked:
                canvas.set_razor_line(scene_x)
            else:
                canvas.clear_razor_line()

    def _clear_linked_razor_lines(self):
        """Remove razor lines from all other canvases."""
        panel = self._get_panel()
        if not panel:
            return
        for row in panel._rows.values():
            if row.canvas is not self:
                row.canvas.clear_razor_line()

    def set_razor_line(self, scene_x: float):
        """Show vertical razor line at scene_x."""
        if not hasattr(self, '_razor_line_item'):
            self._razor_line_item = None
        # remove old
        if self._razor_line_item:
            self._scene.removeItem(self._razor_line_item)
        # draw new dashed line
        pen = QPen(QColor('#ffffff'), 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        h = self._scene.height()
        self._razor_line_item = self._scene.addLine(
            scene_x, 0, scene_x, h, pen
        )
        self._razor_line_item.setZValue(200)

    def clear_razor_line(self):
        """Remove vertical razor line."""
        if (hasattr(self, '_razor_line_item') and
                self._razor_line_item):
            try:
                self._scene.removeItem(
                    self._razor_line_item
                )
            except Exception:
                pass
            self._razor_line_item = None

    def mousePressEvent(self, event):
        if (self._razor_active and
                event.button() ==
                Qt.MouseButton.LeftButton):
            scene_pos = self.mapToScene(event.pos())
            frame = self.app_state.pixel_to_frame(
                scene_pos.x(), float(self.width())
            )
            panel = self._get_panel()
            if panel:
                # Find the clip under the click on THIS canvas
                clicked_clip_id = None
                for cid, item in self._clip_items.items():
                    c = item.clip
                    if (c.start_frame <= frame <
                            c.start_frame + c.duration):
                        clicked_clip_id = cid
                        break
                # Shift = cut all tracks, otherwise
                # cut only clicked clip + its linked partners
                mods = event.modifiers()
                cut_all = bool(
                    mods & Qt.KeyboardModifier.ShiftModifier)
                panel.do_razor_cut(
                    frame,
                    clicked_clip_id=clicked_clip_id,
                    cut_all=cut_all
                )
            event.accept()
            return
        item = self.itemAt(event.pos())
        if item is None:
            mods = event.modifiers()
            if not (mods & (
                Qt.KeyboardModifier.ControlModifier |
                Qt.KeyboardModifier.ShiftModifier
            )):
                self.app_state.deselect_all()
        super().mousePressEvent(event)

    def _set_clips_mouse_enabled(self, enabled: bool):
        """
        In razor mode: make the view itself handle
        ALL events — items become transparent.
        """
        if enabled:
            # restore normal item interaction
            self.setInteractive(True)
            for item in self._clip_items.values():
                item.setAcceptHoverEvents(True)
                item.setAcceptedMouseButtons(
                    Qt.MouseButton.AllButtons
                )
                item.setFlag(
                    item.GraphicsItemFlag.ItemIsSelectable,
                    True
                )
        else:
            # razor: view handles everything
            # setInteractive(False) makes ALL items
            # completely ignore mouse events
            self.setInteractive(False)

    def _get_panel(self):
        """Walk up widget tree to find TimelinePanel."""
        w = self.parent()
        while w:
            from ui.panels.timeline import TimelinePanel
            if isinstance(w, TimelinePanel):
                return w
            w = w.parent()
        return None

    # ── Drop ─────────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(
            'application/x-mediaitem-id'
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(
            'application/x-mediaitem-id'
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(
            'application/x-mediaitem-id'
        ):
            event.ignore()
            return

        item_id = bytes(
            event.mimeData().data(
                'application/x-mediaitem-id'
            )
        ).decode()

        pos       = event.position()
        scene_pos = self.mapToScene(
            int(pos.x()), int(pos.y())
        )
        frame = self.app_state.pixel_to_frame(
            scene_pos.x(), float(self.width())
        )
        frame = max(0, frame)
        event.acceptProposedAction()
        self.clip_dropped.emit(item_id, frame)

    # ── Waveform workers ─────────────────────────────────

    def _start_waveform_worker(self, clip):
        from media.waveform_worker import WaveformWorker
        from media.waveform import load_peaks
        fp = clip.filepath

        # 1. check disk cache first — instant
        cached = load_peaks(fp)
        if cached is not None:
            self._on_waveform_ready(fp, cached, clip.id)
            return

        # 2. reuse mainwindow worker if running
        main = self.window()
        if hasattr(main, '_waveform_workers'):
            w = main._waveform_workers.get(fp)
            if w is not None:
                if w.isRunning():
                    # connect and wait — don't start new
                    w.completed.connect(
                        lambda f, p, c=clip:
                        self._on_waveform_ready(
                            f, p, c.id
                        )
                    )
                    return
                else:
                    # finished — check cache again
                    cached2 = load_peaks(fp)
                    if cached2 is not None:
                        self._on_waveform_ready(
                            fp, cached2, clip.id
                        )
                        return

        # 3. reuse canvas worker if running
        if fp in self._waveform_workers:
            w = self._waveform_workers[fp]
            if w.isRunning():
                w.completed.connect(
                    lambda f, p, c=clip:
                    self._on_waveform_ready(f, p, c.id)
                )
                return
        from pathlib import Path
        name = Path(fp).name
        worker = WaveformWorker(fp)
        worker.completed.connect(
            lambda f, p, c=clip:
            self._on_waveform_ready(f, p, c.id)
        )
        # show progress in mainwindow status bar
        worker.progress.connect(
            lambda f, pct, n=name:
            self._on_waveform_progress(n, pct)
        )
        worker.completed.connect(
            lambda f, p, n=name:
            self._on_waveform_done(n)
        )
        self._waveform_workers[fp] = worker
        worker.start()

    def _on_waveform_progress(self,
                               name: str,
                               pct: int):
        """Forward progress to mainwindow status bar."""
        main = self.parent()
        while main:
            if hasattr(main, 'status_label'):
                main.status_label.setText(
                    f'Waveform: {name} {pct}%'
                )
                return
            main = main.parent() if hasattr(
                main, 'parent'
            ) else None

    def _on_waveform_done(self, name: str):
        """Clear progress from status bar."""
        main = self.parent()
        while main:
            if hasattr(main, 'status_label'):
                main.status_label.setText(
                    f'Waveform ready: {name}'
                )
                return
            main = main.parent() if hasattr(
                main, 'parent'
            ) else None

    def _on_waveform_ready(self, fp, peaks, clip_id):
        if peaks is None:
            return
        item = self._waveform_items.get(clip_id)
        if item:
            item.set_peaks(peaks)


# ─────────────────────────────────────────────────────────────
# TrackRow — unified track widget
# ─────────────────────────────────────────────────────────────

class TrackRow(QWidget):
    """
    One complete track: header (left) + canvas (right).
    Full panel width. Height = track.height.

    Resize handle: full bottom edge (Option B).
    Dragging anywhere on the bottom edge resizes the row.
    """

    height_changed = Signal(str, int)  # track_id, new_h
    clip_dropped   = Signal(str, str, int)
    # (track_id, item_id, frame)

    RESIZE_ZONE = RESIZE_ZONE

    def __init__(self, track: Track,
                 app_state: AppState,
                 parent=None):
        super().__init__(parent)
        self.track     = track
        self.app_state = app_state

        self._resizing       = False
        self._resize_start_y = 0.0
        self._resize_start_h = track.height
        self._in_resize_zone = False

        self.setFixedHeight(track.height + RESIZE_ZONE)
        self.setMouseTracking(True)
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # main content row
        content = QWidget()
        content.setMouseTracking(True)
        layout = QHBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = TrackHeader(self.track)
        layout.addWidget(self.header)

        self.canvas = TrackCanvas(
            self.track, self.app_state
        )
        self.canvas.clip_dropped.connect(
            lambda item_id, frame:
            self.clip_dropped.emit(
                self.track.id, item_id, frame
            )
        )
        layout.addWidget(self.canvas)
        outer.addWidget(content)

        # resize handle strip — visible divider
        self._handle = QWidget()
        self._handle.setFixedHeight(RESIZE_ZONE)
        self._handle.setStyleSheet(
            'background-color: #3a3a3a;'
        )
        self._handle.setMouseTracking(True)
        self._handle.setCursor(
            Qt.CursorShape.SizeVerCursor
        )
        outer.addWidget(self._handle)

        # install event filter on handle for resize
        self._handle.installEventFilter(self)

    # ── Resize via handle strip ───────────────────────────

    def eventFilter(self, obj, event):
        """Capture mouse events on the resize handle."""
        from PySide6.QtCore import QEvent
        if obj is self._handle:
            if (event.type() ==
                    QEvent.Type.MouseButtonPress and
                    event.button() ==
                    Qt.MouseButton.LeftButton):
                self._resizing = True
                self._resize_start_y = (
                    event.globalPosition().y()
                )
                self._resize_start_h = (
                    self.track.height
                )
                return True
            elif (event.type() ==
                      QEvent.Type.MouseMove and
                      self._resizing):
                delta = (event.globalPosition().y()
                         - self._resize_start_y)
                new_h = int(
                    self._resize_start_h + delta
                )
                new_h = max(
                    MIN_TRACK_HEIGHT,
                    min(MAX_TRACK_HEIGHT, new_h)
                )
                if new_h != self.track.height:
                    self.track.height = new_h
                    # content area = total - handle
                    self.setFixedHeight(
                        new_h + RESIZE_ZONE
                    )
                    self.canvas.update_height(new_h)
                    self.height_changed.emit(
                        self.track.id, new_h
                    )
                return True
            elif (event.type() ==
                      QEvent.Type.MouseButtonRelease):
                self._resizing = False
                return True
        return super().eventFilter(obj, event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._resizing = False
        super().mouseReleaseEvent(event)
