from core.effects import (EffectBase, EffectRegistry,
                          ParamDef, ParamType, StreamType)
from typing import Dict, Any, List
import math
import torch


# How hard each control pushes at full travel.
#
# These were wildly uneven: at +-100 Tint moved the picture by 8
# levels out of 255 and Contrast by 41, so most of the panel felt
# dead next to Exposure. They are now calibrated so that every
# +-100 control has comparable authority — see
# tools/calibrate_lumetri.py, which solves each constant against a
# reference frame and prints the table in the changelog.
#
# Exposure is deliberately not in this group: it is measured in
# stops, a real photographic unit, and matching it to the others
# would mean a range of about a third of a stop.
CONTRAST_GAIN = 0.667
HIGHLIGHTS_GAIN = 3.056
SHADOWS_GAIN = 3.211
WHITES_GAIN = 1.684
BLACKS_GAIN = 1.734
TEMPERATURE_GAIN = 0.247
TINT_GAIN = 0.08
SATURATION_GAIN = 1.368
VIBRANCE_GAIN = 2.012

# Tint moves green one way and red+blue the other. For that to be a
# hue change and not a brightness one, the red and blue lift has to
# carry the luminance the green move gives up — and the luminance
# weights are lopsided (R 0.2126, G 0.7152, B 0.0722), so splitting
# it evenly does not. Moving green alone, as this used to, spent 71%
# of the change as brightness; an even split still spent 57%.
TINT_RED_BLUE = 0.7152 / (0.2126 + 0.0722)

# White balance presets, as (temperature, tint) in slider units.
# They describe the light the footage was shot under and apply the
# correction that neutralizes it: tungsten light is orange, so
# correcting for it cools the picture. Daylight is the reference the
# others are measured against, so it corrects by nothing — it is
# there to return to neutral after trying one of the others.
WHITE_BALANCE_PRESETS = {
    'As Shot':  (0.0, 0.0),
    'Daylight': (0.0, 0.0),
    'Cloudy':   (28.0, 0.0),
    'Tungsten': (-48.0, 6.0),
}


def _srgb_to_linear(v: torch.Tensor) -> torch.Tensor:
    return torch.where(v <= 0.04045,
                       v / 12.92,
                       ((v + 0.055) / 1.055).clamp(min=0.0) ** 2.4)


def _linear_to_srgb(v: torch.Tensor) -> torch.Tensor:
    return torch.where(v <= 0.0031308,
                       v * 12.92,
                       1.055 * v.clamp(min=0.0) ** (1.0 / 2.4) - 0.055)


def _rec709_to_linear(v: torch.Tensor) -> torch.Tensor:
    return torch.where(v < 0.081,
                       v / 4.5,
                       ((v + 0.099) / 1.099).clamp(min=0.0) ** (1.0 / 0.45))


def _linear_to_rec709(v: torch.Tensor) -> torch.Tensor:
    return torch.where(v < 0.018,
                       v * 4.5,
                       1.099 * v.clamp(min=0.0) ** 0.45 - 0.099)


# ── Input LUT: source encodings ─────────────────────────────
#
# Each choice names the encoding the footage is in. The clip is
# decoded to scene-linear light and re-encoded for display, which is
# what makes log footage look like a picture: S-Log3, V-Log and the
# rest are flat and milky until converted, and that conversion is
# the whole job of an Input LUT.
#
# These are the published encoding equations, implemented directly.
# A camera's own .cube LUT carries a creative tone curve as well and
# is the exact answer for a specific camera and look; this is the
# transfer function, which is the part that matters for getting the
# picture out of the log container.
#
# Rec.709 is the gentle case and stays: it is close to sRGB, so it
# only lifts the shadows. There is no sRGB entry because sRGB is the
# display encoding already — that is 'None'.


def _cineon_to_linear(v: torch.Tensor) -> torch.Tensor:
    """Generic flat log, the Cineon/DPX curve."""
    code = v * 1023.0
    return ((10.0 ** ((code - 685.0) / 300.0)) - 0.0108) / (1.0 - 0.0108)


def _slog3_to_linear(v: torch.Tensor) -> torch.Tensor:
    """Sony S-Log3."""
    knee = 171.2102946929 / 1023.0
    code = v * 1023.0
    high = (10.0 ** ((code - 420.0) / 261.5)) * 0.19 - 0.01
    low  = (code - 95.0) * 0.01125000 / (171.2102946929 - 95.0)
    return torch.where(v >= knee, high, low)


def _vlog_to_linear(v: torch.Tensor) -> torch.Tensor:
    """Panasonic V-Log."""
    b, c, d = 0.00873, 0.241514, 0.598206
    low  = (v - 0.125) / 5.6
    high = (10.0 ** ((v - d) / c)) - b
    return torch.where(v < 0.181, low, high)


