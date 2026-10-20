"""
In and out points, and exporting the span between them.

Export's "In / Out points" option was a disabled placeholder — the
radio would not select, because there was nothing behind it: Cadenza
had no in or out points anywhere. No command, no keys, nothing drawn
on the ruler.

The back half had been working all along. ExportConfig carries
start_frame and end_frame and the exporter seeks to one and stops at
the other; nothing in the UI ever set them, so every export ran the
whole timeline.
"""

import os
import sys
import types
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

if 'sounddevice' not in sys.modules:
    _stub = types.ModuleType('sounddevice')
    _stub.OutputStream = lambda *a, **k: types.SimpleNamespace(
        start=lambda: None, stop=lambda: None, close=lambda: None,
        write=lambda *a: None, active=False)
    _stub.query_devices = lambda *a, **k: []
    _stub.default = types.SimpleNamespace(device=(None, None),
                                          samplerate=48000)
    sys.modules['sounddevice'] = _stub

import effects  # noqa: F401

from render.export_config import ExportConfig

QtWidgets = pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtWidgets import QApplication            # noqa: E402

from ui.app_state import AppState                     # noqa: E402


@pytest.fixture(scope='module')
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def state(qapp):
    s = AppState()
    s.set_view_width(1145.0)
    s.total_frames = 1800
    return s


# ── the marks themselves ──────────────────────────────────────

def test_nothing_is_marked_to_begin_with(state):
    assert state.mark_in is None
    assert state.mark_out is None
    assert not state.has_marks
    assert state.marked_range() is None


def test_an_in_point_of_zero_is_a_real_mark(state):
    """None and 0 are different: frame 0 is a legitimate in point."""
    state.set_mark_in(0)
    assert state.mark_in == 0
    assert state.has_marks
    assert state.marked_range() == (0, 1800)


def test_marking_both_gives_the_span(state):
    state.set_mark_in(100)
    state.set_mark_out(400)
    assert state.marked_range() == (100, 400)


def test_an_in_point_alone_runs_to_the_end(state):
    state.set_mark_in(600)
    assert state.marked_range() == (600, 1800)


def test_an_out_point_alone_runs_from_the_start(state):
    state.set_mark_out(500)
    assert state.marked_range() == (0, 500)


def test_clearing_puts_it_back(state):
    state.set_mark_in(100)
    state.set_mark_out(400)
    state.clear_marks()
    assert not state.has_marks
    assert state.marked_range() is None


def test_a_negative_mark_is_clamped(state):
    state.set_mark_in(-50)
    assert state.mark_in == 0


def test_the_range_can_be_measured_against_the_content(state):
    """An in point alone should run to the last clip, not into the
    empty timeline past it."""
    state.set_mark_in(600)
    assert state.marked_range(total_frames=900) == (600, 900)


# ── crossing marks ────────────────────────────────────────────

def test_an_in_point_past_the_out_point_drops_the_out_point(state):
    """Rather than refusing the mark: an empty span is not a useful
    thing to leave the user holding."""
    state.set_mark_out(200)
    state.set_mark_in(500)
    assert state.mark_in == 500
    assert state.mark_out is None
    assert state.marked_range() == (500, 1800)


def test_an_out_point_before_the_in_point_drops_the_in_point(state):
    state.set_mark_in(500)
    state.set_mark_out(200)
    assert state.mark_out == 200
    assert state.mark_in is None
    assert state.marked_range() == (0, 200)


def test_a_zero_length_span_is_no_span(state):
    state._mark_in, state._mark_out = 300, 300
    assert state.marked_range() is None


# ── the signal ────────────────────────────────────────────────

def test_marking_announces_itself(state):
    seen = []
    state.marks_changed.connect(lambda: seen.append(1))
    state.set_mark_in(100)
    assert len(seen) == 1
    state.set_mark_out(400)
    assert len(seen) == 2


def test_marking_the_same_frame_twice_says_nothing(state):
    state.set_mark_in(100)
    seen = []
    state.marks_changed.connect(lambda: seen.append(1))
    state.set_mark_in(100)
    assert seen == []


def test_clearing_nothing_says_nothing(state):
    seen = []
    state.marks_changed.connect(lambda: seen.append(1))
    state.clear_marks()
    assert seen == []


# ── the export config honors it ───────────────────────────────

def test_a_default_config_exports_everything():
    cfg = ExportConfig()
    assert cfg.start_frame == 0
    assert cfg.resolved_end_frame(1800) == 1800
    assert cfg.total_frames(1800) == 1800


def test_a_range_narrows_the_export():
    cfg = ExportConfig(start_frame=100, end_frame=400)
    assert cfg.resolved_end_frame(1800) == 400
    assert cfg.total_frames(1800) == 300


def test_the_exporters_arithmetic_lands_on_the_marked_span():
    """What the exporter computes: start, then start + total."""
    cfg = ExportConfig(start_frame=100, end_frame=400)
    start = cfg.start_frame
    end   = start + cfg.total_frames(1800)
    assert (start, end) == (100, 400)


