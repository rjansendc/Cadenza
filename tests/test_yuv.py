"""
GPU YUV->RGB must match what libswscale produces.

Uses test_media/Test_36.mp4 when it is there; test_media is untracked,
so these skip elsewhere.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

np = pytest.importorskip('numpy')
torch = pytest.importorskip('torch')
av = pytest.importorskip('av')

from gpu.yuv import frame_to_rgb_tensor, supported   # noqa: E402

SAMPLE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'test_media', 'Test_36.mp4')


def first_frames(n=6):
    if not os.path.exists(SAMPLE):
        pytest.skip('test_media/Test_36.mp4 not present')
    container = av.open(SAMPLE)
    stream = container.streams.video[0]
    stream.thread_type = 'AUTO'
    out = []
    for i, frame in enumerate(container.decode(stream)):
        out.append(frame)
        if i >= n:
            break
    return out


def test_yuv420p_is_supported():
    frames = first_frames(1)
    assert supported(frames[0])


def test_matches_libswscale():
    for frame in first_frames(4):
        ref = frame.to_ndarray(format='rgb24').astype(np.int16)
        got = frame_to_rgb_tensor(frame, device='cpu').numpy().astype(np.int16)
        assert got.shape == ref.shape
        diff = np.abs(ref - got)
        # chroma upsampling differs (nearest vs interpolated), so a
        # couple of levels is expected; anything more is a bug
        assert diff.mean() < 2.0
        assert diff.max() <= 6


def test_output_is_uint8_hwc():
    frame = first_frames(1)[0]
    t = frame_to_rgb_tensor(frame, device='cpu')
    assert t.dtype == torch.uint8
    assert t.shape == (frame.height, frame.width, 3)


def test_nv12_matches_yuv420p_exactly():
    """
    NVDEC hands back NV12. It carries the same samples as yuv420p in a
    different layout, so our two paths must agree exactly — swscale's
    own nv12 path differs from its yuv420p path by up to 41 of 255, so
    it is not the reference here.
    """
    for frame in first_frames(3):
        a = frame_to_rgb_tensor(frame, device='cpu').numpy().astype(np.int16)
        b = frame_to_rgb_tensor(
            frame.reformat(format='nv12'), device='cpu'
        ).numpy().astype(np.int16)
        assert np.abs(a - b).max() == 0


def test_unsupported_format_falls_back():
    frame = first_frames(1)[0]
    converted = frame.reformat(format='yuv422p')
    assert not supported(converted)
    t = frame_to_rgb_tensor(converted, device='cpu')   # via rgb24
    assert t.shape == (frame.height, frame.width, 3)
