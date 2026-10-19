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

    # where this project was last exported, so a re-export proposes
    # the same file instead of an empty field
    export_path: Optional[str] = None

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

    def audio_track_is_busy(self,
                            track: int,
                            start_frame: int,
                            end_frame: int) -> bool:
        """
        Is anything already on this audio track between these frames?

        Half-open: a clip ending exactly where the next starts is not
        a collision.
        """
        return bool(self.clips_overlapping(
            track, start_frame, end_frame, is_audio=True))

    def grow_tracks(self, seq, is_audio: bool, index: int) -> int:
        """
        Extend the sequence until `index` exists. Returns how many
        tracks were added.
        """
        if seq is None:
            return 0
        from core.track import Track, TrackType
        tracks = seq.audio_tracks if is_audio else seq.video_tracks
        kind   = TrackType.AUDIO if is_audio else TrackType.VIDEO
        added = 0
        while len(tracks) <= index:
            tracks.append(Track(kind, len(tracks)))
            added += 1
        return added

    def _grow_audio_tracks(self, seq, track: int) -> None:
        self.grow_tracks(seq, True, track)

    def nearest_free_track(self,
                           preferred: int,
                           start_frame: int,
                           end_frame: int,
                           is_audio: bool,
                           exclude_ids=(),
                           seq=None):
        """
        The track closest to `preferred` with room between these
        frames, or None if every track of that kind is busy there.

        Used when a clip is dropped or dragged onto occupied
        timeline: it moves to where there is room rather than landing
        on top. Two clips must never hold the same frames on one
        track — overlapping them is only recoverable by undo, and
        nothing on screen says which one is being heard or seen.

        Ties go to the higher-numbered track, so a clip slides away
        from V1/A1 rather than toward it, matching the direction new
        tracks are added in.
        """
        seq = seq if seq is not None else self.active_sequence
        if seq is None:
            return preferred
        tracks = seq.audio_tracks if is_audio else seq.video_tracks
        count  = len(tracks)
        if count == 0:
            return preferred

        preferred = max(0, min(preferred, count - 1))
        for distance in range(count):
            for candidate in (preferred + distance, preferred - distance):
                if 0 <= candidate < count and not self.clips_overlapping(
                        candidate, start_frame, end_frame,
                        is_audio, exclude_ids):
                    return candidate
                if distance == 0:
                    break
        return None

    def first_free_track(self,
                         first: int,
                         start_frame: int,
                         end_frame: int,
                         is_audio: bool,
                         seq=None) -> int:
        """
        Lowest track from `first` down with room between these
        frames, adding tracks to the sequence if they are all busy.

        Newly imported media has to go somewhere — six camera angles
        stacked at the same timecode need six video tracks, and a
        four-stream recording needs four audio tracks — so this grows
        the sequence rather than refusing. Moving a clip that already
        has a home does not: see nearest_free_track.
        """
        track = max(0, first)
        while self.clips_overlapping(track, start_frame, end_frame,
                                     is_audio):
            track += 1
        self.grow_tracks(seq, is_audio, track)
        return track

    def _first_free_audio_track(self,
                                first: int,
                                start_frame: int,
                                end_frame: int,
                                seq=None) -> int:
        return self.first_free_track(first, start_frame, end_frame,
                                     True, seq)

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

        # Which slot the drop row means, within its own section.
        # row_is_video needs this sequence's video count, and an audio
        # row has to be clamped against the audio tracks: clamping it
        # to n_video dropped A4 onto A3 whenever there were more audio
        # tracks than video ones.
        if row_is_video(drop_row, n_video):
            slot = max(0, min((n_video - 1) - drop_row, n_video - 1))
        else:
            slot = max(0, min(drop_row - n_video, max(0, n_audio - 1)))

        # shared link group
        group_id = str(uuid.uuid4())
        created  = []

        span = max(1, media_item.source_frames or 1)

        # video clip. Like a dragged clip, it goes to the nearest
        # video track with room rather than on top of what is there.
        if stream_info.get('video_count', 0) > 0:
            video_track = self.first_free_track(
                min(slot, n_video - 1),
                start_frame, start_frame + span,
                is_audio=False, seq=seq)
            video_clip = self.add_clip(
                media_item,
                track=video_track,
                start_frame=start_frame,
                has_video=True,
                has_audio=False,
                stream_index=0,
                link_group_id=group_id,
                sequence_id=sequence_id
            )
            created.append(video_clip)

        # audio clips — one per stream
        #
        # The drop row is where the search starts, not where the clip
        # must go: each stream takes the first track from there with
        # room over the clip's own span. Dropping a camera angle on
        # V1 used to put its audio straight onto A1 whatever was
        # already there, leaving two clips on one track across the
        # same frames — recoverable only by undo, with nothing on
        # screen to say which one was being heard.
        #
        # Running out of tracks used to `break`, discarding the
        # remaining streams with nothing said — a four-stream
        # recording lost its fourth. The sequence grows instead,
        # because every stream of a take needs a home.
        audio_count = stream_info.get('audio_count', 0)
        search_from = slot

        for i in range(audio_count):
            audio_track = self._first_free_audio_track(
                search_from, start_frame, start_frame + span, seq)
            search_from = audio_track + 1

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
    # save/load live in core/project_io.py. A second pair used to
    # sit here, writing version '1.0.0' as a string against
    # project_io's integer PROJECT_VERSION, so the app raised
    # TypeError on its own files — and it dropped every keyframe
    # and transition besides.


    def __repr__(self):
        return (f"Project({self.name} | "
                f"{len(self.media_pool)} media | "
                f"{len(self.clips)} clips | "
                f"{len(self.sequences)} sequences)")
    
    def clips_overlapping(self,
                          track: int,
                          start_frame: int,
                          end_frame: int,
                          is_audio: bool,
                          exclude_ids=()) -> list:
        """
        Clips of the same kind on `track` meeting [start, end).

        Half-open, so a clip ending exactly where the span starts is
        left alone. Video and audio track indices are both 0-based,
        so the kind has to be compared as well as the index.
        """
        found = []
        for c in self.clips.values():
            if c.id in exclude_ids:
                continue
            if c.track != track or bool(c.has_audio) != bool(is_audio):
                continue
            c_end = c.start_frame + c.duration
            if c.start_frame < end_frame and start_frame < c_end:
                found.append(c)
        return found

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
            # Carry the clip's look across the cut. This used to
            # rebuild the default stack, so the right half of every
            # razor cut lost its grade, motion and keyframes — the
            # comment said "copy effect stack state" while the code
            # threw it away.
            right.effect_stack = c.clone_effect_stack()
            right.envelopes    = c.clone_envelopes(
                frame_offset=frame - c.start_frame
            )

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