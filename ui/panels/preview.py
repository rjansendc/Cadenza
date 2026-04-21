import torch
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox
)
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen
from PySide6.QtCore import Qt, Signal, QRect
from ui.app_state import AppState


class FrameDisplay(QWidget):
    """
    Custom widget that draws the video frame centered with
    a visible border showing the exact canvas boundary.
    The surrounding area is a darker shade so the border is clear.
    """

    BORDER_COLOR  = QColor('#555555')   # frame boundary
    OUTSIDE_COLOR = QColor('#0d0d0d')   # letterbox / outside area

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None

    def set_pixmap(self, pixmap: QPixmap):
        self._pixmap = pixmap
        self.update()

    def clear(self):
        self._pixmap = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.OUTSIDE_COLOR)

        if self._pixmap is None or self._pixmap.isNull():
            painter.setPen(QColor('#333333'))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                'No clip loaded'
            )
            return

        # center the pixmap
        x = (self.width()  - self._pixmap.width())  // 2
        y = (self.height() - self._pixmap.height()) // 2
        painter.drawPixmap(x, y, self._pixmap)

        # draw 1px border around the frame boundary
        pen = QPen(self.BORDER_COLOR, 1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRect(
            x, y,
            self._pixmap.width()  - 1,
            self._pixmap.height() - 1
        ))


class PreviewPanel(QWidget):

    # emitted when playback resolution changes
    # so compositor can update decoder output size
    resolution_changed = Signal(int, int)  # width, height

    RESOLUTIONS = [
        ('Full',  1, 1),
        ('1/2',   2, 2),
        ('1/4',   4, 4),
        ('1/8',   8, 8),
    ]

    def __init__(self, app_state: AppState,
                 parent=None):
        super().__init__(parent)
        self.app_state   = app_state
        self._seq_w      = 1920
        self._seq_h      = 1080
        self._divisor    = 2   # default 1/2

        self.setMinimumSize(480, 270)
        self.setStyleSheet(
            'background-color: #0d0d0d;'
        )
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # video display - custom widget with frame border
        self.label = FrameDisplay(self)
        layout.addWidget(self.label)

        # bottom bar with resolution selector
        bar = QWidget()
        bar.setFixedHeight(22)
        bar.setStyleSheet(
            'background:#111111;'
        )
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(4, 0, 4, 0)
        bar_layout.setSpacing(4)

        lbl = QLabel('Playback:')
        lbl.setStyleSheet(
            'color:#666; font-size:10px;'
            'background:transparent;'
        )
        bar_layout.addWidget(lbl)

        self.res_combo = QComboBox()
        self.res_combo.setFixedHeight(18)
        self.res_combo.setStyleSheet("""
            QComboBox {
                background:#1a1a1a; color:#aaa;
                border:1px solid #333;
                font-size:10px; padding:0 4px;
            }
            QComboBox::drop-down { width:12px; }
            QComboBox QAbstractItemView {
                background:#1a1a1a; color:#aaa;
                selection-background-color:#333;
            }
        """)
        for name, dw, dh in self.RESOLUTIONS:
            self.res_combo.addItem(name, (dw, dh))
        self.res_combo.setCurrentIndex(1)  # 1/2 default
        self.res_combo.currentIndexChanged.connect(
            self._on_resolution_changed
        )
        bar_layout.addWidget(self.res_combo)
        bar_layout.addStretch()

        layout.addWidget(bar)

    def set_sequence_size(self, w: int, h: int):
        """Call when sequence settings are known."""
        self._seq_w = w
        self._seq_h = h
        self._emit_resolution()

    def _on_resolution_changed(self, idx):
        self._emit_resolution()

    def _emit_resolution(self):
        dw, dh = self.res_combo.currentData()
        w = self._seq_w // dw
        h = self._seq_h // dh
        self.resolution_changed.emit(w, h)

    def preview_size(self):
        """Return current preview decode size."""
        dw, dh = self.res_combo.currentData()
        return self._seq_w // dw, self._seq_h // dh

    def display_frame(self,
                       frame_tensor: torch.Tensor):
        if frame_tensor.is_cuda:
            frame = frame_tensor.cpu()
        else:
            frame = frame_tensor

        # Convert to uint8 numpy — keep as contiguous array.
        # Use np.ascontiguousarray to avoid a copy if already uint8.
        arr = frame.numpy()
        if arr.dtype != np.uint8:
            np.clip(arr, 0, 255, out=arr)
            arr = arr.astype(np.uint8, copy=False)
        arr = np.ascontiguousarray(arr)

        h, w, ch = arr.shape

        # Zero-copy QImage — arr must stay alive until pixmap is built.
        # bytes_per_line avoids QImage guessing stride incorrectly.
        image = QImage(
            arr.data, w, h,
            w * ch, QImage.Format.Format_RGB888
        )

        # Scale only when label size changes — cache last size.
        lw = self.label.width()
        lh = self.label.height()
        last = getattr(self, '_last_label_size', (0, 0))
        if (lw, lh) != last or getattr(self, '_last_src_size', (0,0)) != (w, h):
            self._last_label_size = (lw, lh)
            self._last_src_size   = (w, h)
            # Compute scaled size once, reuse every frame
            src_ratio = w / h
            lbl_ratio = lw / lh if lh > 0 else 1
            if src_ratio > lbl_ratio:
                sw = lw
                sh = int(lw / src_ratio)
            else:
                sh = lh
                sw = int(lh * src_ratio)
            self._scaled_w = max(1, sw)
            self._scaled_h = max(1, sh)

        pixmap = QPixmap.fromImage(image).scaled(
            self._scaled_w,
            self._scaled_h,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation
        )
        self.label.set_pixmap(pixmap)

    def clear(self):
        self.label.clear()
