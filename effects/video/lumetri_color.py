from core.effects import (EffectBase, EffectRegistry,
                          ParamDef, ParamType, StreamType)
from typing import Dict, Any, List
import torch


class LumetriColorEffect(EffectBase):
    id          = 'lumetri_color'
    label       = 'Lumetri Color'
    stream_type = StreamType.VIDEO
    stack_order = 50           # late in pipeline

    def param_defs(self) -> List[ParamDef]:
        return [
            # Basic Correction
            ParamDef('input_lut', 'Input LUT', ParamType.CHOICE,
                     default='None', choices=['None', 'Rec.709', 'sRGB']),
            ParamDef('white_balance', 'White Balance', ParamType.CHOICE,
                     default='As Shot', choices=['As Shot', 'Auto', 'Daylight', 'Cloudy', 'Tungsten']),
            ParamDef('temperature', 'Temperature', ParamType.FLOAT,
                     default=0.0, minimum=-100.0, maximum=100.0),
            ParamDef('tint', 'Tint', ParamType.FLOAT,
                     default=0.0, minimum=-100.0, maximum=100.0),

            # Tone
            ParamDef('exposure', 'Exposure', ParamType.FLOAT,
                     default=0.0, minimum=-5.0, maximum=5.0),
            ParamDef('contrast', 'Contrast', ParamType.FLOAT,
                     default=0.0, minimum=-100.0, maximum=100.0),
            ParamDef('highlights', 'Highlights', ParamType.FLOAT,
                     default=0.0, minimum=-100.0, maximum=100.0),
            ParamDef('shadows', 'Shadows', ParamType.FLOAT,
                     default=0.0, minimum=-100.0, maximum=100.0),
            ParamDef('whites', 'Whites', ParamType.FLOAT,
                     default=0.0, minimum=-100.0, maximum=100.0),
            ParamDef('blacks', 'Blacks', ParamType.FLOAT,
                     default=0.0, minimum=-100.0, maximum=100.0),

            # Color
            ParamDef('saturation', 'Saturation', ParamType.FLOAT,
                     default=0.0, minimum=-100.0, maximum=100.0),
            ParamDef('vibrance', 'Vibrance', ParamType.FLOAT,
                     default=0.0, minimum=-100.0, maximum=100.0),
        ]

    def apply_video(self, frame_tensor, params: Dict[str, Any]):
        """
        Full basic color correction pipeline on GPU.
        frame_tensor: uint8 [H, W, 3] on GPU
        Returns:      uint8 [H, W, 3] on GPU
        """
        frame = frame_tensor.float() / 255.0   # [H, W, 3] float 0-1

        exposure    = params.get('exposure',    0.0)
        contrast    = params.get('contrast',    0.0) / 100.0
        highlights  = params.get('highlights',  0.0) / 100.0
        shadows     = params.get('shadows',     0.0) / 100.0
        whites      = params.get('whites',      0.0) / 100.0
        blacks      = params.get('blacks',      0.0) / 100.0
        temperature = params.get('temperature', 0.0) / 100.0
        tint        = params.get('tint',        0.0) / 100.0
        saturation  = params.get('saturation',  0.0) / 100.0
        vibrance    = params.get('vibrance',    0.0) / 100.0

        # --- Exposure (EV stops) ---
        if abs(exposure) > 0.001:
            frame = frame * (2.0 ** exposure)

        # --- Contrast (S-curve around 0.5 midpoint) ---
        if abs(contrast) > 0.001:
            frame = (frame - 0.5) * (1.0 + contrast) + 0.5

        # --- Highlights (pull down bright areas) ---
        if abs(highlights) > 0.001:
            # Mask: 1.0 at pixel=1.0, 0.0 at pixel=0.5
            mask = ((frame - 0.5) * 2.0).clamp(0.0, 1.0)
            frame = frame + highlights * mask * (1.0 - frame)

        # --- Shadows (lift dark areas) ---
        if abs(shadows) > 0.001:
            # Mask: 1.0 at pixel=0.0, 0.0 at pixel=0.5
            mask = (1.0 - (frame * 2.0)).clamp(0.0, 1.0)
            frame = frame + shadows * mask * frame

        # --- Whites (scale the very brightest tones) ---
        if abs(whites) > 0.001:
            mask = frame.pow(2.0)          # stronger at highlights
            frame = frame + whites * mask * (1.0 - frame)

        # --- Blacks (crush or lift the very darkest tones) ---
        if abs(blacks) > 0.001:
            mask = (1.0 - frame).pow(2.0)  # stronger at shadows
            frame = frame + blacks * mask * frame

        # --- Temperature (blue ↔ amber shift) ---
        # Positive = warmer (more red, less blue)
        # Negative = cooler (more blue, less red)
        if abs(temperature) > 0.001:
            frame[:, :, 0] = (frame[:, :, 0] + temperature * 0.1).clamp(0, 1)   # R
            frame[:, :, 2] = (frame[:, :, 2] - temperature * 0.1).clamp(0, 1)   # B

        # --- Tint (green ↔ magenta shift) ---
        # Positive = magenta (more red+blue, less green)
        # Negative = green (more green, less red+blue)
        if abs(tint) > 0.001:
            frame[:, :, 1] = (frame[:, :, 1] - tint * 0.1).clamp(0, 1)          # G

        # --- Luminance for saturation/vibrance ---
        luma = (0.2126 * frame[:, :, 0] +
                0.7152 * frame[:, :, 1] +
                0.0722 * frame[:, :, 2]).unsqueeze(2)

        # --- Saturation (uniform boost/cut) ---
        if abs(saturation) > 0.001:
            frame = luma + (frame - luma) * (1.0 + saturation)

        # --- Vibrance (boosts less-saturated colors more) ---
        # Protects already-saturated and skin tones
        if abs(vibrance) > 0.001:
            sat_per_pixel = (frame - luma).abs().max(dim=2, keepdim=True).values
            # Less-saturated pixels get a stronger boost
            vib_mask = 1.0 - sat_per_pixel.clamp(0, 1)
            frame = luma + (frame - luma) * (1.0 + vibrance * vib_mask)

        frame = frame.clamp(0.0, 1.0)
        return (frame * 255.0).byte()


# self-register
EffectRegistry.register(LumetriColorEffect)
