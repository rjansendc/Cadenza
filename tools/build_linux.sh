#!/usr/bin/env bash
# Build and check a self-contained folder using the local development env.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_dir/tools/activate_linux.sh"
cd -- "$project_dir"
python -m pip check
QT_QPA_PLATFORM=offscreen python -m pytest -q
python -m PyInstaller --noconfirm --clean --distpath dist/linux Cadenza-linux.spec
check_bundle() {
    env -u PYTHONPATH -u PYTHONHOME -u LD_LIBRARY_PATH -u CONDA_PREFIX \
        -u ALSA_CONFIG_PATH -u ALSA_PLUGIN_DIR -u FONTCONFIG_PATH -u FONTCONFIG_FILE \
        -u QT_PLUGIN_PATH -u QT_QPA_PLATFORM_PLUGIN_PATH \
        PATH=/usr/bin:/bin "$@" "$project_dir/dist/linux/Cadenza/Cadenza" --smoke-test
}
check_bundle
check_bundle CUDA_VISIBLE_DEVICES=-1
cp tools/linux_readme.txt dist/linux/Cadenza/README.txt
python - <<'PY'
import json, platform, subprocess
from pathlib import Path
from core.version import __version__
root = Path('dist/linux/Cadenza')
manifest = {'application': 'Cadenza', 'version': __version__,
            'platform': platform.platform(), 'architecture': platform.machine(),
            'python': platform.python_version(),
            'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
            'working_tree_dirty': bool(subprocess.check_output(
                ['git', 'status', '--porcelain'], text=True).strip())}
(root/'build-info.json').write_text(json.dumps(manifest, indent=2)+'\n')
PY
version="$(python -c 'from core.version import __version__; print(__version__)')"
revision="$(git rev-parse --short=7 HEAD)"
archive="Cadenza-${version}-linux-$(uname -m)-${revision}.tar.gz"
tar --exclude=Cadenza/cache -C dist/linux -czf "dist/linux/$archive" Cadenza
(cd dist/linux && sha256sum "$archive" > "$archive.sha256")
echo "Linux release: $project_dir/dist/linux/$archive"
