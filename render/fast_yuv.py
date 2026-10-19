"""
Fast RGB→YUV420p conversion - GPU accelerated.
Does YUV conversion on GPU BEFORE moving to CPU,
avoiding slow numpy operations on large arrays.
"""
import torch
import numpy as np
import av


# Luma coefficients. HD and up is BT.709, standard definition BT.601
# — the same rule gpu/yuv.py applies when decoding, so a frame that
# goes in comes back out unchanged.
BT709 = (0.2126, 0.7152, 0.0722)
BT601 = (0.299,  0.587,  0.114)

HD_FROM_HEIGHT = 720


def matrix_for(height: int) -> tuple:
    """(kr, kg, kb) for a frame of this height."""
    return BT709 if height >= HD_FROM_HEIGHT else BT601


def is_hd(height: int) -> bool:
    return height >= HD_FROM_HEIGHT


def tensor_to_av_frame_fast(tensor: torch.Tensor,
                              pts: int = 0) -> av.VideoFrame:
    """
    Convert RGB tensor [H,W,3] uint8 to AVFrame(yuv420p).
    Performs YUV conversion on GPU if available,
    then transfers only the compact YUV data to CPU.
    This is faster than converting on CPU because:
    - GPU parallelizes the math across all pixels at once
    - YUV420p is 1.5 bytes/pixel vs RGB 3 bytes/pixel
      so we transfer half the data to CPU
    """
    # Move to GPU for conversion if not already there
    if torch.cuda.is_available():
        if tensor.device.type != 'cuda':
            tensor = tensor.cuda()
        rgb = tensor.float()
    else:
        rgb = tensor.float()

    r = rgb[:, :, 0]
    g = rgb[:, :, 1]
    b = rgb[:, :, 2]

    # The matrix has to match the one the decoder and the player use,
    # or saturated color shifts: this encoded BT.601 unconditionally
    # while gpu/yuv.py decodes HD as BT.709 and players assume the
    # same. Measured on test patches, that cost a mean of 6.9 levels
    # and up to 24 on a saturated green — grays were untouched, which
    # is why it was easy to miss.
    kr, kg, kb = matrix_for(int(rgb.shape[0]))
    yf = kr * r + kg * g + kb * b
    y = yf * (219.0 / 255.0) + 16.0
    u = (b - yf) / (2.0 * (1.0 - kb)) * (224.0 / 255.0) + 128.0
    v = (r - yf) / (2.0 * (1.0 - kr)) * (224.0 / 255.0) + 128.0

    # Clamp and convert to uint8 on GPU
    y = y.clamp(16, 235).byte()
    u = u.clamp(16, 240).byte()
    v = v.clamp(16, 240).byte()

    # 420 subsampling on GPU
    u_ds = u[::2, ::2]
    v_ds = v[::2, ::2]

    # Single transfer to CPU for all planes
    y_np  = y.cpu().numpy()
    u_np  = u_ds.cpu().numpy()
    v_np  = v_ds.cpu().numpy()

    h, w = y_np.shape
    frame = av.VideoFrame(width=w, height=h, format='yuv420p')
    try:
        # say which matrix this is, rather than leaving the player to
        # guess from the frame size
        frame.colorspace = (av.video.reformatter.Colorspace.ITU709
                            if is_hd(h)
                            else av.video.reformatter.Colorspace.ITU601)
    except Exception:
        pass
    _fill_plane(frame.planes[0], y_np)
    _fill_plane(frame.planes[1], u_np)
    _fill_plane(frame.planes[2], v_np)
    frame.pts = pts
    return frame


def _fill_plane(plane, data: np.ndarray):
    """
    Copy a tightly packed plane into an AVFrame plane.

    FFmpeg pads every row out to an alignment, so a 1080 wide plane
    has a 1088 byte stride, and Buffer.update wants exactly
    height x stride bytes. Handing it the packed array raised
    "got 2073600 bytes; need 2088960 bytes" — which never showed up
    while every export was 1920 wide, since 1920 needs no padding.
    """
    rows, cols = data.shape
    stride = plane.line_size
    if stride == cols:
        plane.update(np.ascontiguousarray(data))
        return
    padded = np.zeros((rows, stride), dtype=data.dtype)
    padded[:, :cols] = data
    plane.update(padded)


def rgb_tensor_to_yuv420_numpy(tensor: torch.Tensor) -> tuple:
    """Legacy CPU numpy path - kept for compatibility."""
    rgb = tensor.numpy().astype(np.float32) / 255.0
    r, g, b = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
    y = np.clip((0.257*r + 0.504*g + 0.098*b + 0.0625)*255, 16, 235).astype(np.uint8)
    u = np.clip((-0.148*r - 0.291*g + 0.439*b + 0.5)*255, 16, 240).astype(np.uint8)
    v = np.clip((0.439*r - 0.368*g - 0.071*b + 0.5)*255, 16, 240).astype(np.uint8)
    return y, u[::2,::2], v[::2,::2]
