from core.effects import (EffectBase, EffectRegistry,
                           ParamDef, ParamType, StreamType)
from typing import Dict, Any, List
import torch
import math


def db_to_linear(db: float) -> float:
    """Convert dB to linear. -inf (< -96) = silence."""
    if db <= -96.0:
        return 0.0
    return 10.0 ** (db / 20.0)


def linear_to_db(linear: float) -> float:
    """Convert linear to dB. 0.0 = -inf."""
    if linear <= 0.0:
        return -math.inf
    return 20.0 * math.log10(linear)


def db_display(db: float) -> str:
    """Format dB for display — -inf shows as -∞"""
    if db <= -96.0 or db == -math.inf:
        return '-∞'
    return f'{db:.1f} dB'


class VolumeEffect(EffectBase):
    id          = 'volume'
    label       = 'Volume'
    stream_type = StreamType.AUDIO
    stack_order = 30

    def param_defs(self) -> List[ParamDef]:
        return [
            ParamDef('volume_db', 'Level', ParamType.FLOAT,
                     default=0.0, minimum=-96.0,
                     maximum=15.0, unit='dB'),
            ParamDef('muted', 'Mute', ParamType.BOOL,
                     default=False),
        ]

    def apply_audio(self, audio_tensor,
                    params: Dict[str, Any]):
        if params.get('muted', False):
            return torch.zeros_like(audio_tensor)
        db     = params.get('volume_db', 0.0)
        linear = db_to_linear(db)
        return audio_tensor * linear


EffectRegistry.register(VolumeEffect)
