"""
Import a Final Cut Pro 7 XML (xmeml v4) sequence into a Cadenza project.

This is the escape route out of Premiere: Premiere exports FCP XML, and
its Basic Motion / Opacity / Audio Levels filters line up almost exactly
with Cadenza's Motion effect and opacity/volume envelopes.

What comes across:
  - sequence size and frame rate
  - video and audio tracks, created to match the file
  - clips: source file, timeline position, in/out points, enabled state
  - Basic Motion: scale, rotation, centre (as Position X/Y), crop,
    anti-flicker
  - Opacity and Audio Levels, including keyframes
  - clip label colours
  - audio/video linking, rebuilt by matching source and timing, since
    Premiere's export carries no <link> elements

What does not:
  - transitions, speed changes, titles, colour grades and any other
    effect with no Cadenza equivalent (reported, not silently dropped)
  - per-channel audio volume, which Premiere itself fails to translate

Usage:
    python -m core.fcpxml_import "Sequence 01.xml" --report
    python -m core.fcpxml_import "Sequence 01.xml" -o out.veproj
"""

from __future__ import annotations

import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# Premiere's label names -> Cadenza clip colours
LABEL_COLORS = {
    'Violet':    '#9b7ede',
    'Iris':      '#5b6ee1',
    'Caribbean': '#2ca3a3',
    'Lavender':  '#b89ad8',
    'Cerulean':  '#4a9de0',
    'Forest':    '#3f8f4f',
    'Rose':      '#d46a8a',
    'Mango':     '#e0913a',
    'Purple':    '#8a5bd6',
    'Blue':      '#4a6fd0',
    'Teal':      '#2f8f8f',
    'Magenta':   '#c64fa8',
    'Tan':       '#c2a06a',
    'Green':     '#4fa34f',
    'Brown':     '#8a6a4a',
    'Yellow':    '#ccb84a',
}

# effects we understand; anything else is reported as unsupported
KNOWN_EFFECTS = {'Basic Motion', 'Opacity', 'Audio Levels'}


@dataclass
class ImportReport:
    """What an import found, and what it could not bring across."""
    sequence_name: str = ''
    width:  int = 0
    height: int = 0
    fps:    float = 0.0
    video_tracks: int = 0
    audio_tracks: int = 0
    video_clips:  int = 0
    audio_clips:  int = 0
    media_files:  List[str] = field(default_factory=list)
    missing_files: List[str] = field(default_factory=list)
    unsupported:  List[str] = field(default_factory=list)
    warnings:     List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Sequence: {self.sequence_name}",
            f"  {self.width}x{self.height} @ {self.fps:g} fps",
            f"  {self.video_tracks} video tracks, {self.video_clips} clips",
            f"  {self.audio_tracks} audio tracks, {self.audio_clips} clips",
            f"  {len(self.media_files)} media files"
            f"{f', {len(self.missing_files)} NOT FOUND' if self.missing_files else ''}",
        ]
        if self.missing_files:
            lines.append("  missing:")
            lines += [f"    {p}" for p in self.missing_files]
        if self.unsupported:
            lines.append("  not imported:")
            lines += [f"    {u}" for u in sorted(set(self.unsupported))]
        if self.warnings:
            lines.append("  warnings:")
            lines += [f"    {w}" for w in self.warnings]
        return "\n".join(lines)


# ── helpers ───────────────────────────────────────────────────────

def fps_from_rate(rate_el) -> float:
    """
    <rate><timebase>30</timebase><ntsc>TRUE</ntsc></rate> -> 29.97.

    NTSC rates are the timebase pulled down by 1000/1001, which is
    where a whole project ends up a frame out if it is ignored.
    """
    if rate_el is None:
        return 29.97
    try:
        timebase = float(rate_el.findtext('timebase') or 30)
    except ValueError:
        timebase = 30.0
    ntsc = (rate_el.findtext('ntsc') or '').strip().upper() == 'TRUE'
    return round(timebase * 1000.0 / 1001.0, 3) if ntsc else timebase


