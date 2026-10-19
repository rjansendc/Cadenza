# Changelog

## 1.3.0 — 2026-10-19

### Audio

- **Sync Refine now works on clips shorter than four minutes.** Three
  faults, all present since 1.0:
  - The analysis window was subtracted from the search region twice,
    once by the caller and again by the scan loop, so a scan only ran
    when the usable overlap exceeded twice the window. With the window
    capped at 120s, nothing under about four minutes could sync at
    all: it reported "No alignment found" however well the clips were
    already lined up. Long concert takes cleared the bar, which is why
    this went unnoticed.
  - The correlation envelope was built by keeping every hundredth
    sample of the correlation. A correlation peak is a spike a few
    samples wide, so this kept it only when it happened to land on a
    boundary, and the refine step then searched around whatever the
    smoothed remainder peaked at. Dense music and speech survived it —
    their correlation has a broad pedestal around the true lag that
    is still visible at one sample in a hundred — but sharply
    transient audio has no pedestal, and a clip two frames out could
    be "corrected" by five seconds in the wrong direction. The
    envelope is now pooled over blocks, which cannot drop the spike.
  - The measured offset was converted to frames with `int()`, which
    truncates toward zero. An exact 45 frame offset measures as
    -1.50150s where the true value is -1.501502s, so the whole frame
    was discarded and every correction came back one frame short. It
    now rounds.

  Offsets up to five seconds — more than an eyeball alignment is ever
  out by — are now exact, on speech, music, and transients alike.

- **Two clips can no longer hold the same frames on one track.** A
  clip dropped or dragged onto occupied timeline moves to the nearest
  track with room, keeping the time it was put at; if every track of
  its kind is busy across that span, the move is refused and the
  status bar says so. Stacked clips were only recoverable by undo,
  and nothing on screen said which of the two was being heard or
  seen.

  A same-track drag was already refused, but the check consulted the
  clip's own timeline row — the timeline gives each row its own
  graphics scene — so it compared the destination track against clips
  in the *source* row, matched nothing, and let the clip land on top.
  Cross-track drags were never checked at all.

- A file dropped onto a video track no longer puts its audio on top of
  audio that is already there. Pulling a camera angle into V1 while A1
  and A2 held WAVs placed the angle's audio on A1 regardless. Its
  audio streams now take the first tracks with room over the clip's
  own span — A1 is still used when it is free, including when it is
  busy elsewhere in the timeline. A drop on an audio row still starts
  from the track named, and moves down from there only if it is
  occupied.
- A dropped file with more streams than the sequence has tracks no
  longer loses the extras. Placement stopped at the last existing
  track, so a four-stream recording dropped into the default
  three-track sequence silently lost its fourth stream — and six
  camera angles stacked at one timecode need six video tracks. Newly
  imported media now grows the sequence rather than being refused,
  and the status bar says how many tracks were added. Moving a clip
  that already has a home does not grow anything.
- Fixed a crash while waveforms were being computed, introduced by the
  per-stream change below: the request path still asked the canvas for
  two progress handlers that had been removed with the old code, so
  every progress signal from every stream raised
  `AttributeError: 'TrackCanvas' object has no attribute
  '_on_waveform_progress'` and no waveform progress was reported.
- Closing the window while waveforms are still being computed no
  longer leaves threads running into shutdown
  (`QThread: Destroyed while thread '' is still running`, which on
  Windows can take the exit with it). Outstanding work is abandoned
  rather than waited out — a waveform is recomputed or read from
  cache next time. `compute_peaks` takes a separate cancel hook,
  asked on every decoded frame: progress is only reported every 50,
  and a long recording decodes as a handful of large frames, so a
  cancel riding on the progress callback went unseen.
- Every audio stream of a file is now read in one pass. Decoding a
  stream makes the demuxer walk the whole container, past every video
  packet, so the cost tracks the file's size and not its audio:
  measured at 20x the time for the same 30 seconds of audio inside a
  1941 MB 1080p file as from a 0.5 MB audio file. Computing one
  stream at a time meant a four-stream recording was read four times
  over — for a 4K movie, four passes across tens of gigabytes. Peaks
  for all of a file's streams are computed and cached together, so
  the requests that arrive as the other tracks' rows are built are
  answered from that pass.
- Peaks are folded into their buckets as the samples arrive, instead
  of the whole decoded stream being held in memory and bucketed at
  the end — 115 MB per five minutes, about 2.8 GB for a two-hour
  stereo stream, which reading four streams together would have
  multiplied by four. Memory is now the bucket count whatever the
  recording's length. A container that reports no duration at all
  still holds its samples, since bucketing as they arrive needs the
  length in advance.
- Waveforms now span the whole clip. Buckets were sized by a floored
  chunk width, which dropped up to one bucket's worth of samples off
  the end of every stream — measured between 0.05% and 0.26% of the
  file, drawing the waveform very slightly compressed against the
  clip it belongs to (under 3px on an 1145px timeline).
- Waveforms are computed per audio stream rather than per file. A
  multitrack recording drew its first stream's waveform on every track
  while each track played its own audio; each now shows its own. Peak
  caches are keyed by stream, and existing caches stay valid — the
  first stream keeps its original cache entry.

### Timeline and editing

- There is always somewhere to drop a clip past the end of a full
  timeline. The empty room past the last clip was a fixed 900 frames,
  which is a shrinking share of the ruler as a project grows: on an
  hour-long timeline zoomed to fit it came to under 1% of the width —
  about nine pixels — so a full timeline looked like it had no room
  left. It is now a quarter of whatever is on screen, which holds at
  every zoom and in both directions: zoomed in tight it is a few
  frames rather than 900, which used to be seven screens of empty
  timeline to scroll back over.
