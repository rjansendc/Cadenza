from core.effects import (EffectBase, EffectRegistry, 
                           ParamDef, ParamType, StreamType)
from typing import Dict, Any, List

class MotionEffect(EffectBase):
    id          = 'motion'
    label       = 'Motion'
    stream_type = StreamType.VIDEO
    stack_order = 0            # always runs first

    def param_defs(self) -> List[ParamDef]:
        return [
            ParamDef('position_x', 'Position X', ParamType.FLOAT,
                     default=960.0, minimum=0.0, 
                     maximum=3840.0, unit='px'),
            ParamDef('position_y', 'Position Y', ParamType.FLOAT,
                     default=540.0, minimum=0.0,
                     maximum=2160.0, unit='px'),
            ParamDef('scale', 'Scale', ParamType.FLOAT,
                     default=100.0, minimum=0.0,
                     maximum=400.0, unit='%'),
            ParamDef('uniform_scale', 'Uniform Scale',
                     ParamType.BOOL, default=True),
            ParamDef('scale_x', 'Scale Width', ParamType.FLOAT,
                     default=100.0, minimum=0.0,
                     maximum=400.0, unit='%'),
            ParamDef('rotation', 'Rotation', ParamType.FLOAT,
                     default=0.0, minimum=-180.0,
                     maximum=180.0, unit='°'),
            ParamDef('anchor_x', 'Anchor X', ParamType.FLOAT,
                     default=960.0, minimum=0.0,
                     maximum=3840.0, unit='px'),
            ParamDef('anchor_y', 'Anchor Y', ParamType.FLOAT,
                     default=540.0, minimum=0.0,
                     maximum=2160.0, unit='px'),
            ParamDef('anti_flicker', 'Anti-flicker Filter',
                     ParamType.FLOAT, default=0.0,
                     minimum=0.0, maximum=1.0),
            ParamDef('crop_left', 'Crop Left', ParamType.FLOAT,
                     default=0.0, minimum=0.0,
                     maximum=100.0, unit='%',
                     separator_before=True),
            ParamDef('crop_top', 'Crop Top', ParamType.FLOAT,
                     default=0.0, minimum=0.0,
                     maximum=100.0, unit='%'),
            ParamDef('crop_right', 'Crop Right', ParamType.FLOAT,
                     default=0.0, minimum=0.0,
                     maximum=100.0, unit='%'),
            ParamDef('crop_bottom', 'Crop Bottom', ParamType.FLOAT,
                     default=0.0, minimum=0.0,
                     maximum=100.0, unit='%'),
        ]

    # No apply_video: motion is not run as part of the effect stack.
    # Compositor._apply_motion applies it first, straight from the
    # ClipRenderer's parameters, and _apply_video_effects skips this
    # effect by id. Inheriting the base passthrough keeps it harmless
    # if anything ever does call it.

    def scale_to_frame(self, clip_w, clip_h, 
                        canvas_w, canvas_h):
        """Fit inside canvas preserving aspect ratio."""
        scale = min(canvas_w / clip_w, 
                    canvas_h / clip_h) * 100
        self.set('scale', scale)
        self.set('position_x', canvas_w / 2)
        self.set('position_y', canvas_h / 2)

    def fit_to_frame(self, clip_w, clip_h,
                     canvas_w, canvas_h):
        """Fill canvas preserving aspect ratio."""
        scale = max(canvas_w / clip_w,
                    canvas_h / clip_h) * 100
        self.set('scale', scale)
        self.set('position_x', canvas_w / 2)
        self.set('position_y', canvas_h / 2)

# self-register
EffectRegistry.register(MotionEffect)