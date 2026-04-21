"""
StreamingAudioDecoder

Streams audio from a file using PyAV.
Never loads the full file into memory.
Keeps a rolling decode window around the
current playback position.

Window layout:
  [pos - WINDOW_BEHIND ... pos ... pos + WINDOW_AHEAD]

On seek or window miss: re-seek and refill.
Thread-safe via threading.Lock.
"""

import threading
import numpy as np
import av
import av.audio.resampler
from pathlib import Path

# Window sizes in seconds
WINDOW_BEHIND  = 3.0   # seconds behind current position
WINDOW_AHEAD   = 6.0   # seconds ahead (larger = safer)
TOTAL_WINDOW   = WINDOW_BEHIND + WINDOW_AHEAD

# Output format
OUTPUT_FORMAT  = 'fltp'   # float32 planar
OUTPUT_LAYOUT  = 'stereo'
OUTPUT_CHANNELS = 2


class StreamingAudioDecoder:
    """
    Streaming audio decoder with rolling window.

    Usage:
        decoder = StreamingAudioDecoder('concert.mp4')
        decoder.prime(start_time=120.5)  # before playback
        samples = decoder.get_samples(120.5, 4800)
    """

    def __init__(self, filepath: str,
                 target_sample_rate: int = 48000):
        self.filepath           = str(filepath)
        self.target_sample_rate = target_sample_rate
        self._lock              = threading.Lock()

        # open container to read metadata
        container = av.open(self.filepath)
        stream    = next(
            (s for s in container.streams
             if s.type == 'audio'), None
        )
        if stream is None:
            container.close()
            raise ValueError(
                f"No audio stream in {filepath}"
            )

        self.source_sample_rate = stream.sample_rate
        self.source_channels    = stream.channels
        self.duration           = float(
            container.duration / av.time_base
        ) if container.duration else 0.0
        container.close()

        # window state
        self._window:       np.ndarray = None
        self._window_start: float      = -1.0
        self._window_end:   float      = -1.0

    # =========================================================
    # Public API
    # =========================================================

    def prime(self, time_seconds: float):
        """
        Seek to position and fill window.
        Call before playback starts or after seek.
        Blocks until window is filled.
        """
        seek_to = max(0.0, time_seconds - WINDOW_BEHIND)
        with self._lock:
            self._fill_window(seek_to)

    def get_samples(self,
                    time_seconds: float,
                    num_samples:  int
                    ) -> np.ndarray:
        """
        Get num_samples samples starting at time_seconds.
        Returns [OUTPUT_CHANNELS, num_samples] float32.

        Refills window automatically if needed.
        Thread-safe.
        """
        end_time = (time_seconds +
                    num_samples / self.target_sample_rate)

        with self._lock:
            # check if window covers the request
            margin = 1.0  # 1 second safety margin
            if (self._window is None or
                    time_seconds < self._window_start or
                    end_time > self._window_end - margin):
                seek_to = max(
                    0.0, time_seconds - WINDOW_BEHIND
                )
                self._fill_window(seek_to)

            return self._extract(time_seconds, num_samples)

    def close(self):
        """Release resources."""
        with self._lock:
            self._window       = None
            self._window_start = -1.0
            self._window_end   = -1.0

    # =========================================================
    # Private
    # =========================================================

    def _fill_window(self, seek_time: float):
        """
        Seek PyAV and decode TOTAL_WINDOW seconds.
        Must be called with lock held.
        """
        seek_time = max(0.0, seek_time)

        try:
            container = av.open(self.filepath)
            stream    = next(
                s for s in container.streams
                if s.type == 'audio'
            )

            resampler = av.audio.resampler.AudioResampler(
                format=OUTPUT_FORMAT,
                layout=OUTPUT_LAYOUT,
                rate=self.target_sample_rate
            )

            # seek
            if seek_time > 0:
                pts = int(
                    seek_time /
                    float(stream.time_base)
                )
                container.seek(
                    pts,
                    stream=stream,
                    any_frame=True
                )

            # decode
            chunks           = []
            decoded_duration = 0.0
            target_duration  = TOTAL_WINDOW

            for frame in container.decode(stream):
                resampled = resampler.resample(frame)
                for f in resampled:
                    arr = f.to_ndarray()
                    # arr shape: [channels, samples]
                    chunks.append(
                        arr.astype(np.float32)
                    )
                    decoded_duration += (
                        arr.shape[1] /
                        self.target_sample_rate
                    )
                if decoded_duration >= target_duration:
                    break

            container.close()

            if chunks:
                self._window = np.concatenate(
                    chunks, axis=1
                )
            else:
                # silence if nothing decoded
                silent_samples = int(
                    TOTAL_WINDOW * self.target_sample_rate
                )
                self._window = np.zeros(
                    (OUTPUT_CHANNELS, silent_samples),
                    dtype=np.float32
                )

            self._window_start = seek_time
            self._window_end   = (
                seek_time +
                self._window.shape[1] /
                self.target_sample_rate
            )

        except Exception as e:
            print(f"StreamingAudioDecoder fill error: {e}")
            # fill with silence on error
            silent_samples = int(
                TOTAL_WINDOW * self.target_sample_rate
            )
            self._window = np.zeros(
                (OUTPUT_CHANNELS, silent_samples),
                dtype=np.float32
            )
            self._window_start = seek_time
            self._window_end   = (
                seek_time + TOTAL_WINDOW
            )

    def _extract(self,
                 time_seconds: float,
                 num_samples:  int) -> np.ndarray:
        """
        Extract samples from window.
        Must be called with lock held.
        Returns [OUTPUT_CHANNELS, num_samples] float32.
        """
        if self._window is None:
            return np.zeros(
                (OUTPUT_CHANNELS, num_samples),
                dtype=np.float32
            )

        offset = int(
            (time_seconds - self._window_start) *
            self.target_sample_rate
        )
        offset = max(0, offset)

        end        = offset + num_samples
        window_len = self._window.shape[1]

        if offset >= window_len:
            # past end of window — silence
            return np.zeros(
                (OUTPUT_CHANNELS, num_samples),
                dtype=np.float32
            )

        if end <= window_len:
            # fully within window
            return self._window[:, offset:end].copy()

        # partially past end — pad with silence
        available = window_len - offset
        chunk     = self._window[:, offset:].copy()
        pad       = np.zeros(
            (OUTPUT_CHANNELS, num_samples - available),
            dtype=np.float32
        )
        return np.concatenate([chunk, pad], axis=1)

    def __repr__(self):
        return (
            f"StreamingAudioDecoder("
            f"{Path(self.filepath).name} | "
            f"{self.target_sample_rate}Hz | "
            f"{self.duration:.1f}s)"
        )