# HLG's inverse OETF is scene-referred: signal 1.0 lands at linear
# 1.0, which leaves diffuse white — the signal level a white card
# sits at, about 0.75 — down at 0.265. Encoding that straight for
# display gives a dark, low-contrast picture, so the scene light is
# scaled to put diffuse white at 1.0.
HLG_DIFFUSE_WHITE_SIGNAL = 0.75


def _hlg_to_linear(v: torch.Tensor) -> torch.Tensor:
    """BT.2100 hybrid log-gamma, scaled for display."""
    a = 0.17883277
    b = 1.0 - 4.0 * a                       # 0.28466892
    c = 0.5 - a * math.log(4.0 * a)         # 0.55991073

    def scene(x):
        low  = x * x / 3.0
        high = (torch.exp((x - c) / a) + b) / 12.0
        return torch.where(x <= 0.5, low, high)

    white = scene(torch.tensor([HLG_DIFFUSE_WHITE_SIGNAL]))
    return scene(v) / white.clamp(min=1e-6)


# name -> what decodes it to scene-linear
INPUT_LUT_DECODERS = {
    'Rec.709':    _rec709_to_linear,
    'Log (flat)': _cineon_to_linear,
    'S-Log3':     _slog3_to_linear,
    'V-Log':      _vlog_to_linear,
    'HLG':        _hlg_to_linear,
}

HIGHLIGHT_KNEE = 0.8


def _highlight_rolloff(linear: torch.Tensor) -> torch.Tensor:
    """
    Bend scene-linear highlights into the display range.

    Log holds highlights well above 1.0, and clipping them turns a
    bright sky into a flat white card. Everything below the knee is
    untouched; above it the range is compressed smoothly.
    """
    knee = HIGHLIGHT_KNEE
    headroom = 1.0 - knee
    above = (linear - knee).clamp(min=0.0)
    # A rational shoulder, not an exponential one: exp(-x) reaches
    # the float32 floor by about four times diffuse white, so every
    # highlight past that came out the same value. This stays
    # separable into the far highlights.
    rolled = knee + headroom * (above / (above + headroom))
    return torch.where(linear > knee, rolled, linear.clamp(min=0.0))


