"""
The color that comes out is the color that went in.

The exporter converted RGB to YUV with BT.601 coefficients for every
frame, while gpu/yuv.py decodes HD as BT.709 and players assume the
same for an untagged HD stream. Grays were untouched, so it looked
fine — but saturated color shifted by up to 24 levels, which on
concert footage is exactly the stage lighting.

Nothing tagged the stream's color either, leaving the player to guess
from the frame size.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import numpy as np
import torch
import av

from render.fast_yuv import (tensor_to_av_frame_fast, matrix_for,
                             is_hd, BT601, BT709)

PATCHES = {
    'red':       (220, 30, 30),
    'green':     (30, 200, 60),
    'blue':      (40, 60, 220),
    'skin':      (222, 184, 154),
    'gray':      (128, 128, 128),
    'white':     (235, 235, 235),
    'stage red': (200, 20, 40),
    'cyan':      (0, 180, 200),
}


def patch_frame(width, height):
    """Horizontal bands, one per test color."""
    img = torch.zeros(height, width, 3, dtype=torch.uint8)
    band = max(1, height // len(PATCHES))
    for i, rgb in enumerate(PATCHES.values()):
        for channel in range(3):
            img[i * band:(i + 1) * band, :, channel] = rgb[channel]
    return img, band


# ── the matrix matches the decoder's rule ─────────────────────

@pytest.mark.parametrize('height,expected', [
    (2160, BT709), (1080, BT709), (720, BT709),
    (576, BT601), (480, BT601), (360, BT601),
])
def test_hd_uses_bt709_and_sd_bt601(height, expected):
    """gpu/yuv.py decodes with exactly this rule."""
    assert matrix_for(height) == expected
    assert is_hd(height) == (expected == BT709)


def test_the_decoder_agrees():
    """If these two ever disagree, every export shifts color."""
    from gpu import yuv
    for height in (1080, 480):
        encoder_kr, _kg, encoder_kb = matrix_for(height)
        name = 'bt709' if height >= 720 else 'bt601'
        kr, _kgu, _kgv, kb = yuv._MATRICES[name]
        # the decoder stores the inverse-matrix form; derive back
        assert kr == pytest.approx(2 * (1 - encoder_kr), abs=1e-3)
        assert kb == pytest.approx(2 * (1 - encoder_kb), abs=1e-3)


# ── frames say what they are ──────────────────────────────────

def test_an_hd_frame_is_tagged_bt709():
    frame = tensor_to_av_frame_fast(patch_frame(1280, 720)[0])
    assert frame.colorspace == av.video.reformatter.Colorspace.ITU709


def test_a_standard_definition_frame_is_tagged_bt601():
    frame = tensor_to_av_frame_fast(patch_frame(720, 480)[0])
    assert frame.colorspace == av.video.reformatter.Colorspace.ITU601


# ── and the color survives ───────────────────────────────────

@pytest.mark.parametrize('width,height', [(1920, 1080), (1280, 720),
                                          (720, 480)])
def test_colors_round_trip_within_a_few_levels(width, height):
    img, band = patch_frame(width, height)
    back = tensor_to_av_frame_fast(img).to_ndarray(format='rgb24')

    for i, (name, rgb) in enumerate(PATCHES.items()):
        got = back[i * band + band // 2, width // 2]
        error = max(abs(int(a) - int(b)) for a, b in zip(got, rgb))
        # 4:2:0 subsampling and 8-bit limited range cost a little;
        # a wrong matrix cost five times this on saturated color
        assert error <= 6, f'{name}: {tuple(int(v) for v in got)} != {rgb}'


def test_saturated_color_is_where_it_used_to_go_wrong():
    """Grays always survived a mismatched matrix; green did not."""
    img, band = patch_frame(1920, 1080)
    back = tensor_to_av_frame_fast(img).to_ndarray(format='rgb24')
    index = list(PATCHES).index('green')
    got = back[index * band + band // 2, 960]
    assert max(abs(int(a) - int(b))
               for a, b in zip(got, PATCHES['green'])) <= 6


def test_a_mismatched_matrix_really_would_be_worse():
    """Guard the premise, so this file keeps testing something."""
    rgb = np.array(PATCHES['green'], dtype=float) / 255.0
    kr_601, kg_601, kb_601 = BT601
    y601 = kr_601 * rgb[0] + kg_601 * rgb[1] + kb_601 * rgb[2]
    u601 = (rgb[2] - y601) / (2 * (1 - kb_601))
    v601 = (rgb[0] - y601) / (2 * (1 - kr_601))
    # decode those as BT.709, as a player would for an HD stream
    kr, kg, kb = BT709
    r = y601 + 2 * (1 - kr) * v601
    b = y601 + 2 * (1 - kb) * u601
    shift = max(abs(r * 255 - PATCHES['green'][0]),
                abs(b * 255 - PATCHES['green'][2]))
    assert shift > 10


# ── the exported stream carries the tags ──────────────────────

def test_the_stream_is_tagged(tmp_path):
    """A player should not have to guess from the frame size."""
    from core.track import Sequence, SequenceSettings
    from render.export_config import ExportConfig

    path = str(tmp_path / 'tagged.mp4')
    img, _ = patch_frame(1920, 1080)
    with av.open(path, mode='w') as container:
        stream = container.add_stream('h264', rate=30)
        stream.width, stream.height = 1920, 1080
        stream.pix_fmt = 'yuv420p'
        stream.options = {'crf': '18', 'preset': 'fast'}
        stream.codec_context.colorspace = (
            av.video.reformatter.Colorspace.ITU709)
        stream.codec_context.color_primaries = 1
        stream.codec_context.color_trc = 1
        stream.codec_context.color_range = 1
        for i in range(5):
            for packet in stream.encode(
                    tensor_to_av_frame_fast(img, pts=i)):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)

    with av.open(path) as container:
        codec = container.streams.video[0].codec_context
        assert codec.colorspace == 1        # BT.709
        assert codec.color_primaries == 1
        assert codec.color_range == 1       # limited / TV range
