"""
Build proxy media for a project (or a single file).

Proxies are small, all-intra copies kept in cache/proxies/. Preview and
scrubbing use them automatically; export always reads the originals.

    python tools/make_proxies.py "Concert4.veproj"
    python tools/make_proxies.py "D:/video/MVI_0106.mp4" --height 540
    python tools/make_proxies.py "Concert4.veproj" --check

--check measures a random seek against the original and the proxy, so
you can see what it buys before transcoding everything.
"""

import argparse
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import effects  # noqa: F401


def video_paths(target: str):
    """Sources for a project, or just the file itself."""
    if target.lower().endswith('.veproj'):
        from core.project_io import load_project
        project = load_project(target)
        paths = []
        for clip in project.clips.values():
            if clip.has_video and clip.filepath not in paths:
                paths.append(clip.filepath)
        return paths
    return [target]


def check_seeks(path: str, height: int, tries: int = 8):
    """Time random seeks against the original and its proxy."""
    from media.decoder import VideoDecoder
    from core.proxy import has_proxy

    print(f"\n{os.path.basename(path)}")
    random.seed(7)

    original = VideoDecoder(path, use_proxy=False)
    frames = [random.randint(60, max(120, original.frame_count - 60))
              for _ in range(tries)]

    def timed(dec):
        dec._cached_frame_idx = -1
        t0 = time.perf_counter()
        for f in frames:
            dec.get_frame(f)
            dec._cached_frame_idx = -1      # force a real seek
            dec._last_frame_idx = -1
        return (time.perf_counter() - t0) / len(frames) * 1000

    ms_src = timed(original)
    print(f"  original {original.width}x{original.height}: "
          f"{ms_src:7.1f} ms per seek")

    if not has_proxy(path, height):
        print("  proxy: not built yet")
        return
    proxy = VideoDecoder(path, use_proxy=True)
    ms_proxy = timed(proxy)
    print(f"  proxy    {proxy.width}x{proxy.height}: "
          f"{ms_proxy:7.1f} ms per seek   -> {ms_src / max(ms_proxy, 0.01):.1f}x faster")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('target', help='a .veproj file, or one video file')
    ap.add_argument('--height', type=int, default=540,
                    help='proxy height in pixels (default 540)')
    ap.add_argument('--check', action='store_true',
                    help='measure seek times instead of building')
    ap.add_argument('--overwrite', action='store_true',
                    help='rebuild proxies that already exist')
    args = ap.parse_args(argv)

    from core.proxy import (generate_proxy, has_proxy, proxy_path,
                            pick_encoder, CACHE_DIR)

    paths = video_paths(args.target)
    print(f"{len(paths)} video source(s)")

    if args.check:
        for path in paths:
            if os.path.exists(path):
                check_seeks(path, args.height)
            else:
                print(f"\n{os.path.basename(path)}: MISSING")
        return 0

    print(f"encoder: {pick_encoder()}   ->  {CACHE_DIR}\n")
    total_started = time.time()

    for i, path in enumerate(paths, 1):
        name = os.path.basename(path)
        if not os.path.exists(path):
            print(f"[{i}/{len(paths)}] {name}: MISSING")
            continue
        if has_proxy(path, args.height) and not args.overwrite:
            print(f"[{i}/{len(paths)}] {name}: already built")
            continue

        started = time.time()
        last = [-1]

        def show(pct, n=name, idx=i):
            if pct != last[0]:
                last[0] = pct
                print(f"\r[{idx}/{len(paths)}] {n}: {pct}%",
                      end='', flush=True)

        try:
            out = generate_proxy(path, args.height, progress=show,
                                 overwrite=args.overwrite)
            size_mb = out.stat().st_size / 1e6 if out else 0
            print(f"\r[{i}/{len(paths)}] {name}: done in "
                  f"{time.time() - started:.0f}s ({size_mb:.0f} MB)      ")
        except KeyboardInterrupt:
            print("\ninterrupted — partial proxy discarded")
            partial = proxy_path(path, args.height).with_suffix('.partial.mp4')
            partial.unlink(missing_ok=True)
            return 1
        except Exception as e:
            print(f"\r[{i}/{len(paths)}] {name}: failed — {e}        ")

    print(f"\ntotal {time.time() - total_started:.0f}s")
    print("Preview and scrubbing will use these automatically; "
          "export still reads the originals.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
