from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path
import uuid
import json

from core.clip import Clip, ClipType
from core.track import Sequence, SequenceSettings, Track, TrackType

@dataclass
class MediaPoolItem:
    """
    A file that has been imported into the project.
    Separate from Clip — one media item can appear 
    on the timeline multiple times as different clips.
    """
    filepath:   str
    id:         str   = field(
        default_factory=lambda: str(uuid.uuid4())
    )
    name:       str   = ''

    # populated by importer on first load
    has_video:      bool  = True
    has_audio:      bool  = True
    source_width:   int   = 1920
    source_height:  int   = 1080
    source_fps:     float = 29.97
    source_frames:  int   = 0
    source_duration: float = 0.0   # seconds
    file_size:      int   = 0      # bytes

    def __post_init__(self):
        if not self.name:
            self.name = Path(self.filepath).name

    @property
    def duration_timecode(self) -> str:
        """Human readable duration e.g. 00:01:23:15"""
        total = self.source_duration
        h  = int(total // 3600)
        m  = int((total % 3600) // 60)
        s  = int(total % 60)
        f  = int((total % 1) * self.source_fps)
        return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"

    @property
    def resolution_label(self) -> str:
        if self.source_width >= 3840:
            return '4K'
        elif self.source_width >= 1920:
            return '1080p'
        elif self.source_width >= 1280:
            return '720p'
        return f"{self.source_width}x{self.source_height}"

    def __repr__(self):
        return (f"MediaPoolItem({self.name} | "
                f"{self.resolution_label} | "
                f"{self.duration_timecode})")


@dataclass
class Project:
    """
    Top-level container — everything that gets 
    saved and loaded as a .veditor project file.
    """
    name:    str = 'Untitled Project'
    id:      str = field(
        default_factory=lambda: str(uuid.uuid4())
    )

    # where the project file lives on disk
    project_path: Optional[str] = None

    # all imported media
    media_pool: Dict[str, MediaPoolItem] = field(
        default_factory=dict
    )

    # all sequences (like Premiere's sequences)
    sequences: Dict[str, Sequence] = field(
        default_factory=dict
    )

    # which sequence is currently open
    active_sequence_id: Optional[str] = None

    # all clips placed on timelines
    # keyed by clip id
    clips: Dict[str, Clip] = field(
        default_factory=dict
    )

    # app state (not saved — runtime only)
    is_dirty: bool = False   # unsaved changes flag

    def __post_init__(self):
        # create a default sequence if none exist
        if not self.sequences:
            seq = Sequence(name='Sequence 01')
            self.sequences[seq.id] = seq
            self.active_sequence_id = seq.id

    # --- Media Pool ---

    def import_media(self, filepath: str) -> MediaPoolItem:
        """
        Add a file to the media pool.
        Metadata populated later by importer.
        """
        item = MediaPoolItem(filepath=filepath)
        self.media_pool[item.id] = item
        self.is_dirty = True
        return item

    def remove_media(self, item_id: str):
        """Remove from pool — does not remove 
        clips already on timeline."""
        self.media_pool.pop(item_id, None)
        self.is_dirty = True

    # --- Sequences ---

    def add_sequence(self, 
                     name: str = None,
                     settings: SequenceSettings = None
                     ) -> Sequence:
        seq = Sequence(
            name=name or f"Sequence {len(self.sequences)+1:02d}",
            settings=settings or SequenceSettings()
        )
        self.sequences[seq.id] = seq
        self.is_dirty = True
        return seq

    @property
    def active_sequence(self) -> Optional[Sequence]:
        if self.active_sequence_id:
            return self.sequences.get(self.active_sequence_id)
        # fallback: first sequence
        if self.sequences:
            return next(iter(self.sequences.values()))
        return None

    @active_sequence.setter
    def active_sequence(self, seq):
        """Set active sequence by object or id."""
        if seq is None:
            self.active_sequence_id = None
        elif isinstance(seq, str):
            self.active_sequence_id = seq
        else:
            # store in sequences dict if not already
            self.sequences[seq.id] = seq
            self.active_sequence_id = seq.id
        return None

    # --- Clips ---

    def add_clip(self,
                 media_item: MediaPoolItem,
                 track: int,
                 start_frame: int,
                 has_video: bool = None,
                 has_audio: bool = None,
                 stream_index: int = 0,
                 link_group_id: str = None,
                 sequence_id: str = None) -> 'Clip':
        """
        Place a single stream as a clip on the timeline.
        For multi-stream files call add_linked_clips instead.
        """
        from core.clip import Clip
        hv = has_video if has_video is not None \
             else media_item.has_video
        ha = has_audio if has_audio is not None \
             else media_item.has_audio

        clip = Clip(
            filepath=media_item.filepath,
            has_video=hv,
            has_audio=ha,
            source_width=media_item.source_width,
            source_height=media_item.source_height,
            source_fps=media_item.source_fps,
            source_frames=media_item.source_frames,
            track=track,
            start_frame=start_frame,
            stream_index=stream_index,
            link_group_id=link_group_id,
        )
        if clip.has_video and self.active_sequence:
            clip.scale_to_frame(
                self.active_sequence.settings.width,
                self.active_sequence.settings.height
            )
        self.clips[clip.id] = clip
        self.is_dirty = True
        return clip

    def add_linked_clips(self,
                          media_item: MediaPoolItem,
                          drop_row: int,
                          start_frame: int,
                          stream_info: dict,
                          sequence_id: str = None
                          ) -> List['Clip']:
        """
        Create all clips for a multi-stream file,
        linked together.

        stream_info = {
            'video_count': 1,
            'audio_count': 2,   # number of audio streams
        }

        drop_row = which row was dropped on (0-5)
        Row 0-2 = video rows (V3=0, V2=1, V1=2... 
                               but slot = row % 3)
        Row 3-5 = audio rows (A1=3, A2=4, A3=5...
                               slot = row - 3)

        Slot determines alignment:
          slot 0 → V1 + A1, A2...
          slot 1 → V2 + A2, A3...
          slot 2 → V3 + A3, A4...
        """
        from ui.constants import row_is_video, row_is_audio

        # Use actual sequence track counts (dynamic)
        seq = (self.sequences.get(sequence_id)
               if sequence_id else self.active_sequence)
        n_video = len(seq.video_tracks) if seq else 3
        n_audio = len(seq.audio_tracks) if seq else 3

        # determine slot from drop row
        if row_is_video(drop_row):
            slot = (n_video - 1) - drop_row
        else:
            slot = drop_row - n_video

        # clamp slot
        slot = max(0, min(slot, n_video - 1))

        # shared link group
        group_id = str(uuid.uuid4())
        created  = []

        # video clip
        if stream_info.get('video_count', 0) > 0:
            video_clip = self.add_clip(
                media_item,
                track=slot,
                start_frame=start_frame,
                has_video=True,
                has_audio=False,
                stream_index=0,
                link_group_id=group_id,
                sequence_id=sequence_id
            )
            created.append(video_clip)

        # audio clips — one per stream
        audio_count = stream_info.get('audio_count', 0)
        for i in range(audio_count):
            audio_track = slot + i
            # clamp to available audio tracks
            if audio_track >= n_audio:
                break
            audio_clip = self.add_clip(
                media_item,
                track=audio_track,
                start_frame=start_frame,
                has_video=False,
                has_audio=True,
                stream_index=i + 1,
                link_group_id=group_id,
                sequence_id=sequence_id
            )
            created.append(audio_clip)

    

        return created

    def get_linked_clips(self,
                          clip_id: str) -> List['Clip']:
        """All clips in the same link group."""
        clip = self.clips.get(clip_id)
        if not clip or not clip.link_group_id:
            return []
        return [
            c for c in self.clips.values()
            if c.link_group_id == clip.link_group_id
            and c.id != clip_id
        ]

    def get_link_group(self,
                        clip_id: str) -> List['Clip']:
        """All clips in group INCLUDING this one."""
        clip = self.clips.get(clip_id)
        if not clip or not clip.link_group_id:
            return [clip] if clip else []
        return [
            c for c in self.clips.values()
            if c.link_group_id == clip.link_group_id
        ]

    def link_clips(self, clip_ids: List[str]):
        """Link clips together into a new group."""
        group_id = str(uuid.uuid4())
        for clip_id in clip_ids:
            clip = self.clips.get(clip_id)
            if clip:
                clip.link_group_id = group_id
        self.is_dirty = True

    def unlink_clip(self, clip_id: str):
        """Remove ONE clip from its link group."""
        clip = self.clips.get(clip_id)
        if clip:
            clip.link_group_id = None
        self.is_dirty = True

    def unlink_group(self, clip_id: str):
        """Remove ALL clips in group from linking."""
        for clip in self.get_link_group(clip_id):
            clip.link_group_id = None
        self.is_dirty = True



    def remove_clip(self, clip_id: str):
        self.clips.pop(clip_id, None)
        self.is_dirty = True

    def get_clips_for_track(self, 
                             track: int,
                             sequence_id: str = None
                             ) -> List[Clip]:
        """All clips on a given track, sorted by start frame."""
        return sorted(
            [c for c in self.clips.values() 
             if c.track == track],
            key=lambda c: c.start_frame
        )

    def get_clips_at_frame(self, frame: int) -> List[Clip]:
        """All clips active at a given frame position."""
        return [
            c for c in self.clips.values()
            if (c.start_frame <= frame < 
                c.start_frame + c.duration)
            and c.enabled
        ]

    # --- Persistence ---

    def save(self, path: str = None):
        """Save project to .veproj JSON file."""
        save_path = path or self.project_path
        if not save_path:
            raise ValueError("No save path specified")
        self.project_path = save_path

        # Serialize media pool
        media_pool = {}
        for mid, item in self.media_pool.items():
            media_pool[mid] = {
                'id':             item.id,
                'filepath':       item.filepath,
                'name':           item.name,
                'has_video':      item.has_video,
                'has_audio':      item.has_audio,
                'source_width':   getattr(item, 'source_width',  0),
                'source_height':  getattr(item, 'source_height', 0),
                'source_fps':     getattr(item, 'source_fps',    29.97),
                'source_frames':  getattr(item, 'source_frames', 0),
                'source_duration':getattr(item, 'source_duration', 0.0),
            }

        # Serialize clips
        clips = []
        for clip in self.clips.values():
            # Serialize effect params
            effects = []
            for eff in clip.effect_stack:
                effects.append({
                    'id':      eff.id,
                    'enabled': eff.enabled,
                    'params':  eff.get_all(),
                })
            # Serialize envelopes
            envelopes = {}
            for env_name, env in clip.envelopes.items():
                envelopes[env_name] = {
                    'default_value': env.default_value,
                }
            clips.append({
                'id':            clip.id,
                'filepath':      clip.filepath,
                'track':         clip.track,
                'start_frame':   clip.start_frame,
                'in_point':      clip.in_point,
                'out_point':     clip.out_point,
                'has_video':     clip.has_video,
                'has_audio':     clip.has_audio,
                'source_width':  clip.source_width,
                'source_height': clip.source_height,
                'source_fps':    clip.source_fps,
                'source_frames': clip.source_frames,
                'stream_index':  clip.stream_index,
                'link_group_id': clip.link_group_id,
                'enabled':       clip.enabled,
                'muted':         clip.muted,
                'volume':        clip.volume,
                'label_color':   clip.label_color,
                'effects':       effects,
                'envelopes':     envelopes,
            })

        # Serialize sequences
        sequences = []
        for seq in self.sequences.values():
            sequences.append({
                'id':   seq.id,
                'name': seq.name,
                'settings': {
                    'width':       seq.settings.width,
                    'height':      seq.settings.height,
                    'fps':         seq.settings.fps,
                    'sample_rate': seq.settings.sample_rate,
                },
                'video_tracks': [
                    {'index': t.index, 'name': t.name,
                     'locked': t.locked, 'visible': t.visible}
                    for t in seq.video_tracks
                ],
                'audio_tracks': [
                    {'index': t.index, 'name': t.name,
                     'locked': t.locked, 'muted': t.muted}
                    for t in seq.audio_tracks
                ],
            })

        data = {
            'version':    '1.0.0',
            'name':       self.name,
            'id':         self.id,
            'media_pool': media_pool,
            'clips':      clips,
            'sequences':  sequences,
        }

        with open(save_path, 'w') as f:
            json.dump(data, f, indent=2)
        self.is_dirty = False
        print(f"[Save] {len(clips)} clips, "
              f"{len(media_pool)} media items → {save_path}")

    @classmethod
    def load(cls, path: str) -> 'Project':
        """Load project from .veproj JSON file."""
        with open(path, 'r') as f:
            data = json.load(f)

        version = data.get('version', '0.1.0')
        project = cls(name=data.get('name', 'Untitled'))
        project.project_path = path
        project.id = data.get('id', project.id)

        # Legacy stub format — nothing to load
        if version == '0.1.0':
            print("[Load] Legacy project format — no clips saved")
            return project

        # Restore media pool
        from core.project import MediaPoolItem
        for mid, mdata in data.get('media_pool', {}).items():
            item = MediaPoolItem(
                filepath=mdata['filepath'],
                name=mdata.get('name', ''),
            )
            item.id             = mdata['id']
            item.has_video      = mdata.get('has_video', True)
            item.has_audio      = mdata.get('has_audio', True)
            item.source_width   = mdata.get('source_width',   0)
            item.source_height  = mdata.get('source_height',  0)
            item.source_fps     = mdata.get('source_fps',     29.97)
            item.source_frames  = mdata.get('source_frames',  0)
            item.source_duration= mdata.get('source_duration',0.0)
            project.media_pool[item.id] = item

        # Restore sequences
        from core.track import Sequence, SequenceSettings, Track, TrackType
        for sdata in data.get('sequences', []):
            ss = sdata.get('settings', {})
            settings = SequenceSettings(
                width=ss.get('width', 1920),
                height=ss.get('height', 1080),
                fps=ss.get('fps', 29.97),
                sample_rate=ss.get('sample_rate', 48000),
            )
            seq = Sequence(
                id=sdata['id'],
                name=sdata.get('name', 'Sequence 1'),
                settings=settings,
            )
            vtracks = sdata.get('video_tracks', [])
            atracks = sdata.get('audio_tracks', [])
            seq.video_tracks = [
                Track(TrackType.VIDEO, t['index'])
                for t in vtracks
            ] if vtracks else [Track(TrackType.VIDEO, i)
                                for i in range(3)]
            for i, t in enumerate(vtracks):
                seq.video_tracks[i].locked  = t.get('locked',  False)
                seq.video_tracks[i].visible = t.get('visible', True)
            seq.audio_tracks = [
                Track(TrackType.AUDIO, t['index'])
                for t in atracks
            ] if atracks else [Track(TrackType.AUDIO, i)
                                for i in range(3)]
            for i, t in enumerate(atracks):
                seq.audio_tracks[i].locked = t.get('locked', False)
                seq.audio_tracks[i].muted  = t.get('muted',  False)
            project.sequences[seq.id] = seq

        if not project.sequences:
            seq = Sequence()
            project.sequences[seq.id] = seq

        # Restore clips
        from core.clip import Clip
        from core.effects import EffectRegistry
        for cdata in data.get('clips', []):
            clip = Clip(
                filepath=    cdata['filepath'],
                track=       cdata['track'],
                start_frame= cdata['start_frame'],
                in_point=    cdata['in_point'],
                out_point=   cdata['out_point'],
                has_video=   cdata.get('has_video',  True),
                has_audio=   cdata.get('has_audio',  False),
                source_width= cdata.get('source_width',  1920),
                source_height=cdata.get('source_height', 1080),
                source_fps=  cdata.get('source_fps',   29.97),
                source_frames=cdata.get('source_frames', 0),
                stream_index= cdata.get('stream_index',  0),
                link_group_id=cdata.get('link_group_id'),
                enabled=     cdata.get('enabled',  True),
                muted=       cdata.get('muted',    False),
                volume=      cdata.get('volume',   1.0),
                label_color= cdata.get('label_color', ''),
            )
            clip.id = cdata['id']

            # Restore effect params
            for edata in cdata.get('effects', []):
                for eff in clip.effect_stack:
                    if eff.id == edata['id']:
                        eff.enabled = edata.get('enabled', True)
                        for k, v in edata.get('params', {}).items():
                            eff._params[k] = v
                        break

            # Restore envelopes
            for env_name, edata in cdata.get('envelopes', {}).items():
                if env_name in clip.envelopes:
                    clip.envelopes[env_name].default_value = (
                        edata.get('default_value', 1.0))

            project.clips[clip.id] = clip

        print(f"[Load] {len(project.clips)} clips, "
              f"{len(project.media_pool)} media → {path}")
        return project

    def __repr__(self):
        return (f"Project({self.name} | "
                f"{len(self.media_pool)} media | "
                f"{len(self.clips)} clips | "
                f"{len(self.sequences)} sequences)")
    
    def split_clip(self,
                   clip_id: str,
                   frame: int) -> list:
        """
        Split a clip and all its linked clips at frame.
        Returns list of all newly created clips.
        """
        clip = self.clips.get(clip_id)
        if not clip:
            return []

        # get entire link group
        group = self.get_link_group(clip_id)
        if not group:
            group = [clip]

        # new link group for the right halves
        new_group_id = str(uuid.uuid4())
        created = []

        for c in group:
            # frame within this clip's timeline
            if frame <= c.start_frame:
                continue
            if frame >= c.start_frame + c.duration:
                continue

            # create right half — new clip
            right = Clip(
                filepath=c.filepath,
                clip_type=c.clip_type,
                has_video=c.has_video,
                has_audio=c.has_audio,
                source_width=c.source_width,
                source_height=c.source_height,
                source_fps=c.source_fps,
                source_frames=c.source_frames,
                track=c.track,
                start_frame=frame,
                in_point=c.in_point + (
                    frame - c.start_frame
                ),
                out_point=c.out_point,
                stream_index=c.stream_index,
                link_group_id=new_group_id,
                enabled=c.enabled,
                muted=c.muted,
                volume=c.volume,
                label_color=c.label_color,
            )
            # copy effect stack state
            right.effect_stack = []
            right._build_default_stack()

            # trim left half in place
            c.out_point = c.in_point + (
                frame - c.start_frame
            )
            # keep original link group
            # (left half stays in original group)

            self.clips[right.id] = right
            created.append(right)

        self.is_dirty = True
        return created