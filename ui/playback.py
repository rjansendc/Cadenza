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

        # video timer
        self._interval = int(1000.0 / fps)
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
        self._mixer.seek(frame, prime=prime)

    @property
    def is_playing(self) -> bool:
        return self._playing

    # =========================================================
    # Video tick — keep this FAST
    # =========================================================

    def _on_tick(self):
        # use audio mixer as master clock
        # video syncs to audio position
        if self._mixer and self._mixer.is_alive():
            # audio frame = ground truth position
            audio_frame = self._mixer._mix_frame
            video_frame = self.app_state.playhead_frame
            drift = audio_frame - video_frame

            if drift > 10:
                # video too far behind — skip ahead
                frame = audio_frame
            elif drift < -5:
                # video ahead of audio — wait
                return
            else:
                # in sync — advance normally
                frame = video_frame
        else:
            frame = self.app_state.playhead_frame

        if frame >= self.app_state.total_frames:
            self.pause()
            return

        # composite video frame
        if self._compositor and self._clips:
            try:
                tensor = self._compositor.composite_frame(
                    self._clips, frame,
                    sequence=self.sequence,
                    use_cache=True
                )
                self.frame_ready.emit(tensor)
            except Exception as e:
                print(f"Video error frame {frame}: {e}")

        self.app_state.playhead_frame = frame + 1

    # =========================================================
    # Cleanup
    # =========================================================

    def close(self):
        self.stop()
        self._mixer.close()
        if self._compositor:
            self._compositor.close()
