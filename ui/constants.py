# Shared UI constants — import from here everywhere.
# Change one value and the whole UI stays consistent.

TRACK_HEIGHT       = 40    # px per track row (default)
TRACK_HEADER_WIDTH = 140   # px for left header column
CLIP_PADDING       = 1     # px top/bottom within row
RULER_HEIGHT       = 28    # px for timecode ruler
ZOOM_BAR_HEIGHT    = 16    # px for zoom bar

NUM_VIDEO_TRACKS   = 3     # default — can grow dynamically
NUM_AUDIO_TRACKS   = 3     # default — can grow dynamically

# track row indices (V3=0 top, V1=2, A1=3, A3=5 bottom)
def video_row(track_index: int) -> int:
    """V1=index 0 → row 2 (bottom of video section)"""
    return (NUM_VIDEO_TRACKS - 1) - track_index

def audio_row(track_index: int) -> int:
    """A1=index 0 → row 3 (top of audio section)"""
    return NUM_VIDEO_TRACKS + track_index

def row_to_y(row: int) -> float:
    return float(row * TRACK_HEIGHT)

def y_to_row(y: float, clamp: bool = True,
             n_video: int = None, n_audio: int = None) -> int:
    nv = n_video if n_video is not None else NUM_VIDEO_TRACKS
    na = n_audio if n_audio is not None else NUM_AUDIO_TRACKS
    row = int(y // TRACK_HEIGHT)
    if clamp:
        row = max(0, min(row, nv + na - 1))
    return row

def row_is_video(row: int, n_video: int = None) -> bool:
    nv = n_video if n_video is not None else NUM_VIDEO_TRACKS
    return row < nv

def row_is_audio(row: int, n_video: int = None) -> bool:
    nv = n_video if n_video is not None else NUM_VIDEO_TRACKS
    return row >= nv

def snap_row_for_clip(row: int,
                       has_video: bool,
                       has_audio: bool,
                       n_video: int = None,
                       n_audio: int = None) -> int:
    nv = n_video if n_video is not None else NUM_VIDEO_TRACKS
    na = n_audio if n_audio is not None else NUM_AUDIO_TRACKS
    if has_video and not has_audio:
        return max(0, min(row, nv - 1))
    elif has_audio and not has_video:
        return max(nv, min(row, nv + na - 1))
    else:
        return max(0, min(row, nv + na - 1))

def row_to_track_index(row: int, n_video: int = None) -> tuple:
    nv = n_video if n_video is not None else NUM_VIDEO_TRACKS
    if row_is_video(row, nv):
        return ('video', (nv - 1) - row)
    else:
        return ('audio', row - nv)

def compute_track_layout(sequence) -> dict:
    """
    Compute Y positions using actual track.height values.
    Returns {rows: [{track, y, height}], total_height}
    """
    rows  = []
    y_pos = 0

    # V3 first (top), V1 last
    for track in reversed(sequence.video_tracks):
        rows.append({
            'track':  track,
            'y':      y_pos,
            'height': track.height
        })
        y_pos += track.height

    # A1 first, A3 last
    for track in sequence.audio_tracks:
        rows.append({
            'track':  track,
            'y':      y_pos,
            'height': track.height
        })
        y_pos += track.height

    return {'rows': rows, 'total_height': y_pos}

def get_clip_row(sequence, clip) -> dict:
    """
    Get the row dict for a clip's track.
    Returns {'track': ..., 'y': ..., 'height': ...}
    or None if not found.
    """
    from core.track import TrackType
    layout = compute_track_layout(sequence)
    for row in layout['rows']:
        t = row['track']
        if (clip.has_video and
                t.track_type == TrackType.VIDEO and
                t.index == clip.track):
            return row
        if (not clip.has_video and
                clip.has_audio and
                t.track_type == TrackType.AUDIO and
                t.index == clip.track):
            return row
    return None

def scene_y_to_row(scene_y: float,
                    sequence=None) -> int:
    """
    Convert scene y coordinate to row index.
    Uses actual track heights if sequence provided,
    otherwise falls back to fixed TRACK_HEIGHT.
    """
    if sequence is None:
        return y_to_row(scene_y)

    layout = compute_track_layout(sequence)
    for i, row in enumerate(layout['rows']):
        if row['y'] <= scene_y < row['y'] + row['height']:
            return i
    return len(layout['rows']) - 1
