import sys
import os

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

def main():
    # Prepare the caches and say where they are. This used to be
    # Path('cache/waveforms'), which is relative to whatever directory
    # the app happened to be launched from — so it scattered empty
    # folders around and never matched where the caches really went.
    from core.paths import cache_root, cache_dir, is_frozen
    cache_dir('waveforms')
    cache_dir('proxies')
    print(f"Cache: {cache_root()}"
          f"{'' if is_frozen() else '  (running from source)'}")

    app = QApplication(sys.argv)
    app.setApplicationName('Cadenza')
    app.setOrganizationName('Cadenza')

    from ui.mainwindow import MainWindow
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
