"""
AudioOutput — sounddevice output layer.
Callback reads exclusively from RingBuffer.
"""

import numpy as np
import sounddevice as sd
from ui.ring_buffer import RingBuffer


class AudioOutput:

    def __init__(self, ring, sample_rate=48000,
                 channels=2, blocksize=4096):
        self._ring        = ring
        self._sample_rate = sample_rate
        self._channels    = channels
        self._blocksize   = blocksize
        self._stream      = None

    def start(self):
        if self._stream is not None:
            self.stop()
        self._stream = sd.OutputStream(
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype='float32',
            blocksize=self._blocksize,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _callback(self, outdata, frames, time, status):
        samples    = self._ring.read(frames)
        outdata[:] = samples.T

    @property
    def is_active(self):
        return (self._stream is not None and
                self._stream.active)
