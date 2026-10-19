"""
Export follows the sequence.

The default config was built with width and height hardcoded to 1080p
while everything else came from the sequence, so a 4K or portrait
sequence exported at the wrong size — and the dialog could only offer
four preset sizes, falling back to 1080p for anything else. A frame
that did need resizing was stretched to fit rather than padded, so a
portrait sequence came out squashed sideways.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # noqa: F401

import torch

from core.track import Sequence, SequenceSettings
from render.export_config import ExportConfig, RESOLUTION_PRESETS
from render.exporter import ExportThread

pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtWidgets import QApplication        # noqa: E402
from ui.panels.export_dialog import ExportDialog  # noqa: E402


@pytest.fixture(scope='module')
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def two_pngs_for_export(tmp_path, qapp):
    """Two flat colours on disk for the compositor to decode."""
    from PySide6.QtGui import QImage, QColor
    paths = {}
    for name, rgb in (('bg', (200, 0, 0)), ('fg', (0, 200, 0))):
        image = QImage(1920, 1080, QImage.Format.Format_RGB888)
        image.fill(QColor(*rgb))
        path = tmp_path / f'{name}.png'
        image.save(str(path))
        paths[name] = str(path)
    return paths


def config_for(width, height, fps=29.97, sample_rate=48000, channels=2):
    """What MainWindow hands the dialog."""
    return ExportConfig(width=width, height=height, fps=fps,
                        sample_rate=sample_rate, channels=channels)


def dialog(qapp, cfg):
    dlg = ExportDialog(cfg)
    return dlg


# ── what the dialog offers and returns ────────────────────────

@pytest.mark.parametrize('size', [
    (1920, 1080),      # a preset
    (1080, 1920),      # portrait
    (3840, 2160),      # 4K
    (2704, 1520),      # camera native, not a preset at all
])
def test_the_sequence_size_is_the_default(qapp, size):
    dlg = dialog(qapp, config_for(*size))
    built = dlg._build_config('/tmp/out.mp4')
    assert (built.width, built.height) == size
    dlg.close()


def test_an_unusual_size_is_offered_not_swallowed(qapp):
    """2704x1520 is in none of the presets; it used to be impossible
    to pick and silently became 1080p."""
    assert (2704, 1520) not in RESOLUTION_PRESETS.values()
    dlg = dialog(qapp, config_for(2704, 1520))
    assert dlg._res_combo.itemData(0) == (2704, 1520)
    assert 'Sequence' in dlg._res_combo.itemText(0)
    dlg.close()


def test_the_presets_are_still_there(qapp):
    dlg = dialog(qapp, config_for(1080, 1920))
    offered = {dlg._res_combo.itemData(i)
               for i in range(dlg._res_combo.count())}
    for size in RESOLUTION_PRESETS.values():
        assert size in offered
    dlg.close()


def test_choosing_a_preset_overrides_the_sequence(qapp):
    """Following the sequence is the default, not a cage."""
    dlg = dialog(qapp, config_for(3840, 2160))
    target = (1280, 720)
    index = next(i for i in range(dlg._res_combo.count())
                 if dlg._res_combo.itemData(i) == target)
    dlg._res_combo.setCurrentIndex(index)
    built = dlg._build_config('/tmp/out.mp4')
    assert (built.width, built.height) == target
    dlg.close()


def test_rate_and_audio_survive_the_dialog(qapp):
    """_build_config rebuilt the config from scratch and dropped
    everything it did not have a control for."""
    dlg = dialog(qapp, config_for(1080, 1920, fps=59.94,
                                  sample_rate=44100, channels=2))
    built = dlg._build_config('/tmp/out.mp4')
    assert built.fps == 59.94
    assert built.sample_rate == 44100
    assert built.channels == 2
    dlg.close()


# ── the resize itself ─────────────────────────────────────────

def exporter_for(seq_w, seq_h, colour=(200, 40, 40)):
    """An ExportThread stub whose compositor yields one flat frame."""
    thread = ExportThread.__new__(ExportThread)
    frame = torch.zeros(seq_h, seq_w, 3, dtype=torch.uint8)
    for channel, value in enumerate(colour):
        frame[:, :, channel] = value

    class FakeCompositor:
        def composite_frame(self, clips, frame_no, **kw):
            return frame

    thread.compositor = FakeCompositor()
    thread.clips = []
    thread.sequence = Sequence(
        settings=SequenceSettings(width=seq_w, height=seq_h))
    return thread


def test_matching_sizes_are_passed_straight_through():
    thread = exporter_for(1080, 1920)
    out = thread._get_video_frame(0, config_for(1080, 1920))
    assert out.shape == (1920, 1080, 3)
    assert int(out.sum()) > 0


def test_a_portrait_sequence_is_pillarboxed_not_squashed():
    """1080x1920 into a 1920x1080 file: bars at the sides, and the
    picture keeps its shape."""
    thread = exporter_for(1080, 1920)
    out = thread._get_video_frame(0, config_for(1920, 1080))
    assert out.shape == (1080, 1920, 3)

    row = out[540]                                   # across the middle
    lit = (row.sum(dim=1) > 0).nonzero().flatten()
    width = int(lit[-1] - lit[0] + 1)
    # 1080x1920 fitted into 1080 tall is 607 wide, centred
    assert width == pytest.approx(607, abs=2)
    assert int(lit[0]) == pytest.approx((1920 - 607) // 2, abs=2)
    assert int(out[540, 10].sum()) == 0              # left bar is black
    assert int(out[540, 1910].sum()) == 0            # right bar is black


def test_a_landscape_sequence_is_letterboxed_into_portrait():
    thread = exporter_for(1920, 1080)
    out = thread._get_video_frame(0, config_for(1080, 1920))
    assert out.shape == (1920, 1080, 3)
    column = out[:, 540]
    lit = (column.sum(dim=1) > 0).nonzero().flatten()
    height = int(lit[-1] - lit[0] + 1)
    assert height == pytest.approx(607, abs=2)       # bars top and bottom
    assert int(out[10, 540].sum()) == 0


def test_scaling_to_a_smaller_size_keeps_the_whole_picture():
    """Same aspect, just smaller: no bars at all."""
    thread = exporter_for(3840, 2160)
    out = thread._get_video_frame(0, config_for(1920, 1080))
    assert out.shape == (1080, 1920, 3)
    assert int((out.sum(dim=2) == 0).sum()) == 0


# ── the two dialogs offer the same sizes ──────────────────────

def test_both_dialogs_offer_the_same_sizes():
    """They had drifted: export listed 1080x1920 and the sequence
    dialog did not, so a vertical sequence had to be typed by hand."""
    from ui.panels.sequence_settings_dialog import RESOLUTIONS
    sequence_sizes = {(w, h) for _label, w, h in RESOLUTIONS if w}
    assert sequence_sizes == set(RESOLUTION_PRESETS.values())


def test_portrait_is_a_preset_in_both():
    from ui.panels.sequence_settings_dialog import RESOLUTIONS
    assert (1080, 1920) in RESOLUTION_PRESETS.values()
    assert (1080, 1920) in {(w, h) for _l, w, h in RESOLUTIONS if w}


def test_the_sequence_dialog_picks_portrait_without_custom(qapp):
    from ui.panels.sequence_settings_dialog import SequenceSettingsDialog
    from core.track import SequenceSettings
    dlg = SequenceSettingsDialog(SequenceSettings(width=1080, height=1920))
    assert dlg._res_combo.currentText() != 'Custom'
    assert (dlg.get_settings().width,
            dlg.get_settings().height) == (1080, 1920)
    dlg.close()


def test_export_offers_a_custom_size(qapp):
    """There was no way to export at a size that was not a preset."""
    dlg = dialog(qapp, config_for(1920, 1080))
    last = dlg._res_combo.count() - 1
    assert dlg._res_combo.itemData(last) is None     # the Custom row
    dlg._res_combo.setCurrentIndex(last)
    dlg._w_spin.setValue(1456)
    dlg._h_spin.setValue(816)
    built = dlg._build_config('/tmp/out.mp4')
    assert (built.width, built.height) == (1456, 816)
    dlg.close()


def test_the_custom_fields_only_show_for_custom(qapp):
    dlg = dialog(qapp, config_for(1920, 1080))
    dlg.show()
    QApplication.processEvents()
    assert dlg._w_spin.isVisible() is False
    dlg._res_combo.setCurrentIndex(dlg._res_combo.count() - 1)
    QApplication.processEvents()
    assert dlg._w_spin.isVisible() is True
    dlg.close()


# ── the export must match the preview ─────────────────────────

def still(path, start, out, track=0):
    from core.clip import Clip, ClipType
    return Clip(filepath=path, clip_type=ClipType.IMAGE,
                has_video=True, has_audio=False,
                source_width=1920, source_height=1080, source_fps=29.97,
                source_frames=300, track=track,
                start_frame=start, out_point=out)


def exporter_over(seq, clips):
    """A real compositor driving the export's frame getter."""
    from gpu.compositor import Compositor
    comp = Compositor(seq)
    comp.use_proxies = False
    thread = ExportThread.__new__(ExportThread)
    thread.compositor, thread.clips, thread.sequence = comp, clips, seq
    return thread, comp


