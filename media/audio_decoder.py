import torch
import av
import numpy as np
from pathlib import Path


class AudioDecoder:
    """
    Decodes audio from a video or audio file using PyAV.
    Loads full audio into memory for random access.
    """

    def __init__(self, filepath: str):
        self.path = Path(filepath)
        if not self.path.exists():
            raise FileNotFoundError(
                f"File not found: {filepath}"
            )

        # decode full audio via PyAV
        container = av.open(str(self.path))

        # find audio stream
        audio_stream = next(
            (s for s in container.streams
             if s.type == 'audio'), None
        )
        if audio_stream is None:
            raise ValueError(
                f"No audio stream in {filepath}"
            )

        self._sample_rate = audio_stream.sample_rate
        self._channels    = audio_stream.channels

        # decode all audio frames into one buffer
        chunks = []
        resampler = av.audio.resampler.AudioResampler(
            format='fltp',
            layout=audio_stream.layout,
            rate=audio_stream.sample_rate
        )
        for frame in container.decode(audio_stream):
            frame = resampler.resample(frame)
            for f in frame:
                arr = f.to_ndarray()
                chunks.append(arr)
        container.close()

        if not chunks:
            raise ValueError(
                f"No audio decoded from {filepath}"
            )

        # concatenate all chunks
        # shape: [channels, total_samples]
        audio_np = np.concatenate(chunks, axis=1)
        self._waveform    = torch.from_numpy(
            audio_np.copy()
        ).float()
        self._num_samples = self._waveform.shape[1]
        self._duration    = (self._num_samples /
                             self._sample_rate)

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def num_samples(self) -> int:
        return self._num_samples

    def get_samples_at_time(self,
                             time_seconds: float,
                             num_samples: int
                             ) -> torch.Tensor:
        """
        Get num_samples samples starting at time_seconds.
        Returns [channels, num_samples] float32 tensor.
        """
        start = int(time_seconds * self._sample_rate)
        start = max(0, min(
            start, self._num_samples - 1
        ))
        end = min(start + num_samples,
                  self._num_samples)

        chunk = self._waveform[:, start:end]

        # pad if we hit the end
        if chunk.shape[1] < num_samples:
            pad = torch.zeros(
                self._channels,
                num_samples - chunk.shape[1]
            )
            chunk = torch.cat([chunk, pad], dim=1)

        return chunk

    def get_samples_at_frame(self,
                              frame: int,
                              fps: float,
                              num_samples: int
                              ) -> torch.Tensor:
        time_seconds = frame / fps
        return self.get_samples_at_time(
            time_seconds, num_samples
        )

    def __repr__(self):
        return (f"AudioDecoder({self.path.name} | "
                f"{self._channels}ch | "
                f"{self._sample_rate}Hz | "
                f"{self._duration:.1f}s)")