"""
Project save/load — JSON serialization.

Saves the complete project state including:
- Sequence settings and tracks
- All clips with positions, in/out points,
  envelopes, link groups
- Media pool references (paths only)

Does NOT save:
- Waveform cache (recomputed on load)
- GPU state (recomputed on load)
"""

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.project import Project

PROJECT_VERSION = 1


# ── Serialization ─────────────────────────────────────────────

def save_project(project: 'Project',
                 filepath: str) -> bool:
    """
    Save project to JSON file.
    Returns True on success.
    """
    try:
        data = _serialize_project(project)
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        project.project_path = filepath
        project.is_dirty = False
        return True
    except Exception as e:
        print(f'Save error: {e}')
        return False


def load_project(filepath: str) -> 'Project':
    """
    Load project from JSON file.
    Returns Project on success, raises on error.
    """
    path = Path(filepath)
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    version = data.get('version', 1)
    if version > PROJECT_VERSION:
        raise ValueError(
            f'Project version {version} not supported'
        )

    return _deserialize_project(data, filepath)


# ── Serialize helpers ─────────────────────────────────────────

def _serialize_project(project: 'Project') -> dict:
    seq = project.active_sequence
    return {
        'version':   PROJECT_VERSION,
        'name':      project.name,
        'sequence':  _serialize_sequence(seq) if seq else None,
        'clips':     [
            _serialize_clip(c)
            for c in project.clips.values()
        ],
        'media_pool': [
            _serialize_media_item(item)
            for item in project.media_pool.values()
        ],
    }


def _serialize_sequence(seq) -> dict:
    return {
        'id':   seq.id,
        'name': seq.name,
        'settings': {
            'width':          seq.settings.width,
            'height':         seq.settings.height,
            'fps':            seq.settings.fps,
            'sample_rate':    seq.settings.sample_rate,
            'audio_channels': seq.settings.audio_channels,
        },
        'video_tracks': [
            _serialize_track(t)
            for t in seq.video_tracks
        ],
        'audio_tracks': [
            _serialize_track(t)
            for t in seq.audio_tracks
        ],
    }


def _serialize_track(track) -> dict:
    return {
        'id':      track.id,
        'name':    track.name,
        'index':   track.index,
        'muted':   track.muted,
        'locked':  track.locked,
        'visible': track.visible,
        'height':  track.height,
    }


def _serialize_clip(clip) -> dict:
    return {
        'id':           clip.id,
        'filepath':     clip.filepath,
        'name':         clip.name,
        'clip_type':    clip.clip_type.value,
        'has_video':    clip.has_video,
        'has_audio':    clip.has_audio,
        'source_width':  clip.source_width,
        'source_height': clip.source_height,
        'source_fps':    clip.source_fps,
        'source_frames': clip.source_frames,
        'track':        clip.track,
        'start_frame':  clip.start_frame,
        'in_point':     clip.in_point,
        'out_point':    clip.out_point,
        'stream_index': clip.stream_index,
        'link_group_id': clip.link_group_id,
        'enabled':      clip.enabled,
        'muted':        clip.muted,
        'volume':       clip.volume,
        'label_color':  clip.label_color,
        # static effect values: motion, lumetri, time remap. Keyframed
        # parameters live in 'envelopes' instead.
        'effects':      [
            {
                'id':      eff.id,
                'enabled': eff.enabled,
                'params':  eff.get_all(),
            }
            for eff in clip.effect_stack
        ],
        'envelopes':    {
            k: _serialize_envelope(v)
            for k, v in clip.envelopes.items()
        },
    }


def _serialize_envelope(env) -> dict:
    return {
        'param':         env.param,
        'default_value': env.default_value,
        'keyframes':     [
            {'frame': kf.frame, 'value': kf.value}
            for kf in env.keyframes
        ],
    }


def _serialize_media_item(item) -> dict:
    return {
        'id':        item.id,
        'filepath':  item.filepath,
        'name':      item.name,
        'has_video': item.has_video,
        'has_audio':       item.has_audio,
        'source_width':    getattr(item, 'source_width',    1920),
        'source_height':   getattr(item, 'source_height',   1080),
        'source_fps':      getattr(item, 'source_fps',      29.97),
        'source_frames':   getattr(item, 'source_frames',   0),
        'source_duration': getattr(item, 'source_duration', 0.0),
    }


# ── Deserialize helpers ───────────────────────────────────────

