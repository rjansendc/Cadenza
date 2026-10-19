#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
env_dir="$project_dir/.env"
if [[ ! -x "$env_dir/bin/python" ]]; then
    echo 'Run bash tools/setup_linux.sh first.' >&2
    exit 1
fi
source "$project_dir/tools/activate_linux.sh"
cd -- "$project_dir"
exec "$env_dir/bin/python" main.py "$@"