def test_scale_to_frame_exports_as_previewed(two_pngs_for_export):
    """A landscape still fitted to a portrait sequence."""
    seq = Sequence(settings=SequenceSettings(width=1080, height=1920,
                                             fps=29.97))
    clip = still(two_pngs_for_export['bg'], 0, 30)
    clip.scale_to_frame(seq.settings.width, seq.settings.height)
    thread, comp = exporter_over(seq, [clip])

    previewed = comp.composite_frame([clip], 10, sequence=seq)
    comp.invalidate_cache()
    exported = thread._get_video_frame(10, config_for(1080, 1920))
    assert torch.equal(previewed, exported)


def test_a_dissolve_exports_as_a_dissolve(two_pngs_for_export):
    """The sequence was not passed to the compositor, so transitions
    came out as hard cuts in the file."""
    from core.transition import Transition
    seq = Sequence(settings=SequenceSettings(width=1920, height=1080,
                                             fps=29.97))
    a = still(two_pngs_for_export['bg'], 0, 60)
    b = still(two_pngs_for_export['fg'], 60, 60)
    seq.transitions = [Transition(track=0, center_frame=60, duration=30)]
    thread, comp = exporter_over(seq, [a, b])

    for frame in (50, 55, 58, 62, 68):
        comp.invalidate_cache()
        previewed = comp.composite_frame([a, b], frame, sequence=seq)
        comp.invalidate_cache()
        exported = thread._get_video_frame(frame, config_for(1920, 1080))
        assert torch.equal(previewed, exported), f'frame {frame}'

    # and it really is mixing, not just agreeing on a hard cut
    comp.invalidate_cache()
    mid = thread._get_video_frame(58, config_for(1920, 1080))
    pixel = mid[540, 960]
    assert int(pixel[0]) > 20 and int(pixel[1]) > 20


def test_a_hidden_track_stays_out_of_the_file(two_pngs_for_export):
    seq = Sequence(settings=SequenceSettings(width=1920, height=1080,
                                             fps=29.97))
    clip = still(two_pngs_for_export['bg'], 0, 30)
    thread, comp = exporter_over(seq, [clip])

    seq.video_tracks[0].visible = False
    comp.invalidate_cache()
    exported = thread._get_video_frame(10, config_for(1920, 1080))
    assert float(exported.float().mean()) < 1.0
