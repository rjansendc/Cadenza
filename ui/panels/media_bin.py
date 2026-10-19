from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem,
    QPushButton, QLabel, QAbstractItemView,
    QStyledItemDelegate
)
from PySide6.QtCore import Qt, Signal, QMimeData, QByteArray
from PySide6.QtGui import QColor, QDrag

# the short "4K  12:05" summary, kept out of the display text so the
# delegate can right-align it
META_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class MediaRowDelegate(QStyledItemDelegate):
    """
    One line per file: icon and name on the left, size and length
    right-aligned and dimmed.

    A delegate rather than a row widget, because a widget placed in
    the row swallows the mouse press and dragging a file out to the
    timeline would stop working. Qt elides the name against whatever
    room is left, so the summary never disappears and nothing has to
    be recalculated when the panel is resized.
    """

    GAP      = 10          # px between name and summary
    META_DIM = QColor('#7a7a7a')

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        # Blank the text here, not in paint(): the base paint() calls
        # this again itself, which put the full unelided name back and
        # drew it underneath — every row came out doubled, with the
        # long names running under the summary.
        option.text = ''

    def paint(self, painter, option, index):
        opt = option.__class__(option)
        self.initStyleOption(opt, index)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ''
        super().paint(painter, opt, index)

        meta = index.data(META_ROLE) or ''
        rect = opt.rect.adjusted(8, 0, -8, 0)
        fm   = painter.fontMetrics()

        painter.save()
        if meta:
            meta_w = fm.horizontalAdvance(meta)
            painter.setPen(self.META_DIM)
            painter.drawText(
                rect, int(Qt.AlignmentFlag.AlignRight |
                          Qt.AlignmentFlag.AlignVCenter), meta)
            rect.setWidth(max(20, rect.width() - meta_w - self.GAP))

        painter.setPen(opt.palette.text().color()
                       if not (opt.state & opt.state.__class__.State_Selected)
                       else opt.palette.highlightedText().color())
        painter.drawText(
            rect, int(Qt.AlignmentFlag.AlignLeft |
                      Qt.AlignmentFlag.AlignVCenter),
            fm.elidedText(text, Qt.TextElideMode.ElideMiddle,
                          rect.width()))
        painter.restore()
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
        self._list_items: dict = {}
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
                padding: 3px 8px;
                border-bottom: 1px solid #1e1e1e;
            }
            QListWidget::item:selected {
                background-color: #1e3a5a;
                color: #ffffff;
            }
            QListWidget::item:hover {
                background-color: #222222;
            }
            QScrollBar:vertical {
                background: #1a1a1a;
                width: 12px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #4a4a4a;
                border-radius: 5px;
                min-height: 24px;
                margin: 1px;
            }
            QScrollBar::handle:vertical:hover { background: #5f5f5f; }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical { background: #141414; }
            QScrollBar:horizontal {
                background: #1a1a1a;
                height: 12px;
                margin: 0;
            }
            QScrollBar::handle:horizontal {
                background: #4a4a4a;
                border-radius: 5px;
                min-width: 24px;
                margin: 1px;
            }
            QScrollBar::handle:horizontal:hover { background: #5f5f5f; }
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal { width: 0; }
            QScrollBar::add-page:horizontal,
            QScrollBar::sub-page:horizontal { background: #141414; }
        """)
        # the bin is narrow: never scroll sideways, elide instead
        self.list_widget.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list_widget.setItemDelegate(
            MediaRowDelegate(self.list_widget))
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
        self._list_items.clear()

    IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif')

    @staticmethod
    def _icon_for(item: MediaPoolItem) -> str:
        if item.has_video and item.has_audio:
            return '🎬'
        if item.has_video:
            return '📹'
        return '🎵'

    @staticmethod
    def _compact_duration(seconds: float) -> str:
        """m:ss, or h:mm:ss past the hour — the full timecode is far
        too wide for a narrow bin."""
        total = int(round(seconds or 0))
        hours, rest = divmod(total, 3600)
        minutes, secs = divmod(rest, 60)
        if hours:
            return f'{hours}:{minutes:02d}:{secs:02d}'
        return f'{minutes}:{secs:02d}'

    def _meta_for(self, item: MediaPoolItem) -> str:
        """
        The short right-hand summary: what it is, and how long.

        Audio has no frame size — it used to render as a literal
        "0x0" — so it shows its file type instead, and so do stills,
        whose duration is a setting rather than a property of the file.
        """
        import os
        ext = os.path.splitext(item.filepath)[1].lstrip('.').upper()
        if not item.has_video:
            kind = ext or 'AUDIO'
        elif ext.lower() in (e.lstrip('.') for e in self.IMAGE_EXTS):
            kind = ext
        else:
            kind = item.resolution_label
        duration = self._compact_duration(item.source_duration)
        return f'{kind}  {duration}' if duration != '0:00' else kind

    def add_item(self, item: MediaPoolItem):
        """
        One row, one line.

        Rows used to be two lines — name, then size and duration
        underneath — which read as double spacing and halved how many
        files you could see at once.
        """
        self._items[item.id] = item
        list_item = QListWidgetItem()
        list_item.setText(f'{self._icon_for(item)}  {item.name}')
        list_item.setData(META_ROLE, self._meta_for(item))
        list_item.setData(
            Qt.ItemDataRole.UserRole, item.id
        )
        list_item.setToolTip(
            f'{item.name}\n{item.filepath}'
        )
        self._list_items[item.id] = list_item
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