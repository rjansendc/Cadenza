"""
Enhanced GPU compositor with crop support.

This is a modified version of gpu/compositor.py that adds crop functionality
to the _apply_motion method. Even though crop will be grayed out in the UI,
this provides the complete implementation.

Key changes:
- Added crop preprocessing before scale/position
- Maintains fast path for non-cropped, centered clips
- Supports crop as percentage values (0-100%)
"""

def _apply_motion(self, frame: torch.Tensor, motion: dict) -> torch.Tensor:
    """
    Apply motion to frame with crop support.
    Fast path: if centered, no rotation, and no crop → single interpolate.
    Full path: crop first, then scale/position/rotate.
    """
    # Get motion parameters
    scale = (motion.get('scale') or 100.0) / 100.0
    pos_x = motion.get('position_x') or 960.0
    pos_y = motion.get('position_y') or 540.0
    rotation = motion.get('rotation') or 0.0
    
    # Get crop parameters (as percentages)
    crop_left = (motion.get('crop_left') or 0.0) / 100.0
    crop_right = (motion.get('crop_right') or 0.0) / 100.0
    crop_top = (motion.get('crop_top') or 0.0) / 100.0
    crop_bottom = (motion.get('crop_bottom') or 0.0) / 100.0
    
    if scale <= 0:
        scale = 0.01
    
    # Check if any cropping is applied
    has_crop = any([crop_left, crop_right, crop_top, crop_bottom])
    
    # CROP FIRST (if needed)
    if has_crop:
        h, w = frame.shape[:2]
        
        # Calculate crop boundaries
        x1 = int(w * crop_left)
        x2 = int(w * (1.0 - crop_right))
        y1 = int(h * crop_top)
        y2 = int(h * (1.0 - crop_bottom))
        
        # Ensure valid crop region
        x1 = max(0, min(x1, w - 1))
        x2 = max(x1 + 1, min(x2, w))
        y1 = max(0, min(y1, h - 1))
        y2 = max(y1 + 1, min(y2, h))
        
        # Apply crop
        frame = frame[y1:y2, x1:x2, :]
    
    # Convert to tensor format for processing
    t = frame.permute(2, 0, 1).unsqueeze(0) / 255.0

    # --- FAST PATH ---
    # Centered clip, no rotation, no crop → single interpolate
    cx_target = self.width / 2.0
    cy_target = self.height / 2.0
    is_centered = (
        abs(pos_x - cx_target) < 2 and
        abs(pos_y - cy_target) < 2
    )
    
    if is_centered and abs(rotation) < 0.01 and not has_crop:
        t = F.interpolate(
            t,
            size=(self.height, self.width),
            mode='bilinear',
            align_corners=False
        )
        return t.squeeze(0).permute(1, 2, 0) * 255.0

    # --- FULL PATH — crop/offset/rotated clips ---
    src_h = frame.shape[0]
    src_w = frame.shape[1]
    new_h = max(1, int(src_h * scale))
    new_w = max(1, int(src_w * scale))

    # Scale
    t = F.interpolate(
        t, size=(new_h, new_w),
        mode='bilinear', align_corners=False
    )

    # Rotate (if needed)
    if abs(rotation) > 0.01:
        import torchvision.transforms.functional as TF
        t = TF.rotate(t, angle=rotation, expand=False)
        new_h = t.shape[2]
        new_w = t.shape[3]

    # Create output canvas
    canvas = torch.zeros(
        1, 3, self.height, self.width,
        dtype=torch.float32, device='cuda'
    )

    # Position on canvas
    cx = int(pos_x)
    cy = int(pos_y)
    x1 = cx - new_w // 2
    y1 = cy - new_h // 2
    x2 = x1 + new_w
    y2 = y1 + new_h

    # Calculate source and destination regions (clipping)
    sx1 = max(0, -x1)
    sy1 = max(0, -y1)
    dx1 = max(0, x1)
    dy1 = max(0, y1)
    dx2 = min(self.width, x2)
    dy2 = min(self.height, y2)
    sx2 = sx1 + (dx2 - dx1)
    sy2 = sy1 + (dy2 - dy1)

    # Paste into canvas
    if dx2 > dx1 and dy2 > dy1:
        canvas[0, :, dy1:dy2, dx1:dx2] = t[0, :, sy1:sy2, sx1:sx2]

    return canvas.squeeze(0).permute(1, 2, 0) * 255.0


# This function would replace the _apply_motion method in gpu/compositor.py
# Also need to add the global apply_motion function for effects to call:

def apply_motion(frame_tensor, params):
    """
    Global function for motion effect to call.
    This would be added to gpu/compositor.py at module level.
    """
    # This is a simplified version - in reality you'd need access to 
    # the compositor instance to get canvas dimensions
    # For now, assume 1920x1080 output
    
    # Create a temporary compositor-like object
    class TempCompositor:
        def __init__(self):
            self.width = 1920
            self.height = 1080
            
        def _apply_motion(self, frame, motion):
            # Use the enhanced _apply_motion method above
            return _apply_motion(self, frame, motion)
    
    compositor = TempCompositor()
    return compositor._apply_motion(frame_tensor, params)
