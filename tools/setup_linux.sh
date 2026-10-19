#!/usr/bin/env bash
# Install the project's locked development stack without changing other environments.
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
env_dir="$project_dir/.env"
export CONDA_PKGS_DIRS="$project_dir/.local-cache/conda"
export PIP_CACHE_DIR="$project_dir/.local-cache/pip"
export XDG_CACHE_HOME="$project_dir/.local-cache"

if ! command -v conda >/dev/null 2>&1; then
    echo 'Conda must be installed and available on PATH.' >&2
    exit 1
fi

if [[ ! -f "$env_dir/conda-meta/history" ]]; then
    conda create --prefix "$env_dir" --override-channels -c conda-forge \
        python=3.11 pip ffmpeg portaudio xcb-util-cursor libxkbcommon \
        libgl libegl -y
fi

# Pin the CUDA build explicitly; compatible with this host's RTX 3060 Ti.
"$env_dir/bin/python" -m pip install \
    torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 \
    --index-url https://download.pytorch.org/whl/cu121
"$env_dir/bin/python" -m pip install -r "$project_dir/requirements_locked.txt"
# Remove the optional, incorrectly tagged wheel from earlier Linux setups.
if "$env_dir/bin/python" -m pip show decord >/dev/null 2>&1; then
    "$env_dir/bin/python" -m pip uninstall -y decord
fi
"$env_dir/bin/python" -m pip check

source "$project_dir/tools/activate_linux.sh"
cd -- "$project_dir"
"$env_dir/bin/python" -m compileall -q core effects gpu media render sync ui tools main.py
"$env_dir/bin/python" check_env.py
"$env_dir/bin/python" -c 'import av, sounddevice; from ui.mainwindow import MainWindow; print("Application imports passed")'
"$env_dir/bin/python" -m pip freeze > "$env_dir/pip-freeze.txt"
echo 'Environment installed. Launch with: bash tools/run_linux.sh'
