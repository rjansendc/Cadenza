"""
Knowing whether there is anything to lose.

is_dirty was only ever set by structural changes in core/project.py —
importing media, adding or removing a clip. Trimming, grading,
dragging opacity, muting a track: none of them touched it. So the
title never showed the dot, and Close Project went ahead without
asking while real edits were thrown away.

Every undoable edit goes through one stack, so that is what the
window watches.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # noqa: F401

pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtWidgets import QApplication        # noqa: E402
from PySide6.QtGui import QImage, QColor          # noqa: E402

from core.undo import undo_stack, TrimClipCommand, SetOpacityCommand  # noqa: E402


@pytest.fixture(scope='module')
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(scope='module')
def still(tmp_path_factory, qapp):
    path = tmp_path_factory.mktemp('media') / 'slide.png'
    image = QImage(1920, 1080, QImage.Format.Format_RGB888)
    image.fill(QColor(200, 40, 40))
    image.save(str(path))
    return str(path)


@pytest.fixture
def saved(qapp, still, tmp_path):
    """A window with a project that has just been saved."""
    from ui.mainwindow import MainWindow
    undo_stack.clear()
    win = MainWindow()
    win.show()
    QApplication.processEvents()
    win._on_import_paths([still])
    QApplication.processEvents()
    win._on_media_dropped(next(iter(win.project.media_pool)), 2, 0)
    QApplication.processEvents()
    win.project.project_path = str(tmp_path / 'p.veproj')
    win._on_save()
    QApplication.processEvents()
    yield win
    win.project.is_dirty = False
    win.close()


def the_clip(window):
    return next(iter(window.project.clips.values()))


def trim(window):
    clip = the_clip(window)
    before = clip.out_point
    clip.out_point = 500
    undo_stack.push(
        TrimClipCommand(clip, 0, before, clip.start_frame,
                        0, 500, clip.start_frame),
        execute=False)
    QApplication.processEvents()


# ── the baseline ──────────────────────────────────────────────

def test_a_saved_project_is_clean(saved):
    assert saved.project.is_dirty is False
    assert '•' not in saved.windowTitle()


# ── edits that used to go unnoticed ───────────────────────────

def test_trimming_counts_as_a_change(saved):
    trim(saved)
    assert saved.project.is_dirty is True
    assert saved.windowTitle().endswith('•')


def test_dragging_opacity_counts(saved):
    undo_stack.push(SetOpacityCommand(the_clip(saved), 1.0, 0.5))
    QApplication.processEvents()
    assert saved.project.is_dirty is True


def test_adding_a_track_counts(saved):
    saved._on_add_video_track()
    QApplication.processEvents()
    assert saved.project.is_dirty is True


def test_changing_sequence_settings_counts(saved, monkeypatch):
    import ui.panels.sequence_settings_dialog as ssd
    from core.track import SequenceSettings
    monkeypatch.setattr(ssd.SequenceSettingsDialog, 'exec', lambda self: 1)
    monkeypatch.setattr(
        ssd.SequenceSettingsDialog, 'get_settings',
        lambda self: SequenceSettings(width=1280, height=720, fps=29.97))
    saved._on_sequence_settings()
    QApplication.processEvents()
    assert saved.project.is_dirty is True


# ── and back again ────────────────────────────────────────────

def test_undoing_back_to_the_save_point_is_clean_again(saved):
    trim(saved)
    assert saved.project.is_dirty is True
    saved._on_undo()
    QApplication.processEvents()
    assert saved.project.is_dirty is False
    assert '•' not in saved.windowTitle()


def test_redoing_makes_it_dirty_again(saved):
    trim(saved)
    saved._on_undo()
    QApplication.processEvents()
    saved._on_redo()
    QApplication.processEvents()
    assert saved.project.is_dirty is True


def test_saving_again_clears_it(saved):
    trim(saved)
    saved._on_save()
    QApplication.processEvents()
    assert saved.project.is_dirty is False


def test_an_edit_after_saving_shows_up(saved):
    trim(saved)
    saved._on_save()
    QApplication.processEvents()
    undo_stack.push(SetOpacityCommand(the_clip(saved), 1.0, 0.25))
    QApplication.processEvents()
    assert saved.project.is_dirty is True


# ── what this protects ────────────────────────────────────────

def test_closing_after_an_edit_now_asks(saved, monkeypatch):
    """The whole point: these edits used to close without a word."""
    from PySide6.QtWidgets import QMessageBox
    trim(saved)
    asked = []
    monkeypatch.setattr(
        QMessageBox, 'question',
        staticmethod(lambda *a, **k: asked.append(1) or
                     QMessageBox.StandardButton.Cancel))
    saved._on_close_project()
    QApplication.processEvents()
    assert asked, 'closing went ahead without asking'
    assert saved.project.clips, 'the canceled close still cleared it'
