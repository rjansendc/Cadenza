"""
Remembering where you were, and saying what this build is.

Every file dialog opened on '' — whatever folder the app was launched
from — so reaching the footage meant navigating there again each time,
and there was no way back to a recent project. The version was a
literal '1.0' inside an f-string in the About handler.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from core.version import __version__, APP_NAME, environment, version_string

pytest.importorskip('PySide6.QtWidgets')
from PySide6.QtCore import QSettings       # noqa: E402

from ui import recent_files as recent      # noqa: E402


@pytest.fixture(autouse=True)
def private_settings(tmp_path, monkeypatch):
    """Point QSettings at a temp file: a test run must never touch
    the real preferences."""
    path = str(tmp_path / 'settings.ini')
    monkeypatch.setattr(
        recent, 'settings',
        lambda: QSettings(path, QSettings.Format.IniFormat))
    yield


def project_file(tmp_path, name):
    path = tmp_path / name
    path.write_text('{}')
    return str(path)


# ── last folder ───────────────────────────────────────────────

def test_nothing_remembered_at_first():
    assert recent.last_dir(recent.PROJECTS) == ''


def test_a_folder_is_remembered_from_a_file(tmp_path):
    recent.remember_dir(recent.MEDIA, project_file(tmp_path, 'a.mp4'))
    assert recent.last_dir(recent.MEDIA) == str(tmp_path)


def test_each_kind_remembers_its_own(tmp_path):
    """Projects and footage rarely live in the same place."""
    media = tmp_path / 'footage'
    projects = tmp_path / 'edits'
    media.mkdir()
    projects.mkdir()
    recent.remember_dir(recent.MEDIA, str(media / 'a.mp4'))
    recent.remember_dir(recent.PROJECTS, str(projects / 'p.veproj'))
    assert recent.last_dir(recent.MEDIA) == str(media)
    assert recent.last_dir(recent.PROJECTS) == str(projects)


def test_a_folder_that_has_gone_is_not_offered(tmp_path):
    gone = tmp_path / 'external_drive'
    gone.mkdir()
    recent.remember_dir(recent.MEDIA, str(gone / 'a.mp4'))
    gone.rmdir()
    assert recent.last_dir(recent.MEDIA) == ''


# ── recent projects ───────────────────────────────────────────

def test_newest_first(tmp_path):
    for name in ('one.veproj', 'two.veproj', 'three.veproj'):
        recent.add_recent(project_file(tmp_path, name))
    assert [os.path.basename(p) for p in recent.recent_projects()] == [
        'three.veproj', 'two.veproj', 'one.veproj']


def test_opening_one_again_moves_it_to_the_top(tmp_path):
    first = project_file(tmp_path, 'one.veproj')
    recent.add_recent(first)
    recent.add_recent(project_file(tmp_path, 'two.veproj'))
    recent.add_recent(first)
    names = [os.path.basename(p) for p in recent.recent_projects()]
    assert names == ['one.veproj', 'two.veproj']       # no duplicate


def test_the_list_has_a_limit(tmp_path):
    for i in range(recent.MAX_RECENT + 5):
        recent.add_recent(project_file(tmp_path, f'p{i}.veproj'))
    assert len(recent.recent_projects()) == recent.MAX_RECENT


def test_a_deleted_project_drops_off(tmp_path):
    path = project_file(tmp_path, 'gone.veproj')
    recent.add_recent(path)
    recent.add_recent(project_file(tmp_path, 'here.veproj'))
    os.remove(path)
    assert [os.path.basename(p) for p in recent.recent_projects()] == [
        'here.veproj']


def test_adding_a_project_remembers_its_folder(tmp_path):
    recent.add_recent(project_file(tmp_path, 'p.veproj'))
    assert recent.last_dir(recent.PROJECTS) == str(tmp_path)


def test_clearing_empties_the_list(tmp_path):
    recent.add_recent(project_file(tmp_path, 'p.veproj'))
    recent.clear_recent()
    assert recent.recent_projects() == []


# ── version ───────────────────────────────────────────────────

def test_the_version_looks_like_one():
    parts = __version__.split('.')
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


def test_version_string_names_the_app():
    assert version_string() == f'{APP_NAME} {__version__}'


def test_the_environment_survives_whatever_is_missing():
    rows = environment()
    assert rows['Cadenza'] == __version__
    for key in ('Python', 'PySide6', 'PyTorch', 'PyAV'):
        assert rows[key] and isinstance(rows[key], str)


def test_the_gpu_line_says_which_way_it_went():
    import torch
    gpu = environment()['GPU']
    if torch.cuda.is_available():
        assert 'none detected' not in gpu
    else:
        assert 'none detected' in gpu


def test_a_saved_project_records_the_build(tmp_path):
    from core.project import Project
    from core.project_io import save_project
    import json
    path = str(tmp_path / 'p.veproj')
    assert save_project(Project(), path)
    with open(path) as handle:
        assert json.load(handle)['app_version'] == __version__


def test_an_old_file_without_the_stamp_still_loads(tmp_path):
    from core.project import Project
    from core.project_io import save_project, load_project
    import json
    path = str(tmp_path / 'p.veproj')
    save_project(Project(name='Older'), path)
    data = json.load(open(path))
    del data['app_version']
    json.dump(data, open(path, 'w'))
    assert load_project(path).name == 'Older'
