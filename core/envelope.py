from dataclasses import dataclass, field
from typing import List, Optional


# What range each curve lives in, by parameter. These match the clamps
# the renderer applies when it reads them. Envelopes belonging to an
# effect parameter are keyed "<effect>.<param>" and carry their range in
# the effect's own ParamDef, so they are left unclamped here.
PARAM_RANGES = {
    'opacity': (0.0, 1.0),
    'volume':  (0.0, 2.0),      # 2.0 = +6dB
    'pan':     (-1.0, 1.0),     # -1 left, +1 right
}


def _clamp(value: float, lo, hi) -> float:
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


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

    @property
    def value_range(self) -> tuple:
        """(low, high) for this parameter, (None, None) if unbounded."""
        return PARAM_RANGES.get(self.param, (None, None))

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
        """
        Move the whole curve — what dragging the rubber band does.

        With no keyframes that is just the flat value. With keyframes
        the curve shifts bodily, so a fade keeps its shape and only its
        level changes.

        The shift is limited so that no keyframe leaves the parameter's
        range, rather than clamping each keyframe on its own: clamping
        individually would flatten the curve against the limit and the
        shape would not come back when dragged the other way.

        The delta used to be computed after default_value had already
        been overwritten, so it was always zero and the keyframes never
        moved at all.
        """
        lo, hi = self.value_range

        if self.keyframes:
            delta = value - self.default_value
            if delta > 0 and hi is not None:
                headroom = hi - max(kf.value for kf in self.keyframes)
                delta = min(delta, max(0.0, headroom))
            elif delta < 0 and lo is not None:
                headroom = lo - min(kf.value for kf in self.keyframes)
                delta = max(delta, min(0.0, headroom))
            if delta:
                for kf in self.keyframes:
                    kf.value = kf.value + delta

        self.default_value = _clamp(value, lo, hi)

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