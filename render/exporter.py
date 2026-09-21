"""
ExportThread — orchestrates the full export pipeline.
Tested against PyAV 17.0.0.
"""

import av
import numpy as np
import torch
from fractions import Fraction
from typing import List

from PySide6.QtCore import QThread, Signal

from core.clip import Clip
from core.track import Sequence
from render.export_config import ExportConfig
from render.offline_audio_mixer import OfflineAudioMixer
from render.fast_yuv import tensor_to_av_frame_fast


class ExportThread(QThread):

    progress = Signal(int)
    status   = Signal(str)
    finished = Signal(str)
    error    = Signal(str)

    def __init__(self, config, clips, sequence,
                 compositor, parent=None):
        super().__init__(parent)
        self.config      = config
        self.clips       = clips
        self.sequence    = sequence
        self.compositor  = compositor
        self._cancelled  = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        # ensure decord uses torch bridge in this thread
        try:
            import decord
            decord.bridge.set_bridge('torch')
        except Exception:
            pass

        config   = self.config
        sequence = self.sequence

        fps_float   = config.resolved_fps(sequence.settings.fps)
        fps         = Fraction(fps_float).limit_denominator(1001)
        sample_rate = config.resolved_sample_rate(
            sequence.settings.sample_rate)
        channels = config.channels

        seq_end = max(
            (c.start_frame + c.duration for c in self.clips),
            default=0
        )
        total_frames = config.total_frames(seq_end)
        start_frame  = config.start_frame
        end_frame    = start_frame + total_frames
        fps_float    = sequence.settings.fps
        print(f"[Export] {len(self.clips)} clips, "
              f"seq_end={seq_end} ({seq_end/fps_float/60:.1f}min), "
              f"total_frames={total_frames}, "
              f"start={start_frame}, end={end_frame}")
        for c in sorted(self.clips, key=lambda x: x.start_frame):
            print(f"  clip: {c.name} start={c.start_frame} "
                  f"dur={c.duration} end={c.start_frame+c.duration}")

        if total_frames <= 0:
            self.error.emit("No frames to export.")
            return

        self.status.emit("Initialising export...")

        mixer = OfflineAudioMixer(
            sample_rate=sample_rate,
            channels=channels,
            fps=fps_float
        )
        mixer.prepare(self.clips, self.sequence,
                      start_frame=start_frame)

        container = None
        try:
            container = av.open(config.output_path, mode='w')

            # Video stream — pick codec and options
            encoder = getattr(config, 'encoder', 'h264')
            is_nvenc = 'nvenc' in encoder

            if is_nvenc:
                # NVIDIA GPU encoding
                v_stream         = container.add_stream(encoder, rate=fps)
                v_stream.width   = config.width
                v_stream.height  = config.height
                v_stream.pix_fmt = 'yuv420p'
                v_stream.options = {
                    'rc':         'vbr',
                    'cq':         str(config.crf),
                    'preset':     'p4',   # balanced speed/quality
                    'profile':    'high',
                    'b:v':        '0',
                }
            elif encoder == 'h265':
                v_stream         = container.add_stream('libx265', rate=fps)
                v_stream.width   = config.width
                v_stream.height  = config.height
                v_stream.pix_fmt = 'yuv420p'
                v_stream.options = {
                    'crf':     str(config.crf),
                    'preset':  config.preset,
                    'movflags': 'faststart',
                }
            else:
                # Software H.264 (default)
                v_stream         = container.add_stream('h264', rate=fps)
                v_stream.width   = config.width
                v_stream.height  = config.height
                v_stream.pix_fmt = 'yuv420p'
                v_stream.options = {
                    'crf':      str(config.crf),
                    'preset':   config.preset,
                    'profile':  'high',
                    'movflags': 'faststart',
                }

            # Audio stream — PyAV 17 API
            a_stream = container.add_stream('aac', rate=sample_rate)
            a_stream.codec_context.layout   = 'stereo'
            a_stream.codec_context.bit_rate = self._parse_bitrate(
                config.audio_bitrate)

            # Explicit time bases for accurate A/V sync
            # Video: 1 unit = 1 frame
            v_stream.codec_context.time_base = Fraction(1, int(round(fps_float)))
            # Audio: 1 unit = 1 sample
            a_stream.codec_context.time_base = Fraction(1, sample_rate)

            # Pre-seek decoders to starting position so
            # sequential decode kicks in immediately
            self.status.emit("Seeking to start position...")
            from core.clip_renderer import ClipRenderer
            seen_paths = set()
            for c in self.clips:
                if not c.has_video:
                    continue
                if c.filepath in seen_paths:
                    continue
                seen_paths.add(c.filepath)
                dec = self.compositor.get_decoder(c.filepath)
                if dec:
                    renderer = ClipRenderer(c)
                    first_src = renderer.timeline_to_source_frame(
                        start_frame)
                    dec.get_frame(first_src)  # warm seek

            samples_written = 0
            self.status.emit("Exporting...")
            import time as _time
            _t_start   = _time.perf_counter()
            _recent    = []

            _t_decode = _t_yuv = _t_encode = 0.0
            for i, frame in enumerate(range(start_frame, end_frame)):
                if self._cancelled:
                    self.status.emit("Export cancelled.")
                    return

                # Video
                _ta = _time.perf_counter()
                v_tensor = self._get_video_frame(frame, config,
                                                   keep_on_gpu=True)
                _tb = _time.perf_counter()
                v_av     = tensor_to_av_frame_fast(v_tensor, pts=i)
                _tc = _time.perf_counter()
                _t_decode += _tb - _ta
                _t_yuv    += _tc - _tb
                # PTS in stream time base units (frames)
                v_av.pts            = i
                v_av.time_base      = Fraction(1, int(round(fps_float)))
                _td = _time.perf_counter()
                for pkt in v_stream.encode(v_av):
                    container.mux(pkt)
                _t_encode += _time.perf_counter() - _td

                # Audio — sample-accurate sync
                target = int((i + 1) * sample_rate / fps_float)
                n      = target - samples_written
                if n > 0:
                    chunk = mixer.render_frame(self.clips, frame, n)
                    a_av  = self._chunk_to_av_frame(
                        chunk, sample_rate, samples_written)
                    a_av.time_base = Fraction(1, sample_rate)
                    for pkt in a_stream.encode(a_av):
                        container.mux(pkt)
                    samples_written += n

                # Progress
                _recent.append(_time.perf_counter())
                if len(_recent) > 60:
                    _recent.pop(0)
                pct = int((i + 1) / total_frames * 100)
                self.progress.emit(pct)
                if i % 30 == 0 and i > 0 and len(_recent) > 1:
                    # Rate over the last couple of seconds, for display:
                    # it moves as the timeline gets heavier or lighter.
                    _elapsed = _recent[-1] - _recent[0]
                    _fps_est = (len(_recent) - 1) / _elapsed if _elapsed > 0 else 0

                    # Time remaining comes from the average since the
                    # start instead. Per-frame cost swings by a factor
                    # of two or more between a lone 1080p title and
                    # three stacked 4K angles, so an estimate built on
                    # the recent rate alone swung between 37 and 77
                    # minutes on the same render.
                    _since_start = _time.perf_counter() - _t_start
                    _avg_fps = (i + 1) / _since_start if _since_start > 0 else 0
                    _remain  = ((total_frames - i) / _avg_fps / 60
                                if _avg_fps > 0 else 0)
                    print(f"[Export timing] i={i} "
                          f"decode={_t_decode/i*1000:.1f}ms "
                          f"yuv={_t_yuv/i*1000:.1f}ms "
                          f"encode={_t_encode/i*1000:.1f}ms "
                          f"fps={_fps_est:.1f}")
                    self.status.emit(
                        f"Exporting "
                        f"{self._frames_to_tc(frame, fps_float)}"
                        f" ({pct}%)  "
                        f"{_fps_est:.0f} fps  "
                        f"~{_remain:.0f} min remaining"
                    )

            # Flush
            self.status.emit("Finalising...")
            for pkt in v_stream.encode():
                container.mux(pkt)
            for pkt in a_stream.encode():
                container.mux(pkt)

            self.progress.emit(100)
            self.finished.emit(config.output_path)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(
                f"Export failed: {type(e).__name__}: {e}")
        finally:
            if container:
                try:
                    container.close()
                except Exception:
                    pass
            mixer.close()

    # =========================================================
    # Frame conversion — tested against PyAV 17.0.0
    # =========================================================

    def _get_video_frame(self, frame, config,
                          keep_on_gpu: bool = False):
        tensor = self.compositor.composite_frame(
            self.clips, frame, keep_on_gpu=keep_on_gpu)
        seq_w = self.sequence.settings.width
        seq_h = self.sequence.settings.height
        if config.width != seq_w or config.height != seq_h:
            import torch.nn.functional as F
            t = (tensor.float().permute(2,0,1)
                       .unsqueeze(0).div(255.0))
            t = F.interpolate(
                t, size=(config.height, config.width),
                mode='bilinear', align_corners=False)
            tensor = (t.squeeze(0).permute(1,2,0)
                       .mul(255).byte())
        return tensor

    def _tensor_to_av_frame(self, tensor):
        vf = av.VideoFrame.from_ndarray(
            tensor.numpy(), format='rgb24')
        return vf.reformat(format='yuv420p')

    def _chunk_to_av_frame(self, chunk, sample_rate, pts):
        n_ch  = chunk.shape[0]
        n_smp = chunk.shape[1]
        layout = 'stereo' if n_ch == 2 else 'mono'
        af = av.AudioFrame(
            format='fltp', layout=layout, samples=n_smp)
        af.sample_rate = sample_rate
        af.pts         = pts
        for ch in range(n_ch):
            af.planes[ch].update(
                np.ascontiguousarray(
                    chunk[ch], dtype=np.float32
                ).tobytes()
            )
        return af

    def _parse_bitrate(self, s):
        s = s.lower().strip()
        if s.endswith('k'): return int(s[:-1]) * 1000
        if s.endswith('m'): return int(s[:-1]) * 1_000_000
        return int(s)

    def _frames_to_tc(self, frame, fps):
        total_secs = int(frame / fps)
        ff = int(frame % fps)
        ss = total_secs % 60
        mm = (total_secs // 60) % 60
        hh = total_secs // 3600
        return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"
