"""
Lumetri Color: every control does something, and they do comparable
amounts of it.

Two of the twelve were never read at all. Input LUT and White Balance
were declared in param_defs and drawn in the Effects panel, but
apply_video never looked at them: 'As Shot', 'Tungsten' and
'Daylight' all produced byte-identical output.

The rest were wildly uneven. Measured at full travel on a reference
frame, Tint moved the picture by 8 levels out of 255 and Contrast by
41, so most of the panel felt dead beside Exposure at 123. They are
now calibrated to a common target — tools/calibrate_lumetri.py solves
the constants.

And Tint was wrong in kind, not only weak: it moved the green channel
alone, and green carries 71% of the luminance, so it read as a dimmer
with a color cast rather than a green/magenta shift.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import torch

import effects  # noqa: F401

from effects.video.lumetri_color import (LumetriColorEffect,
                                         WHITE_BALANCE_PRESETS)

SLIDERS = ['contrast', 'highlights', 'shadows', 'whites', 'blacks',
           'temperature', 'tint', 'saturation', 'vibrance']


@pytest.fixture(scope='module')
def effect():
    return LumetriColorEffect()


@pytest.fixture(scope='module')
def frame():
    """A ramp plus saturated and skin-toned patches, so every control
    has something to act on."""
    height, width = 180, 320
    ramp = torch.linspace(0, 255, width).round()
    img = torch.zeros(height, width, 3)
    for channel in range(3):
        img[:, :, channel] = ramp
    img[0:40,   :, 0] = 200; img[0:40,   :, 1] = 60;  img[0:40,   :, 2] = 60
    img[40:80,  :, 0] = 60;  img[40:80,  :, 1] = 160; img[40:80,  :, 2] = 90
    img[80:120, :, 0] = 225; img[80:120, :, 1] = 180; img[80:120, :, 2] = 150
    return img.byte()


def shift(effect, frame, **params):
    """Mean change in 8-bit levels against the untouched frame."""
    base = effect.apply_video(frame.clone(), {}).float()
    out  = effect.apply_video(frame.clone(), params).float()
    return float((out - base).abs().mean())


def luma(tensor):
    t = tensor.float()
    return float((0.2126 * t[:, :, 0] + 0.7152 * t[:, :, 1]
                  + 0.0722 * t[:, :, 2]).mean())


# ── defaults change nothing ───────────────────────────────────

def test_an_untouched_clip_is_unchanged(effect, frame):
    out = effect.apply_video(frame.clone(), {})
    assert torch.equal(out, frame)


def test_every_default_together_changes_nothing(effect, frame):
    defaults = {p.name: p.default for p in effect.param_defs()}
    out = effect.apply_video(frame.clone(), defaults)
    assert torch.equal(out, frame)


# ── every control is wired ────────────────────────────────────

@pytest.mark.parametrize('name', SLIDERS)
def test_a_slider_does_something(effect, frame, name):
    assert shift(effect, frame, **{name: 100.0}) > 1.0
    assert shift(effect, frame, **{name: -100.0}) > 1.0


def test_exposure_does_something(effect, frame):
    assert shift(effect, frame, exposure=1.0) > 1.0


@pytest.mark.parametrize('choice', ['Rec.709', 'Log (flat)',
                                   'S-Log3', 'V-Log', 'HLG'])
def test_the_input_lut_does_something(effect, frame, choice):
    """Every choice produced byte-identical output before."""
    assert shift(effect, frame, input_lut=choice) > 1.0


@pytest.mark.parametrize('choice', ['Cloudy', 'Tungsten'])
def test_a_white_balance_preset_does_something(effect, frame, choice):
    assert shift(effect, frame, white_balance=choice) > 1.0


def test_auto_does_nothing_to_a_picture_with_no_cast(effect, frame):
    """Right, not forgotten: the reference frame already averages
    near neutral. Auto on a picture that needs it is tested below."""
    assert shift(effect, frame, white_balance='Auto') < 1.0


def test_as_shot_leaves_the_picture_alone(effect, frame):
    assert shift(effect, frame, white_balance='As Shot') == 0.0


def test_daylight_is_the_reference_and_so_corrects_nothing(effect, frame):
    """Documented, not forgotten: it is there to return to neutral
    after trying one of the others."""
    assert WHITE_BALANCE_PRESETS['Daylight'] == (0.0, 0.0)
    assert shift(effect, frame, white_balance='Daylight') == 0.0


# ── and by comparable amounts ─────────────────────────────────

def test_no_slider_is_an_order_of_magnitude_weaker(effect, frame):
    """The complaint: Exposure obviously worked and much of the rest
    seemed not to."""
    strengths = {name: max(shift(effect, frame, **{name: 100.0}),
                           shift(effect, frame, **{name: -100.0}))
                 for name in SLIDERS}
    weakest = min(strengths.values())
    strongest = max(strengths.values())
    assert strongest / weakest < 1.5, strengths


def test_each_slider_has_real_authority(effect, frame):
    """A third of the range should be plainly visible, not subtle."""
    for name in SLIDERS:
        assert shift(effect, frame, **{name: 33.0}) > 5.0, name


def test_the_old_weak_controls_are_stronger_than_they_were(effect, frame):
    """Highlights, Shadows and Tint measured 12.7, 12.3 and 8.5."""
    assert shift(effect, frame, highlights=100.0) > 25.0
    assert shift(effect, frame, shadows=100.0) > 25.0
    assert shift(effect, frame, tint=100.0) > 25.0


# ── directions are the right way round ────────────────────────

def test_exposure_up_brightens(effect, frame):
    assert luma(effect.apply_video(frame.clone(), {'exposure': 1.0})) > \
           luma(frame)


def test_shadows_up_lifts_the_dark_end(effect, frame):
    out = effect.apply_video(frame.clone(), {'shadows': 100.0})
    dark = frame.float()[:, :, 0] < 64
    assert out.float()[:, :, 0][dark].mean() > frame.float()[:, :, 0][dark].mean()


def test_highlights_down_pulls_the_bright_end(effect, frame):
    out = effect.apply_video(frame.clone(), {'highlights': -100.0})
    bright = frame.float()[:, :, 0] > 192
    assert out.float()[:, :, 0][bright].mean() < \
           frame.float()[:, :, 0][bright].mean()


def test_temperature_up_is_warmer(effect, frame):
    out = effect.apply_video(frame.clone(), {'temperature': 60.0}).float()
    base = effect.apply_video(frame.clone(), {}).float()
    assert float(out[:, :, 0].mean()) > float(base[:, :, 0].mean())   # R up
    assert float(out[:, :, 2].mean()) < float(base[:, :, 2].mean())   # B down


def test_saturation_down_approaches_gray(effect, frame):
    out = effect.apply_video(frame.clone(), {'saturation': -100.0}).float()
    spread = (out.max(dim=2).values - out.min(dim=2).values).mean()
    base = frame.float()
    was  = (base.max(dim=2).values - base.min(dim=2).values).mean()
    assert float(spread) < float(was)


# ── tint is a hue shift, not a dimmer ─────────────────────────

def test_tint_moves_green_against_red_and_blue(effect, frame):
    """It used to move green alone."""
    base = effect.apply_video(frame.clone(), {}).float()
    out  = effect.apply_video(frame.clone(), {'tint': 80.0}).float()
    assert float(out[:, :, 1].mean()) < float(base[:, :, 1].mean())   # G down
    assert float(out[:, :, 0].mean()) > float(base[:, :, 0].mean())   # R up
    assert float(out[:, :, 2].mean()) > float(base[:, :, 2].mean())   # B up


def test_tint_barely_changes_brightness(effect, frame):
    """Moving green alone cost 71% of the luminance change; a hue
    shift should leave the brightness roughly where it was."""
    base = luma(effect.apply_video(frame.clone(), {}))
    for value in (80.0, -80.0):
        out = luma(effect.apply_video(frame.clone(), {'tint': value}))
        assert abs(out - base) < 6.0, (value, out, base)


def test_tint_in_both_directions_moves_green_both_ways(effect, frame):
    base = effect.apply_video(frame.clone(), {}).float()
    up   = effect.apply_video(frame.clone(), {'tint': 80.0}).float()
    down = effect.apply_video(frame.clone(), {'tint': -80.0}).float()
    assert float(up[:, :, 1].mean()) < float(base[:, :, 1].mean())
    assert float(down[:, :, 1].mean()) > float(base[:, :, 1].mean())


# ── the LUT conversions are each other's inverse ──────────────

def test_reading_as_rec709_opens_the_shadows(effect, frame):
    """The Rec.709 curve has a darker toe than sRGB."""
    base = effect.apply_video(frame.clone(), {}).float()
    out  = effect.apply_video(frame.clone(),
                              {'input_lut': 'Rec.709'}).float()
    dark = base[:, :, 0] < 64
    assert float(out[:, :, 0][dark].mean()) > \
           float(base[:, :, 0][dark].mean())


def test_none_is_a_passthrough(effect, frame):
    assert shift(effect, frame, input_lut='None') == 0.0


# ── auto white balance ────────────────────────────────────────

def test_auto_white_balance_cools_a_warm_picture(effect):
    warm = torch.zeros(32, 32, 3)
    warm[:, :, 0] = 200; warm[:, :, 1] = 150; warm[:, :, 2] = 110
    warm = warm.byte()
    out = effect.apply_video(warm.clone(),
                             {'white_balance': 'Auto'}).float()
    # red and blue should be closer together than they were
    before = abs(200 - 110)
    after  = abs(float(out[:, :, 0].mean()) - float(out[:, :, 2].mean()))
    assert after < before


def test_auto_white_balance_leaves_a_neutral_picture_alone(effect):
    gray = torch.full((32, 32, 3), 128, dtype=torch.uint8)
    out = effect.apply_video(gray.clone(), {'white_balance': 'Auto'})
    assert float((out.float() - gray.float()).abs().mean()) < 1.0


def test_a_preset_adds_to_the_sliders(effect, frame):
    """A preset and a slider are the same axis, so they compose."""
    preset = effect.apply_video(frame.clone(),
                                {'white_balance': 'Tungsten'}).float()
    both = effect.apply_video(
        frame.clone(),
        {'white_balance': 'Tungsten', 'temperature': 48.0}).float()
    base = effect.apply_video(frame.clone(), {}).float()
    # Tungsten corrects by -48, so +48 on the slider cancels it
    assert float((both - base).abs().mean()) < \
           float((preset - base).abs().mean())


# ── log footage becomes a picture ─────────────────────────────

LOG_CHOICES = ['Log (flat)', 'S-Log3', 'V-Log', 'HLG']


@pytest.fixture(scope='module')
def flat_log():
    """A low-contrast ramp, the way log footage arrives: nothing near
    black, nothing near white."""
    img = torch.zeros(1, 256, 3)
    for channel in range(3):
        img[0, :, channel] = torch.linspace(26, 180, 256).round()
    return img.byte()


def contrast_of(tensor):
    channel = tensor.float()[0, :, 0]
    return float(channel.max() - channel.min())


@pytest.mark.parametrize('choice', LOG_CHOICES)
def test_a_log_curve_opens_the_picture_up(effect, flat_log, choice):
    """The job an Input LUT is reached for. Rec.709 and sRGB were the
    only choices, and they are nearly the same curve — so whichever
    was picked moved the picture by about 10 levels out of 255."""
    before = contrast_of(flat_log)
    after = contrast_of(effect.apply_video(flat_log.clone(),
                                           {'input_lut': choice}))
    assert after > before * 1.25, (choice, before, after)


@pytest.mark.parametrize('choice', LOG_CHOICES + ['Rec.709'])
def test_a_curve_never_goes_backwards(effect, choice):
    """A transfer function has to be monotonic: a curve that doubles
    back inverts tones and bands. Canon Log 3 was dropped for this —
    its negative segment disagreed with the next by 0.021 at the
    breakpoint."""
    ramp = torch.zeros(1, 256, 3)
    for channel in range(3):
        ramp[0, :, channel] = torch.arange(256)
    out = effect.apply_video(ramp.byte(), {'input_lut': choice})
    values = out[0, :, 0].float()
    assert bool((values[1:] - values[:-1] >= -0.5).all()), choice


@pytest.mark.parametrize('choice,code', [('S-Log3', 420.0 / 1023.0),
                                         ('V-Log', 0.42332)])
def test_mid_gray_decodes_to_mid_gray(choice, code):
    """The one number a log curve must get right: scene linear 0.18
    is mid gray, and each format puts it at a known code value."""
    from effects.video.lumetri_color import INPUT_LUT_DECODERS
    got = float(INPUT_LUT_DECODERS[choice](torch.tensor([code])))
    assert got == pytest.approx(0.18, abs=0.002), (choice, got)


def test_hlg_puts_diffuse_white_at_the_top(effect):
    """Its inverse OETF is scene-referred, which leaves diffuse white
    at 0.265 — encoded straight for display that is a dark, flat
    picture, and HLG came out with less contrast than it went in."""
    from effects.video.lumetri_color import (INPUT_LUT_DECODERS,
                                             HLG_DIFFUSE_WHITE_SIGNAL)
    white = float(INPUT_LUT_DECODERS['HLG'](
        torch.tensor([HLG_DIFFUSE_WHITE_SIGNAL])))
    assert white == pytest.approx(1.0, abs=0.01)


def test_hlg_raises_contrast_rather_than_lowering_it(effect, flat_log):
    before = contrast_of(flat_log)
    after = contrast_of(effect.apply_video(flat_log.clone(),
                                           {'input_lut': 'HLG'}))
    assert after > before


def test_highlights_above_the_range_are_rolled_off_not_clipped(effect):
    """Log holds highlights well above 1.0; clipping them turns a
    bright sky into a flat white card."""
    from effects.video.lumetri_color import _highlight_rolloff
    hot = torch.tensor([0.8, 1.0, 2.0, 4.0, 16.0, 64.0])
    out = _highlight_rolloff(hot)
    assert bool((out[1:] > out[:-1]).all()), out      # still separable
    assert float(out.max()) < 1.0
    # and an exponential shoulder would have flattened by 4x white
    assert float(out[4] - out[3]) > 1e-4, out


def test_an_unknown_lut_name_is_a_passthrough(effect, frame):
    """Projects saved with a choice that no longer exists — C-Log3,
    or the old sRGB entry — must still open."""
    assert shift(effect, frame, input_lut='C-Log3') == 0.0
    assert shift(effect, frame, input_lut='sRGB') == 0.0