class LumetriColorEffect(EffectBase):
    id          = 'lumetri_color'
    label       = 'Lumetri Color'
    stream_type = StreamType.VIDEO
    stack_order = 50           # late in pipeline

    def param_defs(self) -> List[ParamDef]:
        return [
            # Basic Correction
            ParamDef('input_lut', 'Input LUT', ParamType.CHOICE,
                     default='None',
                     choices=['None', 'Rec.709', 'Log (flat)',
                              'S-Log3', 'V-Log', 'HLG']),
            ParamDef('white_balance', 'White Balance', ParamType.CHOICE,
                     default='As Shot',
                     choices=['As Shot', 'Auto', 'Daylight',
                              'Cloudy', 'Tungsten']),
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

    # ── conversions ─────────────────────────────────────────

    @staticmethod
    def _apply_input_lut(frame: torch.Tensor, choice: str) -> torch.Tensor:
        """
        Read the clip as the named encoding and write it out for
        display.

        This was declared in the panel and never read, so every
        choice produced byte-identical output. It then offered only
        Rec.709 and sRGB — two nearly identical transfer functions,
        so whichever was picked moved the picture by about 10 levels
        out of 255. The job an Input LUT is reached for is getting a
        picture out of camera log, which is a large transform.
        """
        decode = INPUT_LUT_DECODERS.get(choice)
        if decode is None:
            return frame
        return _linear_to_srgb(_highlight_rolloff(decode(frame)))

    @staticmethod
    def _white_balance_offsets(frame: torch.Tensor, choice: str):
        """
        Temperature and tint, in slider units, for a preset.

        'Auto' is gray-world: it assumes the average of the picture
        should be neutral and reports the shift that would make it so.
        """
        if choice == 'Auto':
            mean = frame.reshape(-1, 3).mean(dim=0)
            green = float(mean[1])
            if green <= 0.0:
                return 0.0, 0.0
            # how far red and blue sit from green, as slider units
            red_excess  = (float(mean[0]) - green) / TEMPERATURE_GAIN
            blue_excess = (float(mean[2]) - green) / TEMPERATURE_GAIN
            temperature = -(red_excess - blue_excess) / 2.0
            return (max(-100.0, min(100.0, temperature)), 0.0)
        return WHITE_BALANCE_PRESETS.get(choice, (0.0, 0.0))

    # ── the pipeline ────────────────────────────────────────

    def apply_video(self, frame_tensor, params: Dict[str, Any]):
        """
        Full basic color correction pipeline on GPU.
        frame_tensor: uint8 [H, W, 3] on GPU
        Returns:      uint8 [H, W, 3] on GPU
        """
        frame = frame_tensor.float() / 255.0   # [H, W, 3] float 0-1

        # --- Input LUT (transfer function) ---
        frame = self._apply_input_lut(
            frame, params.get('input_lut', 'None'))

        # --- White balance preset, added to the sliders ---
        wb_temperature, wb_tint = self._white_balance_offsets(
            frame, params.get('white_balance', 'As Shot'))

        exposure    = params.get('exposure',    0.0)
        contrast    = params.get('contrast',    0.0) / 100.0
        highlights  = params.get('highlights',  0.0) / 100.0
        shadows     = params.get('shadows',     0.0) / 100.0
        whites      = params.get('whites',      0.0) / 100.0
        blacks      = params.get('blacks',      0.0) / 100.0
        temperature = (params.get('temperature', 0.0)
                       + wb_temperature) / 100.0
        tint        = (params.get('tint', 0.0) + wb_tint) / 100.0
        saturation  = params.get('saturation',  0.0) / 100.0
        vibrance    = params.get('vibrance',    0.0) / 100.0

        # --- Exposure (EV stops) ---
        if abs(exposure) > 0.001:
            frame = frame * (2.0 ** exposure)

        # --- Contrast (S-curve around 0.5 midpoint) ---
        if abs(contrast) > 0.001:
            frame = ((frame - 0.5) * (1.0 + contrast * CONTRAST_GAIN)
                     + 0.5)

        # --- Highlights (pull down bright areas) ---
        if abs(highlights) > 0.001:
            # Mask: 1.0 at pixel=1.0, 0.0 at pixel=0.5
            mask = ((frame - 0.5) * 2.0).clamp(0.0, 1.0)
            frame = frame + (highlights * HIGHLIGHTS_GAIN
                             * mask * (1.0 - frame))

        # --- Shadows (lift dark areas) ---
        if abs(shadows) > 0.001:
            # Mask: 1.0 at pixel=0.0, 0.0 at pixel=0.5
            mask = (1.0 - (frame * 2.0)).clamp(0.0, 1.0)
            frame = frame + shadows * SHADOWS_GAIN * mask * frame

        # --- Whites (scale the very brightest tones) ---
        if abs(whites) > 0.001:
            mask = frame.clamp(0.0, 1.0).pow(2.0)   # stronger at highlights
            frame = frame + whites * WHITES_GAIN * mask * (1.0 - frame)

        # --- Blacks (crush or lift the very darkest tones) ---
        if abs(blacks) > 0.001:
            mask = (1.0 - frame.clamp(0.0, 1.0)).pow(2.0)
            frame = frame + blacks * BLACKS_GAIN * mask * frame

        # --- Temperature (blue ↔ amber shift) ---
        # Positive = warmer (more red, less blue)
        if abs(temperature) > 0.001:
            shift = temperature * TEMPERATURE_GAIN
            frame = torch.stack([frame[:, :, 0] + shift,
                                 frame[:, :, 1],
                                 frame[:, :, 2] - shift], dim=2)

        # --- Tint (green ↔ magenta shift) ---
        # Positive = magenta, negative = green. Red and blue move
        # against green, weighted so the luminance the green move
        # gives up is handed back: this used to move the green
        # channel alone, and green carries 71% of the luminance, so
        # Tint read as a dimmer with a color cast.
        if abs(tint) > 0.001:
            shift = tint * TINT_GAIN
            frame = torch.stack(
                [frame[:, :, 0] + shift * TINT_RED_BLUE,
                 frame[:, :, 1] - shift,
                 frame[:, :, 2] + shift * TINT_RED_BLUE], dim=2)

        # --- Luminance for saturation/vibrance ---
        luma = (0.2126 * frame[:, :, 0] +
                0.7152 * frame[:, :, 1] +
                0.0722 * frame[:, :, 2]).unsqueeze(2)

        # --- Saturation (uniform boost/cut) ---
        if abs(saturation) > 0.001:
            frame = luma + (frame - luma) * (
                1.0 + saturation * SATURATION_GAIN)

        # --- Vibrance (boosts less-saturated colors more) ---
        # Protects already-saturated and skin tones
        if abs(vibrance) > 0.001:
            sat_per_pixel = (frame - luma).abs().max(dim=2,
                                                     keepdim=True).values
            # Less-saturated pixels get a stronger boost
            vib_mask = 1.0 - sat_per_pixel.clamp(0, 1)
            frame = luma + (frame - luma) * (
                1.0 + vibrance * VIBRANCE_GAIN * vib_mask)

        frame = frame.clamp(0.0, 1.0)
        return (frame * 255.0).byte()


# self-register
EffectRegistry.register(LumetriColorEffect)
