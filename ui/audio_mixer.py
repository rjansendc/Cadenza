"""
AudioMixer — background thread that mixes all
active audio clips into the ring buffer.
"""

import threading
import time
import numpy as np
from typing import List, Optional

from core.clip import Clip
from core.clip_renderer import ClipRenderer
from media.streaming_audio_decoder import StreamingAudioDecoder
from ui.ring_buffer import RingBuffer

RING_BUFFER_SECONDS = 5.0
RING_LOW_WATERMARK  = 2.0
MIX_CHUNK_SECONDS   = 0.2
PREFILL_SECONDS     = 3.0


class AudioMixer(threading.Thread):

    def __init__(self, sample_rate=48000, channels=2, fps=29.97):
        super().__init__(daemon=True, name='AudioMixer')
        self.sample_rate = sample_rate
        self.channels    = channels
        self.fps         = fps

        self.ring = RingBuffer(
            capacity_seconds=RING_BUFFER_SECONDS,
            sample_rate=sample_rate,
            channels=channels
        )

        self._clips      = []
        self._renderers  = []
        self._decoders   = {}
        self._sequence   = None
        self._clips_lock = threading.Lock()

        self._playing    = False
        self._mix_frame  = 0
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()

        self._chunk_samples = int(sample_rate * MIX_CHUNK_SECONDS)
        self._low_samples   = int(sample_rate * RING_LOW_WATERMARK)

    def set_clips(self, clips, sequence=None):
        with self._clips_lock:
            self._clips     = list(clips)
            self._sequence  = sequence
            self._renderers = [
                ClipRenderer(c) for c in clips if c.has_audio
            ]
            for clip in clips:
                if clip.has_audio:
                    self._ensure_decoder(clip.filepath)

    def play(self, frame: int):
        self._playing   = False
        self._mix_frame = frame

        start_time = frame / self.fps
        with self._clips_lock:
            for dec in self._decoders.values():
                try:
                    dec.prime(start_time)
                except Exception as e:
                    print(f"[Mixer] prime error: {e}")

        self.ring.clear()
        self._mix_frame = self._do_prefill(frame)
        self._playing   = True
        self._wake_event.set()

    def pause(self):
        self._playing = False

    def seek(self, frame: int):
        """Only call this during manual scrub, not during playback."""
        self._playing   = False
        self._mix_frame = frame
        self.ring.clear()
        seek_time = frame / self.fps
        with self._clips_lock:
            for dec in self._decoders.values():
                try:
                    dec.prime(seek_time)
                except Exception as e:
                    print(f"[Mixer] seek prime error: {e}")

    def stop(self):
        self._playing = False
        self._stop_event.set()
        self._wake_event.set()

    def run(self):
        while not self._stop_event.is_set():
            if not self._playing:
                self._wake_event.wait(timeout=0.05)
                self._wake_event.clear()
                continue

            if self.ring.available < self._low_samples:
                chunk  = self._mix_chunk(self._mix_frame,
                                          self._chunk_samples)
                written = self.ring.write(chunk)
                if written > 0:
                    self._mix_frame += int(
                        written / self.sample_rate * self.fps
                    )
            else:
                sleep_time = (
                    (self.ring.available - self._low_samples)
                    / self.sample_rate
                )
                time.sleep(max(0.01, sleep_time * 0.5))

    def _do_prefill(self, start_frame: int) -> int:
        target = int(PREFILL_SECONDS * self.sample_rate)
        frame  = start_frame
        while self.ring.available < target:
            chunk   = self._mix_chunk(frame, self._chunk_samples)
            written = self.ring.write(chunk)
            if written <= 0:
                break
            frame += int(written / self.sample_rate * self.fps)
        return frame

    def _mix_chunk(self, start_frame, num_samples):
        output = np.zeros((self.channels, num_samples),
                          dtype=np.float32)

        with self._clips_lock:
            renderers = list(self._renderers)
            sequence  = self._sequence

        active = self._get_active(renderers, start_frame, sequence)

        for renderer in active:
            decoder = self._ensure_decoder(renderer.clip.filepath)
            if decoder is None:
                continue
            source_time = renderer.timeline_to_source_time(start_frame)
            try:
                samples = decoder.get_samples(source_time, num_samples)
            except Exception as e:
                print(f"[Mixer] decode error: {e}")
                continue

            samples = self._match_channels(samples)
            volume  = renderer.get_volume_at(start_frame)
            pan     = renderer.get_pan_at(start_frame)

            if self.channels >= 2:
                l_gain = min(1.0, 1.0 - pan)
                r_gain = min(1.0, 1.0 + pan)
                output[0] += samples[0] * volume * l_gain
                output[1] += (samples[min(1, samples.shape[0]-1)]
                               * volume * r_gain)
            else:
                output[0] += samples[0] * volume

        np.clip(output, -1.0, 1.0, out=output)
        return output

    def _get_active(self, renderers, frame, sequence):
        soloed = set()
        if sequence:
            soloed = {t.index for t in sequence.audio_tracks
                      if t.solo}
        result = []
        for r in renderers:
            if not r.is_active_at(frame):
                continue
            if r.clip.muted:
                continue
            if sequence:
                tracks = sequence.audio_tracks
                if r.clip.track < len(tracks):
                    if tracks[r.clip.track].muted:
                        continue
            if soloed and r.clip.track not in soloed:
                continue
            result.append(r)
        return result

    def _match_channels(self, samples):
        src = samples.shape[0]
        if src == self.channels:
            return samples
        if src == 1:
            return np.repeat(samples, self.channels, axis=0)
        if src > self.channels:
            return samples[:self.channels]
        pad = np.zeros((self.channels - src, samples.shape[1]),
                       dtype=np.float32)
        return np.concatenate([samples, pad], axis=0)

    def _ensure_decoder(self, filepath):
        if filepath not in self._decoders:
            try:
                self._decoders[filepath] = StreamingAudioDecoder(
                    filepath, target_sample_rate=self.sample_rate
                )
            except Exception as e:
                print(f"[Mixer] decoder error: {e}")
                return None
        return self._decoders.get(filepath)

    def close(self):
        self.stop()
        self._decoders.clear()
        self.ring.clear()
