"""
Where an export is proposed to go.

The output field opened empty every time and Browse suggested
'output.mp4' in whatever directory the app was launched from, so the
path had to be typed or navigated to on every render. Premiere names
the file after the sequence.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import effects  # noqa: F401

from core.project import Project
from core.project_io import save_project, load_project
from render.export_config import (ExportConfig, safe_filename,
                                  suggest_output_path)


def project_named(name='Concert 4', sequence='Night 1'):
    project = Project(name=name)
    project.active_sequence.name = sequence
    return project


# ── turning a sequence name into a filename ───────────────────

@pytest.mark.parametrize('raw,expected', [
    ('Night 1',            'Night 1'),
    ('Night 1: Act II',    'Night 1 Act II'),      # colon is illegal
    ('bad/name\\here',     'bad name here'),
    ('a<b>c|d?e*f"g',      'a b c d e f g'),
    ('  spaced  out  ',    'spaced out'),
    ('trailing dots...',   'trailing dots'),
    ('',                   'Untitled'),
    ('   ',                'Untitled'),
    ('Ünïcode ok',         'Ünïcode ok'),
])
def test_names_windows_will_accept(raw, expected):
    assert safe_filename(raw) == expected


# ── what gets proposed ────────────────────────────────────────

def test_it_is_named_after_the_sequence():
    project = project_named()
    assert suggest_output_path(
        project, project.active_sequence) == 'Night 1.mp4'


def test_it_falls_back_to_the_project_name():
    project = project_named(sequence='')
    assert suggest_output_path(
        project, project.active_sequence) == 'Concert 4.mp4'


def test_it_lands_in_the_folder_last_exported_to(tmp_path):
    project = project_named()
    path = suggest_output_path(
        project, project.active_sequence, str(tmp_path))
    assert path == os.path.join(str(tmp_path), 'Night 1.mp4')


def test_otherwise_it_lands_beside_the_project(tmp_path):
    project = project_named()
    project.project_path = str(tmp_path / 'show.veproj')
    path = suggest_output_path(project, project.active_sequence)
    assert os.path.dirname(path) == str(tmp_path)


def test_a_project_exported_before_proposes_the_same_file(tmp_path):
    project = project_named()
    previous = str(tmp_path / 'Night 1 master.mp4')
    project.export_path = previous
    assert suggest_output_path(
        project, project.active_sequence, str(tmp_path)) == previous


def test_a_vanished_folder_is_not_proposed(tmp_path):
    """An external drive that is not plugged in this time."""
    project = project_named()
    project.export_path = '/nowhere/at/all/old.mp4'
    path = suggest_output_path(
        project, project.active_sequence, str(tmp_path))
    assert path == os.path.join(str(tmp_path), 'Night 1.mp4')


def test_it_copes_with_nothing_at_all():
    assert suggest_output_path() == 'Untitled.mp4'


# ── and it is remembered ──────────────────────────────────────

def test_the_export_path_survives_save_and_load(tmp_path):
    project = project_named()
    project.export_path = str(tmp_path / 'Night 1 master.mp4')
    path = str(tmp_path / 'show.veproj')
    assert save_project(project, path)

    back = load_project(path)
    assert back.export_path == project.export_path
    assert suggest_output_path(
        back, back.active_sequence) == project.export_path


def test_an_older_project_without_one_still_loads(tmp_path):
    import json
    project = project_named()
    path = str(tmp_path / 'show.veproj')
    save_project(project, path)
    data = json.load(open(path))
    del data['export_path']
    json.dump(data, open(path, 'w'))

    back = load_project(path)
    assert back.export_path is None
    # loading sets project_path, so it proposes a file beside it
    proposed = suggest_output_path(back, back.active_sequence)
    assert proposed == os.path.join(str(tmp_path), 'Night 1.mp4')


# ── the dialog shows it ───────────────────────────────────────

pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtWidgets import QApplication            # noqa: E402
from ui.panels.export_dialog import ExportDialog      # noqa: E402


@pytest.fixture(scope='module')
def qapp():
    yield QApplication.instance() or QApplication([])


def test_the_field_opens_filled_in(qapp, tmp_path):
    suggested = os.path.join(str(tmp_path), 'Night 1.mp4')
    dlg = ExportDialog(ExportConfig(width=1920, height=1080,
                                    output_path=suggested))
    assert dlg._path_edit.text() == suggested
    dlg.close()


def test_an_empty_suggestion_leaves_the_field_empty(qapp):
    dlg = ExportDialog(ExportConfig(width=1920, height=1080))
    assert dlg._path_edit.text() == ''
    dlg.close()
