import numpy as np
import torch
from pathlib import Path
from typing import Optional, Tuple
import hashlib


# Always relative to this file's location
# so cache is always found regardless of
# which directory Python is launched from
from core.paths import cache_dir

# Resolved through core.paths: Path(__file__) points inside _internal/
# in a frozen build, which put the cache inside the application folder
CACHE_DIR = cache_dir('waveforms')


def get_cache_path(filepath: str) -> Path:
    """
    Cache file path based on filename + size.
    Same file = same cache regardless of location.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p    = Path(filepath)
    size = p.stat().st_size if p.exists() else 0
    key  = f"{p.name}_{size}"
    hash_ = hashlib.md5(key.encode()).hexdigest()[:12]
    return CACHE_DIR / f"{p.stem}_{hash_}.peaks"


def load_peaks(filepath: str
               ) -> Optional[np.ndarray]:
    """
    Load cached peaks if available.
    Returns peaks array or None if not cached.
    """
    cache = get_cache_path(filepath)
    # np.save appends .npy automatically
    cache_npy = Path(str(cache) + '.npy')
    actual = cache_npy if cache_npy.exists() else cache
    if actual.exists():
        try:
            return np.load(str(actual))
        except Exception:
            actual.unlink(missing_ok=True)
    return None


def save_peaks(filepath: str,
               peaks: np.ndarray):
    """Save peaks to cache."""
    cache = get_cache_path(filepath)
    try:
        np.save(str(cache), peaks)
    except Exception as e:
        print(f"Peak cache save error: {e}")


def compute_peaks(filepath: str,
                  num_peaks: int = 4000,
                  progress_callback=None
                  ) -> Optional[np.ndarray]:
    """
    Compute waveform peaks from audio file.
    
    num_peaks = number of peak pairs to compute.
    4000 is enough for any zoom level at 1920px wide.
    
    Returns [2, num_peaks] float32 array:
      row 0 = min values (negative)
      row 1 = max values (positive)
    
    progress_callback(percent: int) called during compute.
    """
    # check cache first
    cached = load_peaks(filepath)
    if cached is not None:
        return cached

    try:
        import av
        container = av.open(filepath)

        audio_stream = next(
            (s for s in container.streams
             if s.type == 'audio'), None
        )
        if audio_stream is None:
            container.close()
            return None

        sample_rate = audio_stream.sample_rate

        # decode full audio
        import av.audio.resampler
        resampler = av.audio.resampler.AudioResampler(
            format='fltp',
            layout='stereo',
            rate=sample_rate
        )

        chunks = []
        total_frames = (
            audio_stream.frames
            if audio_stream.frames
            else 1000
        )
        decoded = 0

        # keep L and R channels separate
        chunks_l = []
        chunks_r = []

        for frame in container.decode(audio_stream):
            resampled = resampler.resample(frame)
            for f in resampled:
                arr = f.to_ndarray()  # [channels, samples]
                chunks_l.append(arr[0])  # L
                chunks_r.append(
                    arr[1] if arr.shape[0] > 1
                    else arr[0]  # mono fallback
                )
            decoded += 1
            if progress_callback and decoded % 50 == 0:
                pct = min(
                    90,
                    int(decoded / total_frames * 90)
                )
                progress_callback(pct)

        container.close()

        if not chunks_l:
            return None

        wav_l = np.concatenate(chunks_l)
        wav_r = np.concatenate(chunks_r)
        total = len(wav_l)

        if total == 0:
            return None

        # compute peaks for L and R independently
        chunk_size = max(1, total // num_peaks)
        mins_l = np.zeros(num_peaks, dtype=np.float32)
        maxs_l = np.zeros(num_peaks, dtype=np.float32)
        mins_r = np.zeros(num_peaks, dtype=np.float32)
        maxs_r = np.zeros(num_peaks, dtype=np.float32)

        for i in range(num_peaks):
            start = i * chunk_size
            end   = min(start + chunk_size, total)
            if start >= total:
                break
            mins_l[i] = wav_l[start:end].min()
            maxs_l[i] = wav_l[start:end].max()
            mins_r[i] = wav_r[start:end].min()
            maxs_r[i] = wav_r[start:end].max()

        if progress_callback:
            progress_callback(95)

        # [4, num_peaks]: L_min, L_max, R_min, R_max
        peaks = np.stack([mins_l, maxs_l,
                          mins_r, maxs_r])

        # cache to disk
        save_peaks(filepath, peaks)

        if progress_callback:
            progress_callback(100)

        return peaks

    except Exception as e:
        print(f"Waveform compute error: {e}")
        return None