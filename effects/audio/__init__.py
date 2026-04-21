# Import all audio effects to auto-register them
from .volume import VolumeEffect
from .pan import PanEffect

__all__ = ['VolumeEffect', 'PanEffect']
