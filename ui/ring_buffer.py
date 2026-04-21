"""
RingBuffer — thread-safe audio ring buffer.

Writer (AudioMixer thread) and reader
(sounddevice callback, real-time thread)
operate independently without blocking each other.
"""

import threading
import numpy as np


class RingBuffer:

    def __init__(self, capacity_seconds, sample_rate,
                 channels):
        self.sample_rate = sample_rate
        self.channels    = channels
        self.capacity    = int(capacity_seconds * sample_rate)

        self._buf       = np.zeros(
            (channels, self.capacity), dtype=np.float32
        )
        self._write_pos = 0
        self._read_pos  = 0
        self._available = 0
        self._lock      = threading.Lock()

    @property
    def available(self):
        with self._lock:
            return self._available

    @property
    def free_space(self):
        with self._lock:
            return self.capacity - self._available

    @property
    def available_seconds(self):
        return self.available / self.sample_rate

    @property
    def free_seconds(self):
        return self.free_space / self.sample_rate

    def write(self, samples: np.ndarray) -> int:
        n = samples.shape[1]
        with self._lock:
            space = self.capacity - self._available
            n     = min(n, space)
            if n <= 0:
                return 0
            space1 = min(n, self.capacity - self._write_pos)
            self._buf[
                :, self._write_pos:self._write_pos + space1
            ] = samples[:, :space1]
            if space1 < n:
                space2 = n - space1
                self._buf[:, :space2] = (
                    samples[:, space1:space1 + space2]
                )
                self._write_pos = space2
            else:
                self._write_pos = (
                    (self._write_pos + n) % self.capacity
                )
            self._available += n
            return n

    def read(self, n: int) -> np.ndarray:
        out = np.zeros((self.channels, n), dtype=np.float32)
        with self._lock:
            available = min(n, self._available)
            if available <= 0:
                return out
            space1 = min(
                available, self.capacity - self._read_pos
            )
            out[:, :space1] = self._buf[
                :, self._read_pos:self._read_pos + space1
            ]
            if space1 < available:
                space2 = available - space1
                out[:, space1:space1 + space2] = (
                    self._buf[:, :space2]
                )
                self._read_pos = space2
            else:
                self._read_pos = (
                    (self._read_pos + available)
                    % self.capacity
                )
            self._available -= available
        return out

    def clear(self):
        with self._lock:
            self._write_pos = 0
            self._read_pos  = 0
            self._available = 0
            self._buf[:]    = 0.0
