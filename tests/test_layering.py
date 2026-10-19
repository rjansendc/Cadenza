"""
A clip that does not fill the frame must not blank what is under it.

_apply_motion pads a scaled or offset clip out to canvas size with
black, and the compositor treated that padding as picture: an opaque
picture-in-picture on V2 wiped V1 completely — 1.8 million of 2.07
million pixels went black.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # noqa: F401

import torch

from core.track import Sequence
from core.clip import Clip, ClipType
from gpu.compositor import Compositor

MOTION_DEFAULTS = {
    'position_x': 960.0, 'position_y': 540.0,
    'scale': 100.0, 'scale_x': 100.0, 'uniform_scale': True,
    'rotation': 0.0, 'anchor_x': 960.0, 'anchor_y': 540.0,
    'crop_left': 0.0, 'crop_right': 0.0,
    'crop_top': 0.0, 'crop_bottom': 0.0,
}


def motion(**over):
    m = dict(MOTION_DEFAULTS)
    m.update(over)
    return m


def comp():
    return Compositor(Sequence())


def gray_frame(h=1080, w=1920):
    return torch.zeros(h, w, 3, dtype=torch.float32) + 128.0


# ── the coverage mask itself ──────────────────────────────────

def test_a_full_frame_clip_reports_full_coverage():
    """None means 'covers everything' — the fast path stays fast."""
    _rgb, coverage = comp()._apply_motion(gray_frame(), motion(), 1.0)
    assert coverage is None


def test_a_scaled_clip_reports_partial_coverage():
    c = comp()
    _rgb, coverage = c._apply_motion(gray_frame(), motion(scale=50.0), 1.0)
    assert coverage is not None
    assert coverage.shape == (1, 1, c.height, c.width)
    covered = float(coverage.mean())
    assert 0.2 < covered < 0.3          # half the width, half the height


def test_coverage_is_where_the_picture_is():
    c = comp()
    _rgb, coverage = c._apply_motion(
        gray_frame(), motion(scale=30.0, position_x=1500.0,
                             position_y=850.0), 1.0)
    mask = coverage[0, 0]
    assert float(mask[850, 1500]) == pytest.approx(1.0)   # in the pip
    assert float(mask[50, 50]) == 0.0                     # far corner


def test_a_cropped_clip_leaves_canvas_showing():
    c = comp()
    _rgb, coverage = c._apply_motion(
        gray_frame(), motion(crop_left=50.0), 1.0)
    assert float(coverage.mean()) < 0.75


def test_a_rotated_clip_leaves_its_corners_empty():
    c = comp()
    _rgb, coverage = c._apply_motion(gray_frame(), motion(rotation=20.0), 1.0)
    mask = coverage[0, 0]
    assert float(mask[0, 0]) == 0.0
    assert float(mask[c.height // 2, c.width // 2]) == pytest.approx(1.0)


# ── through the whole compositor, with real files ─────────────

@pytest.fixture
def two_pngs(tmp_path):
    QtGui = pytest.importorskip('PySide6.QtGui')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage, QColor
    QApplication.instance() or QApplication([])
    paths = {}
    for name, rgb in (('bg', (200, 0, 0)), ('fg', (0, 200, 0))):
        im = QImage(1920, 1080, QImage.Format.Format_RGB888)
        im.fill(QColor(*rgb))
        p = tmp_path / f'{name}.png'
        im.save(str(p))
        paths[name] = str(p)
    yield paths


def still(path, track, **over):
    clip = Clip(filepath=path, clip_type=ClipType.IMAGE,
                has_video=True, has_audio=False,
                source_width=1920, source_height=1080,
                source_fps=29.97, source_frames=299,
                track=track, start_frame=0)
    fx = clip.get_effect('motion')
    for key, value in over.items():
        fx.set(key, value)
    return clip


def test_a_pip_on_v2_leaves_v1_visible(two_pngs):
    c = comp()
    c.use_proxies = False
    bg  = still(two_pngs['bg'], 0)
    pip = still(two_pngs['fg'], 1, scale=30.0,
                position_x=1500.0, position_y=850.0)
    out = c.composite_frame([bg, pip], 100, sequence=c.sequence)

    assert [int(v) for v in out[50, 50]]     == [200, 0, 0]   # V1 shows
    assert [int(v) for v in out[540, 960]]   == [200, 0, 0]   # V1 shows
    assert [int(v) for v in out[850, 1500]]  == [0, 200, 0]   # V2 on top
    assert int((out.sum(dim=2) == 0).sum()) == 0              # nothing black


def test_a_full_frame_clip_on_v2_still_covers_v1(two_pngs):
    """The optimization has to keep working: a full-frame opaque clip
    replaces what is under it."""
    c = comp()
    c.use_proxies = False
    out = c.composite_frame(
        [still(two_pngs['bg'], 0), still(two_pngs['fg'], 1)],
        100, sequence=c.sequence)
    assert [int(v) for v in out[540, 960]] == [0, 200, 0]


def test_a_half_transparent_pip_mixes_only_where_it_sits(two_pngs):
    c = comp()
    c.use_proxies = False
    pip = still(two_pngs['fg'], 1, scale=50.0)
    pip.set_opacity(0.5)
    out = c.composite_frame(
        [still(two_pngs['bg'], 0), pip], 100, sequence=c.sequence)
    middle = [int(v) for v in out[540, 960]]
    corner = [int(v) for v in out[50, 50]]
    assert corner == [200, 0, 0]                 # untouched V1
    assert middle[0] == pytest.approx(100, abs=2)   # half red
    assert middle[1] == pytest.approx(100, abs=2)   # half green
