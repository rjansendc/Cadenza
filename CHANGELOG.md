# Changelog

## Unreleased — 1.3.3

### Video

- **An image over a video shows again, on a machine with a GPU.**
  `ImageDecoder` handed back a CPU tensor while `VideoDecoder` put
  its frames on the compute device, so compositing the two raised
  `RuntimeError: Expected all tensors to be on the same device, but
  found at least two devices, cuda:0 and cpu!`. The compositor
  catches that, logs it and drops the clip — so the image silently
  vanished and the video beneath showed through, looking as though
  layer order were being ignored. Images now decode onto the compute
  device like everything else, and the compositor moves whatever a
  decoder hands it, so no future decoder can reintroduce it.

  It cannot happen without a GPU, where every tensor is on the CPU
  already. The tests stand a `meta` device in for a second one, so
  the mismatch is reproducible on any machine.

### Timeline and editing

- The preview re-composites when a clip is added or removed. It holds
  whatever was last composited and nothing redrew it when the clip
  list changed, so dropping an image onto a track above a video —
  with the playhead already inside where it landed — left the
  previous frame on screen, and the image looked as though it had
  been ignored in favor of the video below. Deleting a clip under the
  playhead left the deleted clip showing. The cached frame is dropped
  as well as the re-render requested, since a re-render alone returns
  the same stale composite. Undo has always done this; drop and
  delete did not.

## 1.3.2 — 2026-10-20

### Interface

- The toolbar and transport icons are drawn larger: the select and
  razor tools at 32px, the transport arrows at 24px. The icons are
  multi-resolution `.ico` files carrying 32px and above, so these
  render from a bigger bitmap rather than stretching a 16px one. The
  transport strip and its buttons grew with them, since an icon the
  size of its button leaves the hover square cropping the art.
- The Select tool's icon is a white arrow with a dark keyline rather
  than a blue one, matching the cursor it actually gives you. The
  razor's toolbar icon is the same file as its cursor, so the
  convention already held for one tool and not the other — selecting
  hands back the system arrow, which is white.
- **The ruler keeps following the playhead after the window is
  hidden.** It dropped its signal connections on `hideEvent` and
  nothing restored them, so the first time it was hidden — a
  minimize, a collapsed splitter, any layout change — it stopped
  tracking for the rest of the session. Scrubbing then moved the line
  through the tracks while the ruler's marker stayed where it was,
  catching up only when something else happened to repaint it.
  Present since 1.0.
- The playhead's arrowhead sits on its line. Its base ran x-5 to x+5,
  and a polygon's right edge is exclusive, so it filled the columns
  x-5 to x+4 — half a pixel left of the line.

## 1.3.1 — 2026-10-20

### Audio

- Fixed waveforms never starting after playback had run once. The
  waveform queue is held while playing, since decoding is disk-bound
  and the drives belong to video decode — but the hold was released
  in the play button's handler, and playback stops by routes that
  button never sees. Reaching the end of the timeline calls pause()
  straight from the video tick, and so does starting an export. So
  playing once to the end left the queue paused for the rest of the
  session: a dropped WAV reported "0V + 1A clips linked" and then
  drew nothing, with no message to say why. The hold now lives in the
  playback engine, which sees every stop. New in 1.3.0, where the
  queue was introduced.
- Shutting the queue down on exit no longer leaves it unusable. It is
  a module-level singleton that outlives the window which closed, and
  cancelling its work also left it permanently paused.
- **Importing audio now starts its waveform.** Peaks were computed
  only when a clip was placed on an audio track, so dropping a file
  into the media bin did nothing at all — no work started and nothing
  was said — and the wait landed later, on the edit. The read begins
  at import, one request per file (the queue reads every audio stream
  of a file in one pass), and the status bar reports it. By the time a
  clip is placed the peaks are cached and draw at once. Files already
  cached are not read again, and stills are skipped.
- Waveforms are now computed smallest file first. The cost of a
  waveform is the walk across its container, so a 10 MB WAV is done
  in moments while a 4K movie holds one of the two slots for as long
  as it takes to read the whole file. Taken in the order they were
  asked for, a WAV dropped after a movie drew nothing until the movie
  finished.
- Waveform progress is reported on each percent rather than every 50
  packets, which has nothing to do with how long a file takes to
  read. A three second WAV decodes into 36 packets, so it reported no
  percentage at all before jumping to the end — and 0% is now
  reported the moment the read starts, so a file being read never
  looks like one that has been forgotten. It also caps the updates:
  a five minute file used to fire 281 of them.
