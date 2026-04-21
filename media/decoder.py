import torch
import av
import numpy as np
import threading
from pathlib import Path


class VideoDecoder:
    """
    Hybrid video decoder:
    - Sequential playback: fast forward decode (no seek)
    - Random scrub: PyAV seek to timestamp
    
    No decord — works on any file size instantly.
    Thread-safe with lock around container access.
    """
    def __init__(self, filepath: str):
        self.path  = Path(filepath)
        self._lock = threading.Lock()
        if not self.path.exists():
            raise FileNotFoundError(
                f"Video not found: {filepath}"
            )
        self._container     = None
        self._video_stream  = None
        self._decode_gen    = None  # sequential generator
        self._last_frame    = None  # last decoded frame
        self._last_frame_idx = -1   # its index
        self._sequential_threshold = 3  # frames ahead
        # Same-frame cache — effects panel scrubs same frame
        # repeatedly on every parameter change. Return instantly.
        self._cached_frame_idx: int = -1
        self._cached_frame_tensor = None
        self._init_metadata()

    def _init_metadata(self):
        try:
            container = av.open(str(self.path))
            vs = container.streams.video
            if vs:
                stream = vs[0]
                self.width  = stream.width
                self.height = stream.height
                r = stream.average_rate
                self.fps = float(r) if r else 29.97
                dur = container.duration
                self.duration = (
                    dur / av.time_base if dur else 0.0
                )
                self.frame_count = int(
                    self.duration * self.fps
                )
            else:
                self.width  = 1920
                self.height = 1080
                self.fps    = 29.97
                self.duration    = 0.0
                self.frame_count = 0
            container.close()
        except Exception as e:
            print(f"Metadata error: {e}")
            self.width  = 1920
            self.height = 1080
            self.fps    = 29.97
            self.duration    = 0.0
            self.frame_count = 0

    def _open_container(self):
        if self._container is None:
            self._container = av.open(str(self.path))
            vs = self._container.streams.video
            if vs:
                self._video_stream = vs[0]
                self._video_stream.thread_type = "AUTO"
            self._decode_gen   = None
            self._last_frame_idx = -1
        return self._container, self._video_stream

    def get_frame(self, frame_index: int) -> torch.Tensor:
        frame_index = max(
            0, min(frame_index,
                   max(0, self.frame_count - 1))
        )
        # Same-frame cache — no lock needed for read,
        # tensor is immutable once stored.
        if frame_index == self._cached_frame_idx                 and self._cached_frame_tensor is not None:
            return self._cached_frame_tensor

        with self._lock:
            # Double-check inside lock
            if frame_index == self._cached_frame_idx                     and self._cached_frame_tensor is not None:
                return self._cached_frame_tensor
            try:
                # sequential? use fast forward decode
                delta = frame_index - self._last_frame_idx
                if 0 < delta <= self._sequential_threshold:
                    result = self._next_frames(
                        frame_index, delta
                    )
                else:
                    # random access — seek
                    result = self._seek_frame(frame_index)
                self._cached_frame_idx = frame_index
                self._cached_frame_tensor = result
                return result
            except Exception as e:
                print(f"Frame error {frame_index}: {e}")
                self._close_container()
                try:
                    result = self._seek_frame(frame_index)
                    self._cached_frame_idx = frame_index
                    self._cached_frame_tensor = result
                    return result
                except Exception:
                    return self._blank_frame()

    def _next_frames(self, target_idx: int,
                     delta: int) -> torch.Tensor:
        """
        Advance forward by delta frames using
        sequential decode — much faster than seeking.
        """
        container, stream = self._open_container()
        if stream is None:
            return self._blank_frame()

        # start generator if needed
        if self._decode_gen is None:
            self._decode_gen = container.decode(
                video=0
            )

        best = None
        frames_needed = delta

        try:
            while frames_needed > 0:
                frame = next(self._decode_gen)
                best = frame
                frames_needed -= 1
        except StopIteration:
            self._decode_gen = None

        if best is None:
            return self._seek_frame(target_idx)

        self._last_frame_idx = target_idx
        return self._frame_to_tensor(best)

    def _seek_frame(self,
                     frame_index: int) -> torch.Tensor:
        """Seek to specific frame — for scrubbing."""
        container, stream = self._open_container()
        if stream is None:
            return self._blank_frame()

        # reset sequential generator on seek
        self._decode_gen = None

        time_base = float(stream.time_base or 1/90000)
        target_sec = frame_index / max(self.fps, 1.0)
        pts = int(target_sec / time_base)

        container.seek(
            pts,
            stream=stream,
            backward=True,
            any_frame=False
        )

        best = None
        tolerance = 0.5 / self.fps
        for packet in container.demux(stream):
            for frame in packet.decode():
                if frame.pts is None:
                    continue
                ft = float(frame.pts) * time_base
                # keep advancing until we reach target
                best = frame
                if ft >= target_sec - tolerance:
                    break
            else:
                # inner loop did not break — keep demuxing
                continue
            # inner loop broke — we reached target
            break

        if best is None:
            return self._blank_frame()

        self._last_frame_idx = frame_index
        # restart sequential decode from here
        self._decode_gen = None
        return self._frame_to_tensor(best)

    def set_output_size(self, width: int,
                         height: int):
        """Set target output size for pre-scaling."""
        self._out_w = width
        self._out_h = height

    def _frame_to_tensor(self,
                          frame) -> torch.Tensor:
        img = frame.to_ndarray(format='rgb24')
        # pre-scale on CPU if source is much larger
        # than output — reduces GPU transfer size
        out_w = getattr(self, '_out_w', 0)
        out_h = getattr(self, '_out_h', 0)
        if (out_w > 0 and out_h > 0 and
                img.shape[1] > out_w * 1.5):
            try:
                import cv2
                img = cv2.resize(
                    img, (out_w, out_h),
                    interpolation=cv2.INTER_LINEAR
                )
            except ImportError:
                pass  # cv2 not available, skip
        return torch.from_numpy(
            np.ascontiguousarray(img)
        ).to('cuda')

    def _blank_frame(self) -> torch.Tensor:
        return torch.zeros(
            self.height, self.width, 3,
            dtype=torch.uint8, device='cuda'
        )

    def _close_container(self):
        try:
            if self._container:
                self._container.close()
        except Exception:
            pass
        self._container           = None
        self._video_stream        = None
        self._decode_gen          = None
        self._last_frame_idx      = -1
        self._cached_frame_idx    = -1
        self._cached_frame_tensor = None

    def get_frame_at_time(self,
                           seconds: float) -> torch.Tensor:
        return self.get_frame(int(seconds * self.fps))

    def get_stream_info(self) -> dict:
        info = {
            'video_count': 0, 'audio_count': 0,
            'video_streams': [], 'audio_streams': [],
        }
        try:
            container = av.open(str(self.path))
            for s in container.streams.video:
                info['video_count'] += 1
                info['video_streams'].append({
                    'index': s.index,
                    'width': s.width,
                    'height': s.height,
                    'fps': float(s.average_rate)
                    if s.average_rate else self.fps,
                })
            for s in container.streams.audio:
                info['audio_count'] += 1
                info['audio_streams'].append({
                    'index': s.index,
                    'channels': s.channels,
                    'layout': s.layout.name,
                    'sample_rate': s.sample_rate,
                })
            container.close()
        except Exception as e:
            print(f"Stream info error: {e}")
            info['video_count'] = 1
            info['audio_count'] = 1
        return info

    def __del__(self):
        self._close_container()

    def __repr__(self):
        return (f"VideoDecoder({self.path.name} | "
                f"{self.width}x{self.height} | "
                f"{self.fps:.2f}fps | hybrid)")


