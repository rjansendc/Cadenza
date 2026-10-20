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


def get_cache_path(filepath: str, audio_index: int = 0) -> Path:
    """
    Cache file path based on filename + size.
    Same file = same cache regardless of location.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p    = Path(filepath)
    size = p.stat().st_size if p.exists() else 0
    key  = f"{p.name}_{size}"
    # The first audio stream keeps the original key, so caches built
    # before waveforms knew about streams stay valid — they hold that
    # stream's peaks, which is still the right answer for it.
    if audio_index:
        key += f"_a{audio_index}"
    hash_ = hashlib.md5(key.encode()).hexdigest()[:12]
    suffix = f"_a{audio_index}" if audio_index else ''
    return CACHE_DIR / f"{p.stem}{suffix}_{hash_}.peaks"


def load_peaks(filepath: str, audio_index: int = 0
               ) -> Optional[np.ndarray]:
    """
    Load cached peaks if available.
    Returns peaks array or None if not cached.
    """
    cache = get_cache_path(filepath, audio_index)
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
               peaks: np.ndarray,
               audio_index: int = 0):
    """Save peaks to cache."""
    cache = get_cache_path(filepath, audio_index)
    try:
        np.save(str(cache), peaks)
    except Exception as e:
        print(f"Peak cache save error: {e}")


class _Envelope:
    """
    Folds samples into min/max buckets as they arrive.

    The whole decoded stream used to be held in memory and bucketed
    at the end — 115 MB per five minutes, so about 2.8 GB for a
    two-hour stereo stream. Reading every audio stream of a file in
    one pass would have multiplied that by the stream count, so the
    buckets are filled as the samples come instead. Memory is
    num_peaks floats regardless of how long the recording is.

    Buckets are mapped proportionally — sample `p` of `expected`
    belongs to bucket `p * n // expected` — so every sample lands in
    one. Bucketing by a floored chunk size, as the old code did,
    dropped up to num_peaks samples off the end.
    """

    def __init__(self, num_peaks: int, expected_samples: int):
        self.n        = max(1, num_peaks)
        self.expected = max(1, expected_samples)
        self.mins     = np.full(self.n,  np.inf, dtype=np.float32)
        self.maxs     = np.full(self.n, -np.inf, dtype=np.float32)
        self.pos      = 0
        # Bucketing as samples arrive needs the length in advance. A
        # container that reports no duration at all leaves none, and
        # guessing one folds the whole stream into a single bucket —
        # so that case keeps the samples and buckets them at the end,
        # as the old code always did. Only such a file pays the
        # memory, and only for its own stream.
        self.unknown  = expected_samples <= 0
        self.held     = [] if self.unknown else None

    def _bucket_start(self, bucket: int) -> int:
        """First sample position belonging to this bucket."""
        return -(-bucket * self.expected // self.n)      # ceil

    def add(self, block: np.ndarray):
        if block.size == 0:
            return
        if self.unknown:
            self.held.append(block.copy())
            self.pos += block.size
            return
        start = self.pos
        end   = start + block.size
        self.pos = end

        first = min((start * self.n) // self.expected, self.n - 1)
        last  = min(((end - 1) * self.n) // self.expected, self.n - 1)

        if first == last:                     # the common case
            low, high = block.min(), block.max()
            if low  < self.mins[first]:
                self.mins[first] = low
            if high > self.maxs[first]:
                self.maxs[first] = high
            return

        for bucket in range(first, last + 1):
            low_pos  = max(start, self._bucket_start(bucket))
            high_pos = min(end,   self._bucket_start(bucket + 1))
            if high_pos <= low_pos:
                continue
            segment = block[low_pos - start:high_pos - start]
            low, high = segment.min(), segment.max()
            if low  < self.mins[bucket]:
                self.mins[bucket] = low
            if high > self.maxs[bucket]:
                self.maxs[bucket] = high

    def finish(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        The envelope, stretched to the full width if the stream was
        shorter than its duration claimed.

        A container's duration can be a little long, which would
        otherwise leave empty buckets on the right and draw a
        waveform that stops before the clip does.
        """
        if self.unknown:
            whole = (np.concatenate(self.held) if self.held
                     else np.zeros(1, dtype=np.float32))
            self.held = None
            total = len(whole)
            for bucket in range(self.n):
                low  = bucket * total // self.n
                high = max(low + 1, (bucket + 1) * total // self.n)
                if low >= total:
                    break
                segment = whole[low:high]
                self.mins[bucket] = segment.min()
                self.maxs[bucket] = segment.max()

        mins, maxs = self.mins, self.maxs
        filled = self.n
        if self.unknown:
            return (np.where(np.isfinite(mins), mins, 0.0).astype(np.float32),
                    np.where(np.isfinite(maxs), maxs, 0.0).astype(np.float32))
        if self.pos < self.expected:
            filled = min(self.n,
                         max(1, -(-self.pos * self.n // self.expected)))
        if filled < self.n:
            index = (np.arange(self.n) * filled) // self.n
            mins, maxs = mins[index], maxs[index]
        mins = np.where(np.isfinite(mins), mins, 0.0).astype(np.float32)
        maxs = np.where(np.isfinite(maxs), maxs, 0.0).astype(np.float32)
        return mins, maxs


def compute_peaks_all(filepath: str,
                      num_peaks: int = 4000,
                      audio_indices=None,
                      progress_callback=None,
                      cancel_callback=None) -> dict:
    """
    Peaks for every requested audio stream of one file, in a single
    pass over the container. Returns {audio_index: peaks or None}.

    Decoding one stream makes the demuxer walk the whole container,
    past every video packet, so the cost tracks the file's size and
    not its audio: measured at 20x the time for the same audio inside
    a 1080p file. A four-stream recording was read four times over —
    for a 4K movie, four passes over tens of gigabytes. Reading the
    streams together makes it one pass.

    Streams already cached are returned from cache and left out of
    the pass. If that accounts for all of them the file is not opened
    for decoding at all.

    progress_callback(percent: int), cancel_callback() -> truthy to
    abandon, as for compute_peaks.
    """
    results: dict = {}
    try:
        import av

        # Answer from cache before opening anything: a container whose
        # streams are all cached need not be touched. Only possible
        # when the streams are named — enumerating them means opening
        # the file.
        if audio_indices is not None:
            cached_all = {}
            for index in audio_indices:
                peaks = load_peaks(filepath, index)
                if peaks is None:
                    cached_all = None
                    break
                cached_all[index] = peaks
            if cached_all is not None:
                if progress_callback:
                    progress_callback(100)
                return cached_all

        container = av.open(filepath)
        streams = [s for s in container.streams if s.type == 'audio']
        if not streams:
            container.close()
            return {}

        if audio_indices is None:
            audio_indices = list(range(len(streams)))

        todo = []
        for index in audio_indices:
            if not 0 <= index < len(streams):
                print(f"Waveform: {filepath} has {len(streams)} "
                      f"audio stream(s), asked for {index + 1}")
                results[index] = None
                continue
            cached = load_peaks(filepath, index)
            if cached is not None:
                results[index] = cached
            else:
                todo.append(index)

        if not todo:
            container.close()
            return results

        import av.audio.resampler
        jobs = {}
        for index in todo:
            stream = streams[index]
            rate   = stream.sample_rate
            # Duration, not stream.frames: the latter is 0 for WAV and
            # anything the container does not count.
            expected = 0
            if stream.duration and stream.time_base:
                expected = int(float(stream.duration * stream.time_base)
                               * rate)
            elif container.duration:
                expected = int(container.duration / 1_000_000 * rate)
            jobs[index] = {
                'stream': stream,
                'resampler': av.audio.resampler.AudioResampler(
                    format='fltp', layout='stereo', rate=rate),
                'left':  _Envelope(num_peaks, expected),
                'right': _Envelope(num_peaks, expected),
                'expected': max(1, expected),
            }

        of_stream = {jobs[i]['stream'].index: i for i in todo}
        expected_total = sum(j['expected'] for j in jobs.values())
        decoded_total  = 0
        packets        = 0
        last_pct       = -1

        # Say so as soon as the read starts. Reporting every 50
        # packets meant a short file never reported at all — a three
        # second WAV decodes in 36 — so the status bar went straight
        # from the drop message to nothing, and a file that was being
        # read looked identical to one that had been forgotten.
        if progress_callback:
            progress_callback(0)
            last_pct = 0

        for packet in container.demux([jobs[i]['stream'] for i in todo]):
            index = of_stream.get(packet.stream.index)
            if index is None:
                continue
            job = jobs[index]
            for frame in packet.decode():
                for resampled in job['resampler'].resample(frame):
                    arr = resampled.to_ndarray()   # [channels, samples]
                    job['left'].add(arr[0])
                    job['right'].add(arr[1] if arr.shape[0] > 1
                                     else arr[0])
                    decoded_total += arr.shape[-1]
            packets += 1
            # asked every packet: a flag read is cheap, and the window
            # may be closing on a long read
            if cancel_callback is not None and cancel_callback():
                container.close()
                return {}
            if progress_callback:
                # on each percent, not on a packet count: how many
                # packets a file decodes into has nothing to do with
                # how long it takes to read
                pct = (min(90, int(decoded_total / expected_total * 90))
                       if expected_total else
                       min(90, packets // 50))
                if pct != last_pct:
                    last_pct = pct
                    progress_callback(pct)

        container.close()

        if cancel_callback is not None and cancel_callback():
            return {}
        if progress_callback:
            progress_callback(95)

        for index in todo:
            job = jobs[index]
            mins_l, maxs_l = job['left'].finish()
            mins_r, maxs_r = job['right'].finish()
            # [4, num_peaks]: L_min, L_max, R_min, R_max
            peaks = np.stack([mins_l, maxs_l, mins_r, maxs_r])
            save_peaks(filepath, peaks, index)
            results[index] = peaks

        if progress_callback:
            progress_callback(100)

        return results

    except Exception as e:
        print(f"Waveform compute error: {e}")
        return results


def compute_peaks(filepath: str,
                  num_peaks: int = 4000,
                  audio_index: int = 0,
                  progress_callback=None,
                  cancel_callback=None
                  ) -> Optional[np.ndarray]:
    """
    Compute waveform peaks for one audio stream.

    num_peaks = number of peak pairs to compute.
    4000 is enough for any zoom level at 1920px wide.

    Returns [4, num_peaks] float32 array:
      row 0 = L min, row 1 = L max, row 2 = R min, row 3 = R max

    progress_callback(percent: int) called during compute.

    cancel_callback() is asked on every packet; return anything
    truthy and the decode is abandoned and None returned. Progress is
    reported only every 50 packets, and a long recording decodes as a
    handful of large frames, so the two cannot share one call —
    throttling the question meant a cancel went unseen.

    This is one stream of the single pass in compute_peaks_all.
    Prefer that when more than one stream of a file is wanted: it
    walks the container once instead of once per stream, which is
    where the time goes.
    """
    results = compute_peaks_all(
        filepath,
        num_peaks=num_peaks,
        audio_indices=[audio_index],
        progress_callback=progress_callback,
        cancel_callback=cancel_callback)
    return results.get(audio_index)
