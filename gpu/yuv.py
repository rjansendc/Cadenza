"""
YUV -> RGB on the GPU.

Decoders hand back YUV; asking PyAV for 'rgb24' makes libswscale do the
conversion on the CPU and hands back three bytes per pixel. Measured on
1080p that is 1.47 ms and 6.2 MB per frame, against 0.18 ms and 3.1 MB
for the raw planes — and a 4K frame is four times that.

So take the planes as they are, upload half as much data, and let the
GPU do the arithmetic.
"""

import numpy as np
import torch

# BT.709 (HD) and BT.601 (SD), limited range, as used by camera files
_MATRICES = {
    'bt709': (1.5748, 0.1873, 0.4681, 1.8556),
    'bt601': (1.4020, 0.3441, 0.7141, 1.7720),
}


def supported(frame) -> bool:
    """Can this frame take the fast path?"""
    try:
        return frame.format.name in ('yuv420p', 'yuvj420p', 'nv12')
    except Exception:
        return False


def frame_to_rgb_tensor(frame, device: str = 'cuda') -> torch.Tensor:
    """
    Decode one PyAV frame to an RGB uint8 tensor [H, W, 3] on `device`.

    Falls back to PyAV's own rgb24 conversion for any format this does
    not handle (10-bit, 4:2:2, NV12 and so on).
    """
    if not supported(frame):
        img = frame.to_ndarray(format='rgb24')
        return torch.from_numpy(
            np.ascontiguousarray(img)).to(device)

    h, w = frame.height, frame.width
    fmt = frame.format.name
    buf = frame.to_ndarray(format=fmt)
    planar = torch.from_numpy(np.ascontiguousarray(buf)).to(device)

    y = planar[:h, :].float()
    if fmt == 'nv12':
        # NVDEC hands back NV12: Y rows, then one plane of interleaved
        # U,V pairs at half resolution
        uv = planar[h:h + h // 2, :].reshape(h // 2, w // 2, 2).float()
        u = uv[:, :, 0]
        v = uv[:, :, 1]
    else:
        # yuv420p: Y rows, then U and V packed as quarter-height rows
        uv_rows = h // 4
        u = planar[h:h + uv_rows, :].reshape(h // 2, w // 2).float()
        v = planar[h + uv_rows:h + 2 * uv_rows, :].reshape(
            h // 2, w // 2).float()

    # Chroma is half resolution in both axes. Nearest matches
    # libswscale's siting closely here (mean 0.7 of 255 on a test
    # frame); bilinear misaligns against its chroma siting and was
    # measurably worse.
    u = u.repeat_interleave(2, 0).repeat_interleave(2, 1)[:h, :w]
    v = v.repeat_interleave(2, 0).repeat_interleave(2, 1)[:h, :w]

    full_range = fmt == 'yuvj420p'
    if full_range:
        yy = y
    else:
        # limited range: Y 16-235, C 16-240
        yy = (y - 16.0) * (255.0 / 219.0)
    uu = u - 128.0
    vv = v - 128.0
    if not full_range:
        uu = uu * (255.0 / 224.0)
        vv = vv * (255.0 / 224.0)

    kr, kgu, kgv, kb = _MATRICES['bt709' if h >= 720 else 'bt601']
    r = yy + kr * vv
    g = yy - kgu * uu - kgv * vv
    b = yy + kb * uu

    rgb = torch.stack((r, g, b), dim=2)
    return rgb.clamp_(0, 255).to(torch.uint8)
