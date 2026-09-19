"""
Measure where playback time actually goes.

Run against a project to see composite throughput at each preview
quality, and decode throughput per source file:

    python tools/bench_playback.py Concert4.veproj
    python tools/bench_playback.py Concert4.veproj --start 3000 --frames 120

Reports frames per second. Playback needs to hit the sequence rate
(29.97), so anything below that is where the stutter comes from.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import effects  # noqa: F401  — registers the effect classes


def bench_composite(project, start: int, frames: int):
    from gpu.compositor import Compositor

    seq = project.active_sequence
    clips = list(project.clips.values())
    comp = Compositor(seq)
    w, h = seq.settings.width, seq.settings.height

    print(f"\nSequence {w}x{h} @ {seq.settings.fps:g} fps, "
          f"{len(clips)} clips")
    print(f"Compositing {frames} frames from {start}\n")
    print(f"{'quality':<10} {'canvas':<12} {'fps':>8}  {'ms/frame':>9}")
    print("-" * 44)

    results = {}
    for label, div in (('Full', 1), ('1/2', 2), ('1/4', 4), ('1/8', 8)):
        comp.set_preview_size(w // div, h // div)
        comp.invalidate_cache()

        # one warm-up frame: first composite pays CUDA kernel setup
        comp.composite_frame(clips, start, sequence=seq)

        t0 = time.perf_counter()
        for i in range(frames):
            comp.composite_frame(clips, start + i, sequence=seq)
        elapsed = time.perf_counter() - t0

        fps = frames / elapsed if elapsed else 0.0
        results[label] = fps
        print(f"{label:<10} {f'{w//div}x{h//div}':<12} "
              f"{fps:>8.1f}  {elapsed / frames * 1000:>9.1f}")

    target = seq.settings.fps
    print()
    for label, fps in results.items():
        verdict = 'real time' if fps >= target else 'TOO SLOW'
        print(f"  {label:<6} {fps:6.1f} fps   {verdict}")
    return results


def bench_decoders(project, start: int, frames: int):
    """Decode throughput per source file, in isolation."""
    from media.decoder import VideoDecoder

    seq = project.active_sequence
    files = []
    for clip in project.clips.values():
        if clip.has_video and clip.filepath not in files:
            files.append(clip.filepath)

    print(f"\nDecoding {frames} sequential frames per file\n")
    print(f"{'file':<34} {'size':<12} {'fps':>8}")
    print("-" * 56)

    for path in files:
        if not os.path.exists(path):
            print(f"{os.path.basename(path)[:33]:<34} {'MISSING':<12}")
            continue
        try:
            dec = VideoDecoder(path)
            dec.get_frame(start)                 # warm up + seek
            t0 = time.perf_counter()
            for i in range(frames):
                dec.get_frame(start + i)
            elapsed = time.perf_counter() - t0
            fps = frames / elapsed if elapsed else 0.0
            print(f"{os.path.basename(path)[:33]:<34} "
                  f"{f'{dec.width}x{dec.height}':<12} {fps:>8.1f}")
        except Exception as e:
            print(f"{os.path.basename(path)[:33]:<34} error: {e}")


def bench_hw_vs_sw(path: str, start: int, frames: int):
    """Time one file decoded on the GPU against the CPU."""
    import os
    from media.decoder import VideoDecoder

    print(f"\n{os.path.basename(path)}")
    results = {}
    for label, env in (('GPU (NVDEC)', '1'), ('CPU (software)', '0')):
        os.environ['CADENZA_HWDECODE'] = env
        try:
            dec = VideoDecoder(path)
            dec.get_frame(start)           # open + seek + warm up
            used = 'yes' if getattr(dec, 'hardware_decode', False) else 'no'
            t0 = time.perf_counter()
            for i in range(frames):
                dec.get_frame(start + i)
            elapsed = time.perf_counter() - t0
            fps = frames / elapsed if elapsed else 0.0
            results[label] = fps
            print(f"  {label:<16} {fps:7.1f} fps   "
                  f"{elapsed / frames * 1000:5.1f} ms/frame   "
                  f"hardware: {used}")
        except Exception as e:
            print(f"  {label:<16} failed: {e}")
    os.environ.pop('CADENZA_HWDECODE', None)

    if len(results) == 2:
        gpu, cpu = results['GPU (NVDEC)'], results['CPU (software)']
        if cpu:
            print(f"  -> {gpu / cpu:.2f}x")
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('project', nargs='?', help='a .veproj file')
    ap.add_argument('--start', type=int, default=0,
                    help='first frame to composite (default 0)')
    ap.add_argument('--frames', type=int, default=60,
                    help='how many frames to time (default 60)')
    ap.add_argument('--decoders', action='store_true',
                    help='also time each source file on its own')
    ap.add_argument('--hw', metavar='FILE',
                    help='compare GPU and CPU decoding of one file')
    args = ap.parse_args(argv)

    if args.hw:
        import torch
        print(f"torch {torch.__version__} | CUDA "
              f"{torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO'}")
        bench_hw_vs_sw(args.hw, args.start, args.frames)
        return 0

    from core.project_io import load_project
    project = load_project(args.project)

    import torch
    print(f"torch {torch.__version__} | CUDA "
          f"{'yes: ' + torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO — this will be slow'}")

    bench_composite(project, args.start, args.frames)
    if args.decoders:
        bench_decoders(project, args.start, min(args.frames, 30))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
