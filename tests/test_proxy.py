"""
Proxy media: naming, encoder selection, and that a generated proxy is
all-intra so seeking costs one frame.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

av = pytest.importorskip('av')

from core.proxy import (          # noqa: E402
    proxy_path, has_proxy, pick_encoder, available_encoders,
    generate_proxy, DEFAULT_HEIGHT,
)

SAMPLE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'test_media', 'Test_36.mp4')


def test_proxy_path_is_stable():
    a = proxy_path('/video/MVI_0106.mp4')
    b = proxy_path('/video/MVI_0106.mp4')
    assert a == b
    assert a.name.endswith(f'_{DEFAULT_HEIGHT}p.mp4')


def test_different_heights_are_different_files():
    assert proxy_path('/video/x.mp4', 540) != proxy_path('/video/x.mp4', 270)


def test_same_name_different_folder_shares_a_proxy():
    """Keyed on name and size, so moving media keeps its proxy."""
    assert (proxy_path('/a/MVI_0106.mp4').name ==
            proxy_path('/b/MVI_0106.mp4').name)


def test_missing_file_has_no_proxy():
    assert not has_proxy('/nowhere/does_not_exist.mp4')


def test_an_encoder_is_available():
    assert available_encoders()
    assert pick_encoder() in available_encoders()


def test_generated_proxy_seeks_cheaply(tmp_path):
    if not os.path.exists(SAMPLE):
        pytest.skip('test_media/Test_36.mp4 not present')
    out = proxy_path(SAMPLE)
    if not out.exists():
        pytest.skip('proxy not built — run tools/make_proxies.py')

    container = av.open(str(out))
    stream = container.streams.video[0]
    assert stream.codec_context.height == DEFAULT_HEIGHT

    # frequent keyframes are what make seeking cheap: at most a
    # short GOP of small frames to decode, against a whole GOP of 4K
    from core.proxy import DEFAULT_GOP
    keyframes = 0
    total = 0
    for packet in container.demux(stream):
        if packet.size == 0:
            continue
        total += 1
        if packet.is_keyframe:
            keyframes += 1
        if total >= 60:
            break
    container.close()
    assert keyframes >= total // (DEFAULT_GOP + 1)


def test_decoder_prefers_the_proxy():
    if not os.path.exists(SAMPLE) or not has_proxy(SAMPLE):
        pytest.skip('sample or proxy not present')
    from media.decoder import VideoDecoder

    preview = VideoDecoder(SAMPLE)
    assert preview.is_proxy
    assert preview.height == DEFAULT_HEIGHT

    export = VideoDecoder(SAMPLE, use_proxy=False)
    assert not export.is_proxy
    assert export.height > DEFAULT_HEIGHT
