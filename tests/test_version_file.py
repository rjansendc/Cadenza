"""
The Windows version resource compiled into Cadenza.exe.

Generated from core/version.py at build time, so the number in the
exe's file properties cannot drift from the one the About box reports.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import ast

import pytest

from core.version import __version__, APP_NAME
from tools.version_file import (version_tuple, version_text,
                                write_version_file)


# PyInstaller reads the file by eval'ing it with its own versioninfo
# classes in scope; stand in for them to prove the file parses.
VERSIONINFO_NAMES = [
    'VSVersionInfo', 'FixedFileInfo', 'StringFileInfo', 'StringTable',
    'StringStruct', 'VarFileInfo', 'VarStruct',
]


def evaluate(text):
    scope = {}
    for name in VERSIONINFO_NAMES:
        scope[name] = type(name, (), {
            '__init__': lambda self, *a, **k: setattr(self, 'args', (a, k)),
        })
    return eval(compile(text, 'version_info.txt', 'eval'), scope)


@pytest.mark.parametrize('version,expected', [
    ('1.2.0',   (1, 2, 0, 0)),
    ('0.9.3',   (0, 9, 3, 0)),
    ('2.0.0',   (2, 0, 0, 0)),
    ('12.34.5', (12, 34, 5, 0)),
])
def test_windows_wants_four_numbers(version, expected):
    assert version_tuple(version) == expected


def test_the_resource_parses_the_way_pyinstaller_reads_it():
    assert type(evaluate(version_text())).__name__ == 'VSVersionInfo'


def test_the_resource_carries_this_build_s_version():
    text = version_text()
    dotted = '.'.join(str(p) for p in version_tuple())
    assert f'filevers={version_tuple()}' in text
    assert f"StringStruct('FileVersion',      '{dotted}')" in text
    assert f"StringStruct('ProductVersion',   '{dotted}')" in text
    assert dotted.startswith(__version__)


def test_it_names_the_application():
    text = version_text()
    assert f"StringStruct('ProductName',      '{APP_NAME}')" in text
    assert f"StringStruct('OriginalFilename', '{APP_NAME}.exe')" in text


def test_writing_it_puts_a_file_where_it_says(tmp_path):
    target = tmp_path / 'nested' / 'version_info.txt'
    written = write_version_file(target)
    assert written == str(target)
    assert target.exists()
    assert type(evaluate(target.read_text())).__name__ == 'VSVersionInfo'


def test_bumping_the_version_changes_the_resource():
    """The whole point: one edit, both places."""
    assert version_text('9.9.9') != version_text('1.2.0')
    assert 'filevers=(9, 9, 9, 0)' in version_text('9.9.9')


# ── the spec wires it in ──────────────────────────────────────

def spec_source():
    here = os.path.dirname(os.path.dirname(__file__))
    with open(os.path.join(here, 'Cadenza.spec'), encoding='utf-8') as f:
        return f.read()


def test_the_spec_is_valid_python():
    ast.parse(spec_source())


WINDOWS_SPEC_NOTE = (
    "Cadenza.spec is the Windows build spec. A version resource is a "
    "Windows PE structure, so PyInstaller ignores version= elsewhere "
    "— a Linux or macOS bundle belongs in its own spec file "
    "(Cadenza-linux.spec), not at this path."
)


def test_the_spec_generates_and_uses_the_resource():
    source = spec_source()
    assert 'write_version_file()' in source, WINDOWS_SPEC_NOTE
    assert 'version=_version_resource' in source, WINDOWS_SPEC_NOTE


def test_the_exe_still_gets_its_icon():
    """Adding version= must not have displaced anything."""
    source = spec_source()
    assert "icon='icons/app.ico'" in source, WINDOWS_SPEC_NOTE
    assert "name='Cadenza'" in source
