from PySide6.QtCore import QThread, Signal


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