"""
Opening a project must bring the monitor with it.

The compositor caches the frame size when it is built, and the preview
caches it to work out its decode size from the quality box. Both were
only ever told once, at startup — so opening a portrait or 4K project
left the monitor composing at whatever the previous sequence was.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # noqa: F401

from core.project import Project, MediaPoolItem
from core.track import SequenceSettings
from core.project_io import save_project

pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtWidgets import QApplication        # noqa: E402
from PySide6.QtGui import QImage, QColor          # noqa: E402

SIZES = [(1080, 1920), (3840, 2160), (1920, 1080), (1280, 720)]


@pytest.fixture(scope='module')
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(scope='module')
def still_png(tmp_path_factory, qapp):
    path = tmp_path_factory.mktemp('media') / 'slide.png'
    image = QImage(1920, 1080, QImage.Format.Format_RGB888)
    image.fill(QColor(200, 40, 40))
    image.save(str(path))
    return str(path)


@pytest.fixture
def window(qapp):
    from ui.mainwindow import MainWindow
    win = MainWindow()
    win.show()
    QApplication.processEvents()
    win._update_playback_clips()
    yield win
    win.close()


def project_file(tmp_path, still, width, height, name='p'):
    project = Project(name=name)
    project.active_sequence.settings = SequenceSettings(
        width=width, height=height, fps=29.97)
    item = MediaPoolItem(filepath=still, name='slide.png')
    item.has_video, item.has_audio = True, False
    item.source_width, item.source_height = 1920, 1080
    item.source_frames = 299
    project.media_pool[item.id] = item
    project.add_clip(item, track=0, start_frame=0)
    path = str(tmp_path / f'{name}.veproj')
    assert save_project(project, path)
    return path


@pytest.mark.parametrize('width,height', SIZES)
def test_opening_a_project_resizes_the_compositor(
        window, tmp_path, still_png, width, height):
    window.open_project_path(
        project_file(tmp_path, still_png, width, height))
    QApplication.processEvents()

    comp = window._playback._compositor
    assert (comp.seq_width, comp.seq_height) == (width, height)


@pytest.mark.parametrize('width,height', SIZES)
def test_opening_a_project_tells_the_monitor(
        window, tmp_path, still_png, width, height):
    """The preview divides these by the quality setting; stale values
    gave it the wrong decode size."""
    window.open_project_path(
        project_file(tmp_path, still_png, width, height))
    QApplication.processEvents()

    assert (window.preview._seq_w, window.preview._seq_h) == (width, height)


def test_the_monitor_turns_portrait_with_the_project(
        window, tmp_path, still_png):
    window.open_project_path(
        project_file(tmp_path, still_png, 1920, 1080, 'landscape'))
    QApplication.processEvents()
    wide = window.preview.label._pixmap
    assert wide.width() > wide.height()

    window.open_project_path(
        project_file(tmp_path, still_png, 1080, 1920, 'portrait'))
    QApplication.processEvents()
    tall = window.preview.label._pixmap
    assert tall.height() > tall.width()


def test_the_preview_quality_fraction_is_kept(
        window, tmp_path, still_png):
    """Rebuilding must not quietly promote the monitor to full size."""
    comp = window._playback._compositor
    before = comp.width / comp.seq_width

    window.open_project_path(
        project_file(tmp_path, still_png, 3840, 2160, 'uhd'))
    QApplication.processEvents()

    comp = window._playback._compositor
    assert comp.width / comp.seq_width == pytest.approx(before)


def test_a_new_project_resizes_too(window, qapp, monkeypatch):
    import ui.panels.sequence_settings_dialog as ssd
    monkeypatch.setattr(ssd.SequenceSettingsDialog, 'exec', lambda self: 1)
    monkeypatch.setattr(
        ssd.SequenceSettingsDialog, 'get_settings',
        lambda self: SequenceSettings(width=1080, height=1920, fps=29.97))

    window._on_new_project()
    QApplication.processEvents()

    comp = window._playback._compositor
    assert (comp.seq_width, comp.seq_height) == (1080, 1920)
    assert (window.preview._seq_w, window.preview._seq_h) == (1080, 1920)


# ── and the export follows too ────────────────────────────────

def test_export_matches_the_monitor_after_opening_a_project(
        window, tmp_path, still_png):
    """
    The export shares the playback compositor. With a stale one, the
    canvas was the new sequence's size while seq_width/seq_height were
    still the old sequence's — so geom_scale came out at 1080/1920 and
    every motion value was multiplied by it. A clip fitted to the
    frame exported at 56% of its size.
    """
    import torch
    from render.export_config import ExportConfig
    from render.exporter import ExportThread

    path = project_file(tmp_path, still_png, 1080, 1920, 'portrait_fit')
    window.open_project_path(path)
    QApplication.processEvents()

    seq = window.project.active_sequence
    clip = next(iter(window.project.clips.values()))
    clip.scale_to_frame(seq.settings.width, seq.settings.height)

    comp = window._playback._compositor
    comp.set_preview_size(seq.settings.width, seq.settings.height)
    assert comp.geom_scale == pytest.approx(1.0)

    thread = ExportThread.__new__(ExportThread)
    thread.compositor, thread.clips, thread.sequence = comp, [clip], seq

    comp.invalidate_cache()
    previewed = comp.composite_frame([clip], 5, sequence=seq)
    comp.invalidate_cache()
    exported = thread._get_video_frame(
        5, ExportConfig(width=1080, height=1920, fps=29.97))
    assert torch.equal(previewed, exported)

    # the picture really does fill the width of the portrait frame
    lit = (exported.sum(dim=2) > 10).nonzero()
    height = int(lit[:, 0].max() - lit[:, 0].min() + 1)
    assert height == pytest.approx(607, abs=3)
