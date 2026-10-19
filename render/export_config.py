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

def _frame_sizes():
    """The sizes both dialogs offer, from the one list that defines
    them. Kept importable without Qt — ui.constants pulls in none."""
    from ui.constants import FRAME_SIZES
    return {label.strip(): (w, h) for label, w, h in FRAME_SIZES}


RESOLUTION_PRESETS = _frame_sizes()

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


ILLEGAL_IN_FILENAMES = '<>:"/\\|?*'


def safe_filename(name: str) -> str:
    """A sequence name turned into something Windows will accept."""
    cleaned = ''.join(
        ' ' if ch in ILLEGAL_IN_FILENAMES else ch
        for ch in (name or '')
    )
    cleaned = ' '.join(cleaned.split()).strip(' .')
    return cleaned or 'Untitled'


def suggest_output_path(project=None, sequence=None,
                        last_dir: str = '') -> str:
    """
    Where an export should go before the user says otherwise.

    In order: the file this project was exported to last (as long as
    its folder is still there), then the sequence's own name in the
    folder last exported to, then beside the project file.

    Premiere names the file after the sequence; the field here started
    empty and Browse proposed 'output.mp4' in whatever directory the
    app happened to be launched from.
    """
    import os

    remembered = getattr(project, 'export_path', '') or ''
    if remembered and os.path.isdir(os.path.dirname(remembered)):
        return remembered

    name = None
    if sequence is not None:
        name = getattr(sequence, 'name', None)
    if not name and project is not None:
        name = getattr(project, 'name', None)
    filename = f'{safe_filename(name)}.mp4'

    folder = last_dir if last_dir and os.path.isdir(last_dir) else ''
    if not folder and project is not None:
        project_path = getattr(project, 'project_path', '') or ''
        if project_path:
            beside = os.path.dirname(project_path)
            if os.path.isdir(beside):
                folder = beside

    return os.path.join(folder, filename) if folder else filename


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
