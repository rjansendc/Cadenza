"""
Proxy media — low resolution, all-intra copies used for preview.

Scrubbing 4K long-GOP footage is slow for a structural reason: H.264
can only start decoding at a keyframe, so showing one frame means
decoding everything since the last one — often one to five seconds of
video. Measured here, a random seek into a 4K source costs hundreds of
milliseconds, which is exactly the lag you feel dragging the playhead.

A proxy fixes it at the source: every frame is a keyframe (gop_size=1)
and the picture is a quarter of the size, so any seek is one frame's
work. Premiere solves this the same way.

Proxies live in cache/proxies/ and are used for preview only; export
always reads the originals.
"""

import hashlib
import os
import time
from pathlib import Path
from typing import Callable, Optional

from core.paths import cache_dir

# see core/paths.py: a frozen build must not cache inside _internal/
CACHE_DIR = cache_dir('proxies')

# Running ffmpeg processes, so Ctrl+C can actually stop them. Without
# this the transcodes carry on and the thread pool waits for them.
_RUNNING = set()
_RUNNING_LOCK = None


def cancel_all():
    """Stop every transcode in progress. Safe to call from a handler."""
    for proc in list(_RUNNING):
        try:
            proc.kill()
        except Exception:
            pass
    _RUNNING.clear()

DEFAULT_HEIGHT = 540          # 960x540 from 16:9 sources

# Keyframe spacing in the proxy. All-intra (1) makes every seek one
# frame, but writes 3-4x the data, and the disk write becomes the
# bottleneck during generation. At 12, a seek decodes at most 12 small
# frames — about 6ms, still far below the 164ms an original 4K seek
# costs — and the file is a fraction of the size.
DEFAULT_GOP = 12

# best first; the build decides what is actually there
ENCODERS = ('h264_nvenc', 'libx264', 'mpeg4')


