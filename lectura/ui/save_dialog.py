"""Choose formats, folder and file name, then export."""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar,
                               QPushButton, QVBoxLayout)

from ..exporters import Page, unique_path
from ..session import Item, Session
from ..settings import Settings

FORMATS = [("pptx", "PowerPoint (.pptx)  -  one capture per slide"),
           ("docx", "Word (.docx)  -  two captures per page"),
           ("pdf", "PDF (.pdf)  -  two captures per page")]

_BAD_CHARS = '<>:"/\\|?*'


def safe_name(name: str) -> str:
    name = "".join("-" if c in _BAD_CHARS else c for c in name).strip().rstrip(".")
    return name or "Class"


def run_exports(session: Session, items: list[Item], folder: Path, name: str,
                formats: list[str], timestamps: bool, page_size: str, progress=None) -> list[Path]:
    from .. import exporters  # noqa: F401
    from ..exporters.docx_export import export_docx
    from ..exporters.pdf_export import export_pdf
    from ..exporters.pptx_export import export_pptx

    pages = [Page(session.path_of(i), session.caption(i) if timestamps else "") for i in items]
    title = name
    out: list[Path] = []
    total = len(formats) * len(pages)
    done = [0]

    def step(_i, _n):
        done[0] += 1
        if progress:
            progress(done[0], total)

    folder.mkdir(parents=True, exist_ok=True)
    for fmt in formats:
        path = unique_path(folder / f"{name}.{fmt}")
        if fmt == "pptx":
            export_pptx(pages, path, title=title, progress=step)
        elif fmt == "docx":
            export_docx(pages, path, title=title, page_size=page_size, progress=step)
        elif fmt == "pdf":
            export_pdf(pages, path, title=title, page_size=page_size, progress=step)
        out.append(path)
    return out


class _Worker(QObject):
    progress = Signal(int, int)
    finished = Signal(list, str)


class SaveDialog(QDialog):
    def __init__(self, session: Session, items: list[Item], settings: Settings, parent=None):
        super().__init__(parent)
        self.session, self.items, self.settings = session, items, settings
        self.saved: list[Path] = []
        self.setWindowTitle("Save class")
        self.setMinimumWidth(560)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)
        lay.addWidget(QLabel("Save your class", objectName="h1"))
        lay.addWidget(QLabel(f"{len(items)} capture{'s' if len(items) != 1 else ''} "
                             "will be saved. Pick one or more formats.", objectName="muted"))

        self.checks: dict[str, QCheckBox] = {}
        for key, label in FORMATS:
            cb = QCheckBox(label)
            cb.setChecked(key in settings.formats)
            cb.toggled.connect(self._validate)
            self.checks[key] = cb
            lay.addWidget(cb)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.name = QLineEdit(f"Class {session.started_at:%Y-%m-%d %H-%M}")
        self.name.textChanged.connect(self._validate)
        form.addRow("File name", self.name)

        folder_row = QHBoxLayout()
        self.folder = QLineEdit(settings.last_folder)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        form.addRow("Save to", folder_row)

        self.page_size = QComboBox()
        self.page_size.addItems(["A4", "Letter"])
        self.page_size.setCurrentText(settings.page_size)
        form.addRow("Page size", self.page_size)
        lay.addLayout(form)

        self.timestamps = QCheckBox("Show the class time under each capture")
        self.timestamps.setChecked(settings.timestamps)
        lay.addWidget(self.timestamps)

        self.bar = QProgressBar()
        self.bar.hide()
        lay.addWidget(self.bar)

        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_cancel = QPushButton("Back")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save = QPushButton("Save", objectName="primary")
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self._save)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_save)
        lay.addLayout(row)
        self._validate()

    def _formats(self) -> list[str]:
        return [k for k, cb in self.checks.items() if cb.isChecked()]

    def _validate(self, *a):
        self.btn_save.setEnabled(bool(self._formats()) and bool(self.name.text().strip()))

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Save to folder", self.folder.text())
        if d:
            self.folder.setText(d)

    def _save(self):
        formats = self._formats()
        folder = Path(self.folder.text().strip() or self.settings.last_folder)
        name = safe_name(self.name.text())
        s = self.settings
        s.formats, s.last_folder = formats, str(folder)
        s.timestamps, s.page_size = self.timestamps.isChecked(), self.page_size.currentText()
        s.save()

        for w in (self.btn_save, self.btn_cancel, *self.checks.values(), self.name, self.folder):
            w.setEnabled(False)
        self.bar.show()
        self.bar.setValue(0)

        worker = _Worker(self)
        worker.progress.connect(lambda d, t: (self.bar.setMaximum(t), self.bar.setValue(d)))
        worker.finished.connect(self._done)
        self._worker = worker

        def job():
            try:
                paths = run_exports(self.session, self.items, folder, name, formats,
                                    s.timestamps, s.page_size, worker.progress.emit)
                worker.finished.emit(paths, "")
            except Exception as e:  # report and let the user retry
                worker.finished.emit([], f"{type(e).__name__}: {e}")

        threading.Thread(target=job, daemon=True).start()

    def _done(self, paths: list, error: str):
        if error:
            QMessageBox.critical(self, "Could not save", f"Saving failed:\n{error}\n\n"
                                 "Your captures are still kept; try another folder.")
            for w in (self.btn_save, self.btn_cancel, *self.checks.values(), self.name,
                      self.folder):
                w.setEnabled(True)
            self.bar.hide()
            return
        self.saved = paths
        self.session.mark_exported([str(p) for p in paths])
        box = QMessageBox(self)
        box.setWindowTitle("Saved")
        box.setText("Saved:\n" + "\n".join(p.name for p in paths) + f"\n\nin {paths[0].parent}")
        open_file = box.addButton("Open file", QMessageBox.ButtonRole.AcceptRole)
        open_folder = box.addButton("Show in folder", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Done", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_file:
            os.startfile(str(paths[0]))  # noqa: S606 - opening the user's own file
        elif box.clickedButton() is open_folder:
            subprocess.Popen(["explorer", "/select,", str(paths[0])])
        self.accept()
