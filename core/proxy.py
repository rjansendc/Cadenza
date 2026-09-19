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

CACHE_DIR = Path(__file__).parent.parent / 'cache' / 'proxies'

DEFAULT_HEIGHT = 540          # 960x540 from 16:9 sources

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


def generate_proxy(filepath: str,
                   height: int = DEFAULT_HEIGHT,
                   progress: Optional[Callable[[int], None]] = None,
                   overwrite: bool = False,
                   encoder_name: Optional[str] = None) -> Optional[Path]:
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
    out_stream.gop_size = 1
    if encoder == 'libx264':
        out_stream.options = {'preset': 'veryfast', 'crf': '23',
                              'tune': 'fastdecode'}
    elif encoder == 'h264_nvenc':
        out_stream.options = {'preset': 'p1', 'rc': 'constqp', 'qp': '25'}

    total = in_stream.frames or 0
    done = 0
    try:
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
