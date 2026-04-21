"""
Sync Refine — refines eyeball alignment using FFT cross-correlation.

Strategy:
1. Find the timeline overlap between reference and clip
2. Skip edges, find a region with good signal in both (not muted/silent)
3. Extract audio from that region from both source files
4. FFT cross-correlate with ±30s search window
5. Peak = fine offset correction
6. Optionally plot the correlation curve

Requires: scipy, numpy, matplotlib (for plot)
"""

from __future__ import annotations
import numpy as np
from typing import List, Dict, Optional, Tuple
from core.clip import Clip


def _extract_audio(filepath: str,
                   start_seconds: float,
                   duration_seconds: float,
                   sample_rate: int = 8000) -> Optional[np.ndarray]:
    """
    Extract audio from filepath starting at start_seconds for duration_seconds.
    Returns normalised float32 array or None on failure.
    """
    try:
        import av

        container = av.open(filepath)
        streams = container.streams.audio
        if not streams:
            return None

        stream = streams[0]

        if start_seconds > 0:
            pts = int(start_seconds / float(stream.time_base))
            container.seek(pts, stream=stream, backward=True)

        resampler = av.AudioResampler(
            format='fltp', layout='mono', rate=sample_rate
        )

        chunks = []
        total = 0
        max_samples = int(duration_seconds * sample_rate)

        for frame in container.decode(stream):
            for r in resampler.resample(frame):
                arr = r.to_ndarray()[0].copy()
                chunks.append(arr)
                total += len(arr)
                if total >= max_samples:
                    break
            if total >= max_samples:
                break

        container.close()

        if not chunks:
            return None

        audio = np.concatenate(chunks)[:max_samples].astype(np.float32)
        peak = np.abs(audio).max()
        if peak > 0:
            audio /= peak
        return audio

    except Exception as e:
        print(f"[Sync] Audio extract error: {e}")
        return None


def _rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(audio ** 2)))


def _find_best_signal_window(
        ref_clip: Clip,
        cmp_clip: Clip,
        overlap_start_tl: float,   # timeline seconds
        overlap_end_tl: float,
        window_size: float,
        fps: float,
        sample_rate: int = 8000,   # 8kHz is sufficient for sync accuracy
        silence_threshold: float = 0.01
) -> Optional[Tuple[float, float]]:
    """
    Slide through the overlap region and find the window with the
    best (loudest) signal in BOTH clips simultaneously.

    Returns (ref_source_sec, cmp_source_sec) for the best window,
    or None if no good window found.
    """
    ref_fps = ref_clip.source_fps or fps
    cmp_fps = cmp_clip.source_fps or fps

    # Test just 8 evenly-spaced candidate positions through the overlap
    available = overlap_end_tl - window_size - overlap_start_tl
    if available <= 0:
        return None
    num_candidates = min(8, max(1, int(available / 30)))
    step = available / num_candidates if num_candidates > 1 else available

    best_rms = -1.0
    best_ref_src = None
    best_cmp_src = None

    pos = overlap_start_tl
    while pos + window_size <= overlap_end_tl:
        # Convert timeline position to source file positions
        ref_src = (ref_clip.in_point / ref_fps) + (pos - ref_clip.start_frame / fps)
        cmp_src = (cmp_clip.in_point / cmp_fps) + (pos - cmp_clip.start_frame / fps)

        print(f"[Sync]   scan pos={pos:.1f}s → ref_src={ref_src:.1f}s cmp_src={cmp_src:.1f}s")
        if ref_src < 0 or cmp_src < 0:
            print(f"[Sync]   skipping negative source position")
            pos += step
            continue

        # Sample 2 seconds of audio to check RMS
        probe_dur = 2.0
        ref_probe = _extract_audio(ref_clip.filepath, ref_src, probe_dur, sample_rate)
        cmp_probe = _extract_audio(cmp_clip.filepath, cmp_src, probe_dur, sample_rate)

        if ref_probe is None or cmp_probe is None:
            pos += step
            continue

        ref_rms = _rms(ref_probe)
        cmp_rms = _rms(cmp_probe)

        # Both must be above silence threshold
        if ref_rms < silence_threshold or cmp_rms < silence_threshold:
            print(f"[Sync]   t={pos:.0f}s: skipping (RMS ref={ref_rms:.4f} cmp={cmp_rms:.4f} — too quiet)")
            pos += step
            continue

        # Score = minimum of the two RMS values (weakest link)
        score = min(ref_rms, cmp_rms)
        print(f"[Sync]   t={pos:.0f}s: RMS ref={ref_rms:.4f} cmp={cmp_rms:.4f} score={score:.4f}")

        if score > best_rms:
            best_rms = score
            best_ref_src = ref_src
            best_cmp_src = cmp_src

        pos += step

    if best_ref_src is None:
        return None

    return (best_ref_src, best_cmp_src)


