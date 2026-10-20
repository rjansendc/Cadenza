"""
Solve the Lumetri strength constants so every +-100 control has
comparable authority.

They were wildly uneven: at +-100 Tint moved the picture by 8 levels
out of 255 while Contrast moved it by 41, so most of the panel felt
dead next to Exposure. This bisects each constant against a reference
frame until full travel produces TARGET levels of mean change, and
prints the table.

Run it after changing a control's curve:

    python tools/calibrate_lumetri.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import torch

import effects  # noqa: F401
import effects.video.lumetri_color as module
from effects.video.lumetri_color import LumetriColorEffect

TARGET = 40.0          # mean |delta| in 8-bit levels at full travel


def reference_frame(height=180, width=320):
    """
    A luminance ramp plus saturated and skin-toned patches, so every
    control has something to act on: the tonal ones need a ramp, the
    color ones need color, and vibrance needs a skin tone to
    protect.
    """
    ramp = torch.linspace(0, 255, width).round()
    img = torch.zeros(height, width, 3)
    for channel in range(3):
        img[:, :, channel] = ramp
    img[0:40,   :, 0] = 200; img[0:40,   :, 1] = 60;  img[0:40,   :, 2] = 60
    img[40:80,  :, 0] = 60;  img[40:80,  :, 1] = 160; img[40:80,  :, 2] = 90
    img[80:120, :, 0] = 225; img[80:120, :, 1] = 180; img[80:120, :, 2] = 150
    return img.byte()


CONTROLS = [
    ('contrast',    'CONTRAST_GAIN'),
    ('highlights',  'HIGHLIGHTS_GAIN'),
    ('shadows',     'SHADOWS_GAIN'),
    ('whites',      'WHITES_GAIN'),
    ('blacks',      'BLACKS_GAIN'),
    ('temperature', 'TEMPERATURE_GAIN'),
    ('tint',        'TINT_GAIN'),
    ('saturation',  'SATURATION_GAIN'),
    ('vibrance',    'VIBRANCE_GAIN'),
]


def strength(effect, frame, base, name, gain_attr, gain):
    """Mean |delta| at full travel, both directions, for one gain."""
    original = getattr(module, gain_attr)
    setattr(module, gain_attr, gain)
    try:
        worst = 0.0
        for value in (100.0, -100.0):
            out = effect.apply_video(frame.clone(), {name: value}).float()
            worst = max(worst, float((out - base).abs().mean()))
        return worst
    finally:
        setattr(module, gain_attr, original)


def solve(effect, frame, base, name, gain_attr):
    low, high = 1e-4, 64.0
    for _ in range(60):
        middle = (low + high) / 2.0
        if strength(effect, frame, base, name, gain_attr, middle) < TARGET:
            low = middle
        else:
            high = middle
    return round((low + high) / 2.0, 3)


def main():
    effect = LumetriColorEffect()
    frame  = reference_frame()
    base   = effect.apply_video(frame.clone(), {}).float()

    print(f"target: {TARGET:.0f} levels of mean change at full travel\n")
    print(f"{'control':>14} {'constant':>18} {'solved':>8} {'achieved':>9}")
    solved = {}
    for name, gain_attr in CONTROLS:
        gain = solve(effect, frame, base, name, gain_attr)
        got  = strength(effect, frame, base, name, gain_attr, gain)
        solved[gain_attr] = gain
        print(f"{name:>14} {gain_attr:>18} {gain:>8.3f} {got:>9.2f}")

    print("\nconstants for effects/video/lumetri_color.py:")
    for gain_attr, gain in solved.items():
        print(f"{gain_attr:<17} = {gain}")

    # exposure, for comparison — it is in stops, not slider units
    print("\nexposure, for scale (not equalized — it is in stops):")
    for stops in (0.5, 1.0, 1.5, 5.0):
        out = effect.apply_video(frame.clone(),
                                 {'exposure': stops}).float()
        print(f"  {stops:+.1f} EV -> {float((out - base).abs().mean()):.1f} levels")


if __name__ == '__main__':
    main()
