"""
Fast RGB→YUV420p conversion - GPU accelerated.
Does YUV conversion on GPU BEFORE moving to CPU,
avoiding slow numpy operations on large arrays.
"""
import torch
import numpy as np
import av


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
        rgb = tensor.float() / 255.0
    else:
        rgb = tensor.float() / 255.0

    r = rgb[:, :, 0]
    g = rgb[:, :, 1]
    b = rgb[:, :, 2]

    # BT.601 RGB→YUV on GPU
    y = (0.257*r + 0.504*g + 0.098*b + 0.0625) * 255.0
    u = (-0.148*r - 0.291*g + 0.439*b + 0.5) * 255.0
    v = (0.439*r - 0.368*g - 0.071*b + 0.5) * 255.0

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
    frame.planes[0].update(np.ascontiguousarray(y_np))
    frame.planes[1].update(np.ascontiguousarray(u_np))
    frame.planes[2].update(np.ascontiguousarray(v_np))
    frame.pts = pts
    return frame


def rgb_tensor_to_yuv420_numpy(tensor: torch.Tensor) -> tuple:
    """Legacy CPU numpy path - kept for compatibility."""
    rgb = tensor.numpy().astype(np.float32) / 255.0
    r, g, b = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
    y = np.clip((0.257*r + 0.504*g + 0.098*b + 0.0625)*255, 16, 235).astype(np.uint8)
    u = np.clip((-0.148*r - 0.291*g + 0.439*b + 0.5)*255, 16, 240).astype(np.uint8)
    v = np.clip((0.439*r - 0.368*g - 0.071*b + 0.5)*255, 16, 240).astype(np.uint8)
    return y, u[::2,::2], v[::2,::2]