def _deserialize_project(data: dict,
                          filepath: str) -> 'Project':
    from core.project import Project
    from core.track import (
        Sequence, SequenceSettings,
        Track, TrackType
    )
    from core.clip import Clip, ClipType
    from core.envelope import Envelope, Keyframe

    project = Project()
    project.name     = data.get('name', 'Untitled')
    project.project_path = filepath
    project.is_dirty = False

    # ── sequence ─────────────────────────────────────
    seq_data = data.get('sequence')
    if seq_data:
        settings_data = seq_data.get('settings', {})
        settings = SequenceSettings(
            width=settings_data.get('width',    1920),
            height=settings_data.get('height',  1080),
            fps=settings_data.get('fps',        29.97),
            sample_rate=settings_data.get(
                'sample_rate', 48000
            ),
            audio_channels=settings_data.get(
                'audio_channels', 2
            ),
        )

        video_tracks = [
            _deserialize_track(t, TrackType.VIDEO)
            for t in seq_data.get('video_tracks', [])
        ]
        audio_tracks = [
            _deserialize_track(t, TrackType.AUDIO)
            for t in seq_data.get('audio_tracks', [])
        ]

        seq = Sequence(
            name=seq_data.get('name', 'Sequence 01'),
            id=seq_data.get('id', str(uuid.uuid4())),
            settings=settings,
            video_tracks=video_tracks or None,
            audio_tracks=audio_tracks or None,
        )
        # override default tracks if we loaded them
        if video_tracks:
            seq.video_tracks = video_tracks
        if audio_tracks:
            seq.audio_tracks = audio_tracks

        project.sequences = {seq.id: seq}
        project.active_sequence_id = seq.id

    # ── clips ─────────────────────────────────────────
    for clip_data in data.get('clips', []):
        clip = _deserialize_clip(clip_data)
        project.clips[clip.id] = clip

    # ── media pool ────────────────────────────────────
    for item_data in data.get('media_pool', []):
        _deserialize_media_item(item_data, project)

    # compute total_frames as plain attribute
    project.total_frames = max(
        (c.start_frame + c.duration
         for c in project.clips.values()),
        default=0
    )

    return project


def _deserialize_track(data: dict, tt) -> 'Track':
    from core.track import Track
    t = Track(
        track_type=tt,
        index=data['index'],
        id=data.get('id', str(uuid.uuid4())),
        name=data.get('name', ''),
    )
    t.muted   = data.get('muted',   False)
    t.locked  = data.get('locked',  False)
    t.visible = data.get('visible', True)
    t.height  = data.get('height',  40)
    return t


def _deserialize_clip(data: dict) -> 'Clip':
    from core.clip import Clip, ClipType
    from core.envelope import Envelope, Keyframe

    clip = Clip(
        filepath=data['filepath'],
        clip_type=ClipType(
            data.get('clip_type', 'video_audio')
        ),
        id=data['id'],
        name=data.get('name', ''),
        has_video=data.get('has_video', True),
        has_audio=data.get('has_audio', True),
        source_width=data.get('source_width',   1920),
        source_height=data.get('source_height', 1080),
        source_fps=data.get('source_fps',       29.97),
        source_frames=data.get('source_frames', 0),
        track=data.get('track',       0),
        start_frame=data.get('start_frame', 0),
        in_point=data.get('in_point',   0),
        out_point=data.get('out_point', -1),
        stream_index=data.get('stream_index', 0),
        link_group_id=data.get('link_group_id'),
        enabled=data.get('enabled',  True),
        muted=data.get('muted',      False),
        volume=data.get('volume',    1.0),
        label_color=data.get(
            'label_color', '#4a9de0'
        ),
    )

    # restore effect parameters onto the stack the clip built itself
    for eff_data in data.get('effects', []):
        eff = clip.get_effect(eff_data.get('id'))
        if eff is None:
            continue
        eff.enabled = eff_data.get('enabled', True)
        for name, value in (eff_data.get('params') or {}).items():
            eff.set(name, value)

    # projects saved before the anchor did anything carry 960x540,
    # which is only the centre of a 1080p source
    clip.migrate_anchor()

    # restore envelopes
    for key, env_data in data.get(
        'envelopes', {}
    ).items():
        env = Envelope(
            param=env_data['param'],
            default_value=env_data.get(
                'default_value', 1.0
            ),
        )
        for kf_data in env_data.get('keyframes', []):
            env.keyframes.append(
                Keyframe(
                    frame=kf_data['frame'],
                    value=kf_data['value'],
                )
            )
        clip.envelopes[key] = env

    return clip


def _deserialize_media_item(data: dict,
                              project) -> None:
    """Re-register media item in the pool."""
    from core.project import MediaPoolItem
    item = MediaPoolItem(
        filepath=data['filepath'],
        id=data.get('id', str(uuid.uuid4())),
        name=data.get('name', ''),
        has_video=data.get('has_video', True),
        has_audio=data.get('has_audio', True),
        source_width=data.get('source_width',   1920),
        source_height=data.get('source_height', 1080),
        source_fps=data.get('source_fps',       29.97),
        source_frames=data.get('source_frames', 0),
        source_duration=data.get(
            'source_duration', 0.0
        ),
    )
    project.media_pool[item.id] = item
