"""
Tests for importing Premiere's Final Cut Pro XML export.

The unit tests run anywhere. The end-to-end ones use the real exports in
test_media/, which is not tracked in git, so they skip when absent.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # trigger registrations
from core.fcpxml_import import (
    fps_from_rate, path_from_url, import_fcpxml, LABEL_COLORS,
)

import xml.etree.ElementTree as ET

MEDIA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'test_media')
SAMPLES = [os.path.join(MEDIA_DIR, '00004.xml'),
           os.path.join(MEDIA_DIR, 'Sequence 01.xml')]


def rate(timebase, ntsc):
    return ET.fromstring(
        f"<rate><timebase>{timebase}</timebase>"
        f"<ntsc>{ntsc}</ntsc></rate>")


# ── frame rates ───────────────────────────────────────────────────

def test_ntsc_rates_are_pulled_down():
    # the classic way a whole project ends up a frame out
    assert fps_from_rate(rate(30, 'TRUE')) == 29.97
    assert fps_from_rate(rate(24, 'TRUE')) == 23.976
    assert fps_from_rate(rate(60, 'TRUE')) == 59.94


def test_non_ntsc_rates_are_exact():
    assert fps_from_rate(rate(25, 'FALSE')) == 25.0
    assert fps_from_rate(rate(30, 'FALSE')) == 30.0


def test_missing_rate_defaults_to_2997():
    assert fps_from_rate(None) == 29.97


# ── media paths ───────────────────────────────────────────────────

def test_windows_path_is_decoded():
    url = 'file://localhost/D%3a/nce_video/Concert/MVI_0038.mp4'
    assert path_from_url(url).replace('\\', '/') == \
        'D:/nce_video/Concert/MVI_0038.mp4'


def test_spaces_and_accents_survive():
    url = ('file://localhost/D%3a/x/'
           '11_Ecuador_C%c3%b3mo%20has%20cambiado!_2026.mp4')
    assert path_from_url(url).endswith(
        'C\u00f3mo has cambiado!_2026.mp4')


def test_empty_url_is_empty():
    assert path_from_url('') == ''


# ── the real exports ──────────────────────────────────────────────

@pytest.mark.parametrize('xml_path', SAMPLES)
def test_real_export_imports(xml_path):
    if not os.path.exists(xml_path):
        pytest.skip('sample export not present (test_media is untracked)')

    project, report = import_fcpxml(xml_path)
    root = ET.parse(xml_path).getroot()
    seq = root.find('sequence')

    # tracks and clips match the file exactly
    v_tracks = seq.findall('media/video/track')
    a_tracks = seq.findall('media/audio/track')
    assert report.video_tracks == len(v_tracks)
    assert report.audio_tracks == len(a_tracks)
    assert report.video_clips == sum(
        len(t.findall('clipitem')) for t in v_tracks)
    assert report.audio_clips == sum(
        len(t.findall('clipitem')) for t in a_tracks)

    assert report.fps == 29.97          # 30 NTSC
    assert (report.width, report.height) == (1920, 1080)
    assert len(project.clips) == report.video_clips + report.audio_clips

    # every clip points at a real path and sits on a track that exists
    s = project.active_sequence
    for clip in project.clips.values():
        assert clip.filepath
        limit = (len(s.video_tracks) if clip.has_video
                 else len(s.audio_tracks))
        assert 0 <= clip.track < limit


@pytest.mark.parametrize('xml_path', SAMPLES)
def test_no_clip_imports_fully_transparent(xml_path):
    """
    Premiere writes Opacity=0 on clips that are fully opaque, so
    reading it literally would import an invisible timeline.
    """
    if not os.path.exists(xml_path):
        pytest.skip('sample export not present')

    project, _ = import_fcpxml(xml_path)
    for clip in project.clips.values():
        fx = clip.get_effect('opacity')
        if fx is not None and not clip.is_param_animated('opacity', 'opacity'):
            assert fx.get('opacity') > 0


def test_basic_motion_values_arrive():
    xml_path = SAMPLES[0]
    if not os.path.exists(xml_path):
        pytest.skip('sample export not present')

    project, _ = import_fcpxml(xml_path)
    scales = {c.get_effect('motion').get('scale')
              for c in project.clips.values()
              if c.get_effect('motion')}
    # the export carries 105, 115, 120, 130 ... not just the default
    assert scales - {100.0}


def test_survives_save_and_load(tmp_path):
    xml_path = SAMPLES[0]
    if not os.path.exists(xml_path):
        pytest.skip('sample export not present')

    from core.project_io import save_project, load_project
    project, report = import_fcpxml(xml_path)
    out = str(tmp_path / 'imported.veproj')
    assert save_project(project, out)

    back = load_project(out)
    seq = back.active_sequence
    assert len(back.clips) == len(project.clips)
    assert len(seq.video_tracks) == report.video_tracks
    assert len(seq.audio_tracks) == report.audio_tracks
    assert seq.settings.fps == report.fps

    # static effect values must survive too, not just keyframes
    before = sorted(c.get_effect('motion').get('scale')
                    for c in project.clips.values()
                    if c.get_effect('motion'))
    after = sorted(c.get_effect('motion').get('scale')
                   for c in back.clips.values()
                   if c.get_effect('motion'))
    assert before == after


def test_label_colours_are_mapped():
    xml_path = SAMPLES[0]
    if not os.path.exists(xml_path):
        pytest.skip('sample export not present')

    project, _ = import_fcpxml(xml_path)
    colours = {c.label_color for c in project.clips.values()}
    assert colours & set(LABEL_COLORS.values())
