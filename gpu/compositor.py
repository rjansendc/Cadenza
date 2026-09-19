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
        # preview uses proxy media where it exists; export does not
        self.use_proxies = True
        self.seq_width  = sequence.settings.width
        self.seq_height = sequence.settings.height
        self.width    = sequence.settings.width
        self.height   = sequence.settings.height
        self.fps      = sequence.settings.fps
        # 1.0 = full size. Preview quality composites smaller, which
        # cuts every per-pixel cost: interpolate, paste, blend, and
        # the frame that comes back to the UI.
        self.geom_scale = 1.0

        self._decoders:    Dict[str, object] = {}
        self._frame_cache: Dict[int, object] = {}
        self._cache_size   = 10
        # cache renderers — rebuilt only when clips change
        self._renderers:   list = []
        self._clips_hash:  int  = 0
        import threading
        self._decoder_lock = threading.Lock()
        # decoding is the floor on playback: one 4K frame costs ~9ms,
        # and stacked angles pay that per clip. PyAV releases the GIL
        # while decoding, so fetching them at once overlaps the work.
        self._decode_pool = None

        self._blank = torch.zeros(
            self.height, self.width, 3,
            dtype=torch.uint8
        )

    def set_use_proxies(self, enabled: bool):
        """Switch between proxy and original media (export uses originals)."""
        if enabled == self.use_proxies:
            return
        self.use_proxies = enabled
        with self._decoder_lock:
            self._decoders.clear()
        self.invalidate_cache()

    def set_preview_size(self, width: int, height: int):
        """
        Composite at this size instead of the full sequence size.

        Motion values are expressed in sequence pixels, so everything
        geometric is scaled by the same factor — otherwise a clip keeps
        its full-size position on a smaller canvas and lands in the
        corner.
        """
        width  = max(16, int(width))
        height = max(16, int(height))
        if (width, height) == (self.width, self.height):
            return
        self.width  = width
        self.height = height
        self.geom_scale = (width / self.seq_width) if self.seq_width else 1.0
        self._blank = torch.zeros(
            self.height, self.width, 3, dtype=torch.uint8
        )
        self.invalidate_cache()

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
                    dec = VideoDecoder(
                        filepath, use_proxy=self.use_proxies)
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
                         draft: bool = False,
                         keep_on_gpu: bool = False
                         ) -> torch.Tensor:
        # Cache is opt-in — only playback uses it.
        # Scrub calls always pass use_cache=False (default)
        # so they never get a stale hit.
        if use_cache and playhead_frame in self._frame_cache:
            return self._frame_cache[playhead_frame]

        result = self._composite_internal(
            clips, playhead_frame, sequence, draft=draft
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
                              sequence=None,
                              draft: bool = False
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

        # The canvas is only needed if something shows through: the
        # bottom clip is usually opaque and replaces it outright.
        canvas = None

        # composite bottom to top (V1 first = lowest)
        active_sorted = sorted(
            active,
            key=lambda r: r.clip.track
        )

        # Cutting between camera angles stacks full-frame clips, and
        # decoding one 4K frame costs ~9ms. Anything completely hidden
        # behind an opaque full-frame clip above it is never seen, so
        # start from the topmost clip that covers the canvas.
        for i in range(len(active_sorted) - 1, 0, -1):
            if self._covers_canvas(active_sorted[i], playhead_frame):
                active_sorted = active_sorted[i:]
                break

        frames = self._get_frames(
            active_sorted, playhead_frame, draft=draft)

        for renderer in active_sorted:
            try:
                frame_tensor = frames.get(id(renderer))
                if frame_tensor is None:
                    continue

                # apply motion using ClipRenderer. A proxy frame is
                # smaller than the source the motion values refer to,
                # so tell _apply_motion how much smaller.
                motion = renderer.get_motion_at(playhead_frame)
                src_w = renderer.clip.source_width or 0
                src_scale = (src_w / frame_tensor.shape[1]
                             if src_w and frame_tensor.shape[1] else 1.0)
                frame_tensor = self._apply_motion(
                    frame_tensor, motion, src_scale
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
                    if canvas is None:
                        canvas = torch.zeros(
                            self.height, self.width, 3,
                            dtype=torch.float32,
                            device=frame_tensor.device
                        )
                    canvas = (
                        canvas * (1.0 - opacity) +
                        frame_tensor * opacity
                    )
            except Exception as e:
                import traceback; traceback.print_exc()
                continue

        if canvas is None:
            return self._blank.clone()
        return canvas.clamp(0, 255).byte()

    def _get_frame(self,
                    renderer: ClipRenderer,
                    playhead_frame: int,
                    draft: bool = False
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
            frame = decoder.get_frame(source_frame, draft=draft)
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

    def _get_frames(self, renderers, playhead_frame: int,
                     draft: bool = False) -> dict:
        """
        Decode every clip needed for this frame, in parallel when
        there is more than one. Falls back to sequential decoding if
        the pool cannot be used.
        """
        if len(renderers) <= 1:
            return {
                id(r): self._get_frame(r, playhead_frame, draft=draft)
                for r in renderers
            }

        try:
            if self._decode_pool is None:
                from concurrent.futures import ThreadPoolExecutor
                self._decode_pool = ThreadPoolExecutor(
                    max_workers=4,
                    thread_name_prefix='decode')
            futures = {
                id(r): self._decode_pool.submit(
                    self._get_frame, r, playhead_frame, draft)
                for r in renderers
            }
            return {key: f.result() for key, f in futures.items()}
        except Exception as e:
            print(f"Parallel decode unavailable ({e}), falling back")
            return {
                id(r): self._get_frame(r, playhead_frame, draft=draft)
                for r in renderers
            }

    def _covers_canvas(self, renderer, playhead_frame: int) -> bool:
        """
        Does this clip fill the whole frame, opaque, with nothing
        underneath showing? Deliberately conservative: any rotation,
        crop or transparency and the answer is no.
        """
        try:
            if renderer.get_opacity_at(playhead_frame) < 0.999:
                return False

            m = renderer.get_motion_at(playhead_frame)
            if abs(m.get('rotation') or 0.0) > 0.01:
                return False
            for k in ('crop_left', 'crop_right',
                      'crop_top', 'crop_bottom'):
                if (m.get(k) or 0.0) > 0.0:
                    return False

            gs = self.geom_scale
            scale_h = (m.get('scale') or 100.0) / 100.0 * gs
            uniform = m.get('uniform_scale')
            if uniform is None:
                uniform = True
            scale_w = (scale_h if uniform
                       else (m.get('scale_x') or 100.0) / 100.0 * gs)

            clip = renderer.clip
            src_w = clip.source_width  or self.seq_width
            src_h = clip.source_height or self.seq_height
            w = src_w * scale_w
            h = src_h * scale_h

            cx = (m.get('position_x') or self.seq_width / 2.0) * gs
            cy = (m.get('position_y') or self.seq_height / 2.0) * gs

            return (cx - w / 2.0 <= 0.5 and cy - h / 2.0 <= 0.5 and
                    cx + w / 2.0 >= self.width - 0.5 and
                    cy + h / 2.0 >= self.height - 0.5)
        except Exception:
            return False      # never let an optimisation break a frame

    def _apply_motion(self,
                       frame: torch.Tensor,
                       motion: dict,
                       src_scale: float = 1.0
                       ) -> torch.Tensor:
        """
        Apply motion to frame.
        Fast path: if centered and no rotation,
        just interpolate directly to canvas size.
        """
        # 'scale' drives both axes while Uniform Scale is on.
        # With it off, 'scale' is height only and 'scale_x'
        # (Scale Width) stretches/squeezes the width on its own.
        scale_h  = (motion.get('scale') or 100.0) / 100.0
        pos_x    = motion.get('position_x') or 960.0
        pos_y    = motion.get('position_y') or 540.0
        rotation = motion.get('rotation') or 0.0

        uniform  = motion.get('uniform_scale')
        if uniform is None:
            uniform = True
        scale_w  = (
            scale_h if uniform
            else (motion.get('scale_x') or 100.0) / 100.0
        )

        # a proxy frame stands in for a larger source: scale up to
        # the size the motion values assume
        if src_scale and abs(src_scale - 1.0) > 1e-6:
            scale_h *= src_scale
            scale_w *= src_scale

        # preview quality: shrink the picture and its placement together
        gs = self.geom_scale
        if gs != 1.0:
            scale_h *= gs
            scale_w *= gs
            pos_x   *= gs
            pos_y   *= gs

        if scale_h <= 0:
            scale_h = 0.01
        if scale_w <= 0:
            scale_w = 0.01

        # --- CROP (percent of source, per edge) ---
        # Trim the source first, then keep the remaining picture where
        # it was: the cropped edge goes empty instead of the image
        # jumping across the frame.
        crop_l = max(0.0, min(100.0, motion.get('crop_left')   or 0.0)) / 100.0
        crop_r = max(0.0, min(100.0, motion.get('crop_right')  or 0.0)) / 100.0
        crop_t = max(0.0, min(100.0, motion.get('crop_top')    or 0.0)) / 100.0
        crop_b = max(0.0, min(100.0, motion.get('crop_bottom') or 0.0)) / 100.0
        has_crop = (crop_l or crop_r or crop_t or crop_b)

        # dimensions as decoded, before cropping: the anchor is
        # expressed against the whole source
        frame_h_full = frame.shape[0]
        frame_w_full = frame.shape[1]

        crop_off_x = 0.0
        crop_off_y = 0.0
        if has_crop:
            h_src = frame.shape[0]
            w_src = frame.shape[1]

            x1 = int(w_src * crop_l)
            x2 = w_src - int(w_src * crop_r)
            y1 = int(h_src * crop_t)
            y2 = h_src - int(h_src * crop_b)

            # opposing crops can meet - always leave one pixel
            x1 = max(0, min(x1, w_src - 1))
            x2 = max(x1 + 1, min(x2, w_src))
            y1 = max(0, min(y1, h_src - 1))
            y2 = max(y1 + 1, min(y2, h_src))

            # how far the kept region's centre sits from the source
            # centre, in source pixels - used to hold it in place
            crop_off_x = (x1 + x2) / 2.0 - w_src / 2.0
            crop_off_y = (y1 + y2) / 2.0 - h_src / 2.0

            frame = frame[y1:y2, x1:x2, :]

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
        no_scaling = (
            abs(scale_h - 1.0) < 0.001 and
            abs(scale_w - 1.0) < 0.001
        )
        # Only when the source already matches the canvas: this path
        # resizes straight to canvas size, which would stretch a source
        # of a different shape (a 4:3 clip in a 16:9 sequence) instead
        # of pillarboxing it.
        same_size = (
            frame.shape[0] == self.height and
            frame.shape[1] == self.width
        )
        if (is_centered and abs(rotation) < 0.01
                and no_scaling and not has_crop and same_size):
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
        new_h = max(1, int(src_h * scale_h))
        new_w = max(1, int(src_w * scale_w))

        # Anti-flicker: shrinking with plain bilinear samples every
        # Nth pixel, so fine detail — a striped shirt, distant railings
        # — shimmers as the picture moves. Filtering across the pixels
        # being dropped is what removes it, at a little softness.
        anti_flicker = motion.get('anti_flicker') or 0.0
        smooth = (anti_flicker > 0.0 and
                  (new_w < frame.shape[1] or new_h < frame.shape[0]))
        t = F.interpolate(
            t, size=(new_h, new_w),
            mode='bilinear', align_corners=False,
            antialias=bool(smooth)
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

        # Anchor point: the spot in the source that sits at Position,
        # and that rotation turns around. Stored in ORIGINAL source
        # pixels, so a proxy frame has to be measured in those terms.
        ss = src_scale if src_scale else 1.0
        orig_w = frame_w_full * ss
        orig_h = frame_h_full * ss

        anchor_x = motion.get('anchor_x')
        anchor_y = motion.get('anchor_y')
        # Unset means centre. Each axis independently: fixing one of
        # them must never move the other, which is what special-casing
        # the 960x540 pair used to do.
        if anchor_x is None:
            anchor_x = orig_w / 2.0
        if anchor_y is None:
            anchor_y = orig_h / 2.0

        # vector from the anchor to the middle of the picture. scale_w
        # already carries the proxy factor, so take it back out to work
        # in original source pixels.
        off_x = (orig_w / 2.0 - anchor_x) * (scale_w / ss)
        off_y = (orig_h / 2.0 - anchor_y) * (scale_h / ss)
        if abs(rotation) > 0.01 and (off_x or off_y):
            import math as _math
            a = _math.radians(-rotation)
            off_x, off_y = (
                off_x * _math.cos(a) - off_y * _math.sin(a),
                off_x * _math.sin(a) + off_y * _math.cos(a),
            )

        cx = int(round(pos_x + crop_off_x * scale_w + off_x))
        cy = int(round(pos_y + crop_off_y * scale_h + off_y))
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
            # an effect at its defaults changes nothing, but running it
            # still costs two conversions of the whole frame each way
            try:
                if effect.is_at_defaults():
                    continue
            except Exception:
                pass
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
        if self._decode_pool is not None:
            self._decode_pool.shutdown(wait=False)
            self._decode_pool = None
        self._decoders.clear()
        self._frame_cache.clear()
