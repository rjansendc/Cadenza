# Import all video effects to auto-register them
from .motion import MotionEffect
from .opacity import OpacityEffect  
from .time_remap import TimeRemapEffect
from .lumetri_color import LumetriColorEffect

__all__ = ['MotionEffect', 'OpacityEffect', 'TimeRemapEffect', 'LumetriColorEffect']
