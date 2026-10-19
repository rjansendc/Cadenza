# Source this file to use Cadenza's local Python, FFmpeg and native libraries.
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
env_dir="$project_dir/.env"
export PATH="$env_dir/bin:$PATH"
export LD_LIBRARY_PATH="$env_dir/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export XDG_CACHE_HOME="$project_dir/.local-cache"

# Conda's ALSA config doesn't include the desktop's PulseAudio devices.
# Use the host config/plugins when present, preserving explicit overrides.
if [[ -z "${ALSA_CONFIG_PATH:-}" && -f /usr/share/alsa/alsa.conf ]]; then
    export ALSA_CONFIG_PATH=/usr/share/alsa/alsa.conf
fi
if [[ -z "${ALSA_PLUGIN_DIR:-}" ]]; then
    for alsa_dir in /usr/lib/*-linux-gnu/alsa-lib /usr/lib64/alsa-lib /usr/lib/alsa-lib; do
        if [[ -f "$alsa_dir/libasound_module_pcm_pulse.so" ]]; then
            export ALSA_PLUGIN_DIR="$alsa_dir"
            break
        fi
    done
fi