- The status bar says when a waveform is waiting its turn. The drop
  message is set after the clips are drawn, so it replaced the status
  the canvas had just put there: a file waiting behind larger ones
  reported only "Added: a.wav → 0V + 1A clips linked" and then sat
  unchanged, looking as though waveforms had stopped working.

### Color

- **Input LUT and White Balance now do something.** Both were
  declared in the effect and drawn in the Effects panel, but
  `apply_video` never read them: "As Shot", "Tungsten" and "Daylight"
  all produced byte-identical output. Input LUT now converts the
  transfer function — "Rec.709" reads the clip as Rec.709 and writes
  sRGB, which opens the shadows, and "sRGB" is the inverse. White
  Balance applies the correction for the light the footage was shot
  under, with "Auto" measuring the cast from the picture itself.
  "Daylight" is the reference the others are measured against, so it
  corrects by nothing — it is there to return to neutral.
- **Every Lumetri slider now has comparable authority.** At full
  travel they ranged from 8 levels of change out of 255 to 41, so
  most of the panel felt dead beside Exposure at 123. Measured on a
  reference frame, before and after:

  | control | was | now |
  |---|---|---|
  | Tint | 8.5 | 40.1 |
  | Shadows | 12.3 | 39.9 |
  | Highlights | 12.7 | 40.1 |
  | Temperature | 16.7 | 39.7 |
  | Vibrance | 19.4 | 39.9 |
  | Whites / Blacks | 22.9 | 40.0 |
  | Saturation | 23.8 | 40.0 |
  | Contrast | 40.9 | 40.1 |

  `tools/calibrate_lumetri.py` solves the constants, so a change to
  any control's curve can be rebalanced rather than guessed at.
  Exposure is left alone: it is measured in stops, and matching it to
  the others would mean a range of about a third of a stop — half a
  stop already moves a picture as much as a slider at full travel.
- **Tint is a hue shift rather than a dimmer.** It moved the green
  channel alone, and green carries 71% of the luminance, so Tint read
  as a brightness control with a color cast. Red and blue now move
  against green, weighted so the luminance green gives up is handed
  back: at ±80 the picture's brightness moves by under 2 levels where
  it used to move by 28.

  Clips already graded with Tint, Highlights, Shadows, Temperature,
  Vibrance, Whites, Blacks or Saturation will look different, since
  those controls now do what their numbers said.

### Export

- **In and out points.** Export's "In / Out points" option could not
  be selected: it was a disabled placeholder, and there was nothing
  behind it — Cadenza had no in or out points at all, no command, no
  keys, nothing on the ruler. The back half had been working the
  whole time, with `ExportConfig` carrying `start_frame` and
  `end_frame` and the exporter honoring both; nothing in the UI ever
  set them, so every export ran the full timeline.

  **I** marks in and **O** marks out at the playhead, as in Premiere,
  with Sequence ▸ Mark In / Mark Out / Clear In and Out for finding
  them without the keys (**Ctrl+Shift+X** clears). The ruler shows the
  span and dims what falls outside it, so what will be exported is
  plain without opening the dialog. The export dialog then offers the
  option with the span's length on it, and is preselected when one is
  marked.

  Out is exclusive, like a clip's out point, so marking in and out on
  the same frame exports one frame rather than none. One mark on its
  own is enough: an in point alone runs to the last clip, an out
  point alone from the start. Marking in past an existing out point
  drops the out point rather than refusing, the same as dragging a
  clip's left edge past its right.

### Timeline and editing

- **An audio clip can be linked to a video clip.** A link group needs
  something to link, but every drop was given a fresh group id and
  handed it to whatever it created — so a WAV dropped by itself ended
  up in a group of one, and a group id on its own reads as "linked"
  everywhere it is asked. After unlinking a movie, deleting its audio
  and bringing another WAV up to the video, right-clicking the audio
  offered Unlink while right-clicking the video offered Link: neither
  offered what was wanted and the two could not be joined.

  A single-clip drop is no longer given a group; a group emptied to
  one member by an unlink or a delete lets that member go; and the
  menu now asks whether the clicked clip has a partner rather than
  whether it carries an id, so projects already holding such a group
  read correctly. Linking fewer than two clips does nothing rather
  than making a group of one.

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