- Renamed **Scale to Frame Size** to **Set to Frame Size**, matching
  Premiere. Cadenza sets the clip's Scale property and keeps the source
  at full resolution, which is what Premiere calls Set to Frame Size;
  its Scale to Frame Size conforms the source and reads 100%. Behavior
  is unchanged — a 4K clip in an HD sequence reads 50%, leaving a true
  1:1 push-in available.
- Fitting a clip from the clip's right-click menu now updates the
  Effects panel. It did not, so the Scale box kept its previous value
  and the next nudge of its arrows wrote that stale number back to the
  clip, throwing the picture to whatever it had been before.
- Made Set to Frame Size undoable from both menus, restoring scale,
  position, and anchor together.

### Source

- Changed British spellings to American throughout the source,
  comments, and website: `centre_anchor` is now `center_anchor`, and
  "Export cancelled" and "Unrecognised project version" — the two
  messages a user could see — now read "canceled" and "Unrecognized".
  No behavior changed.

## 1.2.0 — 2026-10-19

Changes from the original 1.1 source to the shared Windows/Linux 1.2 release.
The application version remains `1.2.0` across both platforms.

### Timeline and editing

- Replaced project-length-dependent zoom with an absolute pixels-per-frame
  scale. Adding, stretching, or deleting clips no longer rescales the timeline
  or makes existing clips jump. Zoom to Fit remains an explicit action.
- Corrected zoom anchoring at the playhead and prevented hidden view scrolling
  from moving clips out of alignment with the ruler.
- Made both trim edges reachable on narrow clips. Trim handles take priority
  over opacity controls, so stretching a short clip does not move it instead.
- Allowed still images to extend from either edge without footage-style source
  limits. Left trims stop at the beginning of the timeline.
- Made linked video/audio trims update the linked clips together and recorded
  each trim drag as one undo step.
- Preserved effects, grades, motion settings, and automation on both halves of
  a razor cut, with the right half's keyframes retimed to the cut.
- Fixed whole-curve volume, opacity, and pan adjustments on keyframed clips,
  preserving the curve's shape within the parameter's limits.
- Fixed track row mapping and clip drops when adding tracks beyond the default
  three video and three audio tracks.
- Disconnected obsolete timeline rows during refresh to avoid callbacks into
  deleted graphics objects.

### Projects and interface

- Added **File > Close Project** (`Ctrl+W`), clearing the current project,
  media bin, timeline, and preview while keeping the editor open.
- Added Save, Discard, and Cancel prompts when closing a dirty project or
  quitting. Cancelling Save As also cancels the close.
- Expanded unsaved-change tracking to undoable edits and changes such as
  adding tracks, changing sequence settings, and toggling track controls.
  Undoing back to the saved undo position clears the dirty indicator.
- Added Open Recent and remembered folders for project, media, XML, and
  export dialogs.
- Changed the media bin to compact single-line rows with useful type,
  resolution, and duration summaries; audio no longer displays `0x0`.
- Saved all sequences and the active sequence selection instead of only the
  open sequence. Older project files with a single sequence remain readable.
- Updated the monitor and compositor when opening or changing a sequence so
  portrait, 4K, and other frame sizes use the correct preview dimensions.
- Renamed the existing sequence-settings action to describe what it does.
- Centralized the application version in `core/version.py`, used by the title,
  About dialog, saved-project metadata, and generated Windows version resource.
- Improved errors for unrecognized project-format versions and fixed the XML
  import command's project-saving path.

### Preview and export

- Fixed still-image decoding through the preview compositor.
- Preserved lower video tracks around scaled, moved, rotated, or cropped
  overlays instead of covering them with black padding.
- Fixed CPU rendering paths that previously tried to allocate CUDA tensors.
  NVIDIA acceleration remains available when supported.
- Made export default to the sequence's dimensions and retain its frame rate,
  audio sample rate, and channel count. Added custom export dimensions.
- Preserved aspect ratio with letterboxing or pillarboxing when exporting to
  a different frame shape instead of stretching the picture.
- Fixed exports at widths that require padded FFmpeg frame rows, including
  portrait sizes.
- Corrected RGB-to-YUV export conversion and color metadata: BT.709 for HD
  and BT.601 for SD, avoiding shifts in saturated colors.
- Remembered each project's export path, suggested filenames from sequence
  names, and added overwrite confirmation for existing output files.
- Reduced repeated decode and compositing error messages to one report per
  problem rather than flooding the console on every frame.

### Linux distribution and validation

- Added a Linux PyInstaller build alongside the existing Windows spec, using
  the same application source and version.
- Added local environment setup, launch, and build scripts. Linux releases
  include Qt, FFmpeg, PortAudio, PyAV, PyTorch, and CUDA 12.1 runtime libraries;
  the host supplies the NVIDIA driver and desktop graphics/audio services.
- Added Linux runtime setup for bundled libraries and host audio/font
  configuration, plus portable archives, checksums, and build provenance.
- Added `--smoke-test` diagnostics covering GUI creation, six PNG stills,
  stable zoom, project save/load, preview, audio, FFmpeg, software/NVENC export,
  and Close Project.
- Expanded regression coverage. Validation for this release: **387 tests
  passed, 15 skipped**, plus standalone CPU/GPU and relocated-archive checks
  on Ubuntu 22.04 x86_64.

## 1.1 — comparison baseline

The original `VideoEditor.zip` supplied for the Linux port is the baseline
for this changelog. Its editor Python modules match Git commit `cc8c7c7`.
It already included multi-track editing, audio sync, effects and keyframes,
image clips, proxies, cross dissolves, project save/load, Premiere/FCP XML
interchange, and NVIDIA export. These are existing features, not 1.2 additions.

Earlier release dates and changes are not reconstructed here.
