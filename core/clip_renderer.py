"""
ClipRenderer — pure math, no I/O, no GPU.

Owns the complete mapping from timeline position
to source file position for one clip.

Handles:
  - in_point / out_point (razor cuts, trim)
  - start_frame (timeline placement)
  - speed / reverse (time remapping)
  - volume envelope (local frame evaluation)
  - opacity envelope (local frame evaluation)

Testable without any files or GPU.
"""

from core.clip import Clip


class ClipRenderer:
    """
    Maps timeline frames to source file positions.
    One instance per clip on the timeline.
    """

    def __init__(self, clip: Clip):
        self.clip = clip

    # =========================================================
    # Activity check
    # =========================================================

    def is_active_at(self, timeline_frame: int) -> bool:
        """Is this clip playing at timeline_frame?"""
        if not self.clip.enabled:
            return False
        end = self.clip.start_frame + self.clip.duration
        return self.clip.start_frame <= timeline_frame < end

    # =========================================================
    # Core mapping
    # =========================================================

    def timeline_to_source_time(self,
                                 timeline_frame: int
                                 ) -> float:
        """
        Map a timeline frame to source file time (seconds).

        Equation:
          local_frame  = timeline_frame - start_frame
          clip_frame   = local_frame * speed (+ reverse)
          source_frame = in_point + clip_frame
          source_time  = source_frame / source_fps

        Razor cuts, moves, speed changes all just
        modify clip fields — this equation stays the same.
        """
        local_frame = (timeline_frame -
                       self.clip.start_frame)
        local_frame = max(0, local_frame)

        speed, reverse = self._get_time_remap()

        if reverse:
            clip_frame = (
                (self.clip.duration - 1 - local_frame)
                * speed
            )
        else:
            clip_frame = local_frame * speed

        clip_frame   = max(0.0, clip_frame)
        source_frame = self.clip.in_point + clip_frame

        if self.clip.source_frames > 0:
            source_frame = min(
                source_frame,
                self.clip.source_frames - 1
            )

        fps = self.clip.source_fps or 29.97
        return source_frame / fps

    def timeline_to_source_frame(self,
                                  timeline_frame: int
                                  ) -> int:
        """Map timeline frame to integer source frame."""
        source_time = self.timeline_to_source_time(
            timeline_frame
        )
        fps = self.clip.source_fps or 29.97
        return int(source_time * fps)

    # =========================================================
    # Envelope evaluation — always in LOCAL frame time
    # =========================================================

    def local_frame(self, timeline_frame: int) -> int:
        """
        Frame position relative to clip start.
        Envelopes ALWAYS evaluate here.
        A fade-in at frames 0-30 fades in at the
        same rate regardless of timeline position.
        """
        return max(0, timeline_frame -
                   self.clip.start_frame)

    def get_volume_at(self, timeline_frame: int) -> float:
        """Volume at timeline_frame. 0.0 if muted."""
        if self.clip.muted:
            return 0.0
        lf  = self.local_frame(timeline_frame)
        env = self.clip.envelopes.get('volume')
        if env:
            return max(0.0, min(2.0, env.value_at(lf)))
        return max(0.0, min(2.0, self.clip.volume))

    def get_opacity_at(self,
                        timeline_frame: int) -> float:
        """Opacity at timeline_frame."""
        lf  = self.local_frame(timeline_frame)
        env = self.clip.envelopes.get('opacity')
        if env:
            return max(0.0, min(1.0, env.value_at(lf)))
        return 1.0

    def get_pan_at(self, timeline_frame: int) -> float:
        """Pan at timeline_frame. -1=left, 0=center, 1=right"""
        lf  = self.local_frame(timeline_frame)
        env = self.clip.envelopes.get('pan')
        if env:
            return max(-1.0, min(1.0, env.value_at(lf)))
        return 0.0

    def get_motion_at(self, timeline_frame: int) -> dict:
        """Motion effect parameters at timeline_frame."""
        motion = self.clip.get_effect('motion')
        if motion is None:
            return {
                'position_x':   960.0,
                'position_y':   540.0,
                'scale':        100.0,
                'scale_x':      100.0,
                'uniform_scale': True,
                'rotation':     0.0,
                'anchor_x':     960.0,
                'anchor_y':     540.0,
                'crop_left':    0.0,
                'crop_right':   0.0,
                'crop_top':     0.0,
                'crop_bottom':  0.0,
            }
        return {k: motion.get(k) for k in [
            'position_x', 'position_y', 'scale',
            'scale_x', 'uniform_scale', 'rotation',
            'anchor_x', 'anchor_y',
            'crop_left', 'crop_right',
            'crop_top', 'crop_bottom',
        ]}

    # =========================================================
    # Private
    # =========================================================

    def _get_time_remap(self) -> tuple:
        tr = self.clip.get_effect('time_remap')
        if tr:
            # speed is stored as a percentage (100.0 = normal speed)
            # convert to a multiplier (1.0 = normal speed)
            speed_pct = tr.get('speed') or 100.0
            speed = max(0.0001, speed_pct / 100.0)
            return (speed, bool(tr.get('reverse') or False))
        return (1.0, False)

    def __repr__(self):
        return (
            f"ClipRenderer({self.clip.name} | "
            f"start={self.clip.start_frame} | "
            f"in={self.clip.in_point} | "
            f"dur={self.clip.duration})"
        )
