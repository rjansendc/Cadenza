from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem,
    QPushButton, QLabel, QAbstractItemView
)
from PySide6.QtCore import Qt, Signal, QMimeData, QByteArray
from PySide6.QtGui import QColor, QDrag
from core.project import Project, MediaPoolItem
from ui.app_state import AppState


class DraggableListWidget(QListWidget):
    """QListWidget with drag-out and drop-in support."""

    files_dropped = Signal(list)  # list of file paths

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDefaultDropAction(
            Qt.DropAction.CopyAction
        )
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = []
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if path:
                    paths.append(path)
            if paths:
                self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def startDrag(self, supported_actions):
        item = self.currentItem()
        if not item:
            return

        item_id = item.data(Qt.ItemDataRole.UserRole)

        # pack the media item id into mime data
        mime = QMimeData()
        mime.setData(
            'application/x-mediaitem-id',
            QByteArray(item_id.encode())
        )

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class MediaBinPanel(QWidget):

    media_double_clicked = Signal(MediaPoolItem)
    files_dropped        = Signal(list)  # paths from Explorer

    def __init__(self, project: Project,
                 app_state: AppState,
                 parent=None):
        super().__init__(parent)
        self.project   = project
        self.app_state = app_state
        self._items: dict = {}
        self.setMinimumWidth(180)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # header
        header = QWidget()
        header.setStyleSheet(
            'background-color: #1a1a1a; '
            'border-bottom: 1px solid #333333;'
        )
        header.setFixedHeight(28)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(8, 0, 4, 0)
        title = QLabel('Media Bin')
        title.setStyleSheet(
            'color: #888888; font-size: 10px; '
            'letter-spacing: 1px; border: none;'
        )
        hl.addWidget(title)
        hl.addStretch()
        layout.addWidget(header)

        # draggable file list
        self.list_widget = DraggableListWidget()
        self.list_widget.files_dropped.connect(
            self.files_dropped.emit)
        self.list_widget.setStyleSheet("""
            QListWidget {
                background-color: #151515;
                border: none;
                color: #cccccc;
                font-size: 11px;
            }
            QListWidget::item {
                padding: 6px 8px;
                border-bottom: 1px solid #1e1e1e;
            }
            QListWidget::item:selected {
                background-color: #1e3a5a;
                color: #ffffff;
            }
            QListWidget::item:hover {
                background-color: #222222;
            }
        """)
        self.list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.list_widget.itemDoubleClicked.connect(
            self._on_double_click
        )
        layout.addWidget(self.list_widget)

        # import button
        self.import_btn = QPushButton('+ Import Media')
        self.import_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a1a1a;
                color: #888888;
                border: none;
                border-top: 1px solid #333333;
                padding: 8px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #222222;
                color: #cccccc;
            }
        """)
        self.import_btn.clicked.connect(
            self._on_import_clicked
        )
        layout.addWidget(self.import_btn)

    def clear(self):
        """Clear all items from the media bin."""
        self.list_widget.clear()
        self._items.clear()

    def add_item(self, item: MediaPoolItem):
        self._items[item.id] = item
        list_item = QListWidgetItem()

        if item.has_video and item.has_audio:
            icon = '🎬'
        elif item.has_video:
            icon = '📹'
        else:
            icon = '🎵'

        duration = item.duration_timecode
        res      = item.resolution_label
        display  = f'{item.name}\n{res}  {duration}'
        list_item.setText(f'{icon}  {display}')
        list_item.setData(
            Qt.ItemDataRole.UserRole, item.id
        )
        list_item.setToolTip(item.filepath)
        self.list_widget.addItem(list_item)

    def get_item(self, item_id: str):
        return self._items.get(item_id)

    def _on_double_click(self, 
                          list_item: QListWidgetItem):
        item_id = list_item.data(
            Qt.ItemDataRole.UserRole
        )
        item = self._items.get(item_id)
        if item:
            self.media_double_clicked.emit(item)

    def _on_import_clicked(self):
        main = self.window()
        if hasattr(main, '_on_import_media'):
            main._on_import_media()