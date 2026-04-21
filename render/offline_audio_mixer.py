"""
OfflineAudioMixer — synchronous audio rendering for export.

No threads. No ring buffer. No real-time constraints.

Given a frame number and exact sample count needed,
returns the mixed audio for that frame.

Uses the same ClipRenderer and StreamingAudioDecoder
as the playback mixer — same mapping, same accuracy.

Sample-accurate sync:
  At 29.97fps, frames alternate between needing
  1601 and 1602 samples. The exporter tracks a
  running sample counter and passes the exact
  count needed to keep video/audio in sync.
"""

import numpy as np
from typing import List, Optional, Dict

from core.clip import Clip
from core.clip_renderer import ClipRenderer
from media.streaming_audio_decoder import (
    StreamingAudioDecoder
)


class OfflineAudioMixer:
    """
    Synchronous audio mixer for export.

    Usage:
        mixer = OfflineAudioMixer(
            sample_rate=48000, channels=2, fps=29.97
        )
        mixer.prepare(clips, sequence)

        for frame in range(start, end):
            n       = exact_samples_for_frame(frame)
            chunk   = mixer.render_frame(clips, frame, n)
            # encode chunk to AAC
    """

    def __init__(self,
                 sample_rate: int   = 48000,
                 channels:    int   = 2,
                 fps:         float = 29.97):
        self.sample_rate = sample_rate
        self.channels    = channels
        self.fps         = fps

        self._decoders:  Dict[str, StreamingAudioDecoder] = {}
        self._sequence   = None

    # =========================================================
    # Setup
    # =========================================================

    def prepare(self, clips: List[Clip],
                sequence=None,
                start_frame: int = 0):
        """
        Open decoders and seek to start position.
        Call once before the export loop begins.
        """
        self._sequence = sequence
        start_time     = start_frame / self.fps

        for clip in clips:
            if not clip.has_audio:
                continue
            decoder = self._get_decoder(clip.filepath)
            if decoder:
                decoder.prime(start_time)

    # =========================================================
    # Core render method
    # =========================================================

    def render_frame(self,
                     clips:       List[Clip],
                     frame:       int,
                     num_samples: int
                     ) -> np.ndarray:
        """
        Mix all active audio clips at frame.
        Returns [channels, num_samples] float32.

        num_samples must be computed by the caller
        using a running sample counter for
        sample-accurate sync:

            target = int((frame+1) * sample_rate / fps)
            n      = target - samples_written
            chunk  = mixer.render_frame(clips, frame, n)
            samples_written += n
        """
        output = np.zeros(
            (self.channels, num_samples),
            dtype=np.float32
        )

        active = self._get_active(clips, frame)

        for renderer in active:
            decoder = self._get_decoder(
                renderer.clip.filepath
            )
            if decoder is None:
                continue

            source_time = renderer.timeline_to_source_time(
                frame
            )

            try:
                samples = decoder.get_samples(
                    source_time, num_samples
                )
            except Exception as e:
                print(f"[OfflineMixer] decode error "
                      f"frame {frame}: {e}")
                continue

            samples = self._match_channels(samples)
            volume  = renderer.get_volume_at(frame)
            pan     = renderer.get_pan_at(frame)

            if self.channels >= 2:
                l_gain = min(1.0, 1.0 - pan)
                r_gain = min(1.0, 1.0 + pan)
                output[0] += samples[0] * volume * l_gain
                output[1] += (
                    samples[min(1, samples.shape[0]-1)]
                    * volume * r_gain
                )
            else:
                output[0] += samples[0] * volume

        np.clip(output, -1.0, 1.0, out=output)
        return output

    # =========================================================
    # Helpers
    # =========================================================

    def _get_active(self,
                    clips: List[Clip],
                    frame: int) -> List[ClipRenderer]:
        """
        Build renderers for clips active at frame.
        Respects mute and solo.
        """
        soloed = set()
        if self._sequence:
            soloed = {
                t.index for t in
                self._sequence.audio_tracks
                if t.solo
            }

        result = []
        for clip in clips:
            if not clip.has_audio:
                continue

            renderer = ClipRenderer(clip)
            if not renderer.is_active_at(frame):
                continue
            if clip.muted:
                continue
            if self._sequence:
                tracks = self._sequence.audio_tracks
                if clip.track < len(tracks):
                    if tracks[clip.track].muted:
                        continue
            if soloed and clip.track not in soloed:
                continue

            result.append(renderer)

        return result

    def _get_decoder(self,
                     filepath: str
                     ) -> Optional[StreamingAudioDecoder]:
        if filepath not in self._decoders:
            try:
                self._decoders[filepath] = (
                    StreamingAudioDecoder(
                        filepath,
                        target_sample_rate=self.sample_rate
                    )
                )
            except Exception as e:
                print(f"[OfflineMixer] decoder error: {e}")
                return None
        return self._decoders.get(filepath)

    def _match_channels(self,
                         samples: np.ndarray
                         ) -> np.ndarray:
        src = samples.shape[0]
        if src == self.channels:
            return samples
        if src == 1:
            return np.repeat(
                samples, self.channels, axis=0
            )
        if src > self.channels:
            return samples[:self.channels]
        pad = np.zeros(
            (self.channels - src, samples.shape[1]),
            dtype=np.float32
        )
        return np.concatenate([samples, pad], axis=0)

    def close(self):
        """Release all decoders."""
        self._decoders.clear()
