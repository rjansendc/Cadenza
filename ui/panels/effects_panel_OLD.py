"""
Effects Panel - Professional parameter editing interface.

Displays effects for the currently selected clip with:
- Hierarchical tree (Video/Audio sections)
- Real-time parameter controls (sliders, checkboxes, dropdowns)
- Keyframe diamonds (placeholder)
- Reset buttons
- Parameter linking (Position X/Y, etc.)
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox, QLabel, QPushButton,
    QSlider, QFrame, QSizePolicy, QScrollArea
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QPalette, QColor, QIcon

from core.clip import Clip
from core.effects import EffectBase, StreamType, ParamType
from ui.app_state import AppState


class ParameterWidget(QWidget):
    """
    Single parameter control widget with label, input, keyframe, reset.
    Auto-generates appropriate input based on ParamType.
    """
    
    value_changed = Signal(str, object)  # param_name, value
    
    def __init__(self, param_def, effect, parent=None):
        super().__init__(parent)
        self.param_def = param_def
        self.effect = effect
        self._updating = False  # Prevent recursion
        
        self.setFixedHeight(26)
        self._build_ui()
        self._update_from_effect()
        
    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 2, 8, 2)
        layout.setSpacing(6)
        
        # Parameter label
        label = QLabel(self.param_def.label)
        label.setFixedWidth(80)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        label.setStyleSheet("""
            QLabel {
                color: #cccccc;
                font-size: 11px;
                font-weight: 500;
            }
        """)
        layout.addWidget(label)
        
        # Input control based on parameter type
        self.input_widget = self._create_input_widget()
        layout.addWidget(self.input_widget)
        
        # Unit label (if any)
        if self.param_def.unit:
            unit_label = QLabel(self.param_def.unit)
            unit_label.setFixedWidth(20)
            unit_label.setStyleSheet("""
                QLabel {
                    color: #888888;
                    font-size: 10px;
                }
            """)
            layout.addWidget(unit_label)
        
        # Keyframe diamond (placeholder)
        keyframe_btn = QPushButton("◊")
        keyframe_btn.setFixedSize(16, 16)
        keyframe_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #666666;
                border: none;
                font-size: 10px;
            }
            QPushButton:hover {
                color: #aaaaaa;
            }
        """)
        keyframe_btn.setToolTip("Add keyframe (not implemented)")
        layout.addWidget(keyframe_btn)
        
        # Reset button
        reset_btn = QPushButton("⟲")
        reset_btn.setFixedSize(16, 16)
        reset_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #666666;
                border: none;
                font-size: 12px;
            }
            QPushButton:hover {
                color: #aaaaaa;
                background: #333333;
                border-radius: 8px;
            }
        """)
        reset_btn.setToolTip(f"Reset to {self.param_def.default}")
        reset_btn.clicked.connect(self._reset_value)
        layout.addWidget(reset_btn)
        
    def _create_input_widget(self):
        """Create appropriate input widget based on parameter type."""
        param_type = self.param_def.param_type
        
        if param_type == ParamType.FLOAT:
            widget = QDoubleSpinBox()
            widget.setRange(self.param_def.minimum, self.param_def.maximum)
            widget.setSingleStep(self.param_def.step)
            widget.setDecimals(2)
            widget.valueChanged.connect(self._on_value_changed)
            widget.setStyleSheet(self._get_spinbox_style())
            return widget
            
        elif param_type == ParamType.INT:
            widget = QSpinBox()
            widget.setRange(int(self.param_def.minimum), int(self.param_def.maximum))
            widget.valueChanged.connect(self._on_value_changed)
            widget.setStyleSheet(self._get_spinbox_style())
            return widget
            
        elif param_type == ParamType.BOOL:
            widget = QCheckBox()
            widget.toggled.connect(self._on_value_changed)
            widget.setStyleSheet(self._get_checkbox_style())
            return widget
            
        elif param_type == ParamType.CHOICE:
            widget = QComboBox()
            for choice in self.param_def.choices:
                widget.addItem(choice)
            widget.currentTextChanged.connect(self._on_value_changed)
            widget.setStyleSheet(self._get_combobox_style())
            return widget
            
        else:
            # Default to label
            widget = QLabel("N/A")
            widget.setStyleSheet("color: #666666; font-size: 10px;")
            return widget
    
    def _get_spinbox_style(self):
        return """
            QDoubleSpinBox, QSpinBox {
                background: #2a2a2a;
                color: #cccccc;
                border: 1px solid #444444;
                border-radius: 3px;
                padding: 2px 4px;
                font-size: 11px;
                min-width: 60px;
            }
            QDoubleSpinBox:focus, QSpinBox:focus {
                border-color: #4a9de0;
            }
            QDoubleSpinBox:hover, QSpinBox:hover {
                background: #333333;
            }
        """
    
    def _get_checkbox_style(self):
        return """
            QCheckBox {
                color: #cccccc;
                font-size: 11px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #444444;
                border-radius: 3px;
                background: #2a2a2a;
            }
            QCheckBox::indicator:hover {
                background: #333333;
                border-color: #666666;
            }
            QCheckBox::indicator:checked {
                background: #4a9de0;
                border-color: #4a9de0;
            }
        """
    
    def _get_combobox_style(self):
        return """
            QComboBox {
                background: #2a2a2a;
                color: #cccccc;
                border: 1px solid #444444;
                border-radius: 3px;
                padding: 2px 4px;
                font-size: 11px;
                min-width: 80px;
            }
            QComboBox:focus {
                border-color: #4a9de0;
            }
            QComboBox:hover {
                background: #333333;
            }
            QComboBox QAbstractItemView {
                background: #2a2a2a;
                color: #cccccc;
                selection-background-color: #4a9de0;
                border: 1px solid #444444;
            }
        """
    
    def _on_value_changed(self, value):
        """Handle input value changes."""
        if self._updating:
            return
            
        # Store value in effect
        self.effect.set(self.param_def.name, value)
        
        # Emit signal for preview update
        self.value_changed.emit(self.param_def.name, value)
    
    def _reset_value(self):
        """Reset parameter to default value."""
        default = self.param_def.default
        self.effect.set(self.param_def.name, default)
        self._update_from_effect()
        self.value_changed.emit(self.param_def.name, default)
    
    def _update_from_effect(self):
        """Update widget display from effect value."""
        self._updating = True
        try:
            value = self.effect.get(self.param_def.name)
            if value is None:
                value = self.param_def.default
            
            if isinstance(self.input_widget, (QDoubleSpinBox, QSpinBox)):
                self.input_widget.setValue(value)
            elif isinstance(self.input_widget, QCheckBox):
                self.input_widget.setChecked(value)
            elif isinstance(self.input_widget, QComboBox):
                index = self.input_widget.findText(str(value))
                if index >= 0:
                    self.input_widget.setCurrentIndex(index)
        finally:
            self._updating = False


class EffectSectionWidget(QWidget):
    """
    Widget for one effect (e.g., Motion) with expand/collapse and parameters.
    """
    
    parameter_changed = Signal(str, str, object)  # effect_id, param_name, value
    
    def __init__(self, effect: EffectBase, parent=None):
        super().__init__(parent)
        self.effect = effect
        self.expanded = True
        self.parameter_widgets = []
        
        self._build_ui()
        
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        
        # Header with expand/collapse button and effect name
        header = QWidget()
        header.setFixedHeight(28)
        header.setStyleSheet("""
            QWidget {
                background: #333333;
                border-bottom: 1px solid #444444;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 4, 8, 4)
        
        # Expand/collapse button
        self.expand_btn = QPushButton("▼" if self.expanded else "▶")
        self.expand_btn.setFixedSize(16, 16)
        self.expand_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #aaaaaa;
                border: none;
                font-size: 10px;
            }
            QPushButton:hover {
                color: #ffffff;
            }
        """)
        self.expand_btn.clicked.connect(self._toggle_expand)
        header_layout.addWidget(self.expand_btn)
        
        # Effect name
        name_label = QLabel(self.effect.label)
        name_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 12px;
                font-weight: 600;
            }
        """)
        header_layout.addWidget(name_label)
        header_layout.addStretch()
        
        # Enable/disable checkbox
        self.enabled_checkbox = QCheckBox()
        self.enabled_checkbox.setChecked(self.effect.enabled)
        self.enabled_checkbox.toggled.connect(self._on_enabled_changed)
        self.enabled_checkbox.setStyleSheet("""
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border: 1px solid #666666;
                border-radius: 3px;
                background: #2a2a2a;
            }
            QCheckBox::indicator:checked {
                background: #4a9de0;
                border-color: #4a9de0;
            }
        """)
        header_layout.addWidget(self.enabled_checkbox)
        
        layout.addWidget(header)
        
        # Parameters container
        self.params_widget = QWidget()
        self.params_layout = QVBoxLayout(self.params_widget)
        self.params_layout.setContentsMargins(0, 0, 0, 0)
        self.params_layout.setSpacing(1)
        
        # Create parameter widgets
        self._create_parameter_widgets()
        
        layout.addWidget(self.params_widget)
        
        # Set initial expand state
        self.params_widget.setVisible(self.expanded)
        
    def _create_parameter_widgets(self):
        """Create parameter input widgets."""
        param_defs = self.effect.param_defs()
        
        for param_def in param_defs:
            # Skip crop parameters for now (grayed out as requested)
            if 'crop' in param_def.name.lower():
                continue
                
            # Create separator if needed
            if param_def.separator_before:
                separator = QFrame()
                separator.setFrameShape(QFrame.Shape.HLine)
                separator.setStyleSheet("""
                    QFrame {
                        color: #444444;
                        background-color: #444444;
                        margin: 4px 20px;
                    }
                """)
                self.params_layout.addWidget(separator)
            
            # Create parameter widget
            param_widget = ParameterWidget(param_def, self.effect)
            param_widget.value_changed.connect(
                lambda name, value, eid=self.effect.id: 
                self.parameter_changed.emit(eid, name, value)
            )
            self.parameter_widgets.append(param_widget)
            self.params_layout.addWidget(param_widget)
    
    def _toggle_expand(self):
        """Toggle expand/collapse state."""
        self.expanded = not self.expanded
        self.expand_btn.setText("▼" if self.expanded else "▶")
        self.params_widget.setVisible(self.expanded)
    
    def _on_enabled_changed(self, enabled):
        """Handle effect enable/disable."""
        self.effect.enabled = enabled
        # Emit parameter change to trigger preview update
        self.parameter_changed.emit(self.effect.id, '_enabled', enabled)


