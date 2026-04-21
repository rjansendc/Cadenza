from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, QRect, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QCursor

class ZoomBar(QWidget):
    """
    Premiere-style timeline zoom bar.
    Two handles to zoom, drag middle to pan.

    Emits view_changed(start, end) — normalized 0.0 to 1.0.
    """

    view_changed = Signal(float, float)

    # colors
    COLOR_TRACK   = QColor('#1a1a1a')
    COLOR_BAR     = QColor('#3a3a3a')
    COLOR_HANDLE  = QColor('#6a6a6a')
    COLOR_BAR_HOV = QColor('#4a4a4a')
    COLOR_HND_HOV = QColor('#9a9a9a')

    HANDLE_WIDTH  = 10   # px — width of each end handle
    MIN_BAR_WIDTH = 20   # px — minimum draggable bar width

    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.setMinimumHeight(16)
        self.setMaximumHeight(16)
        self.setMouseTracking(True)

        # drag state
        self._drag_mode  = None  
        # None | 'left' | 'right' | 'middle'
        self._drag_start_x    = 0
        self._drag_start_view = (0.0, 1.0)
        self._hovered         = None  
        # None | 'left' | 'right' | 'middle'

        # connect to app_state so external zoom 
        # (scroll wheel) updates the bar
        self.app_state.zoom_changed.connect(self._on_zoom_changed)

    def _on_zoom_changed(self, start, end):
        self.update()   # repaint

    # --- geometry helpers ---

    def _bar_rects(self):
        """
        Returns (left_handle, middle, right_handle) as QRect.
        All in widget coordinates.
        """
        w  = self.width()
        h  = self.height()
        vs = self.app_state.view_start
        ve = self.app_state.view_end

        bar_left  = int(vs * w)
        bar_right = int(ve * w)
        bar_right = max(bar_right, 
                        bar_left + self.MIN_BAR_WIDTH)

        lh = QRect(bar_left, 0, 
                   self.HANDLE_WIDTH, h)
        rh = QRect(bar_right - self.HANDLE_WIDTH, 0,
                   self.HANDLE_WIDTH, h)
        mid = QRect(lh.right(), 0,
                    rh.left() - lh.right(), h)
        return lh, mid, rh

    def _hit_test(self, x: int):
        lh, mid, rh = self._bar_rects()
        if lh.contains(QPoint(x, self.height() // 2)):
            return 'left'
        if rh.contains(QPoint(x, self.height() // 2)):
            return 'right'
        if mid.contains(QPoint(x, self.height() // 2)):
            return 'middle'
        return None

    # --- paint ---

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()

        # track background
        painter.fillRect(0, 0, w, h, self.COLOR_TRACK)

        lh, mid, rh = self._bar_rects()

        # middle bar
        bar_color = (self.COLOR_BAR_HOV 
                     if self._hovered == 'middle' 
                     else self.COLOR_BAR)
        painter.fillRect(lh.right(), 2, 
                         rh.left() - lh.right(), h - 4,
                         bar_color)

        # left handle
        lh_color = (self.COLOR_HND_HOV 
                    if self._hovered == 'left' 
                    else self.COLOR_HANDLE)
        painter.fillRect(lh.adjusted(0, 1, 0, -1), lh_color)

        # right handle  
        rh_color = (self.COLOR_HND_HOV 
                    if self._hovered == 'right' 
                    else self.COLOR_HANDLE)
        painter.fillRect(rh.adjusted(0, 1, 0, -1), rh_color)

        # handle grip dots
        for rect, color in [(lh, lh_color), (rh, rh_color)]:
            cx = rect.center().x()
            cy = h // 2
            painter.setPen(QPen(self.COLOR_TRACK, 1))
            for dy in (-3, 0, 3):
                painter.drawEllipse(cx - 1, cy + dy - 1, 2, 2)

        painter.end()

    # --- mouse ---

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        self._drag_mode     = self._hit_test(int(x))
        self._drag_start_x  = x
        self._drag_start_view = (
            self.app_state.view_start,
            self.app_state.view_end
        )
        if self._drag_mode:
            self.setCursor(Qt.CursorShape.SizeHorCursor)

    def mouseMoveEvent(self, event):
        x    = event.position().x()
        w    = self.width()

        if self._drag_mode is None:
            # just hovering
            hit = self._hit_test(int(x))
            if hit != self._hovered:
                self._hovered = hit
                cursor = (Qt.CursorShape.SizeHorCursor 
                          if hit in ('left', 'right')
                          else Qt.CursorShape.OpenHandCursor
                          if hit == 'middle'
                          else Qt.CursorShape.ArrowCursor)
                self.setCursor(cursor)
                self.update()
            return

        # dragging
        delta_norm = (x - self._drag_start_x) / w
        s0, e0     = self._drag_start_view

        if self._drag_mode == 'left':
            new_start = max(0.0, min(s0 + delta_norm, 
                                      e0 - 0.005))
            self.app_state.set_view(new_start, e0)

        elif self._drag_mode == 'right':
            new_end = min(1.0, max(e0 + delta_norm,
                                    s0 + 0.005))
            self.app_state.set_view(s0, new_end)

        elif self._drag_mode == 'middle':
            r         = e0 - s0
            new_start = max(0.0, min(s0 + delta_norm, 
                                      1.0 - r))
            self.app_state.set_view(new_start, 
                                     new_start + r)

    def mouseReleaseEvent(self, event):
        self._drag_mode = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseDoubleClickEvent(self, event):
        """Double click resets to full zoom out."""
        self.app_state.set_view(0.0, 1.0)

    def wheelEvent(self, event):
        """
        Scroll wheel zooms in/out at cursor position.
        """
        x        = event.position().x()
        norm_pos = self.app_state.pixel_to_norm(
            x, self.width()
        )
        delta = event.angleDelta().y()
        if delta > 0:
            self.app_state.zoom_in_at_position(norm_pos)
        else:
            self.app_state.zoom_out_at_position(norm_pos)