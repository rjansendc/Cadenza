import torch
import torch.nn.functional as F
from typing import List, Optional, Dict
from core.clip import Clip
from core.clip_renderer import ClipRenderer
from core.track import Sequence


class Compositor:
    """
    Composites all active video clips at a given frame.

    Now uses ClipRenderer for all temporal mapping:
      - in_point / out_point handled correctly
      - speed / reverse handled correctly
      - opacity from envelope at local frame
      - motion parameters at local frame

    GPU-accelerated via PyTorch.
    Output: [H, W, 3] uint8 tensor on CPU.
    """

    def __init__(self, sequence: Sequence):
        self.sequence = sequence
        self.width    = sequence.settings.width
        self.height   = sequence.settings.height
        self.fps      = sequence.settings.fps

        self._decoders:    Dict[str, object] = {}
        self._frame_cache: Dict[int, object] = {}
        self._cache_size   = 10
        # cache renderers — rebuilt only when clips change
        self._renderers:   list = []
        self._clips_hash:  int  = 0
        import threading
        self._decoder_lock = threading.Lock()

        self._blank = torch.zeros(
            self.height, self.width, 3,
            dtype=torch.uint8
        )

    def get_decoder(self, filepath: str):
        # fast path — already exists, no lock needed
        if filepath in self._decoders:
            return self._decoders[filepath]
        # slow path — create decoder under lock
        with self._decoder_lock:
            # double-check after acquiring lock
            if filepath in self._decoders:
                return self._decoders[filepath]
            import os
            ext = os.path.splitext(filepath)[1].lower()
            from media.decoder import VideoDecoder, ImageDecoder
            is_image = ext in ('.jpg', '.jpeg', '.png',
                                '.bmp', '.tiff', '.tif')
            try:
                if is_image:
                    dec = ImageDecoder(filepath)
                else:
                    dec = VideoDecoder(filepath)
                    dec.set_output_size(
                        self.width, self.height
                    )
                self._decoders[filepath] = dec
            except Exception as e:
                print(f"Decoder error {filepath}: {e}")
                return None
        return self._decoders[filepath]

    def composite_frame(self,
                         clips: List[Clip],
                         playhead_frame: int,
                         sequence=None,
                         use_cache: bool = False,
                         keep_on_gpu: bool = False
                         ) -> torch.Tensor:
        # Cache is opt-in — only playback uses it.
        # Scrub calls always pass use_cache=False (default)
        # so they never get a stale hit.
        if use_cache and playhead_frame in self._frame_cache:
            return self._frame_cache[playhead_frame]

        result = self._composite_internal(
            clips, playhead_frame, sequence
        )

        if use_cache:
            cpu_result = result.cpu()
            self._frame_cache[playhead_frame] = cpu_result
            if len(self._frame_cache) > self._cache_size:
                oldest = min(self._frame_cache.keys())
                del self._frame_cache[oldest]
            return cpu_result

        return result if keep_on_gpu else result.cpu()

    def invalidate_cache(self):
        """Force full recomposite on next frame request."""
        self._frame_cache.clear()
        self._clips_hash = None

    def _composite_internal(self,
                              clips: List[Clip],
                              playhead_frame: int,
                              sequence=None
                              ) -> torch.Tensor:
        """
        Composite all active video clips.
        Uses ClipRenderer for correct frame mapping.
        """
        # rebuild renderers only when clip list changes
        # include track visibility in hash
        def _track_visible(c):
            if sequence is None:
                return True
            tracks = sequence.video_tracks
            if c.track < len(tracks):
                return tracks[c.track].visible
            return True

        clips_hash = hash(tuple(
            (c.id, c.start_frame, c.in_point,
             c.out_point, c.enabled,
             _track_visible(c))
            for c in clips if c.has_video
        ))
        if clips_hash != self._clips_hash:
            self._renderers = [
                ClipRenderer(c) for c in clips
                if c.has_video
                and c.enabled
                and _track_visible(c)
            ]
            self._clips_hash = clips_hash
            self._frame_cache.clear()

        # filter to active renderers at this frame
        active = [
            r for r in self._renderers
            if r.is_active_at(playhead_frame)
        ]

        if not active:
            return self._blank.clone()

        # black canvas on GPU
        canvas = torch.zeros(
            self.height, self.width, 3,
            dtype=torch.float32,
            device='cuda'
        )

        # composite bottom to top (V1 first = lowest)
        active_sorted = sorted(
            active,
            key=lambda r: r.clip.track
        )

        for renderer in active_sorted:
            try:
                frame_tensor = self._get_frame(
                    renderer, playhead_frame
                )
                if frame_tensor is None:
                    continue

                # apply motion using ClipRenderer
                motion = renderer.get_motion_at(playhead_frame)
                frame_tensor = self._apply_motion(
                    frame_tensor, motion
                )

                # apply video effect stack (lumetri color, etc.)
                # frame_tensor is float32 [H,W,3] on GPU at this point
                frame_tensor = self._apply_video_effects(
                    renderer.clip, frame_tensor
                )

                # opacity from ClipRenderer (local frame)
                opacity = renderer.get_opacity_at(playhead_frame)

                if opacity >= 1.0:
                    canvas = frame_tensor
                else:
                    canvas = (
                        canvas * (1.0 - opacity) +
                        frame_tensor * opacity
                    )
            except Exception as e:
                import traceback; traceback.print_exc()
                continue

        return canvas.clamp(0, 255).byte()

    def _get_frame(self,
                    renderer: ClipRenderer,
                    playhead_frame: int
                    ) -> Optional[torch.Tensor]:
        """
        Decode source frame using ClipRenderer mapping.
        Returns [H, W, 3] float on GPU.
        """
        decoder = self.get_decoder(
            renderer.clip.filepath
        )
        if decoder is None:
            return None

        # ClipRenderer handles in_point, speed, etc.
        source_frame = renderer.timeline_to_source_frame(
            playhead_frame
        )
        source_frame = max(
            0, min(source_frame, decoder.frame_count - 1)
        )

        try:
            frame = decoder.get_frame(source_frame)
            # decord may return numpy in worker threads
            # if torch bridge not set — convert defensively
            if not isinstance(frame, torch.Tensor):
                frame = torch.from_numpy(
                    frame.asnumpy()
                    if hasattr(frame, 'asnumpy')
                    else frame.__array__()
                )
            return frame.float()
        except Exception as e:
            print(f"Frame decode error: {e}")
            return None

    def _apply_motion(self,
                       frame: torch.Tensor,
                       motion: dict
                       ) -> torch.Tensor:
        """
        Apply motion to frame.
        Fast path: if centered and no rotation,
        just interpolate directly to canvas size.
        """
        scale    = (motion.get('scale') or 100.0) / 100.0
        pos_x    = motion.get('position_x') or 960.0
        pos_y    = motion.get('position_y') or 540.0
        rotation = motion.get('rotation') or 0.0

        if scale <= 0:
            scale = 0.01

        t = frame.permute(2, 0, 1).unsqueeze(0) / 255.0

        # --- FAST PATH ---
        # centered clip, no rotation → single interpolate
        # to canvas size. Skips canvas allocation + paste.
        cx_target = self.width  / 2.0
        cy_target = self.height / 2.0
        is_centered = (
            abs(pos_x - cx_target) < 2 and
            abs(pos_y - cy_target) < 2
        )
        if is_centered and abs(rotation) < 0.01 and abs(scale - 1.0) < 0.001:
            # True fast path: centered, no rotation, no scale change
            # — just resize source to canvas directly
            t = F.interpolate(
                t,
                size=(self.height, self.width),
                mode='bilinear',
                align_corners=False
            )
            return t.squeeze(0).permute(1, 2, 0) * 255.0

        # --- FULL PATH — offset/rotated clips ---
        src_h = frame.shape[0]
        src_w = frame.shape[1]
        new_h = max(1, int(src_h * scale))
        new_w = max(1, int(src_w * scale))

        t = F.interpolate(
            t, size=(new_h, new_w),
            mode='bilinear', align_corners=False
        )

        if abs(rotation) > 0.01:
            import math
            angle_rad = math.radians(-rotation)  # negate: positive = CCW in screen coords
            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)
            # affine grid for rotation around center
            theta = torch.tensor(
                [[cos_a, -sin_a, 0.0],
                 [sin_a,  cos_a, 0.0]],
                dtype=torch.float32, device=t.device
            ).unsqueeze(0)
            grid = F.affine_grid(
                theta,
                t.size(),
                align_corners=False
            )
            t = F.grid_sample(
                t, grid,
                mode='bilinear',
                padding_mode='zeros',
                align_corners=False
            )
            new_h = t.shape[2]
            new_w = t.shape[3]

        canvas = torch.zeros(
            1, 3, self.height, self.width,
            dtype=torch.float32, device='cuda'
        )

        cx = int(pos_x)
        cy = int(pos_y)
        x1 = cx - new_w // 2
        y1 = cy - new_h // 2
        x2 = x1 + new_w
        y2 = y1 + new_h

        sx1 = max(0, -x1);  sy1 = max(0, -y1)
        dx1 = max(0, x1);   dy1 = max(0, y1)
        dx2 = min(self.width, x2)
        dy2 = min(self.height, y2)
        sx2 = sx1 + (dx2 - dx1)
        sy2 = sy1 + (dy2 - dy1)

        if dx2 > dx1 and dy2 > dy1:
            canvas[0, :, dy1:dy2, dx1:dx2] = (
                t[0, :, sy1:sy2, sx1:sx2]
            )

        return canvas.squeeze(0).permute(1, 2, 0) * 255.0

    def _fit_to_canvas(self,
                        frame: torch.Tensor
                        ) -> torch.Tensor:
        t = frame.permute(2, 0, 1).unsqueeze(0) / 255.0
        t = F.interpolate(
            t,
            size=(self.height, self.width),
            mode='bilinear',
            align_corners=False
        )
        return t.squeeze(0).permute(1, 2, 0) * 255.0

    def _apply_video_effects(self,
                               clip,
                               frame: torch.Tensor
                               ) -> torch.Tensor:
        """
        Run the clip's video effect stack on the frame.
        Skips effects at default values for performance.
        frame: float32 [H, W, 3] on GPU (0-255 range)
        Returns: float32 [H, W, 3] on GPU (0-255 range)
        """
        from core.effects import StreamType
        for effect in clip.effect_stack:
            if not effect.enabled:
                continue
            if effect.stream_type not in (
                StreamType.VIDEO, StreamType.ANY
            ):
                continue
            # Skip motion and opacity — handled separately
            if effect.id in ('motion', 'opacity', 'time_remap'):
                continue
            try:
                params = effect.get_all()
                # Convert to uint8 for apply_video, back to float
                frame_u8 = frame.clamp(0, 255).byte()
                result = effect.apply_video(frame_u8, params)
                frame = result.float()
            except Exception as e:
                print(f"Effect {effect.id} error: {e}")
        return frame

    def close(self):
        self._decoders.clear()
        self._frame_cache.clear()
