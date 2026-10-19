# Changelog

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
