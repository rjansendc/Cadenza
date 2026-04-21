import numpy as np
from PySide6.QtWidgets import QGraphicsItem
from PySide6.QtCore import QRectF, Qt, QPointF
from PySide6.QtGui import (
    QPainter, QColor, QPen, QPainterPath,
    QCursor, QBrush
)
from core.clip import Clip
from ui.app_state import AppState
from ui.constants import TRACK_HEIGHT, CLIP_PADDING

WAVEFORM_COLOR = QColor('#2ab87a')
ENVELOPE_COLOR = QColor('#e8e820')
ENVELOPE_WIDTH = 1.5
HANDLE_RADIUS  = 4    # px — grab radius for envelope


class WaveformItem(QGraphicsItem):
    """
    Audio waveform drawn as child of ClipItem.
    Moves automatically with parent clip.
    Handles envelope drag independently.
    """

    def __init__(self,
                 clip: Clip,
                 app_state: AppState,
                 parent: QGraphicsItem = None):
        super().__init__(parent)  # parent = ClipItem
        self.clip      = clip
        self.app_state = app_state
        self._peaks    = None
        self._loading  = True

        # envelope drag state
        self._env_dragging  = False
        self._env_drag_start_y = 0.0
        self._env_start_val    = 1.0

        self.setZValue(1)   # above clip background
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        # Redraw when clip is modified externally
        # (e.g. volume changed in effects panel)
        self.app_state.clip_modified.connect(
            self._on_clip_modified)

    def _on_clip_modified(self, clip_id: str):
        if clip_id == self.clip.id:
            self.update()  # redraw envelope bar at new position

    def set_peaks(self, peaks):
        self._peaks   = peaks
        self._loading = False
        self.update()

    def boundingRect(self) -> QRectF:
        """
        Fill parent clip's rect exactly.
        Since we're a child, coordinates are
        relative to parent.
        """
        if self.parentItem():
            return self.parentItem().boundingRect()
        return QRectF(0, 0, 100, TRACK_HEIGHT)

    def paint(self, painter: QPainter,
              option, widget=None):
        rect = self.boundingRect()
        if rect.width() < 2:
            return

        painter.setClipRect(rect)

        if self._loading or self._peaks is None:
            painter.setPen(QPen(QColor('#2a4a3a'), 1))
            font = painter.font()
            font.setPointSize(8)
            painter.setFont(font)
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignCenter,
                '...'
            )
            return

        self._draw_waveform(painter, rect)
        self._draw_envelope(painter, rect)

    def _draw_waveform(self, painter, rect):
        """Draw stereo waveform — L top half, R bottom half."""
        peaks     = self._peaks
        num_peaks = peaks.shape[1]
        w         = rect.width()
        h         = rect.height()

        if num_peaks == 0 or w <= 0:
            return

        # Normalize to 0 dBFS (full scale digital) —
        # divide by the absolute maximum peak in the full file.
        # This is the DAW standard: a file recorded at maximum
        # level fills the track height. A quiet file sits low.
        # The user sees actual recorded levels and can raise
        # volume in Effect Controls as needed.
        # Calculated from the FULL file before slicing so
        # cuts never change the visual scale.
        import numpy as np
        is_stereo_full = peaks.shape[0] >= 4
        if is_stereo_full:
            all_maxes = np.concatenate([peaks[1], peaks[3]])
        else:
            all_maxes = peaks[1]
        full_peak_max = float(np.abs(all_maxes).max())
        if full_peak_max < 0.0001:
            full_peak_max = 1.0  # silence guard

        # Slice peaks to in_point→out_point region only
        # so waveform shows just the used portion of the file
        source_frames = self.clip.source_frames
        if source_frames > 0:
            in_frac  = self.clip.in_point / source_frames
            if self.clip.out_point == -1:
                out_frac = 1.0
            else:
                out_frac = self.clip.out_point / source_frames
            in_frac  = max(0.0, min(1.0, in_frac))
            out_frac = max(in_frac, min(1.0, out_frac))
            p_start  = int(in_frac  * num_peaks)
            p_end    = int(out_frac * num_peaks)
            p_end    = max(p_start + 1, min(p_end, num_peaks))
            peaks     = peaks[:, p_start:p_end]
            num_peaks = peaks.shape[1]

        # stereo: [4, N] = L_min, L_max, R_min, R_max
        # legacy mono: [2, N] = min, max
        is_stereo = peaks.shape[0] >= 4

        # volume from envelope — scales amplitude display
        env    = self.clip.envelopes.get('volume')
        volume = env.default_value if env else 1.0
        volume = max(0.0, volume)  # no upper clamp — allow saturation

        # normalize: use full file peak (calculated before slice)
        # so scale stays consistent regardless of cut position
        peak_max = full_peak_max
        norm = 1.0 / peak_max

        painter.setPen(QPen(WAVEFORM_COLOR, 1))
        peaks_per_px = num_peaks / w

        if is_stereo:
            # L channel: top half of track
            # R channel: bottom half of track
            half_h = h / 2
            amp    = half_h * volume
            # L: baseline at divider (half_h)
            # R: baseline at track bottom (h)
            # thin divider between L and R
            painter.setPen(QPen(QColor('#1a3a2a'), 1))
            painter.drawLine(
                int(rect.left()),  int(rect.top() + half_h),
                int(rect.right()), int(rect.top() + half_h)
            )
            painter.setPen(QPen(WAVEFORM_COLOR, 1))
            self._draw_channel(
                painter, rect, peaks,
                ch_min=0, ch_max=1,
                baseline=rect.top() + half_h,
                amp=amp,
                norm=norm,
                peaks_per_px=peaks_per_px,
                num_peaks=num_peaks,
                label='L'
            )
            self._draw_channel(
                painter, rect, peaks,
                ch_min=2, ch_max=3,
                baseline=rect.top() + h,
                amp=amp,
                norm=norm,
                peaks_per_px=peaks_per_px,
                num_peaks=num_peaks,
                label='R'
            )
        else:
            # mono — single waveform centered
            self._draw_channel(
                painter, rect, peaks,
                ch_min=0, ch_max=1,
                baseline=rect.top() + h,
                amp=h * volume,
                norm=norm,
                peaks_per_px=peaks_per_px,
                num_peaks=num_peaks
            )

    def _draw_channel(self, painter, rect, peaks,
                       ch_min, ch_max, baseline, amp,
                       norm, peaks_per_px, num_peaks,
                       label=None):
        """Draw one channel as filled waveform."""
        w    = rect.width()

        # build rectified outline (abs values only)
        top_pts = []

        for px in range(int(w)):
            x          = rect.left() + px
            peak_start = int(px * peaks_per_px)
            peak_end   = max(
                peak_start + 1,
                int((px + 1) * peaks_per_px)
            )
            peak_start = max(0, min(
                peak_start, num_peaks - 1
            ))
            peak_end   = max(
                peak_start + 1,
                min(peak_end, num_peaks)
            )

            mn = float(
                peaks[ch_min, peak_start:peak_end].min()
            ) * norm
            mx = float(
                peaks[ch_max, peak_start:peak_end].max()
            ) * norm

            # abs(max) — rectified upward from baseline
            top_pts.append((x, baseline - mx * amp))

        if not top_pts:
            return

        path = QPainterPath()
        path.moveTo(top_pts[0][0], baseline)
        for x, y in top_pts:
            path.lineTo(x, y)
        path.lineTo(top_pts[-1][0], baseline)
        path.closeSubpath()

        # fill
        painter.setBrush(QBrush(WAVEFORM_COLOR))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)

        # L/R label if room
        if label and amp > 12:
            painter.setPen(QPen(QColor('#ffffff'), 1))
            font = painter.font()
            font.setPointSize(7)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                int(rect.left() + 2),
                int(baseline - amp + 10),
                label
            )

    def _draw_envelope(self, painter, rect):
        """Draw volume envelope line."""
        env = self.clip.envelopes.get('volume')
        if env is None:
            return

        h   = rect.height()
        val = env.default_value  # linear
        import math
        if val <= 0.0:
            db = -96.0
        else:
            db = 20.0 * math.log10(val)
        db   = max(-96.0, min(15.0, db))
        # Map: +15dB → near top, 0dB → ~75% down, -96dB → bottom
        frac = (db - (-96.0)) / (15.0 - (-96.0))
        y    = rect.top() + h * (1.0 - frac * 0.9)

        # envelope line
        painter.setPen(
            QPen(ENVELOPE_COLOR, ENVELOPE_WIDTH)
        )
        painter.drawLine(
            int(rect.left()),  int(y),
            int(rect.right()), int(y)
        )

        # grab handle — circle in center (only if needed)
        # Only show dot if value is not default (1.0) or has keyframes
        show_dot = False
        if hasattr(env, 'keyframes') and len(env.keyframes) > 0:
            show_dot = True
        elif abs(val - 1.0) > 0.01:  # Not at 100% volume
            show_dot = True
            
        if show_dot:
            cx = rect.left() + rect.width() / 2
            painter.setBrush(ENVELOPE_COLOR)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(
                QPointF(cx, y),
                HANDLE_RADIUS,
                HANDLE_RADIUS
            )

    # =========================================================
    # Envelope drag
    # =========================================================

    def _envelope_y(self, rect: QRectF) -> float:
        """Y position of envelope line in item coords."""
        env = self.clip.envelopes.get('volume')
        if env is None:
            return rect.center().y()
        import math
        h   = rect.height()
        val = env.default_value
        if val <= 0.0:
            db = -96.0
        else:
            db = 20.0 * math.log10(val)
        db   = max(-96.0, min(15.0, db))
        frac = (db - (-96.0)) / (15.0 - (-96.0))
        return rect.top() + h * (1.0 - frac * 0.9)

    def _is_near_envelope(self,
                           pos: QPointF) -> bool:
        """Check if pos is close to envelope line."""
        rect   = self.boundingRect()
        env_y  = self._envelope_y(rect)
        return abs(pos.y() - env_y) <= HANDLE_RADIUS + 2

    def hoverMoveEvent(self, event):
        if self._is_near_envelope(event.pos()):
            self.setCursor(
                Qt.CursorShape.SizeVerCursor
            )
        else:
            self.setCursor(
                Qt.CursorShape.ArrowCursor
            )

    def hoverLeaveEvent(self, event):
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event):
        if (event.button() ==
                Qt.MouseButton.LeftButton and
                self._is_near_envelope(event.pos())):
            self._env_dragging     = True
            self._env_drag_start_y = event.pos().y()
            env = self.clip.envelopes.get('volume')
            self._env_start_val = (
                env.default_value if env else 1.0
            )
            event.accept()
        else:
            # pass to parent (ClipItem) for clip drag
            event.ignore()

    def mouseMoveEvent(self, event):
        if not self._env_dragging:
            event.ignore()
            return

        rect   = self.boundingRect()
        h      = rect.height()
        delta_y = event.pos().y() - self._env_drag_start_y

        # Map drag distance to dB change
        # Full track height = 75 dB range (-60 to +15)
        import math
        db_range  = 111.0  # -96 to +15
        delta_db  = -(delta_y / h) * db_range * 0.9
        if self._env_start_val <= 0.0:
            start_db = -96.0
        else:
            start_db = 20.0 * math.log10(self._env_start_val)
        new_db  = max(-96.0, min(15.0, start_db + delta_db))
        new_val = 0.0 if new_db <= -96.0 else 10.0 ** (new_db / 20.0)

        env = self.clip.envelopes.get('volume')
        if env:
            old_val = self._env_start_val
            env.default_value = new_val
            from core.undo import undo_stack, SetVolumeCommand
            undo_stack.push(SetVolumeCommand(
                self.clip, old_val, new_val
            ))

        self.update()
        # Notify effects panel so Volume spinbox stays in sync
        self.app_state.clip_modified.emit(self.clip.id)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._env_dragging = False
        event.accept()