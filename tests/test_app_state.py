from ui.app_state import AppState

def test_initial_state():
    state = AppState()
    assert state.playhead_frame == 0
    assert state.active_tool == 'select'
    assert state.view_start == 0.0
    assert state.view_end == 1.0
    assert state.zoom_level == 1.0

def test_playhead_signal(qtbot):
    state = AppState()
    frames_received = []
    state.playhead_changed.connect(
        lambda f: frames_received.append(f)
    )
    state.playhead_frame = 100
    assert frames_received == [100]
    assert state.playhead_frame == 100

def test_zoom_in_at_position():
    state = AppState()
    state.total_frames = 1000
    # zoom in at center
    state.zoom_in_at_position(0.5, factor=0.5)
    assert state.view_start > 0.0
    assert state.view_end < 1.0
    # center should still be roughly 0.5
    center = (state.view_start + state.view_end) / 2
    assert abs(center - 0.5) < 0.01

def test_zoom_clamps_to_bounds():
    state = AppState()
    # try to zoom way out past bounds
    state.set_view(-1.0, 2.0)
    assert state.view_start >= 0.0
    assert state.view_end   <= 1.0

def test_pan_clamps_to_bounds():
    state = AppState()
    state.set_view(0.0, 0.5)
    state.pan_by(-0.5)   # try to pan left past start
    assert state.view_start >= 0.0

def test_frame_pixel_roundtrip():
    state = AppState()
    state.total_frames = 1000
    view_width = 800.0
    frame = 250
    pixel = state.frame_to_pixel(frame, view_width)
    result = state.pixel_to_frame(pixel, view_width)
    assert result == frame

def test_tool_change():
    state = AppState()
    state.active_tool = 'razor'
    assert state.active_tool == 'razor'
    # invalid tool ignored
    state.active_tool = 'invalid'
    assert state.active_tool == 'razor'

def test_timecode():
    state = AppState()
    tc = state.frame_to_timecode(0)
    assert tc == '00:00:00:00'
    tc = state.frame_to_timecode(30, fps=30.0)
    assert tc == '00:00:01:00'