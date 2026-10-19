# Shared UI constants — import from here everywhere.
# Change one value and the whole UI stays consistent.

TRACK_HEIGHT       = 40    # px per track row (default)
TRACK_HEADER_WIDTH = 140   # px for left header column
CLIP_PADDING       = 1     # px top/bottom within row
RULER_HEIGHT       = 28    # px for timecode ruler
ZOOM_BAR_HEIGHT    = 16    # px for zoom bar

NUM_VIDEO_TRACKS   = 3     # default — can grow dynamically
NUM_AUDIO_TRACKS   = 3     # default — can grow dynamically

# ── Timeline scale ─────────────────────────────────────────
# The zoom is absolute — pixels per frame — so editing never rescales
# the ruler. A fresh sequence shows DEFAULT_VISIBLE_FRAMES of time,
# which puts a 10 second still at about a twentieth of the width.
#
# The scale used to be a normalized fraction of the project length, so
# every edit that changed that length silently rescaled the whole
# timeline: six identical stills ended up drawn at six different
# widths, and stretching one moved all the others.
DEFAULT_VISIBLE_FRAMES = 5400   # ~3 minutes at 30fps
# Empty room past the last clip, so there is always somewhere to drop
# a new clip on a full timeline. A share of the visible span rather
# than a frame count: a fixed 900 frames was half a screen zoomed in
# and, on an hour-long project zoomed to fit, under 1% of the ruler —
# about nine pixels, with nowhere to aim. A short project still gets
# DEFAULT_VISIBLE_FRAMES of ruler, which is its own floor.
SCROLL_PAD_FRACTION    = 0.25   # a quarter of the visible span
MIN_VISIBLE_FRAMES     = 12     # how far in the zoom may go

# Frame sizes offered in the sequence and export dialogs. One list,
# so the two cannot drift: export knew about portrait while the
# sequence dialog did not, so a vertical sequence had to be typed in
# by hand even though export offered it as a preset.
FRAME_SIZES = [
    ('1920 x 1080  (1080p HD)',    1920, 1080),
    ('3840 x 2160  (4K UHD)',      3840, 2160),
    ('1280 x 720   (720p HD)',     1280,  720),
    ('720 x 480    (480p SD)',      720,  480),
    ('1080 x 1920  (Vertical HD)', 1080, 1920),
    ('2160 x 3840  (Vertical 4K)', 2160, 3840),
]

# How long a still runs when imported. Premiere keeps this in
# Preferences > Timeline > Still image default duration.
STILL_IMAGE_SECONDS    = 10.0

# track row indices (V3=0 top, V1=2, A1=3, A3=5 bottom).
# n_video defaults to the constant for callers with no sequence to
# hand, but a sequence that has had tracks added must pass its own
# count — otherwise every row below V3 is computed one short.
def video_row(track_index: int, n_video: int = None) -> int:
    """V1=index 0 → the bottom row of the video section"""
    nv = n_video if n_video is not None else NUM_VIDEO_TRACKS
    return (nv - 1) - track_index

def audio_row(track_index: int, n_video: int = None) -> int:
    """A1=index 0 → the first row below the video section"""
    nv = n_video if n_video is not None else NUM_VIDEO_TRACKS
    return nv + track_index

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
