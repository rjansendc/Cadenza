"""
Export a Cadenza sequence as Final Cut Pro 7 XML (xmeml v4).

The mirror of core/fcpxml_import.py. Premiere and DaVinci Resolve both
read this format, so an edit made here can be finished elsewhere, or
handed to someone who does not have Cadenza.

What goes across:
  - sequence size and frame rate (NTSC flagged where it applies)
  - video and audio tracks, with clips: source, position, in/out points,
    enabled state and label colour
  - Basic Motion from the Motion effect: scale, rotation, centre, crop
  - Opacity and Audio Levels, including keyframes

What does not:
  - anchor point, which Basic Motion has no equivalent for
  - cross dissolves, time remapping and Lumetri colour
Anything dropped is listed in the report rather than lost silently.

Known gap, not yet investigated: Premiere opens the sequence and the
cut is right, but Motion values do not survive as expected. Scale is
the prime suspect. Import reads FCP scale as a percentage of the clip
FITTED to the frame — which is what Premiere's own export showed, a 4K
angle filling a 1080p frame written as 100 — and export converts back
the same way. If Premiere's importer instead reads scale as a
percentage of native size, the two disagree and a 4K clip lands at
double or half.

The way to settle it: export a single 4K clip at a known Scale, open it
in Premiere, and read the Scale that Motion shows. Then compare that
against what Premiere writes for the same framing in its own export.
"""

from __future__ import annotations

import os
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# Cadenza label colours -> Premiere's names, for round tripping
from core.fcpxml_import import LABEL_COLORS

COLOR_LABELS = {v: k for k, v in LABEL_COLORS.items()}


@dataclass
class ExportReport:
    sequence_name: str = ''
    video_clips: int = 0
    audio_clips: int = 0
    media_files: int = 0
    dropped: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Sequence: {self.sequence_name}",
            f"  {self.video_clips} video clips, "
            f"{self.audio_clips} audio clips",
            f"  {self.media_files} media files",
        ]
        if self.dropped:
            lines.append("  not exported:")
            lines += [f"    {d}" for d in sorted(set(self.dropped))]
        return "\n".join(lines)


def url_from_path(path: str) -> str:
    """D:\\video\\x.mp4 -> file://localhost/D%3a/video/x.mp4"""
    p = str(path).replace('\\', '/')
    # quote() already encodes the drive colon as %3A; Premiere writes
    # it lowercase, and decoding does not care either way
    quoted = urllib.parse.quote(p, safe='/').replace('%3A', '%3a')
    return f"file://localhost/{quoted.lstrip('/')}"


def rate_element(parent, fps: float):
    """A <rate>, with the NTSC flag set for 29.97 and friends."""
    rate = ET.SubElement(parent, 'rate')
    ntsc = abs(fps - round(fps)) > 0.001
    timebase = int(round(fps * 1001 / 1000)) if ntsc else int(round(fps))
    ET.SubElement(rate, 'timebase').text = str(timebase)
    ET.SubElement(rate, 'ntsc').text = 'TRUE' if ntsc else 'FALSE'
    return rate


def _text(parent, tag, value):
    ET.SubElement(parent, tag).text = str(value)


def _parameter(effect, pid, name, value, minimum=None, maximum=None):
    p = ET.SubElement(effect, 'parameter')
    ET.SubElement(p, 'parameterid').text = pid
    ET.SubElement(p, 'name').text = name
    if minimum is not None:
        ET.SubElement(p, 'valuemin').text = str(minimum)
    if maximum is not None:
        ET.SubElement(p, 'valuemax').text = str(maximum)
    if value is not None:
        ET.SubElement(p, 'value').text = str(value)
    return p


PPRO_TICKS_PER_SECOND = 254016000000


def ppro_ticks(frames: int, fps: float) -> int:
    """Premiere records times in ticks as well as frames."""
    if not fps:
        return 0
    return int(round(frames / fps * PPRO_TICKS_PER_SECOND))


def _logging_info(parent):
    """The empty logginginfo block Premiere writes on both."""
    logging = ET.SubElement(parent, 'logginginfo')
    for tag in ('description', 'scene', 'shottake', 'lognote',
                'good', 'originalvideofilename',
                'originalaudiofilename'):
        ET.SubElement(logging, tag)


