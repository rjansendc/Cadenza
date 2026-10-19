# -*- mode: python ; coding: utf-8 -*-

# Stamp the exe with the app version. Generated here from
# core/version.py so Cadenza.exe's file properties always agree with
# what the About box says.
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.abspath(SPECPATH))
from tools.version_file import write_version_file
from core.version import __version__ as _app_version

_version_resource = write_version_file()
print(f"[spec] Cadenza {_app_version} -> {_version_resource}")

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('icons', 'icons'),
        # 'effects' is NOT shipped as data: nothing reads those files
        # at runtime (the packages import each other, they are not
        # scanned), so the copy in _internal was dead weight — and it
        # handed the source of every effect to anyone with the build.
    ],
    hiddenimports=[
        # Belt and braces: effects/__init__.py imports effects.video,
        # whose __init__ imports the rest, so PyInstaller finds them
        # anyway. Listed explicitly in case that chain is ever changed.
        'effects.video.motion',
        'effects.video.opacity',
        'effects.video.lumetri_color',   # was 'lumetri' — no such module
        'effects.video.time_remap',
        'effects.audio.volume',
        'effects.audio.pan',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Cadenza',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icons/app.ico',
    version=_version_resource,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Cadenza',
)
