"""
Fitting a clip to the sequence frame.

The clip's right-click menu fitted the clip without telling the
Effects panel, so its Scale box kept the old number — and the next
nudge of its arrows wrote that stale value back, throwing the clip to
whatever it had been before. Neither menu made the change undoable.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # noqa: F401

from core.undo import undo_stack, ScaleToFrameCommand

pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtWidgets import QApplication        # noqa: E402
from PySide6.QtGui import QImage                  # noqa: E402

SRC_W, SRC_H = 1640, 924        # smaller than 1080p, so the fit is 116.88%
FITTED = 1920 / SRC_W * 100


@pytest.fixture(scope='module')
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(scope='module')
def still(tmp_path_factory, qapp):
    path = tmp_path_factory.mktemp('media') / 'small.png'
    QImage(SRC_W, SRC_H, QImage.Format.Format_RGB888).save(str(path))
    return str(path)


@pytest.fixture
def window(qapp, still):
    from ui.mainwindow import MainWindow
    from core.project import MediaPoolItem
    undo_stack.clear()
    win = MainWindow()
    win.show()
    QApplication.processEvents()
    item = MediaPoolItem(filepath=still)
    win._populate_media_metadata(item)
    win.project.media_pool[item.id] = item
    win._on_media_dropped(item.id, 2, 0)
    QApplication.processEvents()
    clip = next(iter(win.project.clips.values()))
    win.app_state.select_clip(clip.id)
    QApplication.processEvents()
    yield win, clip
    win.project.is_dirty = False
    win.close()


def panel_scale(window):
    for section in window.effects_panel.effect_widgets:
        for widget in getattr(section, 'parameter_widgets', []):
            if (widget.effect.id == 'motion'
                    and widget.param_def.name == 'scale'):
                return widget.input_widget.value()
    return None


def set_scale(window, clip, value):
    """As if typed into the box."""
    clip.get_effect('motion').set('scale', value)
    window.app_state.clip_modified.emit(clip.id)
    QApplication.processEvents()


# ── the panel keeps up ────────────────────────────────────────

def test_a_dropped_clip_arrives_fitted(window):
    """Cadenza fits on drop, which Premiere does not — so the box
    shows the fit, not 100."""
    win, clip = window
    assert clip.get_effect('motion').get('scale') == pytest.approx(
        FITTED, rel=0.01)
    assert panel_scale(win) == pytest.approx(FITTED, rel=0.01)


def test_the_box_follows_the_right_click_menu(window):
    """The reported bug: it stayed at 200."""
    win, clip = window
    set_scale(win, clip, 200.0)
    assert panel_scale(win) == pytest.approx(200.0)

    win.scale_clips_to_frame([clip])        # what right-click calls
    QApplication.processEvents()

    assert clip.get_effect('motion').get('scale') == pytest.approx(
        FITTED, rel=0.01)
    assert panel_scale(win) == pytest.approx(FITTED, rel=0.01)


def test_the_box_follows_the_clip_menu_too(window):
    win, clip = window
    set_scale(win, clip, 200.0)
    win._on_scale_to_frame()
    QApplication.processEvents()
    assert panel_scale(win) == pytest.approx(FITTED, rel=0.01)


def test_both_menus_agree(window):
    win, clip = window
    set_scale(win, clip, 200.0)
    win._on_scale_to_frame()
    QApplication.processEvents()
    from_menu = clip.get_effect('motion').get('scale')

    set_scale(win, clip, 200.0)
    win.scale_clips_to_frame([clip])
    QApplication.processEvents()
    assert clip.get_effect('motion').get('scale') == pytest.approx(
        from_menu)


# ── and it can be taken back ──────────────────────────────────

def test_fitting_is_undoable(window):
    win, clip = window
    set_scale(win, clip, 200.0)

    win.scale_clips_to_frame([clip])
    QApplication.processEvents()
    assert undo_stack.can_undo
    assert undo_stack.undo_description == 'Set to Frame Size'

    win._on_undo()
    QApplication.processEvents()
    assert clip.get_effect('motion').get('scale') == pytest.approx(200.0)
    assert panel_scale(win) == pytest.approx(200.0)


def test_undo_restores_position_and_anchor_too(window):
    """Fitting rewrites several motion values at once."""
    win, clip = window
    motion = clip.get_effect('motion')
    motion.set('scale', 200.0)
    motion.set('position_x', 100.0)
    motion.set('anchor_x', 42.0)
    before = ScaleToFrameCommand.snapshot(clip)

    win.scale_clips_to_frame([clip])
    QApplication.processEvents()
    assert ScaleToFrameCommand.snapshot(clip) != before

    win._on_undo()
    QApplication.processEvents()
    assert ScaleToFrameCommand.snapshot(clip) == before


def test_fitting_an_already_fitted_clip_adds_no_undo_step(window):
    """Nothing changed, so there is nothing to take back."""
    win, clip = window
    win.scale_clips_to_frame([clip])        # already fitted on drop
    QApplication.processEvents()
    assert not undo_stack.can_undo
