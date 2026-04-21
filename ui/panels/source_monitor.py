"""
Source Monitor — preview clips before placing on timeline.

Double-click a clip in the media bin or on the timeline
to load it here for preview, trimming, and auditioning.

Separate from the Program monitor (timeline output).
"""

import torch
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap, QColor

from ui.app_state import AppState


class SourceMonitor(QWidget):
    """
    Source monitor — preview a single clip.
    Has its own independent playhead and transport.
    """

    # emitted when user sets in/out points
    in_point_set  = Signal(int)   # frame
    out_point_set = Signal(int)   # frame

    def __init__(self, app_state: AppState,
                 parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self._clip      = None
        self._decoder   = None
        self._frame     = 0
        self._playing   = False
        self._in_point  = 0
        self._out_point = -1

        self.setMinimumSize(320, 200)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        self._build_ui()

        self._timer = QTimer()
        self._timer.timeout.connect(self._advance_frame)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # video display
        self.label = QLabel('Source')
        self.label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self.label.setStyleSheet(
            'background-color:#0d0d0d; '
            'color:#444444; font-size:12px;'
        )
        self.label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self.label)

        # clip name
        self.name_label = QLabel('')
        self.name_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self.name_label.setStyleSheet(
            'color:#888888; font-size:10px; '
            'background:#111111; padding:2px;'
        )
        layout.addWidget(self.name_label)

        # scrub bar
        self.scrubber = QSlider(
            Qt.Orientation.Horizontal
        )
        self.scrubber.setRange(0, 1000)
        self.scrubber.setValue(0)
        self.scrubber.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #2a2a2a; height: 4px;
            }
            QSlider::handle:horizontal {
                background: #e8e820;
                width: 10px; height: 10px;
                margin: -3px 0;
                border-radius: 5px;
            }
            QSlider::sub-page:horizontal {
                background: #4a9de0;
            }
        """)
        self.scrubber.sliderMoved.connect(
            self._on_scrub
        )
        layout.addWidget(self.scrubber)

        # transport + in/out buttons
        transport = QHBoxLayout()
        transport.setSpacing(4)

        btn_style = """
            QPushButton {
                background:#2a2a2a; color:#cccccc;
                border:1px solid #383838;
                border-radius:3px; padding:2px 6px;
                font-size:11px;
            }
            QPushButton:hover { background:#3a3a3a; }
            QPushButton:pressed { background:#4a4a4a; }
        """

        self.btn_in  = QPushButton('{ In')
        self.btn_in.setToolTip('Mark In point (I)')
        self.btn_in.clicked.connect(self._mark_in)
        self.btn_in.setStyleSheet(btn_style)

        self.btn_play = QPushButton('▶')
        self.btn_play.setToolTip('Play/Pause (Space)')
        self.btn_play.clicked.connect(
            self._toggle_play
        )
        self.btn_play.setStyleSheet(btn_style)

        self.btn_out = QPushButton('Out }')
        self.btn_out.setToolTip('Mark Out point (O)')
        self.btn_out.clicked.connect(self._mark_out)
        self.btn_out.setStyleSheet(btn_style)

        self.tc_label = QLabel('00:00:00:00')
        self.tc_label.setStyleSheet(
            'color:#e8e820; font-size:11px; '
            'font-family:monospace; '
            'background:transparent;'
        )

        transport.addWidget(self.btn_in)
        transport.addStretch()
        transport.addWidget(self.btn_play)
        transport.addStretch()
        transport.addWidget(self.tc_label)
        transport.addStretch()
        transport.addWidget(self.btn_out)

        layout.addLayout(transport)

    # ── Public API ────────────────────────────────────

    def load_clip(self, clip_or_item):
        """
        Load a clip or media item for preview.
        Accepts Clip, MediaPoolItem, or filepath str.
        """
        self._stop()

        # get filepath
        if isinstance(clip_or_item, str):
            filepath = clip_or_item
            name     = filepath.split('/')[-1]
            in_pt    = 0
            out_pt   = -1
        elif hasattr(clip_or_item, 'filepath'):
            filepath = clip_or_item.filepath
            name     = clip_or_item.name
            in_pt  = getattr(clip_or_item, 'in_point',  0)
            out_pt = getattr(clip_or_item, 'out_point', -1)
        else:
            return

        self._clip     = clip_or_item
        self._in_point = in_pt
        self._out_point = out_pt

        try:
            from media.decoder import VideoDecoder
            self._decoder    = VideoDecoder(filepath)
            self._total      = self._decoder.total_frames
            self._frame      = in_pt
            self._fps        = self._decoder.fps or 29.97
            self.scrubber.setRange(0, self._total - 1)
            self.scrubber.setValue(self._frame)
            self.name_label.setText(name)
            self._show_frame(self._frame)
        except Exception as e:
            self.label.setText(f'Cannot preview:\n{e}')
            self._decoder = None

    def load_media_item(self, item):
        """Load from MediaPoolItem."""
        self.load_clip(item)

    # ── Transport ─────────────────────────────────────

    def _toggle_play(self):
        if self._playing:
            self._stop()
        else:
            self._play()

    def _play(self):
        if not self._decoder:
            return
        self._playing = True
        self.btn_play.setText('⏸')
        interval = max(1, int(1000 / self._fps))
        self._timer.start(interval)

    def _stop(self):
        self._playing = False
        self._timer.stop()
        self.btn_play.setText('▶')

    def _advance_frame(self):
        if not self._decoder:
            return
        end = (self._out_point
               if self._out_point != -1
               else self._total - 1)
        self._frame += 1
        if self._frame > end:
            self._frame = self._in_point
        self.scrubber.setValue(self._frame)
        self._show_frame(self._frame)

    def _on_scrub(self, value: int):
        self._frame = value
        self._show_frame(value)

    def _show_frame(self, frame: int):
        if not self._decoder:
            return
        try:
            img = self._decoder.get_frame(frame)
            if img is None:
                return
            # img is numpy HxWx3 or tensor
            if hasattr(img, 'numpy'):
                arr = img.cpu().numpy()
            else:
                arr = np.array(img)
            if arr.dtype != np.uint8:
                arr = (arr * 255).clip(
                    0, 255
                ).astype(np.uint8)
            h, w = arr.shape[:2]
            qimg = QImage(
                arr.tobytes(), w, h,
                w * 3, QImage.Format.Format_RGB888
            )
            px = QPixmap.fromImage(qimg).scaled(
                self.label.width(),
                self.label.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.label.setPixmap(px)
            self._update_tc(frame)
        except Exception:
            pass

    def _update_tc(self, frame: int):
        fps  = self._fps or 29.97
        secs = frame / fps
        h    = int(secs // 3600)
        m    = int((secs % 3600) // 60)
        s    = int(secs % 60)
        f    = int((secs % 1) * fps)
        self.tc_label.setText(
            f'{h:02d}:{m:02d}:{s:02d}:{f:02d}'
        )

    # ── In/Out points ─────────────────────────────────

    def _mark_in(self):
        self._in_point = self._frame
        if self._clip and hasattr(
            self._clip, 'in_point'
        ):
            self._clip.in_point = self._frame
        self.in_point_set.emit(self._frame)
        self.name_label.setText(
            self.name_label.text().split(' [')[0] +
            f' [In:{self._frame}]'
        )

    def _mark_out(self):
        self._out_point = self._frame
        if self._clip and hasattr(
            self._clip, 'out_point'
        ):
            self._clip.out_point = self._frame
        self.out_point_set.emit(self._frame)

    def clear(self):
        self._stop()
        self._clip    = None
        self._decoder = None
        self.label.setPixmap(QPixmap())
        self.label.setText('Source')
        self.name_label.setText('')
        self.tc_label.setText('00:00:00:00')
        self.scrubber.setValue(0)