def proxy_path(filepath: str, height: int = DEFAULT_HEIGHT) -> Path:
    """
    Where this file's proxy lives. Keyed on name and size, like the
    waveform cache, so moving a file does not orphan its proxy.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = Path(filepath)
    try:
        size = p.stat().st_size
    except OSError:
        size = 0
    key = hashlib.md5(f"{p.name}_{size}_{height}".encode()).hexdigest()[:12]
    return CACHE_DIR / f"{p.stem}_{key}_{height}p.mp4"


def has_proxy(filepath: str, height: int = DEFAULT_HEIGHT) -> bool:
    path = proxy_path(filepath, height)
    return path.exists() and path.stat().st_size > 0


def available_encoders() -> list:
    """Encoders this build has, best first."""
    import av
    found = [n for n in ENCODERS if n in av.codecs_available]
    return found or ['mpeg4']


def pick_encoder() -> str:
    """
    The encoder that actually works here.

    A build can list h264_nvenc while the machine has no NVIDIA
    encoder — opening it then fails, so try each in turn.
    """
    import av
    for name in available_encoders():
        try:
            container = av.open(os.devnull, mode='w', format='mp4')
            stream = container.add_stream(name, rate=30)
            stream.width, stream.height = 320, 240
            stream.pix_fmt = 'yuv420p'
            frame = av.VideoFrame(320, 240, 'yuv420p')
            list(stream.encode(frame))
            container.close()
            return name
        except Exception:
            try:
                container.close()
            except Exception:
                pass
            continue
    return 'mpeg4'


def _cuvid_context(in_stream, width: int, height: int):
    """
    An NVDEC decoder that scales while it decodes, or None.

    cuvid takes a resize option, so the frame arrives already small:
    no 4K frame is ever decoded on the CPU, downloaded at full size,
    or scaled by swscale.
    """
    import av
    cuvid = {
        'h264': 'h264_cuvid', 'hevc': 'hevc_cuvid',
        'mpeg2video': 'mpeg2_cuvid', 'vp9': 'vp9_cuvid',
        'av1': 'av1_cuvid',
    }
    try:
        name = cuvid.get(in_stream.codec_context.name)
        if not name or name not in av.codecs_available:
            return None
        ctx = av.codec.Codec(name, 'r').create()
        ctx.extradata = in_stream.codec_context.extradata
        ctx.options = {'resize': f'{width}x{height}'}
        return ctx
    except Exception:
        return None


def ffmpeg_path() -> Optional[str]:
    """ffmpeg on PATH, or None. PyAV bundles the libraries, not the CLI."""
    import shutil
    return shutil.which('ffmpeg')


def _generate_with_ffmpeg(filepath: str, out_path: Path, height: int,
                          progress: Optional[Callable[[int], None]],
                          verbose: bool, gop: int = DEFAULT_GOP,
                          qp: int = 27,
                          seconds: Optional[float] = None) -> bool:
    """
    Transcode with the ffmpeg binary, keeping frames on the GPU from
    decode to encode: no copy to system memory, and no per-frame trip
    through Python. Several times faster than driving PyAV frame by
    frame. Returns False if it is unavailable or fails.
    """
    import re
    import subprocess

    exe = ffmpeg_path()
    if not exe:
        return False

    tmp_path = out_path.with_suffix('.partial.mp4')
    total_frames = 0
    try:
        import av
        with av.open(str(filepath)) as probe:
            stream = probe.streams.video[0]
            total_frames = stream.frames or 0
    except Exception:
        pass

    cmd = [
        exe, '-hide_banner', '-loglevel', 'error', '-y',
        '-hwaccel', 'cuda', '-hwaccel_output_format', 'cuda',
        '-i', str(filepath),
    ]
    if seconds:
        cmd += ['-t', str(seconds)]
    cmd += [
        '-vf', f'scale_cuda=-2:{height}',
        '-c:v', 'h264_nvenc', '-preset', 'p1',
        '-rc', 'constqp', '-qp', str(qp),
        '-g', str(gop),               # short GOP: cheap seeks, small file
        '-an',                        # audio comes from the original
        '-progress', 'pipe:1', '-nostats',
        str(tmp_path),
    ]
    if verbose:
        print(f"    ffmpeg CUDA pipeline -> {height}p", flush=True)

    proc = None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        _RUNNING.add(proc)
        for line in proc.stdout:
            match = re.match(r'frame=(\d+)', line.strip())
            if match and progress and total_frames:
                done = int(match.group(1))
                progress(min(99, int(done * 100 / total_frames)))
        proc.wait()
        if proc.returncode in (-9, -15, 1) and proc.returncode != 0 \
                and not tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
            return False
        if proc.returncode != 0:
            err = (proc.stderr.read() or '').strip()[:200]
            if verbose:
                print(f"    ffmpeg failed ({err}) — using PyAV", flush=True)
            tmp_path.unlink(missing_ok=True)
            return False
    except KeyboardInterrupt:
        if proc is not None:
            proc.kill()
        tmp_path.unlink(missing_ok=True)
        raise
    except Exception as e:
        if verbose:
            print(f"    ffmpeg unavailable ({e}) — using PyAV", flush=True)
        tmp_path.unlink(missing_ok=True)
        return False
    finally:
        _RUNNING.discard(proc)

    if not tmp_path.exists() or tmp_path.stat().st_size == 0:
        tmp_path.unlink(missing_ok=True)
        return False
    os.replace(tmp_path, out_path)
    if progress:
        progress(100)
    return True


def measure_rate(filepath: str, height: int = DEFAULT_HEIGHT,
                  seconds: float = 60.0, gop: int = DEFAULT_GOP,
                  qp: int = 27) -> Optional[dict]:
    """
    Transcode a short sample and report the rate, so a full run can be
    estimated before committing to it. Returns None if ffmpeg is
    missing; the sample is written to a temp file and deleted.
    """
    import tempfile
    import time as _time

    if not ffmpeg_path():
        return None

    tmp = Path(tempfile.gettempdir()) / 'cadenza_proxy_sample.mp4'
    started = _time.perf_counter()
    ok = _generate_with_ffmpeg(filepath, tmp, height, None, False,
                               gop, qp, seconds=seconds)
    elapsed = _time.perf_counter() - started
    if not ok:
        return None

    total_hours = 0.0
    try:
        import av
        with av.open(str(filepath)) as c:
            total_hours = (c.duration or 0) / 1e6 / 3600
    except Exception:
        pass
    tmp.unlink(missing_ok=True)

    speed = seconds / elapsed if elapsed else 0
    return {
        'sample_seconds': seconds,
        'elapsed': elapsed,
        'speed': speed,                       # x real time
        'source_hours': total_hours,
        'estimate_minutes': (total_hours * 3600 / speed / 60
                             if speed else 0),
    }


def generate_proxy(filepath: str,
                   height: int = DEFAULT_HEIGHT,
                   progress: Optional[Callable[[int], None]] = None,
                   overwrite: bool = False,
                   encoder_name: Optional[str] = None,
                   verbose: bool = False,
                   gop: int = DEFAULT_GOP,
                   qp: int = 27) -> Optional[Path]:
    """
    Write an all-intra proxy for one file. Returns its path, or None
    if the source could not be read.

    progress is called with a percentage, so a long transcode can be
    reported and cancelled by the caller raising inside it.
    """
    import av

    out_path = proxy_path(filepath, height)
    if out_path.exists() and not overwrite:
        return out_path

    if _generate_with_ffmpeg(filepath, out_path, height,
                             progress, verbose, gop, qp):
        return out_path

    src = av.open(str(filepath))
    try:
        in_stream = src.streams.video[0]
    except (IndexError, KeyError):
        src.close()
        return None
    in_stream.thread_type = 'AUTO'

    width = int(round(in_stream.codec_context.width *
                      height / max(1, in_stream.codec_context.height)))
    width -= width % 2            # H.264 needs even dimensions

    tmp_path = out_path.with_suffix('.partial.mp4')
    dst = av.open(str(tmp_path), mode='w')
    encoder = encoder_name or pick_encoder()
    out_stream = dst.add_stream(encoder, rate=in_stream.average_rate)
    out_stream.width  = width
    out_stream.height = height
    out_stream.pix_fmt = 'yuv420p'
    # every frame a keyframe: that is the whole point
    out_stream.gop_size = gop
    if encoder == 'libx264':
        out_stream.options = {'preset': 'veryfast', 'crf': '23',
                              'tune': 'fastdecode'}
    elif encoder == 'h264_nvenc':
        out_stream.options = {'preset': 'p1', 'rc': 'constqp',
                              'qp': str(qp)}

    total = in_stream.frames or 0
    done = 0

    # NVDEC can decode AND downscale on the GPU, so the CPU never sees
    # a 4K frame. That is the difference between a transcode that runs
    # at a few times real time and one that runs at tens.
    hw_ctx = _cuvid_context(in_stream, width, height)
    if verbose:
        src_h = in_stream.codec_context.height
        print(f"    {src_h}p -> {height}p | "
              f"{'GPU decode+scale (NVDEC resize)' if hw_ctx is not None else 'CPU decode + swscale'}"
              f" | encoder {encoder}", flush=True)

    try:
        if hw_ctx is not None:
            for packet in src.demux(in_stream):
                for frame in hw_ctx.decode(packet):
                    small = (frame if frame.width == width
                             else frame.reformat(width=width,
                                                 height=height))
                    for out_packet in out_stream.encode(small):
                        dst.mux(out_packet)
                    done += 1
                    if progress and total and done % 60 == 0:
                        progress(int(done * 100 / total))
        else:
            for frame in src.decode(in_stream):
                small = frame.reformat(width=width, height=height,
                                       format='yuv420p')
                for packet in out_stream.encode(small):
                    dst.mux(packet)
                done += 1
                if progress and total and done % 60 == 0:
                    progress(int(done * 100 / total))
        for packet in out_stream.encode():
            dst.mux(packet)
    finally:
        dst.close()
        src.close()

    os.replace(tmp_path, out_path)
    if progress:
        progress(100)
    return out_path


def needs_proxy(filepath: str, height: int = DEFAULT_HEIGHT,
                 min_source_height: int = 1081) -> bool:
    """
    Is this source big enough to be worth proxying?

    1080p and below already seek quickly enough; the cost is in 4K.
    """
    import av
    try:
        with av.open(str(filepath)) as container:
            stream = container.streams.video[0]
            return stream.codec_context.height >= min_source_height
    except Exception:
        return False


def generate_for_project(project, height: int = DEFAULT_HEIGHT,
                         progress: Optional[Callable[[str, int], None]] = None
                         ) -> dict:
    """Make proxies for every video source a project uses."""
    results = {}
    paths = []
    for clip in project.clips.values():
        if clip.has_video and clip.filepath not in paths:
            paths.append(clip.filepath)

    for path in paths:
        if not os.path.exists(path):
            results[path] = 'missing'
            continue
        if has_proxy(path, height):
            results[path] = 'cached'
            continue
        started = time.time()
        try:
            generate_proxy(
                path, height,
                progress=(lambda pct, p=path:
                          progress(p, pct)) if progress else None)
            results[path] = f"{time.time() - started:.0f}s"
        except Exception as e:
            results[path] = f"failed: {e}"
    return results
