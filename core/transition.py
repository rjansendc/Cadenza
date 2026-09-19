"""
Transitions — currently the cross dissolve.

A transition sits at a cut on one video track and is centred on it: for
a 30 frame dissolve at frame 900, the mix runs from 885 to 915. The
outgoing clip keeps playing past its out point and the incoming one
starts before its in point, which is what "handles" means — those
frames exist in the source file, they were simply trimmed away.

Where a clip has no handles (it was trimmed to the very end of its
media) the decoder returns its last available frame, so the dissolve
still completes, just against a held frame rather than moving pictures.

The compositor draws the outgoing clip normally and the incoming one
over it with rising opacity, which is exactly a cross dissolve.
"""

import uuid
from dataclasses import dataclass, field
from typing import List, Optional

CROSS_DISSOLVE = 'cross_dissolve'

DEFAULT_DURATION = 30          # frames — about a second at 29.97


@dataclass
class Transition:
    """A dissolve centred on a cut, on one track."""

    track:        int                      # track index
    center_frame: int                      # the cut it straddles
    duration:     int = DEFAULT_DURATION   # total length in frames
    kind:         str = CROSS_DISSOLVE
    id:           str = field(
        default_factory=lambda: str(uuid.uuid4()))

    @property
    def start_frame(self) -> int:
        return int(self.center_frame - self.duration // 2)

    @property
    def end_frame(self) -> int:
        return self.start_frame + int(self.duration)

    def covers(self, frame: int) -> bool:
        return self.start_frame <= frame < self.end_frame

    def progress_at(self, frame: int) -> float:
        """0.0 at the start of the mix, 1.0 at its end."""
        if self.duration <= 0:
            return 1.0
        p = (frame - self.start_frame) / float(self.duration)
        return max(0.0, min(1.0, p))

    def __repr__(self):
        return (f"Transition({self.kind} track={self.track} "
                f"@{self.center_frame} len={self.duration})")


def find_at(transitions: List[Transition], track: int,
            frame: int) -> Optional[Transition]:
    """The transition covering this frame on this track, if any."""
    for tr in transitions or []:
        if tr.track == track and tr.covers(frame):
            return tr
    return None


def cut_points(clips, track: int) -> List[int]:
    """
    Frames where one clip ends and the next begins on a track —
    the places a transition can go.
    """
    starts = {}
    ends = {}
    for clip in clips:
        if not clip.has_video or clip.track != track:
            continue
        starts[clip.start_frame] = clip
        ends[clip.start_frame + clip.duration] = clip
    return sorted(f for f in ends if f in starts)


def max_duration(clips, track: int, center: int) -> int:
    """
    The longest dissolve that fits at this cut.

    It cannot eat more than either neighbour's length, or the mix would
    run past the far end of a clip and reveal whatever is underneath.
    """
    outgoing = incoming = None
    for clip in clips:
        if not clip.has_video or clip.track != track:
            continue
        if clip.start_frame + clip.duration == center:
            outgoing = clip
        elif clip.start_frame == center:
            incoming = clip
    if outgoing is None or incoming is None:
        return 0
    return int(min(outgoing.duration, incoming.duration))
