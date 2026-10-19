"""
Writing a frame into an AVFrame whose rows are padded.

FFmpeg pads every plane row out to an alignment — a 1080 wide plane
gets a 1088 byte stride — and Buffer.update wants exactly
height x stride bytes. The exporter handed it a tightly packed array,
which raised

    ValueError: got 2073600 bytes; need 2088960 bytes

the moment anything but a 1920 wide frame was exported. 1920 needs no
padding, and export was hardcoded to 1920x1080, so it never showed.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import numpy as np
import torch
import av

from render.fast_yuv import tensor_to_av_frame_fast


PADDED  = [(1080, 1920), (1444, 1080), (1442, 1080)]
ALIGNED = [(1920, 1080), (1280, 720), (3840, 2160), (2704, 1520)]


def gradient(w, h):
    """Horizontal ramp: a stride mistake slides each row along and
    shows up as the rows disagreeing."""
    ramp = torch.linspace(0, 255, w).round().byte()
    img  = torch.zeros(h, w, 3, dtype=torch.uint8)
    img[:, :, 0] = ramp.unsqueeze(0).expand(h, w)
    img[:, :, 1] = ramp.flip(0).unsqueeze(0).expand(h, w)
    return img


def line_size(w, h):
    return av.VideoFrame(width=w, height=h,
                         format='yuv420p').planes[0].line_size


def test_the_sizes_we_claim_are_padded_really_are():
    """Guard the premise: if FFmpeg's alignment changes, this test
    file stops testing anything."""
    for w, h in PADDED:
        assert line_size(w, h) != w, f'{w}x{h} is not padded after all'
    for w, h in ALIGNED:
        assert line_size(w, h) == w, f'{w}x{h} is padded after all'


@pytest.mark.parametrize('w,h', PADDED + ALIGNED)
def test_a_frame_of_any_width_can_be_written(w, h):
    frame = tensor_to_av_frame_fast(gradient(w, h), pts=3)
    assert (frame.width, frame.height) == (w, h)
    assert frame.pts == 3


@pytest.mark.parametrize('w,h', PADDED)
def test_a_padded_frame_is_not_skewed(w, h):
    """Every row holds the same ramp; a stride bug shifts them."""
    out = tensor_to_av_frame_fast(gradient(w, h)).to_ndarray(
        format='rgb24').astype(float)
    first, last = out[0, :, 0], out[-1, :, 0]
    assert float(np.abs(first - last).max()) < 3      # rows agree
    middle = out[h // 2, :, 0]
    assert np.all(np.diff(middle) >= -2)              # ramp intact
    assert middle[0] < middle[-1]                     # and rising


@pytest.mark.parametrize('w,h', PADDED + ALIGNED)
def test_the_picture_survives_the_round_trip(w, h):
    src = gradient(w, h)
    out = tensor_to_av_frame_fast(src).to_ndarray(format='rgb24')
    # BT.601 limited range plus 4:2:0 subsampling is lossy, so compare
    # loosely — this is about the data landing in the right place
    diff = np.abs(out[:, :, 0].astype(float) -
                  src[:, :, 0].numpy().astype(float))
    assert float(diff.mean()) < 12


def test_odd_dimensions_do_not_raise():
    """Chroma planes round up; nothing should fall over."""
    for w, h in ((1081, 1080), (1080, 1081), (1081, 1081)):
        frame = tensor_to_av_frame_fast(gradient(w, h))
        assert (frame.width, frame.height) == (w, h)


def test_every_plane_is_filled():
    """A short write leaves green or gray edges rather than failing."""
    w, h = 1080, 1920
    frame = tensor_to_av_frame_fast(gradient(w, h))
    for plane in frame.planes:
        assert plane.buffer_size == plane.line_size * plane.height
