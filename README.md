# Cadenza

A GPU-accelerated video editor built in Python with PySide6 and PyTorch. Designed for multi-camera concert editing with audio sync, Lumetri color, and NVIDIA NVENC export.

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
- Windows (tested on Windows 11)

## Installation

```bash
conda create -n cadenza python=3.11
conda activate cadenza
pip install PySide6 torch torchvision av numpy scipy
```

Place `ffmpeg.exe` in the project root or ensure it is on your PATH.

## Usage

```bash
python main.py
```

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
