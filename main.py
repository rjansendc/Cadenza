import sys
import os

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

def main():
    # ensure cache dir exists
    from pathlib import Path
    Path('cache/waveforms').mkdir(
        parents=True, exist_ok=True
    )

    app = QApplication(sys.argv)
    app.setApplicationName('Cadenza')
    app.setOrganizationName('Cadenza')

    from ui.mainwindow import MainWindow
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
