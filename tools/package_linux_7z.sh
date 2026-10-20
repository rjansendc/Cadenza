#!/usr/bin/env bash
# Package a built Linux folder; 7-Zip prompts for the password.
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${1:-}" == --help || "$#" -gt 2 ]]; then
    echo "Usage: bash tools/package_linux_7z.sh [bundle-folder] [output.7z]"
    echo "Defaults: dist/linux/Cadenza and Cadenza_Linux.7z beside that folder."
    exit 0
fi

archiver="$(command -v 7zz || command -v 7z || true)"
if [[ -z "$archiver" ]]; then
    echo 'Install 7-Zip (7zz or 7z) first.' >&2
    exit 1
fi

bundle="${1:-$project_dir/dist/linux/Cadenza}"
if [[ ! -d "$bundle" ]]; then
    echo "Bundle folder not found: $bundle" >&2
    exit 1
fi
bundle="$(realpath -- "$bundle")"
archive="$(realpath -m -- "${2:-$(dirname -- "$bundle")/Cadenza_Linux.7z}")"
if [[ "$archive" != *.7z ]]; then
    echo 'The output filename must end in .7z.' >&2
    exit 1
fi
if [[ -e "$archive" || -L "$archive" ]]; then
    echo "Archive already exists; move or remove it first: $archive" >&2
    exit 1
fi
if [[ "$archive" == "$bundle/"* ]]; then
    echo 'Choose an output location outside the bundle folder.' >&2
    exit 1
fi

# Work beside the bundle so the archive contains one portable folder,
# rather than the absolute path to the build machine's files.
cd -- "$(dirname -- "$bundle")"
echo "Creating: $archive"
"$archiver" a -t7z -mhe=on -p "$archive" -- "$(basename -- "$bundle")"
echo "Created: $archive"