def _empty_info(parent):
    """logginginfo + colorinfo, as clipitems carry."""
    _logging_info(parent)
    colorinfo = ET.SubElement(parent, 'colorinfo')
    for tag in ('lut', 'lut1', 'asc_sop', 'asc_sat', 'lut2'):
        ET.SubElement(colorinfo, tag)


def _keyframes(param, points):
    """points: [(frame, value)] — written as FCP keyframes."""
    for frame, value in points:
        kf = ET.SubElement(param, 'keyframe')
        ET.SubElement(kf, 'when').text = str(int(frame))
        ET.SubElement(kf, 'value').text = str(value)


class FCPXMLExporter:

    def __init__(self, project, sequence=None):
        self.project = project
        self.sequence = sequence or project.active_sequence
        self.report = ExportReport()
        self._file_ids = {}       # filepath -> file id
        self._master_ids = {}     # filepath -> masterclip id

    # ── helpers ───────────────────────────────────────────────

    def _fit_percent(self, clip) -> float:
        """Scale at which this source fills the frame."""
        settings = self.sequence.settings
        src_w = clip.source_width or settings.width
        src_h = clip.source_height or settings.height
        if not src_w or not src_h:
            return 100.0
        return min(settings.width / src_w,
                   settings.height / src_h) * 100.0

    def _file_element(self, parent, clip):
        """
        A <file>. Described in full the first time, then referenced by
        id alone, which is how Premiere writes it.
        """
        path = clip.filepath
        existing = self._file_ids.get(path)
        if existing:
            return ET.SubElement(parent, 'file', {'id': existing})

        file_id = f"file-{len(self._file_ids) + 1}"
        self._file_ids[path] = file_id
        self.report.media_files += 1

        el = ET.SubElement(parent, 'file', {'id': file_id})
        _text(el, 'name', Path(path).name)
        _text(el, 'pathurl', url_from_path(path))
        rate_element(el, clip.source_fps or self.sequence.settings.fps)
        _text(el, 'duration', int(clip.source_frames or 0))

        fps = clip.source_fps or self.sequence.settings.fps
        tc = ET.SubElement(el, 'timecode')
        rate_element(tc, fps)
        _text(tc, 'string', '00;00;00;00')
        _text(tc, 'frame', 0)
        _text(tc, 'displayformat',
              'DF' if abs(fps - round(fps)) > 0.001 else 'NDF')

        # A file describes the source itself: a camera .MP4 holds both
        # video and audio even when this clip only uses one of them,
        # and that is how Premiere writes it.
        has_video, has_audio = self._source_streams(clip)

        media = ET.SubElement(el, 'media')
        if has_video:
            video = ET.SubElement(media, 'video')
            sc = ET.SubElement(video, 'samplecharacteristics')
            rate_element(sc, fps)
            _text(sc, 'width', int(clip.source_width or 1920))
            _text(sc, 'height', int(clip.source_height or 1080))
            _text(sc, 'anamorphic', 'FALSE')
            _text(sc, 'pixelaspectratio', 'square')
            _text(sc, 'fielddominance', 'none')
        if has_audio:
            audio = ET.SubElement(media, 'audio')
            sc = ET.SubElement(audio, 'samplecharacteristics')
            _text(sc, 'depth', 16)
            _text(sc, 'samplerate',
                  self.sequence.settings.sample_rate)
            _text(audio, 'channelcount', 2)
            channel = ET.SubElement(audio, 'audiochannel')
            _text(channel, 'sourcechannel', 1)
        return el

    def _source_streams(self, clip):
        """
        What the source file actually contains, from the media pool
        where possible — a clip only carries the half it uses.
        """
        has_video, has_audio = clip.has_video, clip.has_audio
        for item in getattr(self.project, 'media_pool', {}).values():
            if item.filepath == clip.filepath:
                return bool(item.has_video), bool(item.has_audio)
        # no pool entry: look for the other half on the timeline
        for other in self.project.clips.values():
            if other.filepath == clip.filepath and other is not clip:
                has_video = has_video or other.has_video
                has_audio = has_audio or other.has_audio
        return has_video, has_audio

    def _master_id(self, clip) -> str:
        path = clip.filepath
        if path not in self._master_ids:
            self._master_ids[path] = (
                f"masterclip-{len(self._master_ids) + 1}")
        return self._master_ids[path]

    # ── filters ───────────────────────────────────────────────

    def _basic_motion(self, parent, clip):
        motion = clip.get_effect('motion')
        if motion is None:
            return
        settings = self.sequence.settings

        flt = ET.SubElement(parent, 'filter')
        eff = ET.SubElement(flt, 'effect')
        _text(eff, 'name', 'Basic Motion')
        _text(eff, 'effectid', 'basic')
        _text(eff, 'effectcategory', 'motion')
        _text(eff, 'effecttype', 'motion')
        _text(eff, 'mediatype', 'video')

        # FCP scale is a percentage of the clip FITTED to the frame
        fit = self._fit_percent(clip) or 100.0
        scale_param = _parameter(eff, 'scale', 'Scale', None, 0, 1000)
        if clip.is_param_animated('motion', 'scale'):
            env = clip.envelopes['motion.scale']
            _keyframes(scale_param, [
                (kf.frame, round(kf.value / fit * 100.0, 4))
                for kf in sorted(env.keyframes)])
        else:
            value = motion.get('scale') or 100.0
            ET.SubElement(scale_param, 'value').text = str(
                round(value / fit * 100.0, 4))

        _parameter(eff, 'rotation', 'Rotation',
                   round(motion.get('rotation') or 0.0, 4), -8640, 8640)

        # centre is a fraction of the frame away from the middle
        centre = _parameter(eff, 'center', 'Center', None)
        value = ET.SubElement(centre, 'value')
        pos_x = motion.get('position_x')
        pos_y = motion.get('position_y')
        if pos_x is None:
            pos_x = settings.width / 2.0
        if pos_y is None:
            pos_y = settings.height / 2.0
        _text(value, 'horiz',
              round((pos_x - settings.width / 2.0) / settings.width, 6))
        _text(value, 'vert',
              round((pos_y - settings.height / 2.0) / settings.height, 6))

        _parameter(eff, 'antiflicker', 'Anti-flicker Filter',
                   round(motion.get('anti_flicker') or 0.0, 4), 0, 1)
        for pid, param, label in (
                ('leftcrop', 'crop_left', 'Left'),
                ('rightcrop', 'crop_right', 'Right'),
                ('topcrop', 'crop_top', 'Top'),
                ('bottomcrop', 'crop_bottom', 'Bottom')):
            _parameter(eff, pid, label,
                       round(motion.get(param) or 0.0, 4), 0, 100)

        anchor_x = motion.get('anchor_x')
        if anchor_x is not None and clip.source_width:
            if abs(anchor_x - clip.source_width / 2.0) > 0.5:
                self.report.dropped.append(
                    'Anchor Point (Basic Motion has no equivalent)')

    def _opacity(self, parent, clip):
        fx = clip.get_effect('opacity')
        animated = clip.is_param_animated('opacity', 'opacity')
        value = fx.get('opacity') if fx else 100.0
        if not animated and (value is None or value >= 100.0):
            return                      # nothing to say

        flt = ET.SubElement(parent, 'filter')
        eff = ET.SubElement(flt, 'effect')
        _text(eff, 'name', 'Opacity')
        _text(eff, 'effectid', 'opacity')
        _text(eff, 'effectcategory', 'motion')
        _text(eff, 'effecttype', 'motion')
        _text(eff, 'mediatype', 'video')
        param = _parameter(eff, 'opacity', 'opacity', None, 0, 100)
        if animated:
            env = clip.envelopes['opacity']
            _keyframes(param, [(kf.frame, round(kf.value * 100.0, 4))
                               for kf in sorted(env.keyframes)])
        else:
            ET.SubElement(param, 'value').text = str(round(value, 4))

    def _audio_levels(self, parent, clip):
        env = clip.envelopes.get('volume')
        animated = bool(env and env.keyframes)
        level = env.default_value if env else 1.0
        if not animated and abs(level - 1.0) < 1e-6:
            return

        flt = ET.SubElement(parent, 'filter')
        eff = ET.SubElement(flt, 'effect')
        _text(eff, 'name', 'Audio Levels')
        _text(eff, 'effectid', 'audiolevels')
        _text(eff, 'effectcategory', 'audiolevels')
        _text(eff, 'effecttype', 'audiolevels')
        _text(eff, 'mediatype', 'audio')
        param = _parameter(eff, 'level', 'Level', None, 0, 3.98109)
        if animated:
            _keyframes(param, [(kf.frame, round(kf.value, 6))
                               for kf in sorted(env.keyframes)])
        else:
            ET.SubElement(param, 'value').text = str(round(level, 6))

    # ── clips and tracks ──────────────────────────────────────

    def _clipitem(self, track_el, clip, index: int):
        fps = self.sequence.settings.fps
        ci = ET.SubElement(track_el, 'clipitem',
                           {'id': f"clipitem-{index}"})
        _text(ci, 'masterclipid', self._master_id(clip))
        _text(ci, 'name', clip.name)
        _text(ci, 'enabled', 'TRUE' if clip.enabled else 'FALSE')
        _text(ci, 'duration', int(clip.source_frames or clip.duration))
        rate_element(ci, clip.source_fps or fps)
        _text(ci, 'start', int(clip.start_frame))
        _text(ci, 'end', int(clip.start_frame + clip.duration))
        _text(ci, 'in', int(clip.in_point))
        _text(ci, 'out', int(clip.in_point + clip.duration))
        _text(ci, 'pproTicksIn', ppro_ticks(clip.in_point, fps))
        _text(ci, 'pproTicksOut',
              ppro_ticks(clip.in_point + clip.duration, fps))

        if clip.has_video:
            _text(ci, 'alphatype', 'none')
            _text(ci, 'pixelaspectratio', 'square')
            _text(ci, 'anamorphic', 'FALSE')

        self._file_element(ci, clip)

        # audio clips must say which channel of the file they use, or
        # Premiere refuses the whole import
        if not clip.has_video:
            source = ET.SubElement(ci, 'sourcetrack')
            _text(source, 'mediatype', 'audio')
            _text(source, 'trackindex', 1)

        if clip.has_video:
            self._basic_motion(ci, clip)
            self._opacity(ci, clip)
        else:
            self._audio_levels(ci, clip)

        _empty_info(ci)

        label = COLOR_LABELS.get(clip.label_color)
        if label:
            labels = ET.SubElement(ci, 'labels')
            _text(labels, 'label2', label)
        return ci

    def build(self) -> ET.ElementTree:
        settings = self.sequence.settings
        self.report.sequence_name = self.sequence.name

        root = ET.Element('xmeml', {'version': '4'})
        seq = ET.SubElement(root, 'sequence', {'id': 'sequence-1'})
        _text(seq, 'uuid', self.sequence.id)
        _text(seq, 'name', self.sequence.name)

        clips = [c for c in self.project.clips.values()]
        total = max((c.start_frame + c.duration for c in clips),
                    default=0)
        _text(seq, 'duration', int(total))
        rate_element(seq, settings.fps)

        media = ET.SubElement(seq, 'media')

        # video
        video = ET.SubElement(media, 'video')
        fmt = ET.SubElement(video, 'format')
        sc = ET.SubElement(fmt, 'samplecharacteristics')
        rate_element(sc, settings.fps)
        _text(sc, 'width', settings.width)
        _text(sc, 'height', settings.height)
        codec = ET.SubElement(sc, 'codec')
        _text(codec, 'name', 'Apple ProRes 422')
        app = ET.SubElement(codec, 'appspecificdata')
        _text(app, 'appname', 'Final Cut Pro')
        _text(app, 'appmanufacturer', 'Apple Inc.')
        _text(app, 'appversion', '7.0')
        data = ET.SubElement(app, 'data')
        qt = ET.SubElement(data, 'qtcodec')
        _text(qt, 'codecname', 'Apple ProRes 422')
        _text(qt, 'codectypename', 'Apple ProRes 422')
        _text(qt, 'codectypecode', 'apcn')
        _text(qt, 'codecvendorcode', 'appl')
        _text(qt, 'spatialquality', 1024)
        _text(qt, 'temporalquality', 0)
        _text(qt, 'keyframerate', 0)
        _text(qt, 'datarate', 0)
        _text(sc, 'anamorphic', 'FALSE')
        _text(sc, 'pixelaspectratio', 'square')
        _text(sc, 'fielddominance', 'none')
        _text(sc, 'colordepth', 24)

        index = 1
        for t_index, track in enumerate(self.sequence.video_tracks):
            track_el = ET.SubElement(video, 'track')
            on_track = sorted(
                (c for c in clips if c.has_video and c.track == t_index),
                key=lambda c: c.start_frame)
            for clip in on_track:
                self._clipitem(track_el, clip, index)
                index += 1
                self.report.video_clips += 1
            _text(track_el, 'enabled', 'TRUE' if track.visible else 'FALSE')
            _text(track_el, 'locked', 'TRUE' if track.locked else 'FALSE')

        # audio
        audio = ET.SubElement(media, 'audio')
        _text(audio, 'numOutputChannels', 2)
        a_fmt = ET.SubElement(audio, 'format')
        a_sc = ET.SubElement(a_fmt, 'samplecharacteristics')
        _text(a_sc, 'depth', 16)
        _text(a_sc, 'samplerate', settings.sample_rate)
        outputs = ET.SubElement(audio, 'outputs')
        for channel in (1, 2):
            group = ET.SubElement(outputs, 'group')
            _text(group, 'index', channel)
            _text(group, 'numchannels', 1)
            _text(group, 'downmix', 0)
            ch = ET.SubElement(group, 'channel')
            _text(ch, 'index', channel)

        for t_index, track in enumerate(self.sequence.audio_tracks):
            track_el = ET.SubElement(audio, 'track')
            on_track = sorted(
                (c for c in clips if c.has_audio and c.track == t_index),
                key=lambda c: c.start_frame)
            for clip in on_track:
                self._clipitem(track_el, clip, index)
                index += 1
                self.report.audio_clips += 1
            _text(track_el, 'enabled', 'TRUE' if not track.muted else 'FALSE')
            _text(track_el, 'locked', 'TRUE' if track.locked else 'FALSE')
            _text(track_el, 'outputchannelindex', (t_index % 2) + 1)

        tc = ET.SubElement(seq, 'timecode')
        rate_element(tc, settings.fps)
        _text(tc, 'string', '00;00;00;00')
        _text(tc, 'frame', 0)
        _text(tc, 'displayformat', 'DF' if abs(
            settings.fps - round(settings.fps)) > 0.001 else 'NDF')

        labels = ET.SubElement(seq, 'labels')
        ET.SubElement(labels, 'label2')
        # sequences carry logginginfo but never colorinfo
        _logging_info(seq)

        if getattr(self.sequence, 'transitions', None):
            self.report.dropped.append(
                f"{len(self.sequence.transitions)} cross dissolve(s)")
        for clip in clips:
            if clip.get_effect('time_remap') and not \
                    clip.get_effect('time_remap').is_at_defaults():
                self.report.dropped.append('Time Remapping')
            lumetri = clip.get_effect('lumetri_color')
            if lumetri and not lumetri.is_at_defaults():
                self.report.dropped.append('Lumetri Color')

        return ET.ElementTree(root)


def export_fcpxml(project, path: str, sequence=None):
    """Write a sequence as FCP XML. Returns the report."""
    exporter = FCPXMLExporter(project, sequence)
    tree = exporter.build()
    root = tree.getroot()
    try:
        ET.indent(tree, space='\t')       # Python 3.9+
    except AttributeError:
        pass
    xml = ET.tostring(root, encoding='unicode')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        fh.write('<!DOCTYPE xmeml>\n')
        fh.write(xml)
    return exporter.report


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        description="Export a Cadenza project as Premiere/FCP XML")
    ap.add_argument('project', help='a .veproj file')
    ap.add_argument('-o', '--output', help='the .xml to write')
    args = ap.parse_args(argv)

    from core.project_io import load_project
    project = load_project(args.project)
    out = args.output or os.path.splitext(args.project)[0] + '.xml'
    report = export_fcpxml(project, out)
    print(report.summary())
    print(f"\nwrote {out}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
