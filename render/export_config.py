"""
ExportConfig — all parameters for a single export operation.

Designed to be:
  - Serializable to JSON for save/load later
  - Passable to ExportThread as a single argument
  - Displayable in an export dialog
  - Extensible without breaking existing code

Add new fields with defaults and nothing breaks.
"""

from dataclasses import dataclass, field, asdict
import json


# =========================================================
# Option sets — used by the dialog dropdowns
# =========================================================

RESOLUTION_PRESETS = {
    '1920 x 1080 (HD)':  (1920, 1080),
    '1280 x 720 (720p)': (1280, 720),
    '3840 x 2160 (4K)':  (3840, 2160),
    '1080 x 1920 (Vertical HD)': (1080, 1920),
}

QUALITY_PRESETS = {
    'High (CRF 18)':   18,
    'Medium (CRF 23)': 23,
    'Web (CRF 28)':    28,
}

SPEED_PRESETS = {
    'Fast':   'fast',
    'Medium': 'medium',
    'Slow (best compression)': 'slow',
}

ENCODER_PRESETS = {
    'H.264 Software (x264)':    'h264',
    'H.264 NVIDIA GPU (nvenc)': 'h264_nvenc',
    'H.265 NVIDIA GPU (nvenc)': 'hevc_nvenc',
    'H.265 Software (x265)':    'h265',
}

AUDIO_BITRATE_OPTIONS = {
    '320 kbps': '320k',
    '256 kbps': '256k',
    '192 kbps': '192k',
    '128 kbps': '128k',
}


@dataclass
class ExportConfig:
    """
    All parameters for a single export operation.

    Sensible defaults produce a high-quality 1080p MP4
    with no configuration needed.
    """

    # ── Output ────────────────────────────────────────
    output_path:    str  = ''

    # ── Video ─────────────────────────────────────────
    width:          int  = 1920
    height:         int  = 1080
    crf:            int  = 18       # 0=lossless 51=worst
    preset:         str  = 'fast'   # fast/medium/slow
    fps:            float = 0.0     # 0 = match sequence
    encoder:        str  = 'h264_nvenc'  # h264/h264_nvenc/hevc_nvenc/h265

    # ── Audio ─────────────────────────────────────────
    sample_rate:    int  = 0        # 0 = match sequence
    channels:       int  = 2
    audio_bitrate:  str  = '192k'

    # ── Range ─────────────────────────────────────────
    # -1 = use sequence value
    start_frame:    int  = 0
    end_frame:      int  = -1

    # ── Metadata (future use) ─────────────────────────
    title:          str  = ''
    comment:        str  = 'Created with VideoEditor'

    # =========================================================
    # Helpers
    # =========================================================

    def resolved_fps(self, sequence_fps: float) -> float:
        return self.fps if self.fps > 0 else sequence_fps

    def resolved_sample_rate(self,
                              sequence_sr: int) -> int:
        return (self.sample_rate if self.sample_rate > 0
                else sequence_sr)

    def resolved_end_frame(self,
                            sequence_frames: int) -> int:
        return (self.end_frame if self.end_frame > 0
                else sequence_frames)

    def total_frames(self, sequence_frames: int) -> int:
        return (self.resolved_end_frame(sequence_frames)
                - self.start_frame)

    # =========================================================
    # Serialization — for save/load later
    # =========================================================

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> 'ExportConfig':
        data = json.loads(json_str)
        return cls(**{
            k: v for k, v in data.items()
            if k in cls.__dataclass_fields__
        })

    def __repr__(self):
        return (
            f"ExportConfig("
            f"{self.width}x{self.height} "
            f"CRF{self.crf} {self.preset} | "
            f"{self.audio_bitrate} | "
            f"frames {self.start_frame}-{self.end_frame})"
        )
