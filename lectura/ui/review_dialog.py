"""After Stop: look through the captures, delete bad ones, reorder, then save."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImageReader, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QLabel, QListView,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QVBoxLayout)

from ..session import Item, Session

THUMB = QSize(280, 170)


def _thumb(path) -> QPixmap:
    reader = QImageReader(str(path))
    size = reader.size()
    if size.isValid():
        reader.setScaledSize(size.scaled(THUMB, Qt.AspectRatioMode.KeepAspectRatio))
    return QPixmap.fromImage(reader.read())


class ImageViewer(QDialog):
    """Full-size view with arrow-key navigation."""

    def __init__(self, session: Session, items: list[Item], index: int, parent=None):
        super().__init__(parent)
        self.session, self.items, self.index = session, items, index
        self.setWindowTitle("Capture")
        self.resize(1200, 760)
        lay = QVBoxLayout(self)
        self.label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.label.setMinimumSize(400, 300)
        self.caption = QLabel(objectName="muted", alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.label, 1)
        lay.addWidget(self.caption)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, lambda: self.step(1))
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, lambda: self.step(-1))
        self._pix = QPixmap()
        self.show_index()

    def step(self, d: int):
        self.index = max(0, min(len(self.items) - 1, self.index + d))
        self.show_index()

    def show_index(self):
        item = self.items[self.index]
        self._pix = QPixmap(str(self.session.path_of(item)))
        self.caption.setText(f"{self.index + 1} of {len(self.items)}  ·  "
                             f"{self.session.caption(item)}   (← → to move)")
        self._fit()

    def _fit(self):
        if not self._pix.isNull():
            self.label.setPixmap(self._pix.scaled(self.label.size(),
                                                  Qt.AspectRatioMode.KeepAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()


class ReviewDialog(QDialog):
    """exec() returns Accepted to save; `discarded` is True if the user threw it all away."""

    def __init__(self, session: Session, parent=None):
        super().__init__(parent)
        self.session = session
        self.discarded = False
        self.setWindowTitle("Review captures")
        self.resize(1180, 760)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        title = QLabel("Review your captures", objectName="h1")
        self.info = QLabel(objectName="muted")
        lay.addWidget(title)
        lay.addWidget(self.info)

        self.list = QListWidget()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setIconSize(THUMB)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setMovement(QListView.Movement.Snap)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setSpacing(6)
        self.list.setUniformItemSizes(True)
        self.list.setWordWrap(True)
        self.list.itemDoubleClicked.connect(self.open_viewer)
        lay.addWidget(self.list, 1)

        for item in session.items:
            w = QListWidgetItem(_thumb(session.path_of(item)), "")
            w.setData(Qt.ItemDataRole.UserRole, item)
            w.setSizeHint(QSize(THUMB.width() + 24, THUMB.height() + 48))
            self.list.addItem(w)
        self.list.model().rowsMoved.connect(self.renumber)
        self.renumber()

        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, self.delete_selected)

        row = QHBoxLayout()
        self.btn_delete = QPushButton("Delete selected")
        self.btn_delete.clicked.connect(self.delete_selected)
        btn_discard = QPushButton("Discard all")
        btn_discard.clicked.connect(self.discard_all)
        self.btn_save = QPushButton("Save…", objectName="primary")
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self.accept)
        row.addWidget(self.btn_delete)
        row.addWidget(btn_discard)
        row.addStretch(1)
        row.addWidget(self.btn_save)
        lay.addLayout(row)

    # ------------------------------------------------------------------ helpers
    def current_items(self) -> list[Item]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.list.count())]

    def renumber(self, *args):
        for i in range(self.list.count()):
            w = self.list.item(i)
            item: Item = w.data(Qt.ItemDataRole.UserRole)
            tag = "  (manual)" if item.forced else ""
            w.setText(f"{i + 1}  ·  {self.session.caption(item).split('  ·  ')[0]}{tag}")
        n = self.list.count()
        self.info.setText(f"{n} capture{'s' if n != 1 else ''}.  Drag to reorder · "
                          "Delete key removes · double-click to enlarge")
        if hasattr(self, "btn_save"):
            self.btn_save.setEnabled(n > 0)

    def delete_selected(self):
        rows = sorted((self.list.row(w) for w in self.list.selectedItems()), reverse=True)
        for r in rows:
            self.list.takeItem(r)
        self.renumber()

    def discard_all(self):
        if QMessageBox.question(
                self, "Discard all captures?",
                "This permanently deletes every capture from this class. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.discarded = True
            self.reject()

    def open_viewer(self, w: QListWidgetItem):
        ImageViewer(self.session, self.current_items(), self.list.row(w), self).exec()
