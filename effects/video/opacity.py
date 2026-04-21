from core.effects import (EffectBase, EffectRegistry, 
                          ParamDef, ParamType, StreamType)
from typing import Dict, Any, List
import torch

class OpacityEffect(EffectBase):
    id          = 'opacity'
    label       = 'Opacity'
    stream_type = StreamType.VIDEO
    stack_order = 20           # after motion, before color

    def param_defs(self) -> List[ParamDef]:
        return [
            ParamDef('opacity', 'Opacity', ParamType.FLOAT,
                     default=100.0, minimum=0.0,
                     maximum=100.0, unit='%'),
        ]

    def apply_video(self, frame_tensor, params: Dict[str, Any]):
        """
        Apply opacity to video frame.
        frame_tensor: torch.Tensor shape [H, W, 3] uint8 on GPU
        """
        opacity = params.get('opacity', 100.0) / 100.0
        opacity = max(0.0, min(1.0, opacity))
        
        if opacity >= 1.0:
            return frame_tensor
        
        # Convert to float for multiplication, then back to uint8
        frame_float = frame_tensor.float()
        result = frame_float * opacity
        return result.clamp(0, 255).byte()

# self-register
EffectRegistry.register(OpacityEffect)
