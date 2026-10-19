"""Resolve bundled command-line tools/audio and the desktop audio session."""
import ctypes.util
import os
import sys
from pathlib import Path

bundle = Path(sys._MEIPASS)
os.environ['PATH'] = str(bundle / 'bin') + os.pathsep + os.environ.get('PATH', '')

# sounddevice uses ctypes.find_library, which otherwise needs the host
# linker tools to discover our private, versionless PortAudio library.
_find_library = ctypes.util.find_library


def _bundled_find_library(name):
    if name == 'portaudio' and (bundle / 'libportaudio.so').is_file():
        return str(bundle / 'libportaudio.so')
    return _find_library(name)


ctypes.util.find_library = _bundled_find_library

# Conda's libfontconfig otherwise follows its compiled-in development
# prefix for fonts and caches. Fonts belong to the target Linux desktop.
if 'FONTCONFIG_FILE' not in os.environ and Path('/etc/fonts/fonts.conf').is_file():
    os.environ['FONTCONFIG_FILE'] = '/etc/fonts/fonts.conf'
if 'FONTCONFIG_PATH' not in os.environ and Path('/etc/fonts').is_dir():
    os.environ['FONTCONFIG_PATH'] = '/etc/fonts'

# Bundled ALSA must use the desktop's device/PulseAudio configuration.
if 'ALSA_CONFIG_PATH' not in os.environ and Path('/usr/share/alsa/alsa.conf').is_file():
    os.environ['ALSA_CONFIG_PATH'] = '/usr/share/alsa/alsa.conf'
if 'ALSA_PLUGIN_DIR' not in os.environ:
    candidates = list(Path('/usr/lib').glob('*-linux-gnu/alsa-lib'))
    candidates += [Path('/usr/lib64/alsa-lib'), Path('/usr/lib/alsa-lib')]
    for directory in candidates:
        if (directory / 'libasound_module_pcm_pulse.so').is_file():
            os.environ['ALSA_PLUGIN_DIR'] = str(directory)
            break
