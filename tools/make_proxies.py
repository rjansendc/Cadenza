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


def _run_parallel(paths, args, total_started):
    """
    Transcode several files at once. NVDEC and NVENC handle multiple
    streams, and sources on different drives read in parallel, so the
    wall clock drops well below the sum of the parts.
    """
    import threading
    import time as _time
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    from core.proxy import generate_proxy, DEFAULT_GOP

    print(f"transcoding {args.jobs} at a time — Ctrl+C is safe, "
          f"finished files are kept\n")

    status = {os.path.basename(p): 0 for p in paths}
    lock = threading.Lock()

    def build(path):
        name = os.path.basename(path)
        started = _time.time()

        def show(pct, n=name):
            with lock:
                status[n] = pct

        out = generate_proxy(
            path, args.height, overwrite=args.overwrite, progress=show,
            gop=1 if args.intra else DEFAULT_GOP,
            qp=30 if args.fast else 27)
        with lock:
            status[name] = 100
        return path, out, _time.time() - started

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(build, p): p for p in paths}
        pending = set(futures)
        try:
            while pending:
                finished, pending = wait(pending, timeout=2.0,
                                          return_when=FIRST_COMPLETED)
                for future in finished:
                    try:
                        path, out, elapsed = future.result()
                        size_mb = out.stat().st_size / 1e6 if out else 0
                        print(f"\r{os.path.basename(path)}: done in "
                              f"{elapsed:.0f}s ({size_mb:.0f} MB)"
                              f"{' ' * 30}")
                    except Exception as e:
                        print(f"\rfailed: {e}{' ' * 30}")

                with lock:
                    live = ', '.join(
                        f"{n} {pct}%" for n, pct in status.items()
                        if 0 < pct < 100)
                if live:
                    mins = (_time.time() - total_started) / 60
                    print(f"\r  {live}  |  {mins:.1f} min elapsed",
                          end='', flush=True)
        except KeyboardInterrupt:
            print("\nstopping — finished files are kept")
            from core.proxy import cancel_all
            cancel_all()                      # kill the ffmpeg children
            for f in pending:
                f.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            return 1

    print(f"\ntotal {_time.time() - total_started:.0f}s")
    print("Preview and scrubbing will use these automatically; "
          "export still reads the originals.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('target', help='a .veproj file, or one video file')
    ap.add_argument('--height', type=int, default=540,
                    help='proxy height in pixels (default 540)')
    ap.add_argument('--check', action='store_true',
                    help='measure seek times instead of building')
    ap.add_argument('--overwrite', action='store_true',
                    help='rebuild proxies that already exist')
    ap.add_argument('--rate', action='store_true',
                    help='transcode a 60s sample and estimate the '
                         'full job, without building anything')
    ap.add_argument('--jobs', type=int, default=2, metavar='N',
                    help='files to transcode at once (default 2). '
                         'Sources on separate drives overlap well')
    ap.add_argument('--fast', action='store_true',
                    help='360p, lower quality — quickest to build')
    ap.add_argument('--intra', action='store_true',
                    help='every frame a keyframe: fastest seeks, '
                         'biggest files and slowest to build')
    ap.add_argument('--all', action='store_true',
                    help='include 1080p and smaller sources too '
                         '(by default only 4K and up get proxies)')
    args = ap.parse_args(argv)

    from core.proxy import (generate_proxy, has_proxy, proxy_path,
                            pick_encoder, needs_proxy, CACHE_DIR)

    if args.fast:
        args.height = min(args.height, 360)

    paths = video_paths(args.target)
    print(f"{len(paths)} video source(s)")

    if not args.all and not args.check:
        big = [p for p in paths
               if os.path.exists(p) and needs_proxy(p, args.height)]
        skipped = len(paths) - len(big)
        if skipped:
            print(f"{skipped} at 1080p or smaller — already seek "
                  f"quickly, skipping (use --all to include them)")
        paths = big

    if args.rate:
        from core.proxy import measure_rate, ffmpeg_path, DEFAULT_GOP
        if not ffmpeg_path():
            print("ffmpeg not on PATH — the slower PyAV path would "
                  "be used")
            return 1
        print("timing a 60 second sample per file...\n")
        total = 0.0
        for path in paths:
            if not os.path.exists(path):
                continue
            r = measure_rate(path, args.height,
                             gop=1 if args.intra else DEFAULT_GOP,
                             qp=30 if args.fast else 27)
            if not r:
                print(f"{os.path.basename(path)}: sample failed")
                continue
            total += r['estimate_minutes']
            print(f"{os.path.basename(path)}: {r['speed']:.1f}x real "
                  f"time, {r['source_hours']:.1f}h source "
                  f"-> about {r['estimate_minutes']:.0f} min")
        if total:
            print(f"\nwhole job: about {total:.0f} min at one file at "
                  f"a time, less in parallel")
        return 0

    if args.check:
        for path in paths:
            if os.path.exists(path):
                check_seeks(path, args.height)
            else:
                print(f"\n{os.path.basename(path)}: MISSING")
        return 0

    print(f"encoder: {pick_encoder()}   ->  {CACHE_DIR}")

    todo = [p for p in paths
            if os.path.exists(p)
            and (args.overwrite or not has_proxy(p, args.height))]
    hours = 0.0
    for path in todo:
        try:
            import av
            with av.open(path) as c:
                hours += (c.duration or 0) / 1e6 / 3600
        except Exception:
            pass
    if hours:
        print(f"{len(todo)} file(s) to build, {hours:.1f} hours of "
              f"footage — every frame has to be read and re-encoded")
    print()
    total_started = time.time()

    if args.jobs > 1 and len(todo) > 1:
        return _run_parallel(todo, args, total_started)

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

        def show(pct, n=name, idx=i, t0=started):
            if pct != last[0]:
                last[0] = pct
                elapsed = time.time() - t0
                eta = (elapsed / pct * (100 - pct)) if pct else 0
                print(f"\r[{idx}/{len(paths)}] {n}: {pct}%  "
                      f"{elapsed:.0f}s elapsed, ~{eta:.0f}s left   ",
                      end='', flush=True)

        try:
            print(f"[{i}/{len(paths)}] {name}")
            from core.proxy import DEFAULT_GOP
            out = generate_proxy(path, args.height, progress=show,
                                 overwrite=args.overwrite, verbose=True,
                                 gop=1 if args.intra else DEFAULT_GOP,
                                 qp=30 if args.fast else 27)
            size_mb = out.stat().st_size / 1e6 if out else 0
            elapsed = time.time() - started
            frames = 0
            try:
                import av
                with av.open(str(out)) as c:
                    frames = c.streams.video[0].frames or 0
            except Exception:
                pass
            rate = f", {frames / elapsed:.0f} fps" if frames and elapsed else ""
            print(f"\r[{i}/{len(paths)}] {name}: done in "
                  f"{elapsed:.0f}s ({size_mb:.0f} MB{rate})            ")
        except KeyboardInterrupt:
            print("\nstopping — partial proxy discarded")
            from core.proxy import cancel_all
            cancel_all()
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
