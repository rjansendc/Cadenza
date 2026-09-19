"""
Export to FCP XML, checked by re-importing what we wrote.

A round trip is the honest test: if our own importer reads it back to
the same clips, the file says what we meant.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
import xml.etree.ElementTree as ET

import effects  # noqa: F401
from core.clip import Clip, ClipType
from core.project import Project
from core.fcpxml_export import (
    export_fcpxml, url_from_path, rate_element, FCPXMLExporter,
)
from core.fcpxml_import import import_fcpxml

SAMPLE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'test_media', 'Sequence 01.xml')


def simple_project():
    project = Project()
    seq = project.active_sequence
    seq.name = 'Test Sequence'
    for i in range(2):
        clip = Clip(filepath=f'/media/shot{i}.mp4',
                    clip_type=ClipType.VIDEO,
                    has_video=True, has_audio=False,
                    source_width=3840, source_height=2160,
                    source_frames=5000, source_fps=29.97,
                    track=0, start_frame=i * 100,
                    in_point=0, out_point=100)
        clip.scale_to_frame(seq.settings.width, seq.settings.height)
        project.clips[clip.id] = clip
    return project


# ── paths and rates ───────────────────────────────────────────────

def test_windows_path_becomes_a_file_url():
    url = url_from_path(r'D:\nce_video\MVI_0106.mp4')
    assert url.startswith('file://localhost/D%3a/')
    assert url.endswith('MVI_0106.mp4')


def test_path_url_survives_a_round_trip():
    from core.fcpxml_import import path_from_url
    original = r'D:\video\C\u00f3mo has cambiado!.mp4'
    assert path_from_url(url_from_path(original)).replace('\\', '/') == \
        original.replace('\\', '/')


def test_ntsc_rate_is_flagged():
    root = ET.Element('x')
    rate_element(root, 29.97)
    rate = root.find('rate')
    assert rate.findtext('timebase') == '30'
    assert rate.findtext('ntsc') == 'TRUE'


def test_whole_rate_is_not_flagged():
    root = ET.Element('x')
    rate_element(root, 25.0)
    rate = root.find('rate')
    assert rate.findtext('timebase') == '25'
    assert rate.findtext('ntsc') == 'FALSE'


# ── scale is relative to the frame, as FCP expects ────────────────

def test_scale_is_written_relative_to_fit():
    """A 4K clip filling a 1080p frame is 50% here but 100 in FCP."""
    project = simple_project()
    exporter = FCPXMLExporter(project)
    root = exporter.build().getroot()

    values = []
    for effect in root.iter('effect'):
        if effect.findtext('name') == 'Basic Motion':
            for p in effect.findall('parameter'):
                if p.findtext('parameterid') == 'scale':
                    values.append(float(p.findtext('value')))
    assert values and all(abs(v - 100.0) < 0.01 for v in values)


# ── round trips ───────────────────────────────────────────────────

def test_round_trip_of_a_simple_project(tmp_path):
    project = simple_project()
    out = str(tmp_path / 'out.xml')
    report = export_fcpxml(project, out)
    assert report.video_clips == 2

    back, _ = import_fcpxml(out)
    assert len(back.clips) == 2
    for clip in back.clips.values():
        motion = clip.get_effect('motion')
        assert abs(motion.get('scale') - 50.0) < 0.01   # fitted again
        assert clip.duration == 100


def test_round_trip_of_a_real_concert_project(tmp_path):
    if not os.path.exists(SAMPLE):
        pytest.skip('sample export not present')

    project, first = import_fcpxml(SAMPLE)
    out = str(tmp_path / 'again.xml')
    export_fcpxml(project, out)
    again, second = import_fcpxml(out)

    assert second.video_clips == first.video_clips
    assert second.audio_clips == first.audio_clips
    assert second.video_tracks == first.video_tracks
    assert second.audio_tracks == first.audio_tracks
    assert second.fps == first.fps

    def fingerprint(p):
        return sorted(
            (c.has_video, c.track, c.start_frame, c.duration, c.in_point,
             round(c.get_effect('motion').get('scale'), 2)
             if c.get_effect('motion') else None)
            for c in p.clips.values())

    assert fingerprint(again) == fingerprint(project)


def test_keyframes_survive_the_round_trip(tmp_path):
    project = simple_project()
    clip = list(project.clips.values())[0]
    clip.set_param_keyframe('opacity', 'opacity', 0, 0.0)
    clip.set_param_keyframe('opacity', 'opacity', 30, 100.0)

    out = str(tmp_path / 'kf.xml')
    export_fcpxml(project, out)
    back, _ = import_fcpxml(out)

    animated = [c for c in back.clips.values()
                if c.is_param_animated('opacity', 'opacity')]
    assert len(animated) == 1
    assert animated[0].get_param_at('opacity', 'opacity', 15) == 50.0


def test_report_lists_what_could_not_be_exported():
    from core.transition import Transition
    project = simple_project()
    project.active_sequence.transitions.append(
        Transition(track=0, center_frame=100, duration=20))
    exporter = FCPXMLExporter(project)
    exporter.build()
    assert any('dissolve' in d for d in exporter.report.dropped)
