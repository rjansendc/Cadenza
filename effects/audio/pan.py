from core.effects import (EffectBase, EffectRegistry, 
                          ParamDef, ParamType, StreamType)
from typing import Dict, Any, List
import torch

class PanEffect(EffectBase):
    id          = 'pan'
    label       = 'Pan'
    stream_type = StreamType.AUDIO
    stack_order = 40           # after volume

    def param_defs(self) -> List[ParamDef]:
        return [
            ParamDef('pan', 'Pan', ParamType.FLOAT,
                     default=0.0, minimum=-100.0,
                     maximum=100.0, unit='%'),
        ]

    def apply_audio(self, audio_tensor, params: Dict[str, Any]):
        """
        Apply stereo panning to audio.
        audio_tensor: torch.Tensor shape [channels, samples] float
        Pan: -100 = full left, 0 = center, +100 = full right
        """
        pan = params.get('pan', 0.0) / 100.0  # Convert to -1.0 to 1.0
        pan = max(-1.0, min(1.0, pan))
        
        if audio_tensor.shape[0] < 2:
            # Mono audio - can't pan
            return audio_tensor
            
        if abs(pan) < 0.01:
            # No panning needed
            return audio_tensor
        
        # Calculate left and right gains
        if pan <= 0:
            # Pan left: reduce right channel
            left_gain = 1.0
            right_gain = 1.0 + pan  # pan is negative, so this reduces right
        else:
            # Pan right: reduce left channel  
            left_gain = 1.0 - pan
            right_gain = 1.0
            
        result = audio_tensor.clone()
        result[0] *= left_gain   # Left channel
        result[1] *= right_gain  # Right channel
        
        return result

# self-register
EffectRegistry.register(PanEffect)
