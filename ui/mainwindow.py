import sys
from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter,
    QDockWidget, QMenuBar, QMenu,
    QToolBar, QStatusBar, QLabel,
    QFileDialog, QApplication
)
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import (
    QAction, QKeySequence, QIcon,
    QColor, QPalette
)

from core.project import Project, MediaPoolItem
from core.commands import registry, CommandContext
from ui.app_state import AppState
from ui.constants import (
    snap_row_for_clip, row_to_track_index
)
# Add this line for Effects Panel
from ui.panels.effects_panel import EffectsPanel

def _icon(name: str) -> 'QIcon':
    """Load icon from icons/ folder next to project root."""
    import os
    from PySide6.QtGui import QIcon
    path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        'icons', name
    )
    if os.path.exists(path):
        return QIcon(path)
    return QIcon()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # --- core state ---
        self.project   = Project()
        self.app_state = AppState(parent=self)

        # --- window setup ---
        self.setWindowTitle('Cadenza')
        self.setWindowIcon(_icon('app.ico'))
        self.setMinimumSize(1280, 720)
        self.resize(1600, 900)
        self._apply_dark_theme()

        # --- build UI in order ---
        self._build_menu_bar()
        self._build_tool_bar()
        self._build_status_bar()
        self._build_panels()
        self._connect_signals()

        # --- register core commands ---
        self._register_commands()

        # update title
        self._update_title()

        # --- playback engine ---
        self._playback = None
        self._init_playback()

        from PySide6.QtGui import QShortcut
        delete_sc = QShortcut(
            QKeySequence('Delete'), self
        )
        delete_sc.activated.connect(
            self._on_delete_clip
        )
        # Load effects for Effects Panel
        self._ensure_effects_loaded()

    def _ensure_effects_loaded(self):
        """Import effects modules to trigger registration."""
        try:
            import effects.video
            import effects.audio
            print("Effects loaded successfully")
        except ImportError as e:
            print(f"Warning: Could not load effects - {e}")

    # =========================================================
    # Theme
    # =========================================================

    def _apply_dark_theme(self):
        """Premiere-style dark theme."""
        palette = QPalette()
        dark    = QColor('#1e1e1e')
        darker  = QColor('#141414')
        mid     = QColor('#2a2a2a')
        text    = QColor('#cccccc')
        bright  = QColor('#ffffff')
        accent  = QColor('#4a9de0')
        disabled = QColor('#555555')

        palette.setColor(QPalette.ColorRole.Window,          dark)
        palette.setColor(QPalette.ColorRole.WindowText,      text)
        palette.setColor(QPalette.ColorRole.Base,            darker)
        palette.setColor(QPalette.ColorRole.AlternateBase,   mid)
        palette.setColor(QPalette.ColorRole.Text,            text)
        palette.setColor(QPalette.ColorRole.BrightText,      bright)
        palette.setColor(QPalette.ColorRole.Button,          mid)
        palette.setColor(QPalette.ColorRole.ButtonText,      text)
        palette.setColor(QPalette.ColorRole.Highlight,       accent)
        palette.setColor(QPalette.ColorRole.HighlightedText, bright)
        palette.setColor(QPalette.ColorRole.PlaceholderText, disabled)

        QApplication.instance().setPalette(palette)
        QApplication.instance().setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QMenuBar {
                background-color: #141414;
                color: #cccccc;
                border-bottom: 1px solid #333333;
                padding: 2px;
                font-size: 12px;
            }
            QMenuBar::item:selected {
                background-color: #2a2a2a;
                border-radius: 3px;
            }
            QMenu {
                background-color: #1e1e1e;
                color: #cccccc;
                border: 1px solid #444444;
                font-size: 12px;
            }
            QMenu::item:selected {
                background-color: #4a9de0;
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background: #333333;
                margin: 2px 8px;
            }
            QToolBar {
                background-color: #1a1a1a;
                border-bottom: 1px solid #333333;
                spacing: 4px;
                padding: 2px 6px;
            }
            QToolBar QToolButton {
                background-color: transparent;
                color: #aaaaaa;
                border: none;
                border-radius: 3px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QToolBar QToolButton:hover {
                background-color: #2a2a2a;
                color: #ffffff;
            }
            QToolBar QToolButton:checked {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px dotted #4a9de0;
                border-radius: 3px;
            }
            QToolBar::separator {
                width: 1px;
                background: #333333;
                margin: 4px 2px;
            }
            QDockWidget {
                color: #cccccc;
                font-size: 11px;
            }
            QDockWidget::title {
                background-color: #1a1a1a;
                border-bottom: 1px solid #333333;
                padding: 4px 8px;
                text-align: left;
            }
            QSplitter::handle {
                background-color: #333333;
            }
            QSplitter::handle:horizontal {
                width: 2px;
            }
            QSplitter::handle:vertical {
                height: 2px;
            }
            QSplitter::handle:hover {
                background-color: #4a9de0;
            }
            QStatusBar {
                background-color: #141414;
                color: #888888;
                border-top: 1px solid #333333;
                font-size: 11px;
            }
            QLabel {
                color: #cccccc;
            }
        """)

    def _on_media_dropped(self, item_id: str,
                           raw_row: int,
                           start_frame: int):
        """
        User dropped a media item onto the timeline.
        Creates all linked clips for all streams.
        """
        from ui.constants import (
            snap_row_for_clip, row_to_track_index
        )

        item = self.project.media_pool.get(item_id)
        if not item:
            item = self.media_bin.get_item(item_id)
        if not item:
            return

        # get stream info
        stream_info = getattr(
            item, '_stream_info', {
                'video_count': 1 if item.has_video else 0,
                'audio_count': 1 if item.has_audio else 0,
            }
        )

        # create all linked clips
        clips = self.project.add_linked_clips(
            item,
            drop_row=raw_row,
            start_frame=start_frame,
            stream_info=stream_info
        )

        if not clips:
            return

        # update total frames
        max_end = max(
            c.start_frame + c.duration
            for c in clips
        )
        if max_end > self.app_state.total_frames:
            self.app_state.total_frames = max_end

        # add visuals to timeline
        for clip in clips:
            self.timeline.add_clip(clip)

        self._update_title()

        # status message
        v_count = stream_info.get('video_count', 0)
        a_count = stream_info.get('audio_count', 0)
        self.status_label.setText(
            f'Added: {item.name} → '
            f'{v_count}V + {a_count}A clips linked'
        )

        # sync to playback engine
        self._update_playback_clips()



    # =========================================================
    # Menu Bar
    # =========================================================

    def _build_menu_bar(self):
        mb = self.menuBar()

        # File
        file_menu = mb.addMenu('File')
        self._add_action(file_menu, 'New Project',
                         self._on_new_project,  'Ctrl+N')
        self._add_action(file_menu, 'Open Project...',
                         self._on_open_project, 'Ctrl+O')
        file_menu.addSeparator()
        self._add_action(file_menu, 'Save',
                         self._on_save,          'Ctrl+S')
        self._add_action(file_menu, 'Save As...',
                         self._on_save_as, 'Ctrl+Shift+S')
        file_menu.addSeparator()
        self._add_action(file_menu, 'Import Media...',
                         self._on_import_media,  'Ctrl+I')
        file_menu.addSeparator()
        self._add_action(file_menu, 'Export...',
                         self._on_export,        'Ctrl+E')
        file_menu.addSeparator()
        self._add_action(file_menu, 'Exit',
                         self.close, 'Ctrl+Q')

        # Edit
        edit_menu = mb.addMenu('Edit')
        self._undo_action = self._add_action(
            edit_menu, 'Undo', self._on_undo, 'Ctrl+Z')
        self._undo_action.setEnabled(False)
        self._redo_action = self._add_action(
            edit_menu, 'Redo', self._on_redo, 'Ctrl+Y')
        self._redo_action.setEnabled(False)
        edit_menu.addSeparator()
        self._add_action(edit_menu, 'Select All',
                         self._on_select_all, 'Ctrl+A')
        self._add_action(edit_menu, 'Deselect All',
                         self._on_deselect_all, 'Ctrl+D')

        # Sequence
        seq_menu = mb.addMenu('Sequence')
        self._add_action(seq_menu, 'Sequence Settings...',
                         self._on_new_sequence)
        seq_menu.addSeparator()
        self._add_action(seq_menu, 'Add Video Track',
                         self._on_add_video_track)
        self._add_action(seq_menu, 'Add Audio Track',
                         self._on_add_audio_track)
        seq_menu.addSeparator()
        self._add_action(seq_menu, 'Render Timeline',
                         self._on_render)
        seq_menu.addSeparator()
        self._add_action(seq_menu, 'Sync Refine (eyeball first, ±90s)',
                         self._on_synchronize)

        # View
        view_menu = mb.addMenu('View')
        self._add_action(view_menu, 'Zoom In',
                         self._on_zoom_in,  '=')
        self._add_action(view_menu, 'Zoom Out',
                         self._on_zoom_out, '-')
        self._add_action(view_menu, 'Fit Timeline',
                         self._on_zoom_fit, '\\')

        # Help
        help_menu = mb.addMenu('Help')
        self._add_action(help_menu, 'About',
                         self._on_about)



    def _add_action(self, menu: QMenu, label: str,
                    slot, shortcut: str = None) -> QAction:
        action = QAction(label, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    # =========================================================
    # Toolbar
    # =========================================================

    def _build_tool_bar(self):
        tb = QToolBar('Tools', self)
        tb.setMovable(False)
        tb.setIconSize(QSize(24, 24))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        # tool buttons
        self._tool_actions = {}
        for tool_id, label, shortcut, icon_name in [
            ('select', 'Select (V)', 'V', 'arrow_select.ico'),
            ('razor',  'Razor  (C)', 'C', 'cutt.ico'),
        ]:
            action = QAction(_icon(icon_name), label, self)
            action.setShortcut(QKeySequence(shortcut))
            action.setCheckable(True)
            action.triggered.connect(
                lambda checked, t=tool_id:
                    self._on_tool_selected(t)
            )
            tb.addAction(action)
            self._tool_actions[tool_id] = action

        # select tool active by default
        self._tool_actions['select'].setChecked(True)



        tb.addSeparator()
        # transport controls moved to preview panel strip

    # =========================================================
    # Status Bar
    # =========================================================

    def _build_status_bar(self):
        sb = self.statusBar()
        self.status_label = QLabel('Ready')
        sb.addWidget(self.status_label)

        self.zoom_label = QLabel('Zoom: 1.0x')
        sb.addPermanentWidget(self.zoom_label)

        self.resolution_label = QLabel('1920 x 1080 | 29.97 fps')
        sb.addPermanentWidget(self.resolution_label)

    # =========================================================
    # Panels
    # =========================================================

    def _build_panels(self):
        """
        Layout:
        ┌─────────────────────────────────┐
        │  top splitter                   │
        │  ┌────────────┬────────────┐    │
        │  │ media bin  │  preview   │    │
        │  └────────────┴────────────┘    │
        ├─────────────────────────────────┤
        │  timeline                       │
        └─────────────────────────────────┘
       
        """
       
        # main horizontal splitter (content + effects panel)
        self.main_splitter = QSplitter(
            Qt.Orientation.Horizontal
        )
        self.main_splitter.setHandleWidth(3)

        # left content vertical splitter
        self.left_splitter = QSplitter(
            Qt.Orientation.Vertical
        )
        self.left_splitter.setHandleWidth(3)

        # top horizontal splitter (media bin + preview)
        self.top_splitter = QSplitter(
            Qt.Orientation.Horizontal
        )
        self.top_splitter.setHandleWidth(3)

        # --- Media Bin ---
        from ui.panels.media_bin import MediaBinPanel
        self.media_bin = MediaBinPanel(
            self.project, self.app_state
        )
        self.media_bin.files_dropped.connect(
            self._on_import_paths)
        self.top_splitter.addWidget(self.media_bin)

        # --- Preview + Transport Strip ---
        from ui.panels.preview import PreviewPanel
        from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QToolButton
        self.preview = PreviewPanel(self.app_state)
        self.preview.resolution_changed.connect(
            self._on_preview_resolution_changed
        )

        # Wrap preview in a container with transport strip below
        preview_container = QWidget()
        preview_vbox = QVBoxLayout(preview_container)
        preview_vbox.setContentsMargins(0, 0, 0, 0)
        preview_vbox.setSpacing(0)
        preview_vbox.addWidget(self.preview)

        # Transport strip
        transport = QWidget()
        transport.setFixedHeight(32)
        transport.setStyleSheet(
            'background: #1a1a1a; border-top: 1px solid #333;'
        )
        t_layout = QHBoxLayout(transport)
        t_layout.setContentsMargins(4, 2, 4, 2)
        t_layout.setSpacing(2)
        t_layout.addStretch()  # left stretch to center buttons

        def _tbtn(icon_name, tip, shortcut=None):
            btn = QToolButton()
            btn.setIcon(_icon(icon_name))
            btn.setIconSize(QSize(16, 16))
            btn.setFixedSize(24, 24)
            btn.setToolTip(tip)
            btn.setStyleSheet(
                'QToolButton { background: transparent; border: none; }'
                'QToolButton:hover { background: #333; border-radius: 3px; }'
                'QToolButton:pressed { background: #444; }'
            )
            if shortcut:
                btn.setShortcut(QKeySequence(shortcut))
            return btn

        btn_start = _tbtn('play_reverse_to_end.ico', 'Go to Start (Home)', 'Home')
        btn_start.clicked.connect(self._on_go_start)
        t_layout.addWidget(btn_start)

        btn_rew = _tbtn('play_reverse_step.ico', 'Rewind (J)', 'J')
        btn_rew.clicked.connect(self._on_rewind)
        t_layout.addWidget(btn_rew)

        self._play_btn = _tbtn('play.ico', 'Play/Pause (Space)', 'Space')
        self._play_btn.clicked.connect(self._on_play_pause)
        t_layout.addWidget(self._play_btn)

        btn_fwd = _tbtn('play_step.ico', 'Fast Forward (L)', 'L')
        btn_fwd.clicked.connect(self._on_fast_forward)
        t_layout.addWidget(btn_fwd)

        btn_end = _tbtn('play_to_end.ico', 'Go to End (End)', 'End')
        btn_end.clicked.connect(self._on_go_end)
        t_layout.addWidget(btn_end)

        t_layout.addStretch()  # right stretch to center buttons

        # Timecode display
        self.timecode_label = QLabel('00:00:00:00')
        self.timecode_label.setStyleSheet(
            'color: #e8e820; font-family: monospace; '
            'font-size: 13px; padding: 0 8px;'
        )
        t_layout.addWidget(self.timecode_label)

        preview_vbox.addWidget(transport)
        self.top_splitter.addWidget(preview_container)

        # top: 25% media, 75% program monitor
        self.top_splitter.setStretchFactor(0, 1)
        self.top_splitter.setStretchFactor(1, 3)

        # --- Timeline ---
        from ui.panels.timeline import TimelinePanel
        self.timeline = TimelinePanel(
            self.project, self.app_state
        )

        # wire timeline drop → main window
        # media_dropped now called directly from
        # TimelinePanel._emit_media_dropped
        
       
        # assemble left content
        self.left_splitter.addWidget(self.top_splitter)
        self.left_splitter.addWidget(self.timeline)

        # set sequence size on preview
        _seq = self.project.active_sequence
        if _seq:
            self.preview.set_sequence_size(
                _seq.settings.width,
                _seq.settings.height
            )

        # vertical proportions: 60% top / 40% timeline
        self.left_splitter.setStretchFactor(0, 3)
        self.left_splitter.setStretchFactor(1, 2)

        # --- Effects Panel ---
        self.effects_panel = EffectsPanel(self.app_state)

        # assemble main layout with effects panel
        self.main_splitter.addWidget(self.left_splitter)
        self.main_splitter.addWidget(self.effects_panel)

        # horizontal proportions: 75% content / 25% effects
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 1)

        self.setCentralWidget(self.main_splitter)



    # =========================================================
    # Signals
    # =========================================================

    def _connect_signals(self):
        self.app_state.playhead_changed.connect(
            self._on_playhead_changed
        )
        self.app_state.zoom_changed.connect(
            self._on_zoom_changed
        )
        self.app_state.selection_changed.connect(
            self._on_selection_changed
        )
        self.app_state.clip_modified.connect(
            self._on_clip_modified_preview
        )
        self.app_state.playhead_changed.connect(
            self._on_playhead_scrub
        )

    def _on_playhead_scrub(self, frame: int):
        """When playhead moves manually, show that frame."""
        if not self._playback or \
                not self._playback.is_playing:
            self._scrub_to_playhead()
            if self._playback:
                self._playback.seek(frame)

    # =========================================================
    # Command Registration
    # =========================================================

    def _register_commands(self):
        from core.commands import register_command
        register_command(
            'import_media', 'Import Media...',
            self._on_import_media,
            CommandContext.GLOBAL, 'Ctrl+I'
        )
        register_command(
            'razor_cut', 'Razor at Playhead',
            self._on_razor_cut,
            CommandContext.CLIP, 'Ctrl+K'
        )
        register_command(
            'delete_clip', 'Delete',
            self._on_delete_clip,
            CommandContext.CLIP, 'Delete'
        )
        register_command(
            'scale_to_frame', 'Scale to Frame Size',
            self._on_scale_to_frame,
            CommandContext.CLIP,
            separator_before=True
        )

        register_command(
            'link_clips', 'Link',
            self._on_link_clips,
            CommandContext.CLIP,
            separator_before=True
        )

        register_command(
            'unlink_clip', 'Unlink',
            self._on_unlink_clip,
            CommandContext.CLIP
        )

        register_command(
            'synchronize', 'Sync Refine (eyeball first, ±90s)',
            self._on_synchronize,
            CommandContext.CLIP,
            separator_before=True
        )

    # =========================================================
    # Signal Handlers
    # =========================================================

    def _on_playhead_changed(self, frame: int):
        if self.project.active_sequence:
            fps = self.project.active_sequence.settings.fps
        else:
            fps = 29.97
        tc = self.app_state.frame_to_timecode(frame, fps)
        self.timecode_label.setText(tc)

    def _on_zoom_changed(self, start: float, end: float):
        self.zoom_label.setText(
            f'Zoom: {self.app_state.zoom_level:.1f}x'
        )

    def _on_selection_changed(self, clip_ids: list):
        count = len(clip_ids)
        if count == 0:
            self.status_label.setText('Ready')
        elif count == 1:
            clip = self.project.clips.get(clip_ids[0])
            name = clip.name if clip else 'clip'
            self.status_label.setText(f'Selected: {name}')
        else:
            self.status_label.setText(
                f'{count} clips selected'
            )

    def _on_tool_selected(self, tool_id: str):
        self.app_state.active_tool = tool_id
        for tid, action in self._tool_actions.items():
            action.setChecked(tid == tool_id)

        self.status_label.setText(
            f'Tool: {tool_id.capitalize()}'
        )

    def _on_link_clips(self, **kwargs):
        selected = self.app_state.selected_clip_ids
        if len(selected) > 1:
            self.project.link_clips(selected)
            self.status_label.setText(
                f'Linked {len(selected)} clips'
            )

    def _on_unlink_clip(self, **kwargs):
        for clip_id in self.app_state.selected_clip_ids:
            self.project.unlink_clip(clip_id)
        self.status_label.setText('Unlinked')

    # =========================================================
    # File Actions
    # =========================================================

    def _on_new_project(self):
        from ui.panels.sequence_settings_dialog import SequenceSettingsDialog
        from core.track import SequenceSettings
        dlg = SequenceSettingsDialog(SequenceSettings(), parent=self)
        if dlg.exec():
            settings = dlg.get_settings()
            self.project = Project()
            seq = self.project.add_sequence(settings=settings)
            self.project.active_sequence = seq
            self.app_state.deselect_all()
            self.timeline.project = self.project
            self.media_bin.project = self.project
            self.timeline.refresh()
            self._update_title()
            self.status_label.setText('New project created')

    def _on_open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Open Project', '',
            'Cadenza Project (*.veproj)'
        )
        if not path:
            return
        try:
            from core.project_io import load_project
            project = load_project(path)
            self.project  = project
            self.app_state.total_frames = (
                project.total_frames
            )
            self.app_state.set_view(0.0, 1.0)
            # update timeline in-place
            self.timeline.project = project
            self.timeline.refresh()
            # rebuild media bin
            self.media_bin.list_widget.clear()
            for item in project.media_pool.values():
                self.media_bin.add_item(item)
            self._update_title()
            self._on_zoom_fit()
            self._update_playback_clips()
            self.status_label.setText(
                f'Opened: {path}'
            )
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                self, 'Open Failed', str(e)
            )

    def _on_save(self):
        fp = getattr(self.project, 'project_path', None)
        if fp:
            from core.project_io import save_project
            if save_project(self.project, fp):
                self._update_title()
                self.status_label.setText(
                    'Project saved'
                )
        else:
            self._on_save_as()

    def _on_save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save Project As', '',
            'Cadenza Project (*.veproj)'
        )
        if path:
            if not path.endswith('.veproj'):
                path += '.veproj'
            from core.project_io import save_project
            if save_project(self.project, path):
                self._update_title()
                self.status_label.setText(
                    f'Saved: {path}'
                )

    def _on_import_paths(self, paths: list):
        """Import a list of file paths directly (e.g. from drag/drop)."""
        if not paths:
            return
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for path in paths:
                item = self.project.import_media(path)
                self._populate_media_metadata(item)
                self.media_bin.add_item(item)
            total = max(
                (item.source_frames
                 for item in self.project.media_pool.values()),
                default=0
            )
            self.app_state.total_frames = total
            self.timeline.refresh()
            self.status_label.setText(
                f'Imported {len(paths)} file(s)')
        finally:
            QApplication.restoreOverrideCursor()

    def _on_import_media(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, 'Import Media', '',
            'Media Files ('
            '*.mp4 *.mov *.avi *.mkv *.mts '
            '*.m2ts *.wav *.mp3 *.aac *.flac '
            '*.jpg *.jpeg *.png *.bmp *.tiff *.tif)'
        )
        if not paths:
            return

        # show busy cursor while reading metadata
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
        QApplication.setOverrideCursor(
            Qt.CursorShape.WaitCursor
        )
        self.status_label.setText(
            f'Reading metadata for {len(paths)} file(s)...'
        )
        QApplication.processEvents()

        try:
            for path in paths:
                item = self.project.import_media(path)
                self.status_label.setText(
                    f'Reading: {Path(path).name}'
                )
                QApplication.processEvents()
                self._populate_media_metadata(item)
                self.media_bin.add_item(item)

            # update total duration for zoom math
            total = max(
                (item.source_frames
                 for item in
                 self.project.media_pool.values()),
                default=0
            )
            self.app_state.total_frames = total
            self.timeline.refresh()  # refit all clips to new ruler scale
            self.status_label.setText(
                f'Imported {len(paths)} file(s)'
            )
        finally:
            QApplication.restoreOverrideCursor()

    def _populate_media_metadata(self,
                                   item: MediaPoolItem):
        """
        Read file metadata using PyAV only.
        Fast — reads container headers, not frames.
        Works on files of any size instantly.
        """
        import os
        ext = os.path.splitext(item.filepath)[1].lower()
        if ext in ('.jpg', '.jpeg', '.png', '.bmp',
                    '.tiff', '.tif'):
            self._populate_image_metadata(item)
            return
        try:
            import av
            container = av.open(item.filepath)

            video_streams = container.streams.video
            audio_streams = container.streams.audio

            if video_streams:
                vs = video_streams[0]
                item.source_width  = vs.width
                item.source_height = vs.height
                # fps from stream
                r = vs.average_rate
                item.source_fps = (
                    float(r) if r else 29.97
                )
                # duration from container
                dur = container.duration
                if dur:
                    item.source_duration = (
                        dur / av.time_base
                    )
                else:
                    item.source_duration = 0.0
                # frame count from duration * fps
                item.source_frames = int(
                    item.source_duration *
                    item.source_fps
                )
                item.has_video = True
            else:
                item.has_video = False

            item.has_audio = len(audio_streams) > 0

            # Audio-only file: set source_frames from duration
            if not video_streams and audio_streams:
                dur = container.duration
                if dur:
                    item.source_duration = dur / av.time_base
                else:
                    as_ = audio_streams[0]
                    if as_.duration and as_.time_base:
                        item.source_duration = float(
                            as_.duration * as_.time_base)
                seq = self.project.active_sequence
                seq_fps = seq.settings.fps if seq else 29.97
                item.source_frames = int(
                    item.source_duration * seq_fps)
                item.source_width  = 0
                item.source_height = 0
                print(f"[Import] Audio-only: duration="
                      f"{item.source_duration:.2f}s "
                      f"frames={item.source_frames}")

            # stream info for linked clip creation
            item._stream_info = {
                'video_count': len(video_streams),
                'audio_count': len(audio_streams),
            }
            container.close()

        except Exception as e:
            # Check if it's an image file
            import os
            ext = os.path.splitext(item.filepath)[1].lower()
            if ext in ('.jpg', '.jpeg', '.png', '.bmp',
                        '.tiff', '.tif'):
                self._populate_image_metadata(item)
            else:
                print(f'Metadata error: {e}')
                item.has_video = False
                item.has_audio = True
                item._stream_info = {
                    'video_count': 0,
                    'audio_count': 1
                }



    def _populate_image_metadata(self, item):
        """
        Handle still image import — treat as 10-second video clip.
        """
        from PySide6.QtGui import QImageReader
        reader = QImageReader(item.filepath)
        size   = reader.size()
        seq    = self.project.active_sequence
        fps    = seq.settings.fps if seq else 29.97
        duration_secs = 10.0  # default 10 seconds

        item.has_video       = True
        item.has_audio       = False
        item.source_width    = size.width()  if size.isValid() else 1920
        item.source_height   = size.height() if size.isValid() else 1080
        item.source_fps      = fps
        item.source_duration = duration_secs
        item.source_frames   = int(duration_secs * fps)
        item._stream_info    = {
            'video_count': 1,
            'audio_count': 0,
            'is_image':    True,
        }
        print(f"[Import] Image: {item.name} "
              f"{item.source_width}x{item.source_height} "
              f"→ {duration_secs}s clip")

    # =========================================================
    # Edit Actions
    # =========================================================

    def _on_undo(self):
        from core.undo import undo_stack
        if undo_stack.can_undo:
            desc = undo_stack.undo_description
            undo_stack.undo()
            self.timeline.refresh()
            self._update_playback_clips()
            self._scrub_to_playhead()
            self.status_label.setText(f'Undo: {desc}')
            self._update_undo_actions()
        else:
            self.status_label.setText('Nothing to undo')

    def _on_redo(self):
        from core.undo import undo_stack
        if undo_stack.can_redo:
            desc = undo_stack.redo_description
            undo_stack.redo()
            self.timeline.refresh()
            self._update_playback_clips()
            self._scrub_to_playhead()
            self.status_label.setText(f'Redo: {desc}')
            self._update_undo_actions()
        else:
            self.status_label.setText('Nothing to redo')

    def _update_undo_actions(self):
        """Update Edit menu Undo/Redo labels and enabled state."""
        from core.undo import undo_stack
        if hasattr(self, '_undo_action'):
            can = undo_stack.can_undo
            self._undo_action.setEnabled(can)
            self._undo_action.setText(
                f"Undo {undo_stack.undo_description}" if can else "Undo"
            )
        if hasattr(self, '_redo_action'):
            can = undo_stack.can_redo
            self._redo_action.setEnabled(can)
            self._redo_action.setText(
                f"Redo {undo_stack.redo_description}" if can else "Redo"
            )

    def _on_select_all(self):
        for clip_id in self.project.clips:
            self.app_state.select_clip(
                clip_id, add_to_selection=True
            )

    def _on_deselect_all(self):
        self.app_state.deselect_all()

    # =========================================================
    # Sequence Actions
    # =========================================================

    def _on_add_video_track(self):
        seq = self.project.active_sequence
        if not seq:
            return
        from core.track import Track, TrackType
        idx = len(seq.video_tracks)
        seq.video_tracks.append(Track(TrackType.VIDEO, idx))
        self.timeline.refresh()
        self.status_label.setText(f'Added V{idx+1}')

    def _on_add_audio_track(self):
        seq = self.project.active_sequence
        if not seq:
            return
        from core.track import Track, TrackType
        idx = len(seq.audio_tracks)
        seq.audio_tracks.append(Track(TrackType.AUDIO, idx))
        self.timeline.refresh()
        self.status_label.setText(f'Added A{idx+1}')

    def _on_new_sequence(self):
        """Open sequence settings dialog for current sequence."""
        from ui.panels.sequence_settings_dialog import SequenceSettingsDialog
        seq = self.project.active_sequence
        if not seq:
            return
        dlg = SequenceSettingsDialog(seq.settings, parent=self)
        if dlg.exec():
            seq.settings = dlg.get_settings()
            self.timeline.refresh()
            self.status_label.setText('Sequence settings updated')

    def _on_render(self):
        self.status_label.setText('Render — coming soon')

    def _on_synchronize(self):
        """Synchronize selected clips by audio."""
        selected = self.app_state.selected_clip_ids
        if len(selected) < 2:
            self.status_label.setText(
                'Select 2 or more clips to synchronize'
            )
            return
        seq = self.project.active_sequence
        if not seq:
            return
        from ui.panels.sync_dialog import SyncDialog
        dlg = SyncDialog(
            self.project, seq, selected, parent=self
        )
        if dlg.exec():
            # Timeline refresh after sync
            self.timeline.refresh()
            self._update_playback_clips()
            self._scrub_to_playhead()
            self.status_label.setText('Sync complete')

    # =========================================================
    # View Actions
    # =========================================================

    def _on_zoom_fit(self):
        """Zoom timeline to fit all clips with small margin."""
        clips = list(self.project.clips.values())
        if not clips:
            return
        total = self.app_state.total_frames
        if total <= 0:
            return
        min_f = min(c.start_frame for c in clips)
        max_f = max(c.start_frame + c.duration for c in clips)
        margin = (max_f - min_f) * 0.05  # 5% margin each side
        start_norm = max(0.0, (min_f - margin) / total)
        end_norm   = min(1.0, (max_f + margin) / total)
        self.app_state.set_view(start_norm, end_norm)

    def _zoom_anchor(self) -> float:
        """Normalized position to zoom around — playhead if visible,
        else center of current view."""
        total = self.app_state.total_frames
        if total <= 0:
            return (self.app_state.view_start +
                    self.app_state.view_end) / 2
        ph_norm = self.app_state.playhead_frame / total
        # Use playhead if it's in the visible range
        if (self.app_state.view_start <= ph_norm
                <= self.app_state.view_end):
            return ph_norm
        return (self.app_state.view_start +
                self.app_state.view_end) / 2

    def _on_zoom_in(self):
        self.app_state.zoom_in_at_position(
            self._zoom_anchor())

    def _on_zoom_out(self):
        self.app_state.zoom_out_at_position(
            self._zoom_anchor())

    def _on_zoom_fit(self):
        clips = list(self.project.clips.values())
        if clips:
            min_f = min(c.start_frame for c in clips)
            max_f = max(c.start_frame + c.duration
                        for c in clips)
            # Always update total_frames to actual clip extent
            self.app_state.total_frames = max_f
            if max_f > 0:
                margin = (max_f - min_f) * 0.05
                start  = max(0.0, (min_f - margin) / max_f)
                end    = min(1.0, (max_f + margin) / max_f)
                # Force set_view even if values unchanged
                # so zoom_changed fires and canvases redraw
                self.app_state._view_start = -1  # force emit
                self.app_state.set_view(start, end)
                return
        self.app_state._view_start = -1
        self.app_state.set_view(0.0, 1.0)

    # =========================================================
    # Clip Actions
    # =========================================================

    def _on_preview_resolution_changed(
            self, w: int, h: int):
        """Update decoder output size for all decoders."""
        if (getattr(self, '_playback', None) and
                self._playback._compositor):
            comp = self._playback._compositor
            for dec in comp._decoders.values():
                if dec and hasattr(
                    dec, 'set_output_size'
                ):
                    dec.set_output_size(w, h)
            comp.invalidate_cache()
        self.status_label.setText(
            f'Preview: {w}×{h}'
        )

    def _on_razor_cut(self):
        """Razor is handled directly in TimelineView
        mousePressEvent — nothing needed here."""
        pass

    def _on_delete_clip(self, **kwargs):
        """Delete selected clips and their link groups."""
        from core.undo import (undo_stack, DeleteClipCommand,
                                CompoundCommand)
        to_delete = set()

        for clip_id in self.app_state.selected_clip_ids:
            to_delete.add(clip_id)
            for linked in self.project.get_linked_clips(clip_id):
                to_delete.add(linked.id)

        if not to_delete:
            return

        clips = [self.project.clips[cid]
                 for cid in to_delete
                 if cid in self.project.clips]

        with undo_stack.compound(
                f"Delete {len(clips)} clip(s)"):
            for clip in clips:
                cmd = DeleteClipCommand(
                    self.project, clip,
                    timeline_add_fn=self.timeline.add_clip,
                    timeline_remove_fn=self.timeline.remove_clip
                )
                # Execute manually — compound suppresses redo()
                self.project.remove_clip(clip.id)
                self.timeline.remove_clip(clip.id)
                undo_stack._compound.add(cmd)

        self.app_state.deselect_all()
        # Recalculate total_frames after deletion and reset view
        if self.project.clips:
            new_total = max(
                c.start_frame + c.duration
                for c in self.project.clips.values()
            )
            self.app_state.total_frames = new_total
            # Reset view to show full extent
            self.app_state.set_view(0.0, 1.0)
        self._update_playback_clips()
        self._update_undo_actions()
        self._update_title()
        self.status_label.setText(
            f'Deleted {len(to_delete)} clip(s)'
        )

    def _on_scale_to_frame(self):
        seq = self.project.active_sequence
        if not seq:
            return
        for clip_id in self.app_state.selected_clip_ids:
            clip = self.project.clips.get(clip_id)
            if clip:
                clip.scale_to_frame(
                    seq.settings.width,
                    seq.settings.height
                )
        self.app_state.clip_modified.emit(
            self.app_state.selected_clip_ids[0]
            if self.app_state.selected_clip_ids else ''
        )

    # =========================================================
    # Playback Actions (stubs — wired later)
    # =========================================================

    def _on_play_pause(self):
        if not self._playback:
            self._init_playback()
        if self._playback:
            self._playback.toggle()
            playing = self._playback.is_playing
            if hasattr(self, '_play_btn'):
                self._play_btn.setIcon(
                    _icon('pause.ico') if playing
                    else _icon('play.ico')
                )
            self.status_label.setText(
                'Playing' if playing else 'Paused'
            )


    def _on_rewind(self):
        self.app_state.playhead_frame = max(
            0, self.app_state.playhead_frame - 30
        )

    def _on_fast_forward(self):
        self.app_state.playhead_frame += 30

   
    def _on_go_start(self):
        if self._playback:
            self._playback.pause()
        self.app_state.playhead_frame = 0
        self._scrub_to_playhead()

    def _on_go_end(self):
        if self._playback:
            self._playback.pause()
        self.app_state.playhead_frame = (
            self.app_state.total_frames
        )

    # =========================================================
    # Helpers
    # =========================================================

    def _update_title(self):
        dirty = ' •' if self.project.is_dirty else ''
        self.setWindowTitle(
            f'Cadenza — {self.project.name}{dirty}'
        )

    def _on_about(self):
        self.status_label.setText(
            'Cadenza v1.0 — built with PySide6 + PyTorch'
        )

    def closeEvent(self, event):
        if self.project.is_dirty:
            # TODO: ask to save
            pass
        event.accept()

    # playback functions
    # =========================================================
    # Export
    # =========================================================

    def _on_export(self):
        """Open export dialog."""
        from ui.panels.export_dialog import ExportDialog
        from render.export_config import ExportConfig

        seq = self.project.active_sequence
        if not seq:
            return

        if not self.project.clips:
            self.status_label.setText(
                'Nothing to export — add clips first.'
            )
            return

        # build default config from sequence settings
        config = ExportConfig(
            width        = 1920,
            height       = 1080,
            fps          = seq.settings.fps,
            sample_rate  = seq.settings.sample_rate,
            channels     = seq.settings.audio_channels,
        )

        self._export_dialog = ExportDialog(
            config, parent=self
        )
        self._export_dialog.export_requested.connect(
            self._start_export
        )
        self._export_dialog.rejected.connect(
            self._cancel_export
        )
        self._export_dialog.show()

    def _start_export(self, config):
        """Launch ExportThread with given config."""
        from render.exporter import ExportThread

        seq = self.project.active_sequence
        if not seq or not self._playback:
            return

        # pause playback during export
        if self._playback.is_playing:
            self._playback.pause()

        clips = list(self.project.clips.values())

        self._export_thread = ExportThread(
            config      = config,
            clips       = clips,
            sequence    = seq,
            compositor  = self._playback._compositor,
            parent      = self
        )
        self._export_thread.progress.connect(
            self._export_dialog.set_progress
        )
        self._export_thread.status.connect(
            self._export_dialog.set_status
        )
        self._export_thread.finished.connect(
            self._on_export_finished
        )
        self._export_thread.error.connect(
            self._on_export_error
        )
        self._export_thread.start()

    def _cancel_export(self):
        """Cancel in-progress export."""
        if hasattr(self, '_export_thread'):
            self._export_thread.cancel()
            self._export_thread.wait(3000)

    def _on_export_finished(self, path: str):
        self.status_label.setText(
            f'Export complete: {path}'
        )
        if hasattr(self, '_export_dialog'):
            self._export_dialog.set_finished(path)

    def _on_export_error(self, msg: str):
        self.status_label.setText(f'Export error: {msg}')
        if hasattr(self, '_export_dialog'):
            self._export_dialog.set_error(msg)

    def _init_playback(self):
        """Initialize playback engine."""
        from ui.playback import PlaybackEngine
        seq = self.project.active_sequence
        if seq:
            self._playback = PlaybackEngine(
                self.app_state, seq, parent=self
            )
            self._playback.frame_ready.connect(
                self.preview.display_frame
            )
            self._update_playback_clips()
            # Warm up CUDA kernels in background so first real
            # composite is instant. PyTorch JIT-compiles kernels
            # on first use — this fires that compilation now.
            from PySide6.QtCore import QTimer
            QTimer.singleShot(500, self._cuda_warmup)

    def _cuda_warmup(self):
        """Fire dummy GPU ops to JIT-compile CUDA kernels."""
        import threading
        def _warm():
            try:
                import torch
                import torch.nn.functional as F
                if not torch.cuda.is_available():
                    return
                # Simulate exactly what compositor does:
                # alloc canvas, permute, interpolate, clamp, byte, cpu
                dummy = torch.zeros(
                    540, 960, 3,
                    dtype=torch.float32, device='cuda'
                )
                t = dummy.permute(2, 0, 1).unsqueeze(0) / 255.0
                t = F.interpolate(
                    t, size=(540, 960),
                    mode='bilinear', align_corners=False
                )
                t.squeeze(0).permute(1, 2, 0).clamp(0, 255).byte().cpu()
                torch.cuda.synchronize()
            except Exception:
                pass
        threading.Thread(target=_warm, daemon=True).start()

    def _update_playback_clips(self):
        """Sync clip list to playback engine."""
        if self._playback:
            clips = list(self.project.clips.values())
            self._playback.set_clips(
                clips,
                sequence=self.project.active_sequence
            )
            # Pre-warm decoders in background so first scrub
            # and first parameter change are instant.
            self._prewarm_decoders(clips)

    def _prewarm_decoders(self, clips):
        """Open decoders for all video clips in a background thread."""
        import threading, time
        compositor = (self._playback._compositor
                      if self._playback else None)
        if compositor is None:
            return

        video_paths = list({
            c.filepath for c in clips if c.has_video
        })
        if not video_paths:
            return


        def _warm():
            for path in video_paths:
                try:
                    dec = compositor.get_decoder(path)
                    if dec:
                        # Decode frame 0 to open container
                        dec.get_frame(0)
                        # Also decode current playhead frame so
                        # the first scrub after drop hits the cache
                        ph = self.app_state.playhead_frame
                        if ph > 0:
                            # find the clip for this path to get
                            # the correct source frame mapping
                            for clip in clips:
                                if clip.has_video and clip.filepath == path:
                                    from core.clip_renderer import ClipRenderer
                                    renderer = ClipRenderer(clip)
                                    if renderer.is_active_at(ph):
                                        src = renderer.timeline_to_source_frame(ph)
                                        src = max(0, min(src, dec.frame_count - 1))
                                        dec.get_frame(src)
                                        break
                except Exception as e:
                    pass  # prewarm failure is non-fatal

        t = threading.Thread(target=_warm, daemon=True)
        t.start()

    def _on_clip_modified_preview(self, clip_id: str = None):
        """Force preview refresh when a clip effect changes."""
        if self._playback and self._playback._compositor:
            self._playback._compositor.invalidate_cache()
        self._scrub_to_playhead()

    def _scrub_to_playhead(self):
        if not self.project.clips:
            return
        if self._playback is None:
            self._init_playback()
        frame = self.app_state.playhead_frame
        clips = list(self.project.clips.values())
        if self._playback and self._playback._compositor:
            try:
                tensor = (
                    self._playback._compositor.composite_frame(
                        clips, frame,
                        sequence=self.project.active_sequence,
                        use_cache=False
                    )
                )
                self.preview.display_frame(tensor)
            except Exception as e:
                print(f"Scrub error: {e}")

    def _scrub_to_playhead_OLD(self):
        """Show frame at current playhead position."""
        print(f"DEBUG: _scrub_to_playhead called")
        if not self.project.clips:
            print(f"DEBUG: No clips found in project.clips")
            return
        if self._playback is None:
            print(f"DEBUG: Initializing playback")
            self._init_playback()
        frame = self.app_state.playhead_frame
        print(f"DEBUG: Playhead frame = {frame}")
        clips = list(self.project.clips.values())
        print(f"DEBUG: Found {len(clips)} clips")
        if self._playback and self._playback._compositor:
            try:
                tensor = (
                    self._playback
                    ._compositor
                    .composite_frame(
                        clips, frame,
                        sequence=self.project.active_sequence
                    )
                )
                print(f"DEBUG: Compositor returned tensor shape: {tensor.shape}")
                self.preview.display_frame(tensor)
                print(f"DEBUG: Frame displayed successfully")
            except Exception as e:
                print(f"Scrub error: {e}")