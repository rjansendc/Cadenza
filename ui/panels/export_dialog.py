"""
ExportDialog — export settings and progress UI.

Two modes:
  1. Settings mode  — user configures and clicks Export
  2. Progress mode  — shows progress bar and Cancel

The dialog stays open through export so the user
can see progress and cancel if needed.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton,
    QComboBox, QProgressBar, QFileDialog,
    QRadioButton, QButtonGroup, QGroupBox,
    QWidget, QSizePolicy, QFrame
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from render.export_config import (
    ExportConfig,
    RESOLUTION_PRESETS,
    QUALITY_PRESETS,
    SPEED_PRESETS,
    AUDIO_BITRATE_OPTIONS,
    ENCODER_PRESETS,
)


class ExportDialog(QDialog):
    """
    Export settings dialog with integrated
    progress display.
    """

    # emitted when user clicks Export
    export_requested = Signal(ExportConfig)

    def __init__(self, default_config: ExportConfig,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle('Export')
        self.setMinimumWidth(480)
        self.setModal(True)

        self._config  = default_config
        self._exporting = False

        self._build_ui()
        self._populate_fields()

    # =========================================================
    # UI construction
    # =========================================================

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # title
        title = QLabel('Export')
        font  = QFont()
        font.setPointSize(13)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        self._add_separator(layout)

        # output file
        layout.addWidget(
            self._build_output_section()
        )

        # video settings
        layout.addWidget(
            self._build_video_section()
        )

        # audio settings
        layout.addWidget(
            self._build_audio_section()
        )

        # range
        layout.addWidget(
            self._build_range_section()
        )

        self._add_separator(layout)

        # progress (hidden until export starts)
        self._progress_widget = self._build_progress()
        self._progress_widget.setVisible(False)
        layout.addWidget(self._progress_widget)

        # buttons
        layout.addLayout(self._build_buttons())

        self.setStyleSheet("""
            QDialog {
                background-color: #1e1e1e;
                color: #cccccc;
            }
            QLabel {
                color: #cccccc;
            }
            QGroupBox {
                color: #888888;
                border: 1px solid #333333;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 8px;
                font-size: 11px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }
            QLineEdit, QComboBox {
                background-color: #2a2a2a;
                color: #cccccc;
                border: 1px solid #444444;
                border-radius: 3px;
                padding: 4px 8px;
                min-height: 24px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: #cccccc;
                selection-background-color: #3a5a8a;
            }
            QPushButton {
                background-color: #2a2a2a;
                color: #cccccc;
                border: 1px solid #444444;
                border-radius: 3px;
                padding: 6px 16px;
                min-height: 28px;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
            }
            QPushButton#export_btn {
                background-color: #2a6b8a;
                color: #ffffff;
                border: none;
                font-weight: bold;
            }
            QPushButton#export_btn:hover {
                background-color: #3a8ab0;
            }
            QPushButton#export_btn:disabled {
                background-color: #1a3a4a;
                color: #666666;
            }
            QProgressBar {
                background-color: #2a2a2a;
                border: 1px solid #444444;
                border-radius: 3px;
                text-align: center;
                color: #cccccc;
                min-height: 20px;
            }
            QProgressBar::chunk {
                background-color: #2a6b8a;
                border-radius: 2px;
            }
            QRadioButton {
                color: #cccccc;
            }
            QFrame[frameShape="4"] {
                color: #333333;
            }
        """)

    def _build_output_section(self) -> QGroupBox:
        box    = QGroupBox('Output File')
        layout = QHBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)

        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText(
            'Select output file...'
        )
        layout.addWidget(self._path_edit)

        browse_btn = QPushButton('Browse...')
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse_output)
        layout.addWidget(browse_btn)

        return box

    def _build_video_section(self) -> QGroupBox:
        box    = QGroupBox('Video')
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # resolution
        row = QHBoxLayout()
        row.addWidget(QLabel('Resolution:'))
        self._res_combo = QComboBox()
        for label in RESOLUTION_PRESETS:
            self._res_combo.addItem(label)
        row.addWidget(self._res_combo)
        layout.addLayout(row)

        # quality
        row2 = QHBoxLayout()
        row2.addWidget(QLabel('Quality:'))
        self._quality_combo = QComboBox()
        for label in QUALITY_PRESETS:
            self._quality_combo.addItem(label)
        row2.addWidget(self._quality_combo)
        layout.addLayout(row2)

        # speed
        row3 = QHBoxLayout()
        row3.addWidget(QLabel('Encode speed:'))
        self._speed_combo = QComboBox()
        for label in SPEED_PRESETS:
            self._speed_combo.addItem(label)
        row3.addWidget(self._speed_combo)
        layout.addLayout(row3)

        # encoder
        row4 = QHBoxLayout()
        row4.addWidget(QLabel('Encoder:'))
        self._encoder_combo = QComboBox()
        import av as _av
        _available = _av.codecs_available
        _nvenc_ok  = 'h264_nvenc' in _available
        for label, enc in ENCODER_PRESETS.items():
            self._encoder_combo.addItem(label)
            # disable NVENC options if not available
            if 'nvenc' in enc and not _nvenc_ok:
                idx = self._encoder_combo.count() - 1
                item = self._encoder_combo.model().item(idx)
                item.setEnabled(False)
                item.setText(label + ' (not available)')
        row4.addWidget(self._encoder_combo)
        if not _nvenc_ok:
            from PySide6.QtWidgets import QLabel as _QL
            warn = _QL('⚠ NVIDIA GPU not detected')
            warn.setStyleSheet('color: #e08040; font-size: 10px;')
            layout.addWidget(warn)
        layout.addLayout(row4)

        return box

    def _build_audio_section(self) -> QGroupBox:
        box    = QGroupBox('Audio')
        layout = QHBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)

        layout.addWidget(QLabel('Bitrate:'))
        self._audio_combo = QComboBox()
        for label in AUDIO_BITRATE_OPTIONS:
            self._audio_combo.addItem(label)
        layout.addWidget(self._audio_combo)
        layout.addStretch()

        return box

    def _build_range_section(self) -> QGroupBox:
        box    = QGroupBox('Range')
        layout = QHBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)

        self._range_group = QButtonGroup(self)
        self._full_radio  = QRadioButton(
            'Full timeline'
        )
        self._inout_radio = QRadioButton(
            'In / Out points'
        )
        self._full_radio.setChecked(True)
        self._inout_radio.setEnabled(False)   # future
        self._range_group.addButton(self._full_radio)
        self._range_group.addButton(self._inout_radio)
        layout.addWidget(self._full_radio)
        layout.addWidget(self._inout_radio)
        layout.addStretch()

        return box

    def _build_progress(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        layout.addWidget(self._progress_bar)

        self._status_label = QLabel('')
        self._status_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        font = QFont()
        font.setPointSize(9)
        self._status_label.setFont(font)
        layout.addWidget(self._status_label)

        return widget

    def _build_buttons(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.addStretch()

        self._cancel_btn = QPushButton('Close')
        self._cancel_btn.clicked.connect(
            self._on_cancel
        )
        layout.addWidget(self._cancel_btn)

        self._export_btn = QPushButton('Export')
        self._export_btn.setObjectName('export_btn')
        self._export_btn.clicked.connect(
            self._on_export
        )
        layout.addWidget(self._export_btn)

        return layout

    def _add_separator(self, layout):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

    # =========================================================
    # Field population
    # =========================================================

    def _populate_fields(self):
        cfg = self._config

        # resolution
        target = f"{cfg.width} x {cfg.height}"
        for i, label in enumerate(RESOLUTION_PRESETS):
            w, h = RESOLUTION_PRESETS[label]
            if w == cfg.width and h == cfg.height:
                self._res_combo.setCurrentIndex(i)
                break

        # quality
        for i, (label, crf) in enumerate(
            QUALITY_PRESETS.items()
        ):
            if crf == cfg.crf:
                self._quality_combo.setCurrentIndex(i)
                break

        # speed
        for i, (label, preset) in enumerate(
            SPEED_PRESETS.items()
        ):
            if preset == cfg.preset:
                self._speed_combo.setCurrentIndex(i)
                break

        import av as _av2
        _nvenc = 'h264_nvenc' in _av2.codecs_available
        _default_enc = getattr(cfg, 'encoder', 
                               'h264_nvenc' if _nvenc else 'h264')
        for i, (label, enc) in enumerate(
            ENCODER_PRESETS.items()
        ):
            if enc == _default_enc:
                self._encoder_combo.setCurrentIndex(i)
                break

        # audio
        for i, (label, br) in enumerate(
            AUDIO_BITRATE_OPTIONS.items()
        ):
            if br == cfg.audio_bitrate:
                self._audio_combo.setCurrentIndex(i)
                break

    # =========================================================
    # Progress updates (called from mainwindow)
    # =========================================================

    def set_progress(self, pct: int):
        self._progress_bar.setValue(pct)

    def set_status(self, msg: str):
        self._status_label.setText(msg)

    def set_finished(self, path: str):
        self._exporting = False
        self._progress_bar.setValue(100)
        self._status_label.setText(
            f'Done: {path}'
        )
        self._export_btn.setEnabled(True)
        self._cancel_btn.setText('Close')

    def set_error(self, msg: str):
        self._exporting = False
        self._status_label.setText(f'Error: {msg}')
        self._export_btn.setEnabled(True)
        self._cancel_btn.setText('Close')

    # =========================================================
    # Button handlers
    # =========================================================

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            'Export to MP4',
            self._path_edit.text() or
            'output.mp4',
            'MP4 Files (*.mp4)'
        )
        if path:
            if not path.lower().endswith('.mp4'):
                path += '.mp4'
            self._path_edit.setText(path)

    def _on_export(self):
        path = self._path_edit.text().strip()
        if not path:
            self._status_label.setText(
                'Please select an output file.'
            )
            self._progress_widget.setVisible(True)
            return

        # build config from UI
        config = self._build_config(path)

        # switch to progress mode
        self._exporting = True
        self._progress_widget.setVisible(True)
        self._progress_bar.setValue(0)
        self._status_label.setText(
            'Starting export...'
        )
        self._export_btn.setEnabled(False)
        self._cancel_btn.setText('Cancel')

        self.export_requested.emit(config)

    def _on_cancel(self):
        if self._exporting:
            # signal mainwindow to cancel
            self.rejected.emit()
        else:
            self.accept()

    def _build_config(self,
                       output_path: str
                       ) -> ExportConfig:
        """Read UI fields → ExportConfig."""
        # resolution
        res_label = self._res_combo.currentText()
        w, h      = RESOLUTION_PRESETS.get(
            res_label, (1920, 1080)
        )

        # quality
        q_label = self._quality_combo.currentText()
        crf     = QUALITY_PRESETS.get(q_label, 18)

        # speed
        s_label = self._speed_combo.currentText()
        preset  = SPEED_PRESETS.get(s_label, 'fast')

        # encoder
        e_label  = self._encoder_combo.currentText()
        encoder  = ENCODER_PRESETS.get(e_label, 'h264')

        # audio
        a_label  = self._audio_combo.currentText()
        bitrate  = AUDIO_BITRATE_OPTIONS.get(
            a_label, '192k'
        )

        return ExportConfig(
            output_path   = output_path,
            width         = w,
            height        = h,
            crf           = crf,
            preset        = preset,
            encoder       = encoder,
            audio_bitrate = bitrate,
            start_frame   = 0,
            end_frame     = -1,
        )
