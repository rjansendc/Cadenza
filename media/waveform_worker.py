from PySide6.QtCore import QThread, QObject, Signal


class WaveformWorker(QThread):
    """
    Background thread computing every audio stream of one file.

    One thread per file, not per stream. Decoding a stream makes the
    demuxer walk the whole container, past every video packet, so the
    cost tracks the file's size rather than its audio — measured at
    20x the time for the same audio inside a 1080p file. A
    four-stream recording was read four times over, which for a 4K
    movie is four passes across tens of gigabytes.
    """

    progress  = Signal(str, int)      # filepath, percent
    completed = Signal(str, object)   # filepath, {audio_index: peaks}

    def __init__(self, filepath: str, parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self._cancelled = False

    def cancel(self):
        """Abandon the decode when it is next asked."""
        self._cancelled = True

    def run(self):
        # lower priority so video decode wins
        self.setPriority(QThread.Priority.LowPriority)
        from media.waveform import compute_peaks_all

        def on_progress(pct: int):
            self.progress.emit(self.filepath, pct)

        results = compute_peaks_all(
            self.filepath,
            num_peaks=4000,
            progress_callback=on_progress,
            cancel_callback=lambda: self._cancelled
        )
        if self._cancelled:
            return
        self.completed.emit(self.filepath, results)


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

    Jobs are keyed by file. Every audio stream of a file is computed
    in the one pass and cached, so a request for another of its
    streams — which arrives a moment later as the next track's row is
    built — is answered from that pass or from cache, never by
    reading the file again.
    """

    MAX_CONCURRENT = 2          # files at a time

    def __init__(self):
        super().__init__()
        self._pending   = []     # filepaths waiting their turn
        self._workers   = {}     # filepath -> running worker
        self._retired   = {}     # kept alive until the thread finishes
        self._callbacks = {}     # (filepath, audio_index) -> [(done, prog)]
        self._paused    = False

    # ── public ────────────────────────────────────────────────

    def submit(self, filepath: str, audio_index: int = 0,
               completed=None, progress=None):
        """
        Ask for one audio stream's peaks. Callbacks fire on the main
        thread. Asking again for anything in the same file joins the
        pass already running rather than starting another.
        """
        self._callbacks.setdefault((filepath, audio_index), []).append(
            (completed, progress))
        if filepath in self._workers:
            return                      # its pass covers every stream
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
            filepath = self._pending.pop(0)
            worker = WaveformWorker(filepath)
            worker.progress.connect(self._on_progress)
            worker.completed.connect(self._on_completed)
            worker.finished.connect(
                lambda f=filepath: self._retired.pop(f, None))
            self._workers[filepath] = worker
            worker.start()

    def shutdown(self, msecs: int = 3000):
        """
        Give up every job and wait for the threads to stop.

        Qt destroys a QThread that is still running when the process
        goes down — "QThread: Destroyed while thread '' is still
        running", and on Windows that can take the exit with it. A
        waveform is disposable, so cancel rather than finish. Any
        thread that does not stop in time keeps its reference, since
        dropping it is the thing being avoided.
        """
        self._paused = True
        self._pending.clear()
        self._callbacks.clear()
        running = dict(self._workers)
        running.update(self._retired)
        for worker in running.values():
            worker.cancel()
        for worker in running.values():
            if worker.isRunning():
                worker.wait(msecs)
        self._workers.clear()
        self._retired = {f: w for f, w in running.items()
                         if w.isRunning()}

    def _on_progress(self, filepath: str, pct: int):
        for (path, _index), waiting in list(self._callbacks.items()):
            if path != filepath:
                continue
            for _completed, progress in waiting:
                if progress is not None:
                    progress(filepath, pct)

    def _on_completed(self, filepath: str, results):
        worker = self._workers.pop(filepath, None)
        if worker is not None:
            # hold a reference until the thread has actually finished,
            # or Qt may delete a QThread that is still running
            self._retired[filepath] = worker
        results = results or {}
        for key in [k for k in self._callbacks if k[0] == filepath]:
            _path, index = key
            peaks = results.get(index)
            for completed, _progress in self._callbacks.pop(key, []):
                if completed is not None:
                    completed(filepath, peaks)
        self._drain()


waveform_queue = _WaveformQueue()
