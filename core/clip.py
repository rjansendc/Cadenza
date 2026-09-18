from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum
import uuid
from core.envelope import Envelope


def _db_to_linear(db: float) -> float:
    from effects.audio.volume import db_to_linear
    return db_to_linear(float(db))


def _linear_to_db(linear: float) -> float:
    from effects.audio.volume import linear_to_db
    db = linear_to_db(float(linear))
    return -96.0 if db == float('-inf') else db

class ClipType(Enum):
    VIDEO       = "video"
    AUDIO       = "audio"
    VIDEO_AUDIO = "video_audio"
    IMAGE       = "image"

@dataclass
class Clip:
    filepath:   str
    clip_type:  ClipType = ClipType.VIDEO_AUDIO

    id:   str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ''

    has_video: bool = True
    has_audio: bool = True

    source_width:   int   = 1920
    source_height:  int   = 1080
    source_fps:     float = 29.97
    source_frames:  int   = 0

    track:       int = 0
    start_frame: int = 0
    in_point:    int = 0
    out_point:   int = -1

    effect_stack: List = field(default_factory=list)

    # linking
    link_group_id: Optional[str] = None
    stream_index:  int = 0   # which stream in source file
                              # 0=video, 1=first audio, 2=second audio...

    enabled:     bool = True
    muted:       bool = False    # added this line
    volume:      float = 1.0     # added this line
    label_color: str  = '#4a9de0'

    # per-clip automation envelopes
    envelopes: dict = field(default_factory=dict)

    def __post_init__(self):
        from pathlib import Path
        if not self.name:
            self.name = Path(self.filepath).name
        if not self.effect_stack:
            self._build_default_stack()
        # build default envelopes
        if not self.envelopes:
            self._build_default_envelopes()

    def _build_default_envelopes(self):
        """Create default flat envelopes."""
        if self.has_audio:
            self.envelopes['volume'] = Envelope(
                param='volume',
                default_value=1.0
            )
        if self.has_video:
            self.envelopes['opacity'] = Envelope(
                param='opacity',
                default_value=1.0
            )
        if self.has_audio:
            self.envelopes['pan'] = Envelope(
                param='pan',
                default_value=0.0
            )

    # ── effect parameter keyframes ────────────────────────────
    # Envelopes are keyed "<effect_id>.<param>" (e.g. "motion.scale").
    # Opacity, volume and pan predate that scheme: they keep their bare
    # names so old projects still load, and they store values in the
    # units the renderer wants (0-1, linear gain, -1..1) rather than the
    # units the panel shows (%, dB, -100..100). PARAM_CODECS carries
    # both facts, so callers can work in panel units throughout.

    PARAM_CODECS = {
        ('opacity', 'opacity'): (
            'opacity',
            lambda v: float(v) / 100.0,      # panel % -> envelope
            lambda v: float(v) * 100.0,      # envelope -> panel %
        ),
        ('pan', 'pan'): (
            'pan',
            lambda v: float(v) / 100.0,
            lambda v: float(v) * 100.0,
        ),
        ('volume', 'volume_db'): (
            'volume',
            lambda v: _db_to_linear(v),      # panel dB -> linear gain
            lambda v: _linear_to_db(v),
        ),
    }

    @classmethod
    def _param_codec(cls, effect_id: str, param: str):
        """(envelope key, to_envelope, from_envelope) for a parameter."""
        codec = cls.PARAM_CODECS.get((effect_id, param))
        if codec is not None:
            return codec
        return (f"{effect_id}.{param}", float, float)

    @classmethod
    def envelope_key(cls, effect_id: str, param: str) -> str:
        return cls._param_codec(effect_id, param)[0]

    def is_param_animated(self, effect_id: str,
                           param: str) -> bool:
        """True when this parameter has keyframes."""
        env = self.envelopes.get(
            self.envelope_key(effect_id, param))
        return bool(env and env.keyframes)

    def has_keyframe_at(self, effect_id: str, param: str,
                         frame: int) -> bool:
        env = self.envelopes.get(
            self.envelope_key(effect_id, param))
        if not env:
            return False
        return any(kf.frame == frame for kf in env.keyframes)

    def get_param_at(self, effect_id: str, param: str,
                      frame: int):
        """
        Parameter value at a clip-local frame, in panel units: the
        envelope when keyframed, otherwise the effect's static value.
        """
        key, _to_env, from_env = self._param_codec(effect_id, param)
        env = self.envelopes.get(key)
        if env and env.keyframes:
            return from_env(env.value_at(frame))
        fx = self.get_effect(effect_id)
        return fx.get(param) if fx else None

    def set_param_keyframe(self, effect_id: str, param: str,
                            frame: int, value: float):
        """
        Add or move a keyframe, creating the envelope if needed.
        `value` is in panel units.
        """
        from core.envelope import Envelope
        key, to_env, _from_env = self._param_codec(effect_id, param)
        env = self.envelopes.get(key)
        if env is None:
            fx = self.get_effect(effect_id)
            static = fx.get(param) if fx else value
            env = Envelope(
                param=key,
                default_value=to_env(
                    static if static is not None else value),
            )
            self.envelopes[key] = env
        env.add_keyframe(frame, to_env(value))

    def remove_param_keyframe(self, effect_id: str, param: str,
                               frame: int):
        """
        Remove one keyframe. When the last one goes, drop the
        envelope so the static value takes over again — except for
        opacity/volume/pan, whose flat envelope IS the static value.
        """
        key, _to_env, _from_env = self._param_codec(effect_id, param)
        env = self.envelopes.get(key)
        if env is None:
            return
        env.remove_keyframe(frame)
        if not env.keyframes and '.' in key:
            del self.envelopes[key]

    def _envelope_keys(self, effect_id=None) -> list:
        """Envelope keys belonging to an effect, or all of them."""
        if effect_id is None:
            return list(self.envelopes.keys())
        prefix = f"{effect_id}."
        legacy = {k for (eid, _p), (k, _t, _f)
                  in self.PARAM_CODECS.items() if eid == effect_id}
        return [k for k in self.envelopes
                if k.startswith(prefix) or k in legacy]

    def keyframe_frames(self, effect_id=None) -> list:
        """
        Every frame carrying a keyframe, sorted.
        effect_id=None covers every parameter on the clip.
        """
        frames = set()
        for key in self._envelope_keys(effect_id):
            env = self.envelopes.get(key)
            for kf in getattr(env, 'keyframes', []):
                frames.add(kf.frame)
        return sorted(frames)

    def move_keyframes(self, from_frame: int, to_frame: int,
                        effect_id=None) -> dict:
        """
        Retime every keyframe that sits on from_frame.

        Timeline markers stand for a frame, not a single parameter, so
        dragging one moves everything keyframed there together.
        Returns {envelope_key: value} for any keyframes overwritten at
        the destination, so undo can put them back.
        """
        if from_frame == to_frame:
            return {}

        moving = {}
        overwritten = {}
        for key in self._envelope_keys(effect_id):
            env = self.envelopes.get(key)
            if env is None:
                continue
            for kf in list(env.keyframes):
                if kf.frame == from_frame:
                    moving[key] = kf.value
                elif kf.frame == to_frame:
                    overwritten[key] = kf.value

        for key, value in moving.items():
            env = self.envelopes[key]
            env.remove_keyframe(from_frame)
            env.add_keyframe(to_frame, value)

        return overwritten

    def remove_keyframes_at(self, frame: int,
                             effect_id=None) -> dict:
        """
        Delete every keyframe on a frame — what a timeline marker
        stands for. Returns {envelope_key: value} so undo can restore.
        """
        removed = {}
        for key in self._envelope_keys(effect_id):
            env = self.envelopes.get(key)
            if env is None:
                continue
            for kf in list(env.keyframes):
                if kf.frame == frame:
                    removed[key] = kf.value
                    env.remove_keyframe(frame)
            # a motion envelope with no keyframes left is dead weight;
            # opacity/volume/pan keep theirs as the flat value
            if not env.keyframes and '.' in key:
                del self.envelopes[key]
        return removed

    def restore_envelope_keyframes(self, frame: int, values: dict):
        """
        Put keyframes back exactly as they were (undo helper),
        recreating any envelope that was dropped when its last
        keyframe went.
        """
        from core.envelope import Envelope
        for key, value in (values or {}).items():
            env = self.envelopes.get(key)
            if env is None:
                env = Envelope(param=key, default_value=float(value))
                self.envelopes[key] = env
            env.add_keyframe(frame, value)

    def get_volume_at(self, frame: int) -> float:
        """Volume at a specific frame."""
        env = self.envelopes.get('volume')
        if env:
            return env.value_at(frame)
        return self.volume

    def get_opacity_at(self, frame: int) -> float:
        """Opacity at a specific frame."""
        env = self.envelopes.get('opacity')
        if env:
            return env.value_at(frame)
        return 1.0

    def set_volume(self, value: float):
        """Set flat volume — no keyframes."""
        self.volume = value
        env = self.envelopes.get('volume')
        if env:
            env.default_value = value

    def set_opacity(self, value: float):
        """Set flat opacity — no keyframes."""
        env = self.envelopes.get('opacity')
        if env:
            env.default_value = value

    def set_pan(self, value: float):
        """Set flat pan — no keyframes. -1=left, 0=center, 1=right"""
        env = self.envelopes.get('pan')
        if env:
            env.default_value = value
        

    def _build_default_stack(self):
        import effects
        from core.effects import (default_video_stack,
                                   default_audio_stack,
                                   default_video_only_stack)
        if self.has_video and self.has_audio:
            self.effect_stack = default_video_stack()
        elif self.has_video:
            self.effect_stack = default_video_only_stack()
        else:
            self.effect_stack = default_audio_stack()

    def get_effect(self, effect_id: str):
        return next(
            (e for e in self.effect_stack
             if e.id == effect_id), None
        )

    def visible_effects(self):
        from core.effects import StreamType
        result = []
        for e in self.effect_stack:
            if (self.has_video and
                e.stream_type in (StreamType.VIDEO,
                                   StreamType.ANY)):
                result.append(e)
            elif (self.has_audio and
                  e.stream_type == StreamType.AUDIO):
                result.append(e)
        return result

    @property
    def duration(self) -> int:
        if self.out_point == -1:
            return self.source_frames - self.in_point
        return self.out_point - self.in_point

    def scale_to_frame(self, canvas_w: int,
                        canvas_h: int):
        motion = self.get_effect('motion')
        if motion:
            motion.scale_to_frame(
                self.source_width, self.source_height,
                canvas_w, canvas_h
            )

    @property
    def is_linked(self) -> bool:
        return self.link_group_id is not None

    def __repr__(self):
        linked = f' linked={self.link_group_id[:8]}' \
                 if self.link_group_id else ''
        return (f"Clip({self.name} | "
                f"{'V' if self.has_video else ''}"
                f"{'A' if self.has_audio else ''} | "
                f"track={self.track} | "
                f"start={self.start_frame} | "
                f"stream={self.stream_index}"
                f"{linked})")