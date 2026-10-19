"""
The timeline scale is absolute: pixels per frame.

Editing must never change it. It used to be a normalized fraction of
the project length, so every drop, stretch or delete rescaled the whole
timeline — six identical stills ended up drawn at six different widths.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from ui.constants import (DEFAULT_VISIBLE_FRAMES, SCROLL_PAD_FRACTION,
                          MIN_VISIBLE_FRAMES, STILL_IMAGE_SECONDS)

try:
    from ui.app_state import AppState
    HAVE_QT = True
except Exception:                     # pragma: no cover
    HAVE_QT = False

pytestmark = pytest.mark.skipif(not HAVE_QT, reason='needs PySide6')

CANVAS = 1145.0          # a representative timeline canvas width
STILL  = 299             # a 10s still at 29.97fps


def state(width=CANVAS):
    s = AppState()
    s.set_view_width(width)
    return s


def test_default_span_puts_a_still_at_a_twentieth():
    """A 10s still on an empty timeline takes a small slice, as in
    Premiere — not the whole window."""
    s = state()
    width = s.frame_to_pixel(STILL, CANVAS) - s.frame_to_pixel(0, CANVAS)
    fraction = width / CANVAS
    assert 1 / 25 < fraction < 1 / 14, fraction


def test_content_growth_does_not_change_the_scale():
    """Six drops, one after another: the scale holds."""
    s = state()
    before = s.px_per_frame
    for i in range(1, 7):
        s.total_frames = i * STILL
        assert s.px_per_frame == before


def test_clips_keep_their_width_as_content_grows():
    s = state()
    s.total_frames = STILL
    first = (s.frame_to_pixel(STILL, CANVAS) -
             s.frame_to_pixel(0, CANVAS))
    s.total_frames = 6 * STILL
    later = (s.frame_to_pixel(STILL, CANVAS) -
             s.frame_to_pixel(0, CANVAS))
    assert first == later


def test_stretching_the_last_clip_moves_nothing_else():
    """The reported bug: one stretch shifted every other clip."""
    s = state()
    s.total_frames = 6 * STILL
    starts = [i * STILL for i in range(6)]
    before = [s.frame_to_pixel(f, CANVAS) for f in starts]
    s.total_frames = 5 * STILL + 1006      # last clip stretched
    after = [s.frame_to_pixel(f, CANVAS) for f in starts]
    assert before == after


def test_deleting_everything_leaves_the_zoom_alone():
    s = state()
    s.total_frames = 6 * STILL
    s.set_view(0.1, 0.3)
    zoomed = s.px_per_frame
    s.total_frames = 0
    assert s.px_per_frame == zoomed


def test_scroll_range_follows_content_with_room_to_spare():
    s = state()
    assert s.scroll_frames == DEFAULT_VISIBLE_FRAMES      # empty
    s.total_frames = DEFAULT_VISIBLE_FRAMES * 2
    # there is always empty timeline past the last clip to drop into
    assert s.scroll_frames > s.total_frames


def test_the_room_past_the_last_clip_is_a_share_of_the_screen():
    """A fixed frame count is a shrinking share of the width as a
    project grows: 900 frames is under 1% of an hour-long timeline
    zoomed to fit — about nine pixels, with nowhere to drop a clip."""
    for frames in (17982, 107892, 323676):        # 10 min, 1 hr, 3 hr
        s = state()
        s.total_frames = frames
        s.zoom_to_fit(0, frames)
        pad_px = (s.scroll_frames - s.total_frames) * s.px_per_frame
        assert pad_px == pytest.approx(CANVAS * SCROLL_PAD_FRACTION,
                                       rel=0.02), frames


def test_the_room_does_not_shrink_as_the_project_grows():
    short, long = state(), state()
    short.total_frames = 17982
    short.zoom_to_fit(0, 17982)
    long.total_frames = 323676
    long.zoom_to_fit(0, 323676)
    short_px = (short.scroll_frames - short.total_frames) * short.px_per_frame
    long_px  = (long.scroll_frames - long.total_frames) * long.px_per_frame
    assert long_px == pytest.approx(short_px, rel=0.02)


def test_zoomed_in_the_room_does_not_become_a_wasteland():
    """Proportional cuts both ways: a quarter of a tight zoom is a
    few frames, not the 900 that used to be appended regardless —
    which was seven screens of empty timeline to scroll back over."""
    s = state()
    s.total_frames = 107892
    for _ in range(12):
        s.zoom_in_at_position(0.5, factor=0.5)
    pad = s.scroll_frames - s.total_frames
    assert 0 < pad < 900
    assert pad == pytest.approx(s.visible_frames * SCROLL_PAD_FRACTION)


def test_total_frames_announces_itself():
    """It is half the scroll range; a silent change left the widgets
    drawing at a scale nobody told them about."""
    s = state()
    seen = []
    s.zoom_changed.connect(lambda a, b: seen.append((a, b)))
    s.total_frames = 1794
    assert len(seen) == 1
    s.total_frames = 1794          # no change, no signal
    assert len(seen) == 1


def test_frame_pixel_roundtrip_at_any_zoom():
    s = state()
    s.total_frames = 6 * STILL
    for view in ((0.0, 1.0), (0.1, 0.4), (0.5, 0.52)):
        s.set_view(*view)
        for frame in (0, 1, STILL, 1794):
            px = s.frame_to_pixel(frame, CANVAS)
            assert s.pixel_to_frame(px, CANVAS) == frame


def test_drag_delta_is_content_independent():
    """A 10px drag must mean the same number of frames regardless of
    what else is on the timeline."""
    s = state()
    s.total_frames = STILL
    small = 10 * s.frames_per_pixel()
    s.total_frames = 100 * STILL
    assert 10 * s.frames_per_pixel() == small


def test_zoom_in_keeps_the_anchor_put():
    s = state()
    s.total_frames = 6 * STILL
    anchor = 0.5
    frame_at_anchor = s.norm_to_frame(anchor)
    px_before = s.frame_to_pixel(frame_at_anchor, CANVAS)
    s.zoom_in_at_position(anchor, factor=0.5)
    px_after = s.frame_to_pixel(frame_at_anchor, CANVAS)
    assert abs(px_after - px_before) < 1.0
    assert s.visible_frames < s.scroll_frames


def test_zoom_limits_hold():
    s = state()
    for _ in range(40):
        s.zoom_in_at_position(0.5, factor=0.5)
    assert s.visible_frames >= MIN_VISIBLE_FRAMES - 1e-6
    for _ in range(40):
        s.zoom_out_at_position(0.5, factor=2.0)
    assert s.visible_frames <= s.scroll_frames + 1e-6
    assert s.view_start >= 0.0 and s.view_end <= 1.0


def test_zoom_to_fit_is_the_one_thing_that_rescales():
    s = state()
    s.total_frames = 6 * STILL
    before = s.px_per_frame
    s.zoom_to_fit(0, 6 * STILL)
    assert s.px_per_frame != before
    # the content now roughly fills the window
    assert 6 * STILL < s.visible_frames < 6 * STILL * 1.25


def test_resize_keeps_the_zoom_and_reveals_more():
    s = state()
    s.total_frames = 6 * STILL
    s.set_view(0.0, 0.25)
    ppf = s.px_per_frame
    visible = s.visible_frames
    s.set_view_width(CANVAS * 2)
    assert s.px_per_frame == ppf          # same scale
    assert s.visible_frames > visible     # more time on screen


def test_still_duration_is_configurable():
    assert STILL_IMAGE_SECONDS > 0
