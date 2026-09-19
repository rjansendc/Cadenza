"""
ScrubWorker — composites scrub frames off the UI thread.

Dragging the playhead emits a position on every mouse move. Rendering
each one inline means a 4K seek per event on the UI thread, and the
events queue up faster than they can be served: the window stops
responding and the picture arrives a second or two after the mouse.

This keeps exactly one pending request — the newest position — and
throws away anything superseded while a frame is being made. The
picture then follows the mouse as fast as decoding allows, and never
builds a backlog.
"""

from PySide6.QtCore import QThread, Signal, QMutex, QWaitCondition


class ScrubWorker(QThread):

    frame_ready = Signal(object)     # composited tensor

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mutex   = QMutex()
        self._wait    = QWaitCondition()
        self._pending = None         # (frame, draft) or None
        self._running = True
        self._compositor = None
        self._clips      = []
        self._sequence   = None

    # ── from the UI thread ────────────────────────────────────

    def set_context(self, compositor, clips, sequence):
        self._mutex.lock()
        self._compositor = compositor
        self._clips      = clips
        self._sequence   = sequence
        self._mutex.unlock()

    def request(self, frame: int, draft: bool = False):
        """Ask for a frame, replacing any request not yet started."""
        self._mutex.lock()
        self._pending = (frame, draft)
        self._mutex.unlock()
        self._wait.wakeAll()

    def stop(self):
        self._mutex.lock()
        self._running = False
        self._mutex.unlock()
        self._wait.wakeAll()
        self.wait(2000)

    # ── worker thread ─────────────────────────────────────────

    def run(self):
        while True:
            self._mutex.lock()
            while self._running and self._pending is None:
                self._wait.wait(self._mutex)
            if not self._running:
                self._mutex.unlock()
                return
            frame, draft = self._pending
            self._pending = None
            compositor = self._compositor
            clips      = list(self._clips)
            sequence   = self._sequence
            self._mutex.unlock()

            if compositor is None or not clips:
                continue
            try:
                tensor = compositor.composite_frame(
                    clips, frame, sequence=sequence,
                    use_cache=False, draft=draft)
                self.frame_ready.emit(tensor)
            except Exception as e:
                print(f"Scrub error at frame {frame}: {e}")
