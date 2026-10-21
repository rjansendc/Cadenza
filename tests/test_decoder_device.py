"""
Every decoded frame lands on the same device.

ImageDecoder handed back a CPU tensor while VideoDecoder put its
frames on the GPU, so compositing an image over a video raised

    Compositing Image28.jpg failed: RuntimeError: Expected all
    tensors to be on the same device, but found at least two
    devices, cuda:0 and cpu!

The compositor catches that, logs it and drops the clip — so the
image silently vanished and the video underneath showed through,
looking as though layer order were being ignored.

It cannot happen on a machine without a GPU, where everything is on
the CPU already, which is why it survived every test written on one.
These use torch's 'meta' device to stand in for a second device, so
the mismatch is reproducible anywhere.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import torch

import effects  # noqa: F401

QtGui = pytest.importorskip('PySide6.QtGui')
from PySide6.QtWidgets import QApplication        # noqa: E402
from PySide6.QtGui import QImage, QColor          # noqa: E402

import gpu.device                                  # noqa: E402


@pytest.fixture(scope='module')
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(scope='module')
def still(tmp_path_factory, qapp):
    image = QImage(320, 180, QImage.Format.Format_RGB888)
    image.fill(QColor(200, 40, 40))
    path = tmp_path_factory.mktemp('media') / 'still.png'
    image.save(str(path))
    return str(path)


@pytest.fixture
def elsewhere(monkeypatch):
    """Pretend the compute device is somewhere other than the CPU."""
    device = torch.device('meta')
    monkeypatch.setattr(gpu.device, 'compute_device', lambda: device)
    return device


# ── the decoder itself ────────────────────────────────────────

def test_an_image_decodes_onto_the_compute_device(still, elsewhere):
    """It used to come back on the CPU whatever the device was."""
    from media.decoder import ImageDecoder
    frame = ImageDecoder(still).get_frame(0)
    assert frame is not None
    assert frame.device.type == elsewhere.type, frame.device


def test_an_image_decodes_onto_the_cpu_when_that_is_all_there_is(still):
    from media.decoder import ImageDecoder
    frame = ImageDecoder(still).get_frame(0)
    assert frame is not None
    assert frame.device == gpu.device.compute_device()


def test_the_pixels_survive_the_move(still):
    from media.decoder import ImageDecoder
    frame = ImageDecoder(still).get_frame(0)
    centre = frame[frame.shape[0] // 2, frame.shape[1] // 2]
    assert [int(v) for v in centre] == [200, 40, 40]


def test_every_frame_request_is_on_the_device(still, elsewhere):
    """The frame is cached after the first read, so the device has to
    come back with it."""
    from media.decoder import ImageDecoder
    decoder = ImageDecoder(still)
    for index in (0, 1, 50):
        assert decoder.get_frame(index).device.type == elsewhere.type


# ── and the compositor insists on it ──────────────────────────

def test_the_compositor_moves_whatever_a_decoder_hands_back(
        still, monkeypatch, elsewhere):
    """
    Belt and braces: a decoder that ignores the device must not be
    able to drop a clip out of the composite. Driven through
    _get_frame, which is where every decoded frame arrives.
    """
    from core.clip import Clip, ClipType
    from core.clip_renderer import ClipRenderer
    from core.track import Sequence
    from gpu.compositor import Compositor
    import gpu.compositor as compositor_module

    class WrongDevice:
        """Hands back a CPU tensor, as ImageDecoder used to."""
        frame_count = 100

        def get_frame(self, index, draft=False):
            return torch.zeros(180, 320, 3, device='cpu')

    monkeypatch.setattr(compositor_module.gpu.device
                        if hasattr(compositor_module, 'gpu')
                        else gpu.device,
                        'compute_device', lambda: elsewhere)

    compositor = Compositor(Sequence())
    monkeypatch.setattr(compositor, 'get_decoder',
                        lambda path: WrongDevice())

    clip = Clip(filepath=still, clip_type=ClipType.IMAGE,
                has_video=True, has_audio=False,
                source_width=320, source_height=180,
                source_fps=29.97, source_frames=299,
                track=0, start_frame=0)
    frame = compositor._get_frame(ClipRenderer(clip), 10)
    assert frame is not None
    assert frame.device.type == elsewhere.type, frame.device


def test_an_image_and_a_video_frame_agree(still):
    """The pair that used to disagree."""
    from media.decoder import ImageDecoder
    image_frame = ImageDecoder(still).get_frame(0)
    video_like = torch.zeros(180, 320, 3,
                             device=gpu.device.compute_device())
    assert image_frame.device == video_like.device
    # and so they can be mixed, which is what compositing does
    mixed = image_frame * 0.5 + video_like * 0.5
    assert mixed.shape == image_frame.shape
