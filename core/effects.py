from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type
from enum import Enum

class StreamType(Enum):
    VIDEO = "video"
    AUDIO = "audio"
    ANY   = "any"      # applies to both (e.g. time remap)

class ParamType(Enum):
    FLOAT   = "float"  # slider
    INT     = "int"    # integer slider
    BOOL    = "bool"   # checkbox
    COLOR   = "color"  # color picker
    CHOICE  = "choice" # dropdown
    LABEL   = "label"  # section header, no input

@dataclass
class ParamDef:
    """
    Describes one parameter — the UI reads this to 
    draw the correct control automatically.
    """
    name:        str
    label:       str
    param_type:  ParamType
    default:     Any        = 0.0
    minimum:     float      = 0.0
    maximum:     float      = 1.0
    step:        float      = 0.01
    unit:        str        = ''    # '%', '°', 'px', 'dB'
    choices:     List[str]  = field(default_factory=list)
    separator_before: bool  = False # draw a line above in UI

class EffectBase:
    """
    Base class for every effect in the system.
    Subclass this, set class attributes, implement apply_*.
    Self-registers when imported.
    """
    # --- subclasses set these ---
    id:          str        = ''
    label:       str        = ''
    stream_type: StreamType = StreamType.VIDEO
    stack_order: int        = 100   # lower runs first
    default_enabled: bool   = True

    def __init__(self):
        self.enabled: bool = self.default_enabled
        # build param value dict from definitions
        self._params: Dict[str, Any] = {
            p.name: p.default 
            for p in self.param_defs()
        }

    # --- subclasses implement these ---

    def param_defs(self) -> List[ParamDef]:
        """
        Return list of ParamDef — UI draws controls from this.
        Override in every subclass.
        """
        return []

    def apply_video(self, frame_tensor, params: Dict[str, Any]):
        """
        Process a video frame tensor.
        frame_tensor: torch.Tensor shape [H, W, 3] uint8 on GPU
        Returns processed tensor same shape.
        """
        return frame_tensor   # passthrough by default

    def apply_audio(self, audio_tensor, params: Dict[str, Any]):
        """
        Process an audio tensor.
        audio_tensor: torch.Tensor shape [channels, samples] float
        Returns processed tensor same shape.
        """
        return audio_tensor   # passthrough by default

    # --- param access helpers ---

    def get(self, name: str) -> Any:
        return self._params.get(name)

    def set(self, name: str, value: Any):
        self._params[name] = value

    def get_all(self) -> Dict[str, Any]:
        return dict(self._params)

    def reset(self):
        """Reset all params to defaults."""
        for p in self.param_defs():
            self._params[p.name] = p.default

    def __repr__(self):
        return f"{self.__class__.__name__}(enabled={self.enabled})"


class EffectRegistry:
    """
    Central registry for all effect types.
    Effects self-register by calling EffectRegistry.register()
    at the bottom of their file.
    """
    _effects: Dict[str, Type[EffectBase]] = {}

    @classmethod
    def register(cls, effect_class: Type[EffectBase]):
        if not effect_class.id:
            raise ValueError(
                f"{effect_class.__name__} must define a unique id"
            )
        cls._effects[effect_class.id] = effect_class
        return effect_class   # allows use as decorator

    @classmethod
    def get(cls, effect_id: str) -> Optional[Type[EffectBase]]:
        return cls._effects.get(effect_id)

    @classmethod
    def all(cls) -> List[Type[EffectBase]]:
        return sorted(
            cls._effects.values(),
            key=lambda e: e.stack_order
        )

    @classmethod
    def for_stream(cls, 
                   stream_type: StreamType
                   ) -> List[Type[EffectBase]]:
        """Return all effects valid for a given stream type."""
        return [
            e for e in cls.all()
            if e.stream_type in (stream_type, StreamType.ANY)
        ]

    @classmethod
    def create(cls, effect_id: str) -> Optional[EffectBase]:
        """Instantiate an effect by id."""
        effect_class = cls.get(effect_id)
        if effect_class:
            return effect_class()
        return None


def default_video_stack() -> List[EffectBase]:
    """
    Default effect stack for a video+audio clip.
    Matches Premiere's default order.
    """
    ids = ['motion', 'opacity', 'time_remap', 
           'volume', 'pan', 'lumetri_color']
    stack = []
    for effect_id in ids:
        effect = EffectRegistry.create(effect_id)
        if effect:
            stack.append(effect)
    return stack

def default_audio_stack() -> List[EffectBase]:
    """Default effect stack for an audio-only clip."""
    ids = ['volume', 'pan', 'gain']
    stack = []
    for effect_id in ids:
        effect = EffectRegistry.create(effect_id)
        if effect:
            stack.append(effect)
    return stack

def default_video_only_stack() -> List[EffectBase]:
    """Default effect stack for a video clip with no audio."""
    ids = ['motion', 'opacity', 'time_remap', 'lumetri_color']
    stack = []
    for effect_id in ids:
        effect = EffectRegistry.create(effect_id)
        if effect:
            stack.append(effect)
    return stack