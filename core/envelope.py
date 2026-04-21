from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Keyframe:
    frame: int
    value: float    # 0.0-2.0 volume, 0.0-1.0 opacity

    def __lt__(self, other):
        return self.frame < other.frame


@dataclass
class Envelope:
    """
    Per-clip automation curve.
    No keyframes = flat line at default_value.
    Keyframes = interpolated curve.
    """
    param:         str   # 'volume' or 'opacity'
    default_value: float = 1.0
    keyframes:     List[Keyframe] = field(
        default_factory=list
    )

    def value_at(self, frame: int) -> float:
        """
        Get value at frame.
        No keyframes → flat default_value.
        With keyframes → linear interpolation.
        """
        if not self.keyframes:
            return self.default_value

        # sort keyframes by frame
        kfs = sorted(self.keyframes)

        # before first keyframe
        if frame <= kfs[0].frame:
            return kfs[0].value

        # after last keyframe
        if frame >= kfs[-1].frame:
            return kfs[-1].value

        # find surrounding keyframes
        for i in range(len(kfs) - 1):
            k0 = kfs[i]
            k1 = kfs[i + 1]
            if k0.frame <= frame <= k1.frame:
                # linear interpolation
                t = ((frame - k0.frame) /
                     (k1.frame - k0.frame))
                return k0.value + t * (
                    k1.value - k0.value
                )

        return self.default_value

    def set_default(self, value: float):
        """Drag whole line — no keyframes."""
        self.default_value = value
        # if no keyframes this is all we need
        # if keyframes exist, shift all by delta
        if self.keyframes:
            delta = value - self.default_value
            for kf in self.keyframes:
                kf.value = max(0.0, min(
                    2.0, kf.value + delta
                ))

    def add_keyframe(self, frame: int,
                      value: float):
        """Add or update a keyframe."""
        # remove existing at same frame
        self.keyframes = [
            k for k in self.keyframes
            if k.frame != frame
        ]
        self.keyframes.append(Keyframe(frame, value))
        self.keyframes.sort()

    def remove_keyframe(self, frame: int):
        self.keyframes = [
            k for k in self.keyframes
            if k.frame != frame
        ]

    def clear_keyframes(self):
        self.keyframes = []

    @property
    def is_flat(self) -> bool:
        return len(self.keyframes) == 0

    def __repr__(self):
        if self.is_flat:
            return (f"Envelope({self.param} "
                    f"flat={self.default_value:.2f})")
        return (f"Envelope({self.param} "
                f"{len(self.keyframes)} keyframes)")