# ── the dialog ────────────────────────────────────────────────

def dialog(qapp, marked_range):
    from ui.panels.export_dialog import ExportDialog
    cfg = ExportConfig(output_path='/tmp/out.mp4', width=640, height=360)
    return ExportDialog(cfg, marked_range=marked_range)


def test_the_option_is_offered_when_a_span_is_marked(qapp):
    dlg = dialog(qapp, (100, 400))
    try:
        assert dlg._inout_radio.isEnabled()
        assert dlg._inout_radio.isChecked()
        assert '300 frames' in dlg._inout_radio.text()
    finally:
        dlg.deleteLater()


def test_the_option_stays_off_when_nothing_is_marked(qapp):
    """It would not select because there was nothing to select."""
    dlg = dialog(qapp, None)
    try:
        assert not dlg._inout_radio.isEnabled()
        assert dlg._full_radio.isChecked()
        assert 'Mark in and out' in dlg._inout_radio.toolTip()
    finally:
        dlg.deleteLater()


def test_the_built_config_carries_the_span(qapp):
    dlg = dialog(qapp, (100, 400))
    try:
        cfg = dlg._build_config('/tmp/out.mp4')
        assert (cfg.start_frame, cfg.end_frame) == (100, 400)
    finally:
        dlg.deleteLater()


def test_choosing_full_timeline_ignores_the_span(qapp):
    dlg = dialog(qapp, (100, 400))
    try:
        dlg._full_radio.setChecked(True)
        cfg = dlg._build_config('/tmp/out.mp4')
        assert (cfg.start_frame, cfg.end_frame) == (0, -1)
    finally:
        dlg.deleteLater()


def test_with_nothing_marked_the_config_exports_everything(qapp):
    dlg = dialog(qapp, None)
    try:
        cfg = dlg._build_config('/tmp/out.mp4')
        assert (cfg.start_frame, cfg.end_frame) == (0, -1)
    finally:
        dlg.deleteLater()


# ── through the window: keys, menu, and the dialog ────────────

@pytest.fixture
def window(qapp):
    from ui.mainwindow import MainWindow
    win = MainWindow()
    QApplication.processEvents()
    yield win
    win.project.is_dirty = False
    win.close()


def action_named(window, label):
    for action in window.findChildren(
            type(window.menuBar().actions()[0])):
        if action.text() == label:
            return action
    for menu in window.menuBar().findChildren(QtWidgets.QMenu):
        for action in menu.actions():
            if action.text() == label:
                return action
    return None


def test_the_menu_offers_the_commands(window):
    """So they can be found without knowing the keys."""
    for label in ('Mark In', 'Mark Out', 'Clear In and Out'):
        assert action_named(window, label) is not None, label


def test_the_keys_match_premiere(window):
    assert action_named(window, 'Mark In').shortcut().toString() == 'I'
    assert action_named(window, 'Mark Out').shortcut().toString() == 'O'


def test_mark_in_takes_the_playhead(window):
    window.app_state.playhead_frame = 250
    window._on_mark_in()
    assert window.app_state.mark_in == 250


def test_mark_out_includes_the_frame_under_the_playhead(window):
    """Exclusive, like a clip's out point: marking in and out on one
    frame gives one frame, not none."""
    window.app_state.playhead_frame = 250
    window._on_mark_in()
    window._on_mark_out()
    assert window.app_state.marked_range(1000) == (250, 251)


def test_the_commands_report_in_the_status_bar(window):
    window.app_state.playhead_frame = 300
    window._on_mark_in()
    assert 'Mark in' in window.status_label.text()
    window._on_clear_marks()
    assert 'cleared' in window.status_label.text()


def test_the_span_reaches_the_export_dialog(window, monkeypatch, tmp_path):
    """The whole point. The dialog is handed the marked range when it
    opens, measured against the content."""
    from ui.panels.export_dialog import ExportDialog
    image = tmp_path / 'f.png'
    from PySide6.QtGui import QImage, QColor
    img = QImage(320, 180, QImage.Format.Format_RGB888)
    img.fill(QColor(90, 90, 90))
    img.save(str(image))
    window._on_import_paths([str(image)])
    QApplication.processEvents()
    window._on_media_dropped(next(iter(window.project.media_pool)), 2, 0)
    QApplication.processEvents()

    window.app_state.playhead_frame = 20
    window._on_mark_in()
    window.app_state.playhead_frame = 79
    window._on_mark_out()

    seen = {}

    class Fake(ExportDialog):
        def __init__(self, config, marked_range=None, parent=None):
            seen['range'] = marked_range
            super().__init__(config, marked_range=marked_range,
                             parent=parent)

        def show(self):
            pass

    monkeypatch.setattr('ui.panels.export_dialog.ExportDialog', Fake)
    window._on_export()
    QApplication.processEvents()
    assert seen.get('range') == (20, 80)
    if window._export_dialog:
        window._export_dialog.deleteLater()
        window._export_dialog = None
