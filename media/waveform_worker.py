from PySide6.QtCore import QThread, QObject, Signal


class WaveformWorker(QThread):
    """
    Background thread for waveform peak computation.
    Emits progress and completion signals.
    """

    progress  = Signal(str, int)    # filepath, percent
    completed = Signal(str, object) # filepath, peaks array

    def __init__(self, filepath: str, parent=None):
        super().__init__(parent)
        self.filepath = filepath

    def run(self):
        # lower priority so video decode wins
        self.setPriority(
            QThread.Priority.LowPriority
        )
        """Runs in background thread."""
        from media.waveform import compute_peaks

        def on_progress(pct: int):
            self.progress.emit(self.filepath, pct)

        peaks = compute_peaks(
            self.filepath,
            num_peaks=4000,
            progress_callback=on_progress
        )
        self.completed.emit(self.filepath, peaks)


class _WaveformQueue(QObject):
    """
    Runs waveform decoding a couple of files at a time.

    Waveforms are disk-bound, not CPU-bound: each worker reads a whole
    source file end to end. Importing a concert project means 20-plus
    media files, and starting a thread for each pins the drives at 100%,
    starving the video decoder. Playback syncs video to the audio clock,
    so a stalled read shows up as drift and then a skip.

    Same total work, done two at a time, with the queue held while
    playback runs.
    """

    MAX_CONCURRENT = 2

    def __init__(self):
        super().__init__()
        self._pending   = []     # filepaths waiting their turn
        self._workers   = {}     # filepath -> running worker
        self._retired   = {}     # kept alive until the thread finishes
        self._callbacks = {}     # filepath -> [(completed, progress)]
        self._paused    = False

    # ── public ────────────────────────────────────────────────

    def submit(self, filepath: str, completed=None, progress=None):
        """
        Ask for a file's peaks. Callbacks fire on the main thread.
        Asking twice for the same file joins the existing job.
        """
        self._callbacks.setdefault(filepath, []).append(
            (completed, progress))
        if filepath in self._workers:
            return                      # already decoding
        if filepath not in self._pending:
            self._pending.append(filepath)
        self._drain()

    def pause(self):
        """Stop starting new jobs — the disk belongs to playback."""
        self._paused = True

    def resume(self):
        self._paused = False
        self._drain()

    @property
    def busy(self) -> bool:
        return bool(self._workers or self._pending)

    # ── internals ─────────────────────────────────────────────

    def _drain(self):
        while (not self._paused
               and len(self._workers) < self.MAX_CONCURRENT
               and self._pending):
            fp = self._pending.pop(0)
            worker = WaveformWorker(fp)
            worker.progress.connect(self._on_progress)
            worker.completed.connect(self._on_completed)
            worker.finished.connect(
                lambda f=fp: self._retired.pop(f, None))
            self._workers[fp] = worker
            worker.start()

    def _on_progress(self, filepath: str, pct: int):
        for _completed, progress in self._callbacks.get(filepath, []):
            if progress is not None:
                progress(filepath, pct)

    def _on_completed(self, filepath: str, peaks):
        worker = self._workers.pop(filepath, None)
        if worker is not None:
            # hold a reference until the thread has actually finished,
            # or Qt may delete a QThread that is still running
            self._retired[filepath] = worker
        for completed, _progress in self._callbacks.pop(filepath, []):
            if completed is not None:
                completed(filepath, peaks)
        self._drain()


waveform_queue = _WaveformQueue()