class ImageDecoder:
    """
    Decoder for still images (jpg, png, etc).
    Returns the same frame for every frame request.
    """
    def __init__(self, filepath: str, fps: float = 29.97,
                 duration: float = 10.0):
        self.path       = filepath
        self.fps        = fps
        self.duration   = duration
        self.frame_count = int(duration * fps)
        self._frame_cache = None
        self._lock       = __import__('threading').Lock()

        # read image dimensions
        try:
            from PySide6.QtGui import QImageReader
            reader = QImageReader(filepath)
            size   = reader.size()
            self.width  = size.width()  if size.isValid() else 1920
            self.height = size.height() if size.isValid() else 1080
        except Exception:
            self.width, self.height = 1920, 1080

    def _load_frame(self):
        """Load image into a torch tensor once, cache it."""
        import torch
        import numpy as np
        from PySide6.QtGui import QImage
        img = QImage(self.path).convertToFormat(
            QImage.Format.Format_RGB888)
        if img.isNull():
            return None
        w, h = img.width(), img.height()
        # Use bytesPerLine to handle row padding correctly
        bpl = img.bytesPerLine()
        ptr = img.constBits()
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, bpl)
        # Strip padding — keep only w*3 bytes per row
        arr = arr[:, :w * 3].reshape(h, w, 3)
        return torch.from_numpy(arr.copy()).float()

    def get_frame(self, frame_idx: int):
        """Return the image as a tensor for any frame index."""
        with self._lock:
            if self._frame_cache is None:
                self._frame_cache = self._load_frame()
            return self._frame_cache
