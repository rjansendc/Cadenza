from core.effects import (EffectBase, EffectRegistry, 
                          ParamDef, ParamType, StreamType)
from typing import Dict, Any, List

class TimeRemapEffect(EffectBase):
    id          = 'time_remap'
    label       = 'Time Remapping'
    stream_type = StreamType.ANY
    stack_order = 10           # early in pipeline

    def param_defs(self) -> List[ParamDef]:
        return [
            ParamDef('speed', 'Speed', ParamType.FLOAT,
                     default=100.0, minimum=0.0,
                     maximum=1000.0, unit='%'),
            ParamDef('reverse', 'Reverse Speed', ParamType.BOOL,
                     default=False),
            ParamDef('frame_blending', 'Frame Blending', ParamType.BOOL,
                     default=False),
        ]

    def apply_video(self, frame_tensor, params: Dict[str, Any]):
        """
        Time remapping is handled at the decode/render level,
        not as a frame filter. This is a placeholder.
        """
        return frame_tensor

    def apply_audio(self, audio_tensor, params: Dict[str, Any]):
        """
        Time remapping affects audio playback rate.
        This is a placeholder - actual implementation
        would be in the audio mixer.
        """
        return audio_tensor

# self-register
EffectRegistry.register(TimeRemapEffect)
