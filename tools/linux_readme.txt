Cadenza for Linux x86_64

Extract the whole archive, open the Cadenza directory, and run:

    ./Cadenza

Keep _internal beside the executable. No Python or Conda installation is
required. FFmpeg, Qt, PortAudio, PyAV and the CUDA-enabled PyTorch runtime
are included. The host supplies the desktop session, graphics/audio
drivers and standard Linux system libraries.

Built and tested on Ubuntu 22.04 x86_64. For GPU preview and NVIDIA NVENC,
use an NVIDIA driver compatible with CUDA 12.1. CPU rendering and software
H.264 export are also supported. Linux ALSA/PulseAudio settings come from
the host desktop. This build does not install or change any system driver.

To run the built-in diagnostic checks (creates temporary test media):

    ./Cadenza --smoke-test

This checks GUI creation, six still images, zoom stability, project IO,
preview, audio device discovery, FFmpeg, software/NVENC export, and Close Project.
CUDA_VISIBLE_DEVICES=-1 ./Cadenza --smoke-test checks the CPU path.

The application version comes from core/version.py. Build provenance,
including the Git source commit, is in build-info.json.

Redistribution includes third-party libraries; their license notices are
shipped in _internal/third-party-licenses where available.
