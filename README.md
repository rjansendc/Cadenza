# Cadenza

A GPU-accelerated video editor built in Python with PySide6 and PyTorch. Designed for multi-camera concert editing with audio sync, Lumetri color, and NVIDIA NVENC export.

See the [changelog](CHANGELOG.md) for changes between releases.

## Features

- **Multi-track timeline** — video and audio tracks with drag, trim, razor cut
- **Audio sync** — FFT cross-correlation to automatically align multi-camera recordings
- **GPU compositing** — PyTorch-based compositor with real-time preview
- **Lumetri color** — temperature, tint, exposure, contrast, highlights, shadows
- **NVIDIA NVENC export** — hardware-accelerated H.264/H.265 export (~28fps for 4K)
- **Audio effects** — volume (dB), pan, mute with waveform display
- **Image support** — import jpg/png as stretchable clips
- **Project save/load** — full serialization of clips, effects, and envelopes

## Requirements

- Python 3.11+
- NVIDIA GPU (recommended for export and compositing)
- Windows 11 or Linux (tested on Ubuntu 22.04 x86_64)

## Installation

```bash
conda create -n cadenza python=3.11
conda activate cadenza
pip install PySide6 torch torchvision av numpy scipy
```

## Usage

```bash
python main.py
```

## Linux release

The application version comes from `core/version.py`. The Linux build uses
the current Git checkout, leaving the committed Windows spec unchanged.

Extract `Cadenza-<version>-linux-x86_64-<commit>.tar.gz`, open its `Cadenza` directory,
and run `./Cadenza`. Keep `_internal` beside the executable. Python,
Conda, Qt, FFmpeg, PortAudio, and CUDA runtime libraries are bundled.
The host provides the desktop session and graphics/audio drivers.

The release is built on Ubuntu 22.04 x86_64. NVIDIA acceleration needs a
driver compatible with CUDA 12.1; Cadenza also supports CPU rendering and
software H.264 export.

### Building on Linux

Install Conda and make it available on `PATH`, then run:

```bash
bash tools/setup_linux.sh
bash tools/build_linux.sh
```

Setup uses `.env/` and keeps downloads in `.local-cache/`. The build runs
the tests, uses `Cadenza-linux.spec`, checks the frozen executable without
the development environment, and produces a portable directory, `.tar.gz`,
and SHA-256 checksum in `dist/linux/`. `Cadenza.spec` remains the Windows recipe.

For source development:

```bash
bash tools/run_linux.sh
# Or activate Python, FFmpeg, and the desktop audio settings:
source tools/activate_linux.sh
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

For diagnostics of the finished bundle:

```bash
./Cadenza --smoke-test
CUDA_VISIBLE_DEVICES=-1 ./Cadenza --smoke-test
```

These exercise the GUI, six stills, zoom stability, project IO, preview,
audio, bundled FFmpeg, software/GPU export, and Close Project. No sample footage is needed.

### Password-protected Linux archive

With 7-Zip (`7zz` or `7z`) installed, run:

```bash
bash tools/package_linux_7z.sh
# Or package a build in another location:
bash tools/package_linux_7z.sh "/path/to/dist/Cadenza"
```

Set `Password=""` near the top of the script to your preferred password to
reuse it without typing it each time. Leave it empty to be prompted instead.
The script creates `Cadenza_Linux.7z` beside the build folder, encrypting both
contents and filenames. It defaults to `dist/linux/Cadenza`; an optional second
argument sets the output path.
An existing archive must be moved or removed before running it again.

## Stack

| Component | Library |
|-----------|---------|
| UI | PySide6 (Qt6) |
| GPU compositing | PyTorch / CUDA |
| Video decode | PyAV (FFmpeg) |
| Audio sync | scipy (FFT) |
| Export | PyAV + NVENC |

## Project Structure

```
cadenza/
├── core/          # Project, clip, effects, undo
├── effects/       # Video and audio effect plugins
├── gpu/           # GPU compositor
├── media/         # Decoder, waveform
├── render/        # Export pipeline
├── sync/          # Audio sync algorithm
├── ui/            # PySide6 UI panels and widgets
└── main.py
```

## License

MIT
