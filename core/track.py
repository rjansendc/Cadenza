from dataclasses import dataclass, field
from typing import List
from enum import Enum
import uuid

class TrackType(Enum):
    VIDEO = "video"
    AUDIO = "audio"

# Z-order ranges — audio never overlaps video
AUDIO_Z_BASE = 0       # A1=0, A2=1, A3=2 ...
VIDEO_Z_BASE  = 1000   # V1=1000, V2=1001 ...

@dataclass
class Track:
    track_type: TrackType
    index:      int          # 0-based

    id:      str  = field(default_factory=lambda: str(uuid.uuid4()))
    name:    str  = ''
    z_order: int  = 0        # set in __post_init__

    # State
    muted:   bool = False
    solo:    bool = False
    locked:  bool = False
    visible: bool = True     # video only
    height:  int  = 40       # px in timeline UI

    def __post_init__(self):
        if not self.name:
            prefix = 'V' if self.track_type == TrackType.VIDEO \
                     else 'A'
            self.name = f"{prefix}{self.index + 1}"
        # assign z_order from range
        if self.track_type == TrackType.VIDEO:
            self.z_order = VIDEO_Z_BASE + self.index
        else:
            self.z_order = AUDIO_Z_BASE + self.index

@dataclass
class SequenceSettings:
    width:          int   = 1920
    height:         int   = 1080
    fps:            float = 29.97
    sample_rate:    int   = 48000
    audio_channels: int   = 2

@dataclass
class Sequence:
    name:     str = 'Sequence 01'
    id:       str = field(
        default_factory=lambda: str(uuid.uuid4())
    )
    settings: SequenceSettings = field(
        default_factory=SequenceSettings
    )
    video_tracks: List[Track] = field(default_factory=list)
    audio_tracks: List[Track] = field(default_factory=list)

    def __post_init__(self):
        if not self.video_tracks:
            self.video_tracks = [
                Track(TrackType.VIDEO, i) for i in range(3)
            ]
        if not self.audio_tracks:
            self.audio_tracks = [
                Track(TrackType.AUDIO, i) for i in range(3)
            ]

    def all_tracks_by_z(self) -> List[Track]:
        """All tracks sorted by z_order — compositor render order."""
        all_tracks = self.video_tracks + self.audio_tracks
        return sorted(all_tracks, key=lambda t: t.z_order)