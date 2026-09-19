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
    def __init__(self, filepath: str, use_proxy: bool = True):
        self.source_path = Path(filepath)
        self.path  = Path(filepath)
        self.is_proxy = False
        self._lock = threading.Lock()
        if not self.path.exists():
            raise FileNotFoundError(
                f"Video not found: {filepath}"
            )

        # Preview reads the proxy when one exists: every frame is a
        # keyframe there, so seeking costs one frame instead of a
        # whole GOP. Export passes use_proxy=False.
        if use_proxy:
            try:
                from core.proxy import proxy_path
                candidate = proxy_path(filepath)
                if candidate.exists() and candidate.stat().st_size > 0:
                    self.path = candidate
                    self.is_proxy = True
            except Exception:
                pass
        self._container     = None
        self._video_stream  = None
        self._hw_ctx        = None   # NVDEC context, when available
        self.hardware_decode = False
        self._decode_gen    = None  # sequential generator
        self._last_frame    = None  # last decoded frame
        self._last_frame_idx = -1   # its index
        self._sequential_threshold = 3  # frames ahead
        # Same-frame cache — effects panel scrubs same frame
        # repeatedly on every parameter change. Return instantly.
        self._cached_frame_idx: int = -1
        self._cached_frame_tensor = None
        # Recently decoded frames, newest last. Dragging the playhead
        # back over ground already covered then costs nothing, which
        # is most of what scrubbing actually does.
        from collections import OrderedDict
        self._frame_lru = OrderedDict()
        self._lru_size = 12
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

    # codecs NVDEC can take off the CPU
    _CUVID = {
        'h264': 'h264_cuvid',
        'hevc': 'hevc_cuvid',
        'mpeg2video': 'mpeg2_cuvid',
        'vp9':  'vp9_cuvid',
        'av1':  'av1_cuvid',
    }

    def _make_hw_context(self, stream):
        """
        Decode on the GPU's video engine instead of the CPU, when the
        build has it. Set CADENZA_HWDECODE=0 to force software.

        Returns None when unavailable, and the caller carries on with
        the software path.
        """
        import os
        # Plain NVDEC is a loss: measured 150 fps against 188 in
        # software, because PyAV copies every frame back to system
        # memory anyway. It wins when it also DOWNSCALES, since then
        # only a small frame crosses the bus — the same trick the
        # proxy generator uses, but with no transcode first.
        # Measured on a 3090 Ti with 4K H.264: software 162 fps
        # sequential and 89ms per seek; NVDEC 153 fps; NVDEC decoding
        # straight to 540p 175 fps but 102ms per seek. Scrubbing is
        # seeks, so software wins where it matters. CADENZA_HWDECODE
        # can be 'scaled' or '1' to try the others.
        mode = os.environ.get('CADENZA_HWDECODE', '0')
        if mode == '0':
            return None
        want_resize = (mode == 'scaled'
                       and getattr(self, '_out_w', 0) > 0
                       and getattr(self, '_out_h', 0) > 0
                       and self.width > self._out_w * 1.5)
        if mode == 'scaled' and not want_resize:
            return None
        try:
            if not torch.cuda.is_available():
                return None
            name = stream.codec_context.name
            hw_name = self._CUVID.get(name)
            if not hw_name or hw_name not in av.codecs_available:
                return None
            codec = av.codec.Codec(hw_name, 'r')
            ctx = codec.create()
            ctx.extradata = stream.codec_context.extradata
            if want_resize:
                # decode straight to preview size: the GOP is still
                # walked, but on the video engine, and a 540p frame
                # comes back instead of a 24MB 4K one
                w = self._out_w - (self._out_w % 2)
                h = self._out_h - (self._out_h % 2)
                ctx.options = {'resize': f'{w}x{h}'}
                self.decoded_width, self.decoded_height = w, h
            return ctx
        except Exception as e:
            print(f"NVDEC unavailable for {self.path.name}: {e}")
            return None

    def _open_container(self):
        if self._container is None:
            self._container = av.open(str(self.path))
            vs = self._container.streams.video
            if vs:
                self._video_stream = vs[0]
                self._video_stream.thread_type = "AUTO"
                self._hw_ctx = self._make_hw_context(
                    self._video_stream)
                self.hardware_decode = self._hw_ctx is not None
            self._decode_gen   = None
            self._last_frame_idx = -1
        return self._container, self._video_stream

    def _iter_frames(self):
        """Frames in order, from the GPU decoder when there is one."""
        container, stream = self._open_container()
        if stream is None:
            return
        if self._hw_ctx is None:
            for frame in container.decode(video=0):
                yield frame
            return
        for packet in container.demux(stream):
            try:
                for frame in self._hw_ctx.decode(packet):
                    yield frame
            except Exception as e:
                print(f"NVDEC decode error, falling back: {e}")
                self._hw_ctx = None
                self.hardware_decode = False
                for frame in container.decode(video=0):
                    yield frame
                return

    def get_frame(self, frame_index: int,
                   draft: bool = False) -> torch.Tensor:
        frame_index = max(
            0, min(frame_index,
                   max(0, self.frame_count - 1))
        )
        # Same-frame cache — no lock needed for read,
        # tensor is immutable once stored.
        if frame_index == self._cached_frame_idx                 and self._cached_frame_tensor is not None:
            return self._cached_frame_tensor

        cached = self._frame_lru.get(frame_index)
        if cached is not None:
            self._frame_lru.move_to_end(frame_index)
            return cached

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
                    result = self._seek_frame(
                        frame_index, draft=draft)
                if not draft:
                    self._cached_frame_idx = frame_index
                    self._cached_frame_tensor = result
                    self._remember(frame_index, result)
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

    def _remember(self, frame_index: int, tensor):
        """Keep the most recent frames for revisits while scrubbing."""
        self._frame_lru[frame_index] = tensor
        self._frame_lru.move_to_end(frame_index)
        while len(self._frame_lru) > self._lru_size:
            self._frame_lru.popitem(last=False)

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
            self._decode_gen = self._iter_frames()

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

    def _seek_frame(self, frame_index: int,
                     draft: bool = False) -> torch.Tensor:
        """
        Seek to a specific frame.

        draft=True returns the keyframe at or before the target instead
        of decoding forward to it. Long-GOP 4K can be seconds of video
        between keyframes, and walking that for every mouse move is
        what makes dragging the playhead unusable. The exact frame is
        fetched when the drag ends.
        """
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

        if self._hw_ctx is not None:
            try:
                self._hw_ctx.flush_buffers()
            except Exception:
                pass

        best = None
        tolerance = 0.5 / self.fps
        for packet in container.demux(stream):
            try:
                decoded = (self._hw_ctx.decode(packet)
                           if self._hw_ctx is not None
                           else packet.decode())
            except Exception as e:
                print(f"NVDEC seek error, using software: {e}")
                self._hw_ctx = None
                self.hardware_decode = False
                decoded = packet.decode()
            for frame in decoded:
                if frame.pts is None:
                    continue
                ft = float(frame.pts) * time_base
                # keep advancing until we reach target
                best = frame
                if draft or ft >= target_sec - tolerance:
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

    def set_output_size(self, width: int, height: int):
        """
        Preview size. When NVDEC is in use it decodes straight to this
        size, so the container is reopened to pick it up.
        """
        if (width, height) == (getattr(self, '_out_w', 0),
                                getattr(self, '_out_h', 0)):
            return
        self._out_w = width
        self._out_h = height
        with self._lock:
            self._close_container()

    def _frame_to_tensor(self,
                          frame) -> torch.Tensor:
        """
        Upload the decoded frame as RGB on the GPU.

        Converting YUV->RGB on the GPU instead of asking PyAV for
        'rgb24' saves the CPU colour conversion and halves the bytes
        transferred (1080p: 1.47ms/6.2MB -> 0.18ms/3.1MB; a 4K frame
        is four times that). Any format the fast path does not handle
        falls back to libswscale.
        """
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        try:
            from gpu.yuv import frame_to_rgb_tensor
            return frame_to_rgb_tensor(frame, device=device)
        except Exception as e:
            print(f"YUV fast path unavailable ({e}), using rgb24")
            img = frame.to_ndarray(format='rgb24')
            return torch.from_numpy(
                np.ascontiguousarray(img)
            ).to(device)

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
        self._hw_ctx              = None
        self.hardware_decode      = False
        try:
            self._frame_lru.clear()
        except AttributeError:
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