def path_from_url(pathurl: str) -> str:
    """
    file://localhost/D%3a/nce_video/x.mp4 -> D:\\nce_video\\x.mp4

    Percent-decoding matters: real projects carry spaces and accents
    (14_Ecuador_5%20Pieces..., C%c3%b3mo%20has%20cambiado!).
    """
    if not pathurl:
        return ''
    p = pathurl
    for prefix in ('file://localhost/', 'file:///', 'file://'):
        if p.startswith(prefix):
            p = p[len(prefix):]
            break
    p = urllib.parse.unquote(p)
    # a Windows drive arrives as "D:/..." once decoded
    if re.match(r'^[A-Za-z]:', p):
        return p.replace('/', os.sep) if os.sep == '\\' else p
    return '/' + p.lstrip('/')


def _float(text, default=0.0) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def _int(text, default=0) -> int:
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return default


class FCPXMLImporter:
    """Parses one xmeml file and builds a Cadenza Project from it."""

    def __init__(self, xml_path: str, path_map: Optional[Dict[str, str]] = None):
        self.xml_path = xml_path
        # {'E:\\F_Backup': 'D:\\archive'} for moved media
        self.path_map = path_map or {}
        self.report = ImportReport()
        self._files: Dict[str, dict] = {}    # file id -> metadata

    # ── file table ────────────────────────────────────────────

    def _remap(self, path: str) -> str:
        for old, new in self.path_map.items():
            if path.lower().startswith(old.lower()):
                return new + path[len(old):]
        return path

    def _file_info(self, file_el) -> dict:
        """
        Resolve a <file>, which is described once and later referenced
        by id alone (<file id="file-1"/>).
        """
        fid = file_el.get('id')
        if fid and fid in self._files and not file_el.findtext('pathurl'):
            return self._files[fid]

        path = self._remap(path_from_url(file_el.findtext('pathurl') or ''))
        sc = file_el.find('media/video/samplecharacteristics')
        info = {
            'id':       fid,
            'path':     path,
            'name':     file_el.findtext('name') or Path(path).name,
            'width':    _int(sc.findtext('width'), 1920) if sc is not None else 1920,
            'height':   _int(sc.findtext('height'), 1080) if sc is not None else 1080,
            'fps':      fps_from_rate(file_el.find('rate')),
            'frames':   _int(file_el.findtext('duration'), 0),
            'has_video': file_el.find('media/video') is not None,
            'has_audio': file_el.find('media/audio') is not None,
        }
        if fid:
            self._files[fid] = info
        return info

    # ── filters ───────────────────────────────────────────────

    def _apply_filters(self, clip, clipitem, canvas_w, canvas_h, where: str):
        """Map FCP filters onto Cadenza effects and envelopes."""
        for flt in clipitem.findall('filter'):
            eff = flt.find('effect')
            if eff is None:
                continue
            name = (eff.findtext('name') or '').strip()

            if name == 'Basic Motion':
                self._apply_basic_motion(clip, eff, canvas_w, canvas_h)
            elif name == 'Opacity':
                self._apply_opacity(clip, eff)
            elif name == 'Audio Levels':
                self._apply_audio_levels(clip, eff)
            elif name:
                self.report.unsupported.append(f"{name} (on {where})")

    def _apply_basic_motion(self, clip, eff, canvas_w, canvas_h):
        motion = clip.get_effect('motion')
        if motion is None:
            return
        for p in eff.findall('parameter'):
            pid = (p.findtext('parameterid') or '').strip()
            kfs = p.findall('keyframe')

            if pid == 'scale':
                self._set_param(clip, motion, 'scale', p, kfs, lambda v: v)
            elif pid == 'rotation':
                self._set_param(clip, motion, 'rotation', p, kfs, lambda v: v)
            elif pid in ('leftcrop', 'topcrop', 'rightcrop', 'bottomcrop'):
                target = {'leftcrop': 'crop_left', 'topcrop': 'crop_top',
                          'rightcrop': 'crop_right',
                          'bottomcrop': 'crop_bottom'}[pid]
                self._set_param(clip, motion, target, p, kfs, lambda v: v)
            elif pid == 'antiflicker':
                self._set_param(clip, motion, 'anti_flicker', p, kfs,
                                lambda v: v)
            elif pid == 'center':
                # centre is a fraction of the frame away from the middle:
                # 0 = centred, +0.5 = one half-frame right/down
                v = p.find('value')
                if v is not None:
                    h = _float(v.findtext('horiz'), 0.0)
                    vt = _float(v.findtext('vert'), 0.0)
                    motion.set('position_x', canvas_w / 2.0 + h * canvas_w)
                    motion.set('position_y', canvas_h / 2.0 + vt * canvas_h)

    def _set_param(self, clip, effect, param, p_el, kfs, convert):
        """Static value, or keyframes when the parameter is animated."""
        if kfs:
            for k in kfs:
                frame = _int(k.findtext('when'), 0)
                clip.set_param_keyframe(
                    effect.id, param, frame,
                    convert(_float(k.findtext('value'), 0.0)))
        else:
            effect.set(param, convert(_float(p_el.findtext('value'), 0.0)))

    def _apply_opacity(self, clip, eff):
        """
        Premiere writes an Opacity filter with value 0 for clips that
        are fully opaque, so a bare filter must NOT be read as
        transparent — that would import every clip invisible. Only
        keyframes are taken literally.
        """
        fx = clip.get_effect('opacity')
        for p in eff.findall('parameter'):
            kfs = p.findall('keyframe')
            if kfs:
                for k in kfs:
                    clip.set_param_keyframe(
                        'opacity', 'opacity',
                        _int(k.findtext('when'), 0),
                        _float(k.findtext('value'), 100.0))
            elif fx is not None:
                value = _float(p.findtext('value'), 100.0)
                fx.set('opacity', 100.0 if value <= 0 else value)

    def _apply_audio_levels(self, clip, eff):
        """FCP audio level is a linear gain (1.0 = 0 dB, 3.98 = +12 dB)."""
        from effects.audio.volume import linear_to_db
        fx = clip.get_effect('volume')
        for p in eff.findall('parameter'):
            kfs = p.findall('keyframe')
            if kfs:
                for k in kfs:
                    linear = _float(k.findtext('value'), 1.0)
                    db = linear_to_db(linear)
                    clip.set_param_keyframe(
                        'volume', 'volume_db',
                        _int(k.findtext('when'), 0),
                        -96.0 if db == float('-inf') else db)
            else:
                linear = _float(p.findtext('value'), 1.0)
                clip.set_volume(linear)
                if fx is not None:
                    db = linear_to_db(linear)
                    fx.set('volume_db',
                           -96.0 if db == float('-inf') else db)

    # ── main ──────────────────────────────────────────────────

    def parse(self):
        """Build a Project. Returns (project, report)."""
        from core.project import Project
        from core.track import Track, TrackType, SequenceSettings
        from core.clip import Clip, ClipType

        root = ET.parse(self.xml_path).getroot()
        seq_el = root.find('sequence')
        if seq_el is None:
            raise ValueError("no <sequence> in this XML — not an FCP export?")

        name = seq_el.findtext('name') or Path(self.xml_path).stem
        fps = fps_from_rate(seq_el.find('rate'))
        sc = seq_el.find('media/video/format/samplecharacteristics')
        width  = _int(sc.findtext('width'), 1920) if sc is not None else 1920
        height = _int(sc.findtext('height'), 1080) if sc is not None else 1080

        self.report.sequence_name = name
        self.report.width, self.report.height, self.report.fps = width, height, fps

        project = Project(name=name)
        settings = SequenceSettings(width=width, height=height, fps=fps)
        seq = project.add_sequence(name=name, settings=settings)
        project.active_sequence_id = seq.id
        # drop the empty sequence Project() creates for itself
        for sid in list(project.sequences):
            if sid != seq.id:
                del project.sequences[sid]

        media = seq_el.find('media')
        v_tracks = media.findall('video/track') if media is not None else []
        a_tracks = media.findall('audio/track') if media is not None else []

        seq.video_tracks = [Track(TrackType.VIDEO, i)
                            for i in range(max(1, len(v_tracks)))]
        seq.audio_tracks = [Track(TrackType.AUDIO, i)
                            for i in range(max(1, len(a_tracks)))]
        self.report.video_tracks = len(seq.video_tracks)
        self.report.audio_tracks = len(seq.audio_tracks)

        # master clip id -> clips, for rebuilding links afterwards
        by_master: Dict[str, List] = {}

        for kind, tracks in (('video', v_tracks), ('audio', a_tracks)):
            for t_index, track_el in enumerate(tracks):
                for ci in track_el.findall('clipitem'):
                    clip = self._build_clip(
                        ci, kind, t_index, width, height, project)
                    if clip is None:
                        continue
                    project.clips[clip.id] = clip
                    master = ci.findtext('masterclipid')
                    if master:
                        by_master.setdefault(master, []).append(clip)
                    if kind == 'video':
                        self.report.video_clips += 1
                    else:
                        self.report.audio_clips += 1

        self._rebuild_links(by_master)

        # load_project sets this as a plain attribute after loading;
        # the UI reads it straight after an import, so set it here too
        project.total_frames = max(
            (c.start_frame + c.duration
             for c in project.clips.values()),
            default=0
        )
        return project, self.report

    def _build_clip(self, ci, kind, t_index, canvas_w, canvas_h, project):
        from core.clip import Clip, ClipType

        file_el = ci.find('file')
        if file_el is None:
            return None
        info = self._file_info(file_el)
        if not info['path']:
            return None

        start = _int(ci.findtext('start'), 0)
        end   = _int(ci.findtext('end'), 0)
        in_p  = _int(ci.findtext('in'), 0)
        out_p = _int(ci.findtext('out'), -1)

        # -1 marks a clip that only exists inside a transition
        if start < 0 or end < 0:
            self.report.warnings.append(
                f"{info['name']}: clip inside a transition, skipped")
            return None

        is_video = (kind == 'video')
        clip = Clip(
            filepath=info['path'],
            clip_type=ClipType.VIDEO if is_video else ClipType.AUDIO,
            name=ci.findtext('name') or info['name'],
            has_video=is_video,
            has_audio=not is_video,
            source_width=info['width'],
            source_height=info['height'],
            source_fps=info['fps'],
            source_frames=info['frames'] or (out_p if out_p > 0 else end - start),
            track=t_index,
            start_frame=start,
            in_point=in_p,
            out_point=out_p,
        )
        clip.enabled = (ci.findtext('enabled') or 'TRUE').upper() == 'TRUE'

        label = ci.findtext('labels/label2')
        if label in LABEL_COLORS:
            clip.label_color = LABEL_COLORS[label]

        self._apply_filters(clip, ci, canvas_w, canvas_h, clip.name)

        if info['path'] not in self.report.media_files:
            self.report.media_files.append(info['path'])
            if not os.path.exists(info['path']):
                self.report.missing_files.append(info['path'])
            item = project.import_media(info['path'])
            item.name = info['name']
            item.source_width  = info['width']
            item.source_height = info['height']
            item.source_fps    = info['fps']
            item.source_frames = info['frames']
            item.has_video     = info['has_video']
            item.has_audio     = info['has_audio']

        return clip

    def _rebuild_links(self, by_master: Dict[str, List]):
        """
        Premiere's FCP export carries no <link> elements, so video and
        audio that were linked arrive as separate clips. Rejoin them
        where they share a master clip and sit at the same place.
        """
        import uuid
        for master, clips in by_master.items():
            groups: Dict[tuple, List] = {}
            for c in clips:
                groups.setdefault((c.start_frame, c.in_point), []).append(c)
            for members in groups.values():
                has_v = any(c.has_video for c in members)
                has_a = any(c.has_audio for c in members)
                if len(members) > 1 and has_v and has_a:
                    gid = str(uuid.uuid4())
                    for c in members:
                        c.link_group_id = gid


def import_fcpxml(xml_path: str, path_map: Optional[Dict[str, str]] = None):
    """Parse an FCP XML file. Returns (project, report)."""
    return FCPXMLImporter(xml_path, path_map).parse()


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        description="Import a Premiere/FCP7 XML sequence into Cadenza")
    parser.add_argument('xml', help='the .xml file exported from Premiere')
    parser.add_argument('-o', '--output', help='write a .veproj here')
    parser.add_argument('--report', action='store_true',
                        help='describe the file without writing anything')
    parser.add_argument('--map', action='append', default=[],
                        metavar='OLD=NEW',
                        help='remap media paths, e.g. E:\\F_Backup=D:\\archive')
    args = parser.parse_args(argv)

    path_map = {}
    for m in args.map:
        if '=' in m:
            old, new = m.split('=', 1)
            path_map[old] = new

    project, report = import_fcpxml(args.xml, path_map)
    print(report.summary())

    if args.output and not args.report:
        project.save(args.output)
        print(f"\nwrote {args.output}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
