"""
Closing a project, and not losing work on the way out.

There was no way to close a project at all — only to replace it by
opening or creating another — and quitting with unsaved changes
carried a "TODO: ask to save" that simply dropped them.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # noqa: F401

pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtWidgets import QApplication, QMessageBox   # noqa: E402
from PySide6.QtGui import QImage, QColor                  # noqa: E402


@pytest.fixture(scope='module')
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(scope='module')
def stills(tmp_path_factory, qapp):
    folder = tmp_path_factory.mktemp('media')
    paths = []
    for i in range(3):
        image = QImage(1920, 1080, QImage.Format.Format_RGB888)
        image.fill(QColor(60 * i, 100, 160))
        path = folder / f'slide{i}.png'
        image.save(str(path))
        paths.append(str(path))
    return paths


@pytest.fixture
def window(qapp):
    from ui.mainwindow import MainWindow
    win = MainWindow()
    win.show()
    QApplication.processEvents()
    yield win
    # closing a dirty window now asks, and a real QMessageBox would
    # block the run forever — there is nothing to save in a test
    win.project.is_dirty = False
    win.close()


def load(window, stills):
    """Import and place a clip, the way the UI does."""
    window._on_import_paths(stills)
    QApplication.processEvents()
    first = next(iter(window.project.media_pool))
    window._on_media_dropped(first, 2, 0)
    QApplication.processEvents()


def answer_with(monkeypatch, button):
    monkeypatch.setattr(
        QMessageBox, 'question',
        staticmethod(lambda *a, **k: button))


def test_the_menu_offers_it(window):
    labels = []
    for menu_action in window.menuBar().actions():
        menu = menu_action.menu()
        if menu and menu_action.text() == 'File':
            labels = [a.text() for a in menu.actions()]
    assert 'Close Project' in labels


def test_closing_empties_everything(window, stills, monkeypatch):
    load(window, stills)
    assert window.project.clips
    assert window.media_bin.list_widget.count() == 3

    answer_with(monkeypatch, QMessageBox.StandardButton.Discard)
    window._on_close_project()
    QApplication.processEvents()

    assert window.project.clips == {}
    assert window.media_bin.list_widget.count() == 0
    assert window.app_state.total_frames == 0
    assert window.preview.label._pixmap is None
    assert '•' not in window.windowTitle()      # no longer dirty


def test_cancelling_keeps_the_project(window, stills, monkeypatch):
    load(window, stills)
    clips = dict(window.project.clips)

    answer_with(monkeypatch, QMessageBox.StandardButton.Cancel)
    window._on_close_project()
    QApplication.processEvents()

    assert window.project.clips == clips
    assert window.media_bin.list_widget.count() == 3


def test_a_clean_project_closes_without_asking(window, monkeypatch):
    """Nothing to lose, so no dialog."""
    asked = []
    monkeypatch.setattr(
        QMessageBox, 'question',
        staticmethod(lambda *a, **k: asked.append(1) or
                     QMessageBox.StandardButton.Discard))
    window.project.is_dirty = False
    window._on_close_project()
    QApplication.processEvents()
    assert asked == []


def test_the_window_still_works_afterwards(window, stills, monkeypatch):
    answer_with(monkeypatch, QMessageBox.StandardButton.Discard)
    load(window, stills)
    window._on_close_project()
    QApplication.processEvents()

    load(window, stills)
    assert len(window.project.clips) == 1
    assert window.media_bin.list_widget.count() == 3


# ── quitting ──────────────────────────────────────────────────

def test_quitting_dirty_asks_first(window, stills, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    load(window, stills)

    answer_with(monkeypatch, QMessageBox.StandardButton.Cancel)
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()               # stayed open

    answer_with(monkeypatch, QMessageBox.StandardButton.Discard)
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()


def test_quitting_clean_does_not_ask(window, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    asked = []
    monkeypatch.setattr(
        QMessageBox, 'question',
        staticmethod(lambda *a, **k: asked.append(1) or
                     QMessageBox.StandardButton.Discard))
    window.project.is_dirty = False
    event = QCloseEvent()
    window.closeEvent(event)
    assert asked == []
    assert event.isAccepted()


# ── choosing Save ─────────────────────────────────────────────

def test_choosing_save_writes_the_file_then_closes(
        window, stills, tmp_path, monkeypatch):
    """Save, not Discard: the work must be on disk afterwards."""
    from core.project_io import load_project
    load(window, stills)
    path = str(tmp_path / 'show.veproj')
    window.project.project_path = path
    clips_before = len(window.project.clips)

    answer_with(monkeypatch, QMessageBox.StandardButton.Save)
    window._on_close_project()
    QApplication.processEvents()

    assert os.path.exists(path)
    assert len(load_project(path).clips) == clips_before
    assert window.project.clips == {}          # and it did close


def test_save_on_quit_writes_the_file(
        window, stills, tmp_path, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from core.project_io import load_project
    load(window, stills)
    path = str(tmp_path / 'onquit.veproj')
    window.project.project_path = path

    answer_with(monkeypatch, QMessageBox.StandardButton.Save)
    event = QCloseEvent()
    window.closeEvent(event)

    assert os.path.exists(path)
    assert load_project(path).clips
    assert event.isAccepted()


def test_a_save_that_does_not_happen_stops_the_close(
        window, stills, monkeypatch):
    """Save As can be cancelled, which leaves the project dirty —
    closing anyway would throw the work away."""
    load(window, stills)
    window.project.project_path = None         # forces Save As
    clips = dict(window.project.clips)

    answer_with(monkeypatch, QMessageBox.StandardButton.Save)
    # stand in for the user cancelling the file dialog
    monkeypatch.setattr(type(window), '_on_save_as', lambda self: None)

    window._on_close_project()
    QApplication.processEvents()

    assert window.project.clips == clips       # nothing lost
