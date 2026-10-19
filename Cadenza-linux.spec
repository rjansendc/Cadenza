# -*- mode: python ; coding: utf-8 -*-
"""Portable one-directory Linux bundle; CUDA remains available."""
import sys
import json
import importlib.metadata
from pathlib import Path

root = Path(SPECPATH)
env = Path(sys.prefix)
native = env / 'lib'
datas = [(str(root / 'icons'), 'icons')]

# Keep upstream license notices with the redistributable libraries.
for distribution in importlib.metadata.distributions():
    package_name = distribution.metadata.get('Name', 'unknown')
    for entry in distribution.files or []:
        path = Path(distribution.locate_file(entry))
        if (path.is_file() and path.suffix not in ('.py', '.pyc', '.so')
                and ('license' in path.name.lower() or path.name.lower().startswith('copying'))):
            relative = Path(*entry.parts[:-1])
            if '..' not in relative.parts:
                datas.append((str(path), str(Path('third-party-licenses/python') / package_name / relative)))
for record in (env / 'conda-meta').glob('*.json'):
    metadata = json.loads(record.read_text())
    cached = Path(metadata.get('link', {}).get('source', '/nonexistent'))
    license_dir = cached / 'info' / 'licenses'
    for path in license_dir.rglob('*'):
        if path.is_file():
            destination = Path('third-party-licenses/native') / metadata['name'] / path.relative_to(license_dir).parent
            datas.append((str(path), str(destination)))

# These are loaded dynamically and can escape dependency discovery.
binaries = [(str(env / 'bin' / 'ffmpeg'), 'bin'),
            (str(env / 'bin' / 'ffprobe'), 'bin')]
for name in ('libportaudio.so', 'libxcb-cursor.so.0',
             'libxkbcommon-x11.so.0', 'libxkbcommon.so.0',
             'libEGL.so.1', 'libGL.so.1'):
    library = native / name
    if library.exists():
        binaries.append((str(library), '.'))

a = Analysis(
    [str(root / 'main.py')],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        'effects.video.motion', 'effects.video.opacity',
        'effects.video.lumetri_color', 'effects.video.time_remap',
        'effects.audio.volume', 'effects.audio.pan',
    ],
    hookspath=[],
    hooksconfig={'matplotlib': {'backends': ['QtAgg']}},
    runtime_hooks=[str(root / 'tools' / 'pyinstaller_linux_runtime.py')],
    excludes=['decord', 'torchvision', 'torchaudio', 'triton',
              'pytest', 'PyInstaller', 'tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='Cadenza', debug=False, strip=False, upx=False, console=True,
)
coll = COLLECT(exe, a.binaries, a.datas,
               strip=False, upx=False, name='Cadenza')
