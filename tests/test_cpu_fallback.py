"""
Cadenza wants a GPU but must run without one.

_apply_motion used to allocate its canvas with device='cuda', so on a
machine without an NVIDIA card every scaled, offset or rotated clip
raised AssertionError from torch — swallowed by the compositor and
logged as a dropped frame, which looked like a decode problem.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import effects  # noqa: F401

import torch

from core.track import Sequence
from gpu.compositor import Compositor
from gpu.device import compute_device, have_gpu


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


def frame_on(device, h=1080, w=1920):
    return torch.zeros(h, w, 3, dtype=torch.float32, device=device) + 128.0


def compositor():
    seq = Sequence()
    return Compositor(seq)


def test_compute_device_is_honest():
    dev = compute_device()
    assert dev.type in ('cuda', 'cpu')
    assert have_gpu() == (dev.type == 'cuda')
    assert (dev.type == 'cuda') == torch.cuda.is_available()


def test_scaled_clip_composites_on_cpu():
    """The reported crash: anything off the fast path allocated CUDA."""
    comp = compositor()
    out, _cov = comp._apply_motion(
        frame_on('cpu'), motion(scale=80.0), 1.0)
    assert out.device.type == 'cpu'
    assert out.shape == (comp.height, comp.width, 3)


def test_offset_clip_composites_on_cpu():
    comp = compositor()
    out, _cov = comp._apply_motion(
        frame_on('cpu'), motion(position_x=400.0, position_y=300.0), 1.0)
    assert out.device.type == 'cpu'


def test_rotated_clip_composites_on_cpu():
    comp = compositor()
    out, _cov = comp._apply_motion(
        frame_on('cpu'), motion(rotation=15.0), 1.0)
    assert out.device.type == 'cpu'


def test_cropped_clip_composites_on_cpu():
    comp = compositor()
    out, _cov = comp._apply_motion(
        frame_on('cpu'), motion(crop_left=10.0, crop_top=5.0), 1.0)
    assert out.device.type == 'cpu'


def test_the_canvas_follows_the_frame():
    """Whatever device the decoder produced, the canvas joins it —
    mixing the two would fail on the paste."""
    comp = compositor()
    for device in (['cpu', 'cuda'] if torch.cuda.is_available()
                   else ['cpu']):
        out, _cov = comp._apply_motion(
            frame_on(device), motion(scale=50.0), 1.0)
        assert out.device.type == device


def test_a_scaled_clip_lands_where_it_should():
    """Not just 'does not crash': the picture has to be in the frame."""
    comp = compositor()
    out, _cov = comp._apply_motion(
        frame_on('cpu'), motion(scale=50.0), 1.0)
    center = out[comp.height // 2, comp.width // 2]
    corner = out[0, 0]
    assert float(center.mean()) > 1.0      # picture in the middle
    assert float(corner.mean()) == 0.0     # empty canvas around it


def test_yuv_helper_needs_no_device_named():
    """frame_to_rgb_tensor defaulted to 'cuda'."""
    import inspect
    from gpu.yuv import frame_to_rgb_tensor
    default = inspect.signature(
        frame_to_rgb_tensor).parameters['device'].default
    assert default is None


def test_blank_frame_is_not_pinned_to_cuda():
    import inspect
    from media.decoder import VideoDecoder
    src = inspect.getsource(VideoDecoder._blank_frame)
    assert "device='cuda'" not in src