class EffectsPanel(QWidget):
    """
    Main Effects Panel widget showing effects for selected clip(s).
    """
    
    def __init__(self, app_state: AppState, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.current_clip = None
        self.effect_widgets = []
        
        # Debounce timer for preview updates — must have parent
        # so Qt owns it and it fires reliably on the main thread
        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self._request_preview_update)
        self._scrub_pending = False
        
        self._build_ui()
        self._connect_signals()
        
    def _build_ui(self):
        self.setMinimumWidth(280)
        self.setStyleSheet("""
            EffectsPanel {
                background-color: #1a1a1a;
                border-left: 1px solid #333333;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header
        header = QWidget()
        header.setFixedHeight(32)
        header.setStyleSheet("""
            QWidget {
                background: #2a2a2a;
                border-bottom: 1px solid #444444;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 6, 12, 6)
        
        title = QLabel("Effect Controls")
        title.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 13px;
                font-weight: 600;
            }
        """)
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        layout.addWidget(header)
        
        # Scroll area for effects
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: #1a1a1a;
            }
            QScrollBar:vertical {
                background: #2a2a2a;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #555555;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #666666;
            }
        """)
        
        self.effects_widget = QWidget()
        self.effects_layout = QVBoxLayout(self.effects_widget)
        self.effects_layout.setContentsMargins(0, 8, 0, 8)
        self.effects_layout.setSpacing(2)
        
        scroll_area.setWidget(self.effects_widget)
        layout.addWidget(scroll_area)
        
        # Initial state
        self._show_no_selection()
        
    def _connect_signals(self):
        """Connect to app state signals."""
        self.app_state.selection_changed.connect(self._on_selection_changed)
        self.app_state.clip_modified.connect(self._on_clip_modified)

    def _on_clip_modified(self, clip_id: str):
        """Refresh Effects panel when clip properties change externally
        (e.g. opacity envelope dragged on the timeline clip)."""
        if self.current_clip is None:
            return
        if clip_id != self.current_clip.id:
            return
        # Re-sync envelope values into effect params without
        # rebuilding all the widgets — just update the spinboxes.
        for effect in self.current_clip.effect_stack:
            if effect.id == 'opacity':
                env = self.current_clip.envelopes.get('opacity')
                if env is not None:
                    effect.set('opacity', round(env.default_value * 100.0, 2))
            elif effect.id == 'volume':
                env = self.current_clip.envelopes.get('volume')
                if env is not None:
                    effect.set('volume', round(env.default_value * 100.0, 2))
                effect.set('muted', self.current_clip.muted)
            elif effect.id == 'pan':
                env = self.current_clip.envelopes.get('pan')
                if env is not None:
                    effect.set('pan', round(env.default_value * 100.0, 2))
        # Refresh each parameter widget display
        for effect_widget in self.effect_widgets:
            for param_widget in effect_widget.parameter_widgets:
                param_widget._update_from_effect()
        
    def _on_selection_changed(self, clip_ids=None):
        """Handle clip selection changes."""
        ids = self.app_state.selected_clip_ids
        if len(ids) == 1:
            # find clip from mainwindow project
            main = self.window()
            clip = None
            if hasattr(main, 'project'):
                clip = main.project.clips.get(ids[0])
            if clip:
                self.current_clip = clip
                self._show_clip_effects(clip)
        else:
            # Don't clear the panel when selection is lost —
            # clicking on the ruler/timeline background fires
            # deselect_all() which would destroy all the effect
            # widgets and break their signal connections.
            # Only clear if no clip was ever shown.
            if self.current_clip is None:
                self._show_no_selection()
            # If a clip is already shown, leave it visible.
    
    def _show_clip_effects(self, clip: Clip):
        """Display effects for the given clip."""
        # Sync clip's envelope/native values INTO effect params
        # so the UI displays what the compositor is actually using.
        for effect in clip.effect_stack:
            if effect.id == 'opacity':
                env = clip.envelopes.get('opacity')
                if env is not None:
                    # Show the flat default value (envelope's base level)
                    effect.set('opacity', round(env.default_value * 100.0, 2))
            elif effect.id == 'volume':
                env = clip.envelopes.get('volume')
                if env is not None:
                    effect.set('volume', round(env.default_value * 100.0, 2))
                effect.set('muted', clip.muted)
            elif effect.id == 'pan':
                env = clip.envelopes.get('pan')
                if env is not None:
                    effect.set('pan', round(env.default_value * 100.0, 2))
        # Clear existing widgets
        self._clear_effects()
        
        # Group effects by stream type
        video_effects = []
        audio_effects = []
        
        for effect in clip.effect_stack:
            if effect.stream_type == StreamType.VIDEO or effect.stream_type == StreamType.ANY:
                video_effects.append(effect)
            if effect.stream_type == StreamType.AUDIO or effect.stream_type == StreamType.ANY:
                audio_effects.append(effect)
        
        # Add Video section
        if video_effects and clip.has_video:
            video_header = self._create_section_header("Video")
            self.effects_layout.addWidget(video_header)
            
            for effect in video_effects:
                effect_widget = EffectSectionWidget(effect)
                effect_widget.parameter_changed.connect(self._on_parameter_changed)
                self.effect_widgets.append(effect_widget)
                self.effects_layout.addWidget(effect_widget)
        
        # Add Audio section  
        if audio_effects and clip.has_audio:
            audio_header = self._create_section_header("Audio")
            self.effects_layout.addWidget(audio_header)
            
            for effect in audio_effects:
                effect_widget = EffectSectionWidget(effect)
                effect_widget.parameter_changed.connect(self._on_parameter_changed)
                self.effect_widgets.append(effect_widget)
                self.effects_layout.addWidget(effect_widget)
        
        self.effects_layout.addStretch()
    
    def _show_no_selection(self):
        """Show message when no clip is selected."""
        self._clear_effects()
        
        message = QLabel("Select a clip to view its effects")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setStyleSheet("""
            QLabel {
                color: #666666;
                font-size: 12px;
                padding: 40px;
            }
        """)
        self.effects_layout.addWidget(message)
        self.effects_layout.addStretch()
    
    def _create_section_header(self, title):
        """Create a section header (Video/Audio)."""
        header = QWidget()
        header.setFixedHeight(24)
        header.setStyleSheet("""
            QWidget {
                background: #444444;
                border-top: 1px solid #555555;
                border-bottom: 1px solid #333333;
            }
        """)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(12, 4, 12, 4)
        
        # Icon based on section type
        icon = "📹" if title == "Video" else "🔊"
        
        label = QLabel(f"{icon} {title}")
        label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 11px;
                font-weight: 600;
            }
        """)
        layout.addWidget(label)
        layout.addStretch()
        
        return header
    
    def _clear_effects(self):
        """Clear all effect widgets."""
        while self.effects_layout.count():
            child = self.effects_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        self.effect_widgets.clear()
    
    def _on_parameter_changed(self, effect_id, param_name, value):
        """Handle parameter value changes.

        Writes opacity/volume/mute through to the clip's native
        fields so the compositor and audio mixer stay in sync.
        Pushes undoable commands to the undo stack.
        """
        from core.undo import (undo_stack, SetOpacityCommand,
                                SetVolumeCommand, SetMutedCommand,
                                SetEffectParamCommand)

        clip = self.current_clip
        if clip is not None:
            if effect_id == 'opacity' and param_name == 'opacity':
                old = clip.get_opacity_at(0)
                clip.set_opacity(float(value) / 100.0)
                undo_stack.push(SetOpacityCommand(
                    clip, old, float(value) / 100.0
                ))
            elif effect_id == 'volume' and param_name == 'volume':
                old = clip.get_volume_at(0)
                clip.set_volume(float(value) / 100.0)
                undo_stack.push(SetVolumeCommand(
                    clip, old, float(value) / 100.0
                ))
            elif effect_id == 'volume' and param_name == 'muted':
                old = clip.muted
                clip.muted = bool(value)
                undo_stack.push(SetMutedCommand(clip, old, bool(value)))
                self.app_state.clip_modified.emit(clip.id)
            elif effect_id == 'pan' and param_name == 'pan':
                # PanEffect: -100 to 100% → clip.set_pan wants -1.0 to 1.0
                old_pan = clip.envelopes.get('pan')
                old_val = old_pan.default_value if old_pan else 0.0
                clip.set_pan(float(value) / 100.0)
                undo_stack.push(SetEffectParamCommand(
                    clip, 'pan', 'pan', old_val, float(value) / 100.0
                ))
            else:
                # Generic effect param (scale, rotation, position, etc.)
                fx = clip.get_effect(effect_id)
                if fx is not None:
                    old = fx.get(param_name)
                    undo_stack.push(SetEffectParamCommand(
                        clip, effect_id, param_name, old, value
                    ))

        # Update undo menu labels
        main_window = self.window()
        if hasattr(main_window, '_update_undo_actions'):
            main_window._update_undo_actions()

        # Invalidate compositor cache so new values are rendered
        main_window = self.window()
        if (hasattr(main_window, '_playback') and
                main_window._playback and
                main_window._playback._compositor):
            main_window._playback._compositor.invalidate_cache()

        # Debounce — restart timer on every change, fire once settled.
        self.update_timer.stop()
        self.update_timer.start(80)

    def _request_preview_update(self):
        """Request preview panel to update with new effect values."""
        if self._scrub_pending:
            self.update_timer.start(80)
            return
        main_window = self.window()
        if hasattr(main_window, '_scrub_to_playhead'):
            self._scrub_pending = True
            try:
                main_window._scrub_to_playhead()
            finally:
                self._scrub_pending = False
