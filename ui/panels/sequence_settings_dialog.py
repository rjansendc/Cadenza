"""
SequenceSettingsDialog — set resolution, fps, sample rate.
Used for both New Project and Sequence > Settings.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QFormLayout, QGroupBox,
    QSpinBox
)
from PySide6.QtCore import Qt
from core.track import SequenceSettings

STYLE = """
    QDialog { background: #1e1e1e; color: #cccccc; }
    QGroupBox {
        border: 1px solid #444; border-radius: 4px;
        margin-top: 8px; padding: 8px;
        color: #aaaaaa; font-size: 11px;
    }
    QGroupBox::title { subcontrol-origin: margin; left: 8px; }
    QLabel { color: #cccccc; }
    QComboBox, QSpinBox {
        background: #2d2d2d; color: #cccccc;
        border: 1px solid #555; border-radius: 3px;
        padding: 3px 6px; min-width: 160px;
    }
    QComboBox::drop-down { border: none; }
    QComboBox:hover, QSpinBox:hover { border-color: #4a9fd4; }
    QPushButton {
        background: #2d2d2d; color: #cccccc;
        border: 1px solid #555; border-radius: 3px;
        padding: 6px 16px; min-width: 80px;
    }
    QPushButton:hover { background: #3a3a3a; }
    QPushButton#ok {
        background: #4a9fd4; color: white; border: none;
    }
    QPushButton#ok:hover { background: #5aade0; }
"""

RESOLUTIONS = [
    ("1920 × 1080  (1080p HD)",  1920, 1080),
    ("3840 × 2160  (4K UHD)",    3840, 2160),
    ("1280 × 720   (720p HD)",   1280,  720),
    ("720 × 480    (480p SD)",    720,  480),
    ("Custom",                      0,    0),
]

FRAME_RATES = [
    ("23.976",  23.976),
    ("24",      24.0),
    ("25",      25.0),
    ("29.97",   29.97),
    ("30",      30.0),
    ("59.94",   59.94),
    ("60",      60.0),
]

SAMPLE_RATES = [
    ("48000 Hz", 48000),
    ("44100 Hz", 44100),
]


class SequenceSettingsDialog(QDialog):
    def __init__(self, current: SequenceSettings = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sequence Settings")
        self.setStyleSheet(STYLE)
        self.setFixedWidth(360)
        self.setWindowFlags(
            self.windowFlags() &
            ~Qt.WindowType.WindowContextHelpButtonHint
        )

        s = current or SequenceSettings()
        self._build_ui(s)

    def _build_ui(self, s: SequenceSettings):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        group = QGroupBox("Video")
        form = QFormLayout(group)
        form.setSpacing(8)

        # Resolution
        self._res_combo = QComboBox()
        for label, w, h in RESOLUTIONS:
            self._res_combo.addItem(label, (w, h))
        # match current
        matched = False
        for i, (_, w, h) in enumerate(RESOLUTIONS[:-1]):
            if w == s.width and h == s.height:
                self._res_combo.setCurrentIndex(i)
                matched = True
                break
        if not matched:
            self._res_combo.setCurrentIndex(len(RESOLUTIONS) - 1)
        self._res_combo.currentIndexChanged.connect(
            self._on_res_changed)
        form.addRow("Resolution:", self._res_combo)

        # Custom W/H (hidden unless Custom selected)
        self._custom_row = QHBoxLayout()
        self._w_spin = QSpinBox()
        self._w_spin.setRange(320, 7680)
        self._w_spin.setValue(s.width)
        self._h_spin = QSpinBox()
        self._h_spin.setRange(240, 4320)
        self._h_spin.setValue(s.height)
        self._custom_row.addWidget(QLabel("W:"))
        self._custom_row.addWidget(self._w_spin)
        self._custom_row.addWidget(QLabel("H:"))
        self._custom_row.addWidget(self._h_spin)
        form.addRow("", self._custom_row)
        self._custom_widget = self._custom_row
        self._on_res_changed(self._res_combo.currentIndex())

        # Frame rate
        self._fps_combo = QComboBox()
        for label, fps in FRAME_RATES:
            self._fps_combo.addItem(label, fps)
        for i, (_, fps) in enumerate(FRAME_RATES):
            if abs(fps - s.fps) < 0.01:
                self._fps_combo.setCurrentIndex(i)
                break
        form.addRow("Frame Rate:", self._fps_combo)

        layout.addWidget(group)

        # Audio group
        audio_group = QGroupBox("Audio")
        audio_form = QFormLayout(audio_group)
        audio_form.setSpacing(8)

        self._sr_combo = QComboBox()
        for label, sr in SAMPLE_RATES:
            self._sr_combo.addItem(label, sr)
        for i, (_, sr) in enumerate(SAMPLE_RATES):
            if sr == s.sample_rate:
                self._sr_combo.setCurrentIndex(i)
                break
        audio_form.addRow("Sample Rate:", self._sr_combo)
        layout.addWidget(audio_group)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        ok = QPushButton("OK")
        ok.setObjectName("ok")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        btn_row.addWidget(ok)
        layout.addLayout(btn_row)

    def _on_res_changed(self, idx):
        is_custom = (idx == len(RESOLUTIONS) - 1)
        # show/hide custom spinboxes
        for i in range(self._custom_row.count()):
            w = self._custom_row.itemAt(i).widget()
            if w:
                w.setVisible(is_custom)

    def get_settings(self) -> SequenceSettings:
        idx = self._res_combo.currentIndex()
        w, h = self._res_combo.itemData(idx)
        if w == 0:  # Custom
            w = self._w_spin.value()
            h = self._h_spin.value()
        fps = self._fps_combo.currentData()
        sr  = self._sr_combo.currentData()
        return SequenceSettings(
            width=w, height=h, fps=fps, sample_rate=sr
        )

    @staticmethod
    def suggest_settings(media_item=None) -> SequenceSettings:
        """
        Suggest sequence settings based on imported media.
        Only matches source if it's below 1080p — never upsizes.
        """
        default = SequenceSettings()
        if media_item is None or not media_item.has_video:
            return default
        src_w = media_item.source_width
        src_h = media_item.source_height
        src_fps = media_item.source_fps or 29.97
        # Only match if source is below 1080p
        if src_h < 1080:
            return SequenceSettings(
                width=src_w,
                height=src_h,
                fps=src_fps,
                sample_rate=default.sample_rate
            )
        # Otherwise use defaults but match fps
        return SequenceSettings(
            width=default.width,
            height=default.height,
            fps=src_fps,
            sample_rate=default.sample_rate
        )
