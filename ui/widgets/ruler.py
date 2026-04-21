from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from ui.app_state import AppState

class Ruler(QWidget):
    """
    Timecode ruler across the top of the timeline.
    Draws tick marks and timecodes at current zoom level.
    Repaints automatically when zoom changes.
    Click to move playhead.
    """

    HEIGHT = 28

    # colors
    COLOR_BG       = QColor('#141414')
    COLOR_TICK     = QColor('#444444')
    COLOR_TICK_MAJ = QColor('#666666')
    COLOR_TEXT     = QColor('#888888')
    COLOR_PLAYHEAD = QColor('#e8e820')
    COLOR_BORDER   = QColor('#333333')

    def __init__(self, app_state: AppState,
                 fps: float = 29.97,
                 parent=None):
        super().__init__(parent)
        self.app_state  = app_state
        self.fps        = fps
        self.setFixedHeight(self.HEIGHT)
        self.setMouseTracking(True)

        # connect to zoom/playhead changes → repaint
        # use named methods so we can disconnect cleanly
        self.app_state.zoom_changed.connect(
            self._on_change
        )
        self.app_state.playhead_changed.connect(
            self._on_change
        )

    def _on_change(self, *_):
        if not self.isVisible():
            return
        try:
            self.update()
        except RuntimeError:
            pass

    def _disconnect_signals(self):
        """Safely disconnect — swallow both exceptions and RuntimeWarnings."""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            try:
                self.app_state.zoom_changed.disconnect(
                    self._on_change
                )
            except Exception:
                pass
            try:
                self.app_state.playhead_changed.disconnect(
                    self._on_change
                )
            except Exception:
                pass

    def hideEvent(self, event):
        self._disconnect_signals()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._disconnect_signals()
        super().closeEvent(event)

    def set_fps(self, fps: float):
        self.fps = fps
        self.update()

    # =========================================================
    # Paint
    # =========================================================

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing, False
        )
        w = self.width()
        h = self.height()

        # background
        painter.fillRect(0, 0, w, h, self.COLOR_BG)

        # bottom border
        painter.setPen(QPen(self.COLOR_BORDER, 1))
        painter.drawLine(0, h - 1, w, h - 1)

        if self.app_state.total_frames <= 0:
            painter.end()
            return

        # --- choose tick interval based on zoom ---
        # we want roughly one label every 80px
        total   = self.app_state.total_frames
        visible = self.app_state.visible_range * total
        px_per_frame = w / visible if visible > 0 else 1.0

        # candidate intervals in frames
        candidates = [
            1, 2, 5, 10, 15, 30, 60, 150, 300,
            600, 900, 1800, 3600, 9000, 18000
        ]
        interval = 30   # default 1 second
        for c in candidates:
            if c * px_per_frame >= 80:
                interval = c
                break

        # minor tick = interval // 5  (or 1 if too small)
        minor = max(1, interval // 5)

        # --- draw ticks ---
        start_frame = int(
            self.app_state.view_start * total
        )
        end_frame   = int(
            self.app_state.view_end * total
        ) + interval

        # snap start to interval boundary
        start_frame = (start_frame // minor) * minor

        font = QFont('Courier New', 9)
        painter.setFont(font)

        for frame in range(start_frame,
                           end_frame + 1, minor):
            if frame < 0 or frame > total:
                continue

            px = self.app_state.frame_to_pixel(
                frame, float(w)
            )
            if px < 0 or px > w:
                continue

            is_major = (frame % interval == 0)

            if is_major:
                # major tick — full height with label
                painter.setPen(
                    QPen(self.COLOR_TICK_MAJ, 1)
                )
                painter.drawLine(
                    int(px), h - 14,
                    int(px), h - 1
                )
                # timecode label
                tc = self._frame_to_tc(frame)
                painter.setPen(QPen(self.COLOR_TEXT, 1))
                painter.drawText(
                    int(px) + 3, 0,
                    80, h - 14,
                    Qt.AlignmentFlag.AlignLeft |
                    Qt.AlignmentFlag.AlignVCenter,
                    tc
                )
            else:
                # minor tick — short
                painter.setPen(
                    QPen(self.COLOR_TICK, 1)
                )
                painter.drawLine(
                    int(px), h - 6,
                    int(px), h - 1
                )

        # --- playhead marker ---
        ph_px = self.app_state.frame_to_pixel(
            self.app_state.playhead_frame, float(w)
        )
        if 0 <= ph_px <= w:
            painter.setPen(
                QPen(self.COLOR_PLAYHEAD, 1)
            )
            painter.drawLine(
                int(ph_px), 0,
                int(ph_px), h
            )
            # playhead triangle
            painter.setBrush(self.COLOR_PLAYHEAD)
            painter.setPen(Qt.PenStyle.NoPen)
            x = int(ph_px)
            points = [
                (x - 5, 0),
                (x + 5, 0),
                (x,     10),
            ]
            from PySide6.QtGui import QPolygon
            from PySide6.QtCore import QPoint
            poly = QPolygon([
                QPoint(p[0], p[1]) for p in points
            ])
            painter.drawPolygon(poly)

        painter.end()

    # =========================================================
    # Mouse — click to set playhead
    # =========================================================

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._set_playhead_from_mouse(
                event.position().x()
            )

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self._set_playhead_from_mouse(
                event.position().x()
            )

    def _set_playhead_from_mouse(self, x: float):
        frame = self.app_state.pixel_to_frame(
            x, float(self.width())
        )
        frame = max(0, min(
            frame, self.app_state.total_frames
        ))
        self.app_state.playhead_frame = frame

    # =========================================================
    # Timecode helper
    # =========================================================

    def _frame_to_tc(self, frame: int) -> str:
        total_sec = frame / self.fps
        h  = int(total_sec // 3600)
        m  = int((total_sec % 3600) // 60)
        s  = int(total_sec % 60)
        f  = int((total_sec % 1) * self.fps)
        if h > 0:
            return f'{h}:{m:02d}:{s:02d}'
        elif m > 0:
            return f'{m}:{s:02d}'
        else:
            return f'{s:02d}:{f:02d}'

    def wheelEvent(self, event):
        """Pass scroll wheel to app_state zoom."""
        x        = event.position().x()
        norm_pos = self.app_state.pixel_to_norm(
            x, float(self.width())
        )
        delta = event.angleDelta().y()
        if delta > 0:
            self.app_state.zoom_in_at_position(norm_pos)
        else:
            self.app_state.zoom_out_at_position(norm_pos)