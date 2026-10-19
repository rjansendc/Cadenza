"""
The media bin lists one file per line.

Rows used to be two lines — name, then size and duration underneath —
which read as double spacing and halved how many files fitted before
you had to scroll. Audio files have no frame size, so they rendered
their resolution as a literal "0x0".
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from core.project import Project, MediaPoolItem

pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtWidgets import QApplication            # noqa: E402
from PySide6.QtCore import Qt                         # noqa: E402

from ui.app_state import AppState                     # noqa: E402
from ui.panels.media_bin import MediaBinPanel, META_ROLE  # noqa: E402


@pytest.fixture(scope='module')
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def bin_panel(qapp):
    panel = MediaBinPanel(Project(), AppState())
    panel.resize(260, 400)
    yield panel


def media(name, **kw):
    item = MediaPoolItem(filepath='D:/concert/' + name, name=name)
    for key, value in kw.items():
        setattr(item, key, value)
    return item


CAMERA = dict(has_video=True, has_audio=True,
              source_width=3840, source_height=2160,
              source_duration=725.0)
WAV    = dict(has_video=False, has_audio=True,
              source_width=0, source_height=0,
              source_duration=3640.0)
STILL  = dict(has_video=True, has_audio=False,
              source_width=1920, source_height=1080,
              source_duration=10.0)


# ── the short summary ─────────────────────────────────────────

def test_a_camera_file_shows_its_resolution(bin_panel):
    assert bin_panel._meta_for(media('a.MP4', **CAMERA)) == '4K  12:05'


def test_audio_shows_its_type_not_a_frame_size(bin_panel):
    meta = bin_panel._meta_for(media('060101_0084.wav', **WAV))
    assert '0x0' not in meta
    assert meta == 'WAV  1:00:40'


def test_audio_with_no_extension_still_says_something(bin_panel):
    item = media('recording', **WAV)
    item.filepath = 'D:/concert/recording'
    assert bin_panel._meta_for(item).startswith('AUDIO')


def test_a_still_shows_its_file_type(bin_panel):
    """Its duration is a setting, not a property of the file, so the
    type is the useful half."""
    assert bin_panel._meta_for(media('slide1.png', **STILL)) == 'PNG  0:10'


@pytest.mark.parametrize('seconds,expected', [
    (0,      ''),          # no duration yet — just the type
    (9.4,    '0:09'),
    (65,     '1:05'),
    (154,    '2:34'),
    (3640,   '1:00:40'),
    (7325,   '2:02:05'),
])
def test_durations_are_compact(bin_panel, seconds, expected):
    """The full 00:01:23:15 timecode is far too wide for the bin."""
    item = media('x.wav', **dict(WAV, source_duration=seconds))
    meta = bin_panel._meta_for(item)
    if expected:
        assert meta == f'WAV  {expected}'
    else:
        assert meta == 'WAV'


# ── rows ──────────────────────────────────────────────────────

def test_a_row_is_one_line(bin_panel):
    item = media('GX010079.MP4', **CAMERA)
    bin_panel.add_item(item)
    row = bin_panel.list_widget.item(0)
    assert '\n' not in row.text()
    assert 'GX010079.MP4' in row.text()


def test_the_summary_rides_in_its_own_role(bin_panel):
    """Kept off the display text so the delegate can right-align it."""
    item = media('GX010079.MP4', **CAMERA)
    bin_panel.add_item(item)
    row = bin_panel.list_widget.item(0)
    assert row.data(META_ROLE) == '4K  12:05'
    assert '4K' not in row.text()


def test_the_row_still_carries_its_media_id(bin_panel):
    """startDrag reads this to drop the file on the timeline."""
    item = media('GX010079.MP4', **CAMERA)
    bin_panel.add_item(item)
    row = bin_panel.list_widget.item(0)
    assert row.data(Qt.ItemDataRole.UserRole) == item.id
    assert bin_panel.get_item(item.id) is item


def test_the_tooltip_still_has_the_full_path(bin_panel):
    item = media('GX010079.MP4', **CAMERA)
    bin_panel.add_item(item)
    assert 'D:/concert/GX010079.MP4' in bin_panel.list_widget.item(0).toolTip()


def test_every_imported_file_gets_a_row(bin_panel):
    """Four wavs after two cameras were off the bottom before."""
    for name, kw in (('cam1.MP4', CAMERA), ('cam2.MP4', CAMERA),
                     ('a.wav', WAV), ('b.wav', WAV),
                     ('c.wav', WAV), ('d.wav', WAV)):
        bin_panel.add_item(media(name, **kw))
    assert bin_panel.list_widget.count() == 6


def test_clearing_empties_both_books(bin_panel):
    bin_panel.add_item(media('cam1.MP4', **CAMERA))
    bin_panel.clear()
    assert bin_panel.list_widget.count() == 0
    assert bin_panel._items == {}
    assert bin_panel._list_items == {}


def test_rows_are_a_single_line_tall(bin_panel):
    """Two-line rows are what made the list look double spaced."""
    for i in range(4):
        bin_panel.add_item(media(f'cam{i}.MP4', **CAMERA))
    bin_panel.show()
    QApplication.processEvents()
    line = bin_panel.list_widget.fontMetrics().height()
    assert bin_panel.list_widget.sizeHintForRow(0) < line * 2