def sync_clips_to_reference(
        reference_clip: Clip,
        clips_to_align: List[Clip],
        sample_rate: int = 8000,
        fps: float = 29.97,
        search_seconds: float = 90.0,
        analysis_seconds: float = 120.0,
        channel: int = 0,
        progress_fn=None,
        show_plot: bool = True
) -> Dict[str, int]:
    """
    Refine eyeball alignment using FFT cross-correlation.
    Returns {clip_id: frame_offset_correction}.
    """
    results: Dict[str, int] = {}
    total = len(clips_to_align)

    for i, clip in enumerate(clips_to_align):
        if progress_fn:
            progress_fn(f"Refining {clip.name}...", i + 1, total + 1)

        print(f"\n[Sync] === Refining: {clip.name} ===")
        print(f"[Sync] Reference: {reference_clip.name} "
              f"start={reference_clip.start_frame} "
              f"duration={reference_clip.duration} "
              f"track={reference_clip.track}")
        print(f"[Sync] Clip:      {clip.name} "
              f"start={clip.start_frame} "
              f"duration={clip.duration} "
              f"track={clip.track}")

        ref_fps = reference_clip.source_fps or fps
        cmp_fps = clip.source_fps or fps

        # --- Step 1: Find source file overlap ---
        # Use source file time ranges (in_point to out_point),
        # not timeline positions. This works even after razor
        # cuts and repositioning.
        ref_fps_l = reference_clip.source_fps or fps
        cmp_fps_l = clip.source_fps or fps

        ref_src_start = reference_clip.in_point / ref_fps_l
        ref_src_end   = (reference_clip.in_point +
                         reference_clip.duration) / ref_fps_l
        cmp_src_start = clip.in_point / cmp_fps_l
        cmp_src_end   = (clip.in_point +
                         clip.duration) / cmp_fps_l

        # For cross-camera sync, clips won't overlap in source.
        # Use the full clip durations as the search window instead.
        ref_dur = ref_src_end - ref_src_start
        cmp_dur = cmp_src_end - cmp_src_start
        overlap_dur = min(ref_dur, cmp_dur)

        print(f"[Sync] Ref source: {ref_src_start:.1f}s-{ref_src_end:.1f}s "
              f"({ref_dur:.1f}s)")
        print(f"[Sync] Cmp source: {cmp_src_start:.1f}s-{cmp_src_end:.1f}s "
              f"({cmp_dur:.1f}s)")
        print(f"[Sync] Usable overlap duration: {overlap_dur:.1f}s")

        if overlap_dur < 10.0:
            print(f"[Sync] Clips too short ({overlap_dur:.1f}s) for reliable sync")
            continue

        # Map source positions back to timeline for the scan window
        # ref timeline pos = start_frame/fps + (src_pos - in_point/fps)
        ref_tl_start = (reference_clip.start_frame / fps +
                        ref_src_start - reference_clip.in_point / ref_fps_l)
        ref_tl_end   = (reference_clip.start_frame / fps +
                        ref_src_end   - reference_clip.in_point / ref_fps_l)
        cmp_tl_start = (clip.start_frame / fps +
                        cmp_src_start - clip.in_point / cmp_fps_l)
        cmp_tl_end   = (clip.start_frame / fps +
                        cmp_src_end   - clip.in_point / cmp_fps_l)

        overlap_start = max(ref_tl_start, cmp_tl_start)
        overlap_end   = min(ref_tl_end,   cmp_tl_end)

        # If no timeline overlap, use ref clip's window for scanning
        if overlap_end - overlap_start < 10.0:
            overlap_start = ref_tl_start
            overlap_end   = ref_tl_end

        # --- Step 2: Usable window inside overlap ---
        # Skip edges (up to 20% each side, max 30s)
        edge_skip = min(30.0, overlap_dur * 0.2)
        sample_region_start = overlap_start + edge_skip
        sample_region_end   = overlap_end   - edge_skip
        available           = sample_region_end - sample_region_start
        window_size         = min(analysis_seconds, available)

        print(f"[Sync] Edge skip: {edge_skip:.1f}s, available window: {available:.1f}s, "
              f"using: {window_size:.1f}s")

        if window_size < 5.0:
            print(f"[Sync] Not enough usable overlap — try aligning clips closer")
            continue

        # --- Step 3: Find best signal window ---
        print(f"[Sync] Scanning for best signal...")
        window = _find_best_signal_window(
            reference_clip, clip,
            sample_region_start, sample_region_end - window_size,
            window_size, fps, 4000  # use low rate for fast signal scan
        )

        if window is None:
            print(f"[Sync] No good signal window found — check clip audio")
            continue

        ref_src, cmp_src = window
        print(f"[Sync] Best window: ref@{ref_src:.1f}s, clip@{cmp_src:.1f}s")

        # --- Step 4: Extract audio ---
        if progress_fn:
            progress_fn(f"Extracting audio for {clip.name}...", i + 1, total + 1)

        ref_audio = _extract_audio(reference_clip.filepath, ref_src,
                                    window_size, sample_rate)
        cmp_audio = _extract_audio(clip.filepath, cmp_src,
                                    window_size, sample_rate)

        if ref_audio is None or cmp_audio is None:
            print(f"[Sync] Failed to extract audio")
            continue

        print(f"[Sync] Extracted: ref={len(ref_audio)/sample_rate:.1f}s "
              f"cmp={len(cmp_audio)/sample_rate:.1f}s")

        # --- Step 5: FFT cross-correlation ---
        if progress_fn:
            progress_fn(f"Correlating {clip.name}...", i + 1, total + 1)

        try:
            from scipy.signal import fftconvolve

            corr     = fftconvolve(ref_audio, cmp_audio[::-1], mode='full')
            zero_lag = len(cmp_audio) - 1

            # Limit search to ±search_seconds
            max_s = int(search_seconds * sample_rate)
            lo    = max(0, zero_lag - max_s)
            hi    = min(len(corr), zero_lag + max_s + 1)

            search_corr = corr[lo:hi]

            # Envelope peak detection: smooth abs(corr) to find the
            # center of the correlation hill, then refine with raw corr
            # Envelope peak: downsample corr for fast Gaussian, map peak back
            from scipy.ndimage import gaussian_filter1d
            ds = 100  # downsample factor — 100x faster filter
            corr_ds = search_corr[::ds]
            sigma_ds = max(1, sample_rate // ds)  # 1s in downsampled space
            env_ds   = gaussian_filter1d(np.abs(corr_ds), sigma=sigma_ds)
            env_peak_ds = int(np.argmax(env_ds))
            # Map back to full-res and refine within ±1s window
            env_peak = env_peak_ds * ds
            refine_r = sample_rate  # ±1s in full-res samples
            lo_r = max(0, env_peak - refine_r)
            hi_r = min(len(search_corr), env_peak + refine_r + 1)
            peak_idx = lo_r + int(np.argmax(search_corr[lo_r:hi_r]))

            offset_samp = (lo + peak_idx) - zero_lag
            offset_secs = offset_samp / sample_rate
            frame_offset = int(offset_secs * fps)

            # Absolute recording offset:
            # At the sample window, ref is at ref_src seconds into its file
            # and cmp is at cmp_src seconds into its file.
            # The correlation says cmp audio leads ref by offset_secs.
            # So: cmp_file_time_at_same_moment = ref_src - offset_secs
            # Absolute offset = cmp recording started (cmp_src - offset_secs - ref_src) 
            #                   seconds after reference
            ref_fps_local = reference_clip.source_fps or fps
            cmp_fps_local = clip.source_fps or fps
            ref_in_secs   = reference_clip.in_point / ref_fps_local
            cmp_in_secs   = clip.in_point / cmp_fps_local

            # ref_src and cmp_src are the source file positions of the sample window
            # offset_secs: positive = cmp audio is ahead of ref = cmp recorded earlier
            # absolute offset = how much earlier cmp started vs ref in real time
            absolute_offset = (cmp_src - offset_secs) - ref_src
            abs_s   = abs(absolute_offset)
            abs_min = int(abs_s // 60)
            abs_sec = abs_s % 60
            abs_sign = '+' if absolute_offset >= 0 else '-'

            # Warn if peak is near the search boundary (result may be unreliable)
            boundary_pct = abs(offset_secs) / search_seconds
            if boundary_pct > 0.85:
                print(f"[Sync] WARNING: peak is near search boundary "
                      f"({abs(offset_secs):.1f}s of ±{search_seconds:.0f}s) "
                      f"— try moving clip closer before syncing")
            print(f"[Sync] Fine correction: {offset_secs:+.3f}s → {frame_offset:+d} frames")
            print(f"[Sync] Absolute offset between recordings: "
                  f"{abs_sign}{abs_min}m {abs_sec:.3f}s "
                  f"({absolute_offset:+.3f}s)")
            print(f"[Sync]   (positive = clip started recording later than reference)")

            results[clip.id] = frame_offset

            # --- Step 6: Plot ---
            if show_plot:
                _plot_correlation(
                    search_corr, sample_rate, search_seconds,
                    offset_secs, clip.name
                )

        except Exception as e:
            print(f"[Sync] Correlation error: {e}")
            import traceback; traceback.print_exc()

    return results


def _plot_correlation(corr: np.ndarray,
                      sample_rate: int,
                      search_seconds: float,
                      peak_offset: float,
                      clip_name: str):
    """Plot the correlation curve with the peak marked."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        plt.switch_backend('Agg')  # force Agg even if already imported
        import tempfile, os

        n = len(corr)
        times = np.linspace(-search_seconds, search_seconds, n)

        # Downsample FIRST, then compute envelope on small array
        max_pts = 4000
        step = max(1, len(corr) // max_pts)
        c_plot = corr[::step]
        t_plot = times[::step]

        # Envelope on downsampled data — fast
        from scipy.ndimage import gaussian_filter1d as _gf
        _sigma = max(1, len(c_plot) // 60)  # ~1/60th of plot width
        e_plot = _gf(np.abs(c_plot), sigma=_sigma)

        fig, ax = plt.subplots(figsize=(14, 5))
        ax.plot(t_plot, c_plot, color='#4a9fd4', linewidth=0.6,
                alpha=0.5, label='Correlation (raw)')
        ax.plot(t_plot, e_plot,  color='#f0a040', linewidth=1.5,
                label='Envelope (smoothed)')
        ax.plot(t_plot, -e_plot, color='#f0a040', linewidth=1.5, alpha=0.4)
        ax.axvline(peak_offset, color='#e05050', linewidth=2.0,
                   label=f'Peak: {peak_offset:+.3f}s')
        ax.axvline(0, color='#888888', linewidth=1.0, linestyle='--',
                   label='Zero lag (current alignment)')
        ax.set_xlabel('Offset (seconds)')
        ax.set_ylabel('Correlation')
        ax.set_title(f'Cross-correlation: {clip_name}  |  Peak offset: {peak_offset:+.3f}s')
        ax.legend()
        ax.grid(True, alpha=0.3)

        # Save to temp file and open with OS default viewer
        tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False,
                                          prefix='sync_correlation_')
        path = tmp.name
        tmp.close()
        fig.savefig(path, dpi=100)
        plt.close(fig)
        print(f"[Sync] Plot saved: {path}")
        os.startfile(path)  # Windows: opens with default image viewer

    except Exception as e:
        print(f"[Sync] Plot error: {e}")


def apply_sync_offsets(
        reference_clip: Clip,
        clips_to_align: List[Clip],
        offsets: Dict[str, int],
        project=None
) -> None:
    """
    Apply fine corrections to each clip's current position.
    offset > 0: clip audio leads reference → move clip right (+)
    offset < 0: clip audio lags reference → move clip left (-)
    """
    for clip in clips_to_align:
        offset = offsets.get(clip.id)
        if offset is None:
            continue

        new_start = clip.start_frame + offset

        print(f"[Sync] {clip.name}: "
              f"{clip.start_frame} + {offset:+d} = {max(0, new_start)}")

        if project and clip.link_group_id:
            for linked_clip in project.get_link_group(clip.id):
                linked_clip.start_frame = max(0, new_start)
        else:
            clip.start_frame = max(0, new_start)
