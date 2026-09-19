"""
PlaybackEngine — coordinates video and audio playback.

Video: QTimer fires at fps rate, compositor renders frame
Audio: AudioMixer thread fills ring buffer continuously
       AudioOutput reads from ring buffer in real-time
"""

from PySide6.QtCore import QObject, QTimer, Signal, Qt
from typing import List

from core.clip import Clip
from core.track import Sequence
from ui.app_state import AppState
from ui.ring_buffer import RingBuffer
from ui.audio_mixer import AudioMixer
from ui.audio_output import AudioOutput


class PlaybackEngine(QObject):

    frame_ready = Signal(object)   # torch.Tensor

    def __init__(self,
                 app_state: AppState,
                 sequence:  Sequence,
                 parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self.sequence  = sequence
        self._clips:   List[Clip] = []
        self._playing  = False
        self._prof_composite = 0.0
        self._prof_emit      = 0.0
        self._prof_frames    = 0
        self._compositor = None

        fps         = sequence.settings.fps
        sample_rate = sequence.settings.sample_rate
        channels    = sequence.settings.audio_channels

        # audio pipeline
        self._mixer = AudioMixer(
            sample_rate=sample_rate,
            channels=channels,
            fps=fps
        )
        self._output = AudioOutput(
            ring=self._mixer.ring,
            sample_rate=sample_rate,
            channels=channels,
            blocksize=4096   # larger block = more stable
        )

        # start mixer thread immediately
        self._mixer.start()

        # video timer. Oversampled: the tick decides which frame the
        # audio has reached rather than assuming one frame per tick,
        # so timer jitter stops accumulating into drift.
        self._interval = max(4, int(1000.0 / fps / 2))
        self._last_shown = -1
        self._timer    = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._on_tick)

    # =========================================================
    # Clip management
    # =========================================================

    def set_clips(self, clips: List[Clip],
                  sequence=None):
        """Update clip list."""
        self._clips = clips

        # Follow the current sequence. It was only passed to the mixer
        # before, so after opening a project the compositor still held
        # the sequence captured at startup — and anything read from it,
        # transitions included, was invisible during playback.
        if sequence is not None and sequence is not self.sequence:
            self.sequence = sequence
            if self._compositor is not None:
                self._compositor.sequence = sequence

        if self._compositor is None:
            from gpu.compositor import Compositor
            self._compositor = Compositor(self.sequence)
        # compositor caches renderers internally
        # no action needed here

        # pass sequence for mute/solo support
        seq = sequence or self.sequence
        self._mixer.set_clips(clips, seq)

    # =========================================================
    # Playback control
    # =========================================================

    def play(self):
        if self._playing:
            return

        if self._compositor is None:
            from gpu.compositor import Compositor
            self._compositor = Compositor(self.sequence)

        self._playing = True
        self._last_shown = -1
        frame = self.app_state.playhead_frame

        # start audio in background — non-blocking
        # mixer.play() does prefill in calling thread
        # but streaming decoder prime is fast (just seek)
        self._mixer.play(frame=frame)
        self._output.start()

        # start video timer
        self._timer.start(self._interval)

    def pause(self):
        if not self._playing:
            return
        self._playing = False
        self._timer.stop()
        self._mixer.pause()
        self._output.stop()

    def stop(self):
        self._playing = False
        self._timer.stop()
        self._mixer.pause()
        self._output.stop()
        self.app_state.playhead_frame = 0

    def toggle(self):
        if self._playing:
            self.pause()
        else:
            self.play()

    def seek(self, frame: int, prime: bool = True):
        self._last_shown = -1
        self._mixer.seek(frame, prime=prime)

    @property
    def is_playing(self) -> bool:
        return self._playing

    # =========================================================
    # Video tick — keep this FAST
    # =========================================================

    def _audio_play_frame(self):
        """
        The frame currently coming out of the speakers.

        _mix_frame is how far the mixer has MIXED, and the ring holds a
        couple of seconds beyond what has been heard — syncing video to
        it puts the picture seconds ahead of the sound.
        """
        if not (self._mixer and self._mixer.is_alive()):
            return None
        fps = self.sequence.settings.fps
        buffered_frames = self._mixer.ring.available_seconds * fps
        return self._mixer._mix_frame - buffered_frames

    def _on_tick(self):
        # The audio output position is the master clock: show whatever
        # frame it has reached, rather than advancing one frame per
        # tick and hoping the timer is exact.
        target = self._audio_play_frame()
        if target is None:
            frame = self.app_state.playhead_frame + 1
        else:
            frame = int(round(target))
            # never run backwards, and never stall completely
            if frame <= self._last_shown:
                if self._last_shown >= 0:
                    return
                frame = max(0, frame)

        if frame < 0:
            frame = 0

        if frame >= self.app_state.total_frames:
            self.pause()
            return

        self._last_shown = frame

        # composite video frame
        if self._compositor and self._clips:
            try:
                import os
                import time as _time
                profile = os.environ.get('CADENZA_PROFILE') == '1'
                t0 = _time.perf_counter() if profile else 0.0

                tensor = self._compositor.composite_frame(
                    self._clips, frame,
                    sequence=self.sequence,
                    use_cache=True
                )
                t1 = _time.perf_counter() if profile else 0.0
                self.frame_ready.emit(tensor)

                if profile:
                    self._prof_composite += (t1 - t0)
                    self._prof_emit += (_time.perf_counter() - t1)
                    self._prof_frames += 1
                    if self._prof_frames >= 60:
                        n = self._prof_frames
                        heard = self._audio_play_frame()
                        drift = (int(round(heard)) - frame
                                 if heard is not None else 0)
                        budget = 1000.0 / max(1e-6, self.sequence.settings.fps)
                        print(f"[video] composite "
                              f"{self._prof_composite / n * 1000:5.1f} ms | "
                              f"display {self._prof_emit / n * 1000:4.1f} ms | "
                              f"budget {budget:4.1f} ms | "
                              f"audio ahead by {drift} frames", flush=True)
                        self._prof_composite = 0.0
                        self._prof_emit = 0.0
                        self._prof_frames = 0
            except Exception as e:
                print(f"Video error frame {frame}: {e}")

        self.app_state.playhead_frame = frame

    # =========================================================
    # Cleanup
    # =========================================================

    def close(self):
        self.stop()
        self._mixer.close()
        if self._compositor:
            self._compositor.close()
