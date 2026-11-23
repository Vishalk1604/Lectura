"""Main window: pick the class window, set the capture area, record."""

from __future__ import annotations

import threading
import time

import numpy as np
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QSlider, QSystemTrayIcon,
                               QVBoxLayout, QWidget)

from .. import APP_NAME, winlist
from ..autocrop import detect_content_rect, to_fraction
from ..capture import CaptureSource, PrintWindowSource, WgcSource, open_source
from ..hotkey import GlobalHotkey
from ..recorder import FULL, RecorderCore
from ..session import Item, Session
from ..settings import Settings
from . import app_icon, to_qimage
from .crop_view import CropView
from .review_dialog import ReviewDialog
from .save_dialog import SaveDialog

PREFERRED = ("meet", "classroom", "kiteroom", "zoom", "teams")


class Bridge(QObject):
    """Carries events from worker threads to the UI thread."""
    captured = Signal(object, object)   # Item, image
    status = Signal(str)
    frame = Signal(object)
    hotkey = Signal()


class WindowCombo(QComboBox):
    """Refreshes the window list every time it is opened."""

    def __init__(self, refresh, parent=None):
        super().__init__(parent)
        self._refresh = refresh

    def showPopup(self):
        self._refresh()
        super().showPopup()


def card() -> QFrame:
    f = QFrame(objectName="card")
    return f


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.bridge = Bridge()
        self.bridge.captured.connect(self._on_captured)
        self.bridge.status.connect(self._on_status)
        self.bridge.frame.connect(self._on_frame)
        self.bridge.hotkey.connect(self.capture_now)

        self._windows: list[winlist.WindowInfo] = []
        self._preview: CaptureSource | None = None
        self._preview_started = 0.0
        self._need_autodetect = False
        self._core: RecorderCore | None = None
        self._thread: threading.Thread | None = None
        self._rec_started = 0.0
        self._paused_total = 0.0
        self._last_status = ""
        self._closing = False

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1040, 820)
        self._build()

        self._timer = QTimer(self, interval=250, timeout=self._tick)
        self._timer.start()
        self.refresh_windows(select_preferred=True)

        self.hotkey = GlobalHotkey(settings.hotkey, self.bridge.hotkey.emit)
        if self.hotkey.start():
            self.hotkey_label.setText(f"Capture-now hotkey: {settings.hotkey} (works from any app)")
        else:
            self.hotkey_label.setText(f"Hotkey unavailable: {self.hotkey.error}")

        self.tray = QSystemTrayIcon(app_icon(), self)
        menu = QMenu()
        menu.addAction(QAction("Show Lectura", self, triggered=self._show_from_tray))
        self.tray_capture = QAction("Capture now", self, triggered=self.capture_now)
        self.tray_pause = QAction("Pause", self, triggered=self.toggle_pause)
        self.tray_stop = QAction("Stop && review", self, triggered=self.stop_recording)
        for a in (self.tray_capture, self.tray_pause, self.tray_stop):
            menu.addAction(a)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self._show_from_tray()
                                    if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        self._set_state("idle")

    # ------------------------------------------------------------------ layout
    def _build(self):
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        head = QHBoxLayout()
        t = QLabel(APP_NAME, objectName="h1")
        sub = QLabel("Captures every slide and whiteboard page from your online class.",
                     objectName="muted")
        head.addWidget(t)
        head.addSpacing(10)
        head.addWidget(sub, 1)
        lay.addLayout(head)

        # window picker
        c = card()
        cl = QHBoxLayout(c)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.addWidget(QLabel("Class window"))
        self.combo = WindowCombo(lambda: self.refresh_windows())
        self.combo.setMinimumWidth(420)
        self.combo.currentIndexChanged.connect(self._on_window_changed)
        cl.addWidget(self.combo, 1)
        lay.addWidget(c)

        # preview
        self.view = CropView()
        self.view.cropChanged.connect(self._on_crop_changed)
        lay.addWidget(self.view, 1)

        crop_row = QHBoxLayout()
        self.crop_hint = QLabel("The highlighted box is what gets captured. "
                                "Drag it, resize it, or draw a new one.", objectName="muted")
        self.btn_detect = QPushButton("Auto-detect area")
        self.btn_detect.clicked.connect(self.auto_detect)
        self.btn_full = QPushButton("Whole window")
        self.btn_full.clicked.connect(lambda: self.view.set_crop(FULL, emit=True))
        crop_row.addWidget(self.crop_hint, 1)
        crop_row.addWidget(self.btn_detect)
        crop_row.addWidget(self.btn_full)
        lay.addLayout(crop_row)

        # sensitivity
        c = card()
        sl = QHBoxLayout(c)
        sl.setContentsMargins(12, 8, 12, 8)
        sl.addWidget(QLabel("Sensitivity"))
        sl.addSpacing(8)
        sl.addWidget(QLabel("Fewer captures", objectName="muted"))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(round(self.settings.sensitivity * 100)))
        self.slider.valueChanged.connect(self._on_sensitivity)
        sl.addWidget(self.slider, 1)
        sl.addWidget(QLabel("More captures", objectName="muted"))
        lay.addWidget(c)

        # status
        c = card()
        st = QHBoxLayout(c)
        st.setContentsMargins(14, 10, 14, 10)
        col = QVBoxLayout()
        self.status = QLabel("Ready", objectName="status")
        self.substatus = QLabel("", objectName="muted")
        self.substatus.setWordWrap(True)
        self.hotkey_label = QLabel("", objectName="muted")
        col.addWidget(self.status)
        col.addWidget(self.substatus)
        col.addWidget(self.hotkey_label)
        st.addLayout(col, 1)
        self.last_thumb = QLabel()
        self.last_thumb.setFixedSize(176, 99)
        self.last_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.last_thumb.setStyleSheet("background:#eef0f6;border-radius:6px;color:#9ea3b5;")
        self.last_thumb.setText("last capture")
        st.addWidget(self.last_thumb)
        lay.addWidget(c)

        # buttons
        row = QHBoxLayout()
        self.btn_start = QPushButton("Start recording", objectName="primary")
        self.btn_start.setMinimumHeight(40)
        self.btn_start.clicked.connect(self.start_recording)
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setMinimumHeight(40)
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_capture = QPushButton("Capture now")
        self.btn_capture.setMinimumHeight(40)
        self.btn_capture.clicked.connect(self.capture_now)
        self.btn_stop = QPushButton("Stop && review", objectName="danger")
        self.btn_stop.setMinimumHeight(40)
        self.btn_stop.clicked.connect(self.stop_recording)
        row.addWidget(self.btn_start, 2)
        row.addWidget(self.btn_pause, 1)
        row.addWidget(self.btn_capture, 1)
        row.addWidget(self.btn_stop, 1)
        lay.addLayout(row)

        self.setCentralWidget(root)

    # ------------------------------------------------------------------ state
    @property
    def recording(self) -> bool:
        return self._core is not None

    def _set_state(self, state: str):
        rec = state in ("recording", "paused")
        self.combo.setEnabled(not rec)
        self.btn_start.setEnabled(state == "idle")
        self.btn_pause.setEnabled(rec)
        self.btn_capture.setEnabled(rec)
        self.btn_stop.setEnabled(rec)
        self.btn_pause.setText("Resume" if state == "paused" else "Pause")
        self.tray_pause.setText("Resume" if state == "paused" else "Pause")
        if rec:
            self.tray.show()
        else:
            self.tray.hide()

    def _current_window(self) -> winlist.WindowInfo | None:
        i = self.combo.currentIndex()
        return self._windows[i] if 0 <= i < len(self._windows) else None

    # ------------------------------------------------------------------ windows
    def refresh_windows(self, select_preferred: bool = False):
        if self.recording:
            return
        cur = self._current_window()
        wins = winlist.list_windows()
        self._windows = wins
        self.combo.blockSignals(True)
        self.combo.clear()
        for w in wins:
            self.combo.addItem(w.label)
        idx = -1
        if cur is not None:
            idx = next((i for i, w in enumerate(wins) if w.hwnd == cur.hwnd), -1)
        if idx < 0 and (select_preferred or cur is None):
            idx = next((i for i, w in enumerate(wins)
                        if any(k in w.title.lower() for k in PREFERRED)), -1)
        self.combo.setCurrentIndex(idx)
        self.combo.blockSignals(False)
        if cur is None or idx < 0 or wins[idx].hwnd != cur.hwnd:
            self._on_window_changed(idx)

    def _on_window_changed(self, _idx: int):
        if self.recording:
            return
        self._stop_preview()
        w = self._current_window()
        self.view.set_frame(None)
        if w is None:
            self.view.placeholder = "Pick the class window above to see it here"
            self.status.setText("Ready")
            self.substatus.setText("Choose the window your class is in (browser or app).")
            return
        key = winlist.site_key(w.process, w.title)
        saved = self.settings.crops.get(key)
        if saved:
            self.view.set_crop(saved)
            self._need_autodetect = False
        else:
            self.view.set_crop(FULL)
            self._need_autodetect = True
        self.status.setText("Ready")
        self.substatus.setText("Check that the box covers only the slides / shared screen, "
                               "then press Start recording.")
        self._start_preview(w.hwnd)

    def _start_preview(self, hwnd: int):
        self.view.placeholder = "Loading preview…"
        try:
            src: CaptureSource = WgcSource(hwnd)
            src.start()
        except Exception:
            src = PrintWindowSource(hwnd)
        self._preview = src
        self._preview_started = time.monotonic()

    def _stop_preview(self):
        if self._preview is not None:
            try:
                self._preview.stop()
            except Exception:
                pass
        self._preview = None

    def _tick(self):
        """UI timer: idle preview + recording clock."""
        if self.recording:
            self._update_clock()
            return
        w = self._current_window()
        if w is None or self._preview is None:
            return
        if not winlist.is_window(w.hwnd):
            self.refresh_windows()
            return
        if winlist.is_minimized(w.hwnd):
            self.substatus.setText("The class window is minimized. Restore it (it can stay "
                                   "behind other windows) so it can be captured.")
            return
        frame = self._preview.latest()
        if frame is None:
            if (isinstance(self._preview, WgcSource)
                    and time.monotonic() - self._preview_started > 2.5):
                self._preview.stop()  # WGC gave nothing: try the other method
                self._preview = PrintWindowSource(w.hwnd)
            return
        self.view.set_frame(frame)
        if self._need_autodetect:
            self._need_autodetect = False
            self._apply_autodetect(frame)

    def auto_detect(self):
        frame = self._preview.latest() if self._preview else None
        if frame is None and self._core is not None:
            frame = self._core.source.latest()
        if frame is not None:
            self._apply_autodetect(frame)

    def _apply_autodetect(self, frame: np.ndarray):
        h, w = frame.shape[:2]
        rect = detect_content_rect(frame)
        self.view.set_crop(to_fraction(rect, w, h), emit=True)

    def _on_crop_changed(self, frac):
        w = self._current_window()
        if w is not None:
            self.settings.crops[winlist.site_key(w.process, w.title)] = list(frac)
            self.settings.save()
        if self._core is not None:
            self._core.set_crop(frac)

    def _on_sensitivity(self, v: int):
        self.settings.sensitivity = v / 100
        self.settings.save()
        if self._core is not None:
            self._core.set_sensitivity(v / 100)

    # ------------------------------------------------------------------ recording
    def start_recording(self):
        w = self._current_window()
        if w is None:
            QMessageBox.information(self, APP_NAME, "Pick the class window first.")
            return
        if not winlist.is_window(w.hwnd):
            self.refresh_windows()
            return
        src = self._preview
        self._preview = None
        if src is None or src.latest() is None:
            if src is not None:
                src.stop()
            src = open_source(w.hwnd)
        session = Session.new(w.title)
        self._core = RecorderCore(
            src, w.hwnd, session, crop_frac=self.view.crop(),
            sensitivity=self.slider.value() / 100,
            on_capture=self.bridge.captured.emit, on_status=self.bridge.status.emit,
            on_frame=self.bridge.frame.emit)
        self._rec_started = time.monotonic()
        self._thread = threading.Thread(target=self._core.run, daemon=True, name="recorder")
        self._thread.start()
        self.last_thumb.clear()
        self.last_thumb.setText("last capture")
        self._set_state("recording")
        self.tray.setToolTip(f"{APP_NAME}: recording")
        self._update_clock()

    def toggle_pause(self):
        if self._core is None:
            return
        self._core.set_paused(not self._core.paused)
        self._set_state("paused" if self._core.paused else "recording")
        self._update_clock()

    def capture_now(self):
        if self._core is None:
            return
        self._core.request_capture()
        self.substatus.setText("Capturing the current screen…")

    def stop_recording(self):
        if self._core is not None:
            self.status.setText("Finishing…")
            self._core.stop()

    def _update_clock(self):
        core = self._core
        if core is None:
            return
        el = int(time.monotonic() - self._rec_started)
        h, rem = divmod(el, 3600)
        m, s = divmod(rem, 60)
        n = core.count
        state = self._last_status or "recording"
        label = {"recording": "● Recording", "paused": "❚❚ Paused",
                 "minimized": "❚❚ Waiting – class window minimized",
                 "waiting": "● Waiting for the window to draw",
                 "closed": "Class window closed", "error": "Error"}.get(state, "● Recording")
        self.status.setText(f"{label}  ·  {n} captured  ·  {h:02d}:{m:02d}:{s:02d}")
        color = {"recording": "#e5484d", "paused": "#b7791f", "minimized": "#b7791f"}.get(
            state, "#1f2330")
        self.status.setStyleSheet(f"color:{color};")
        self.tray.setToolTip(f"{APP_NAME}: {n} captured")

    def _on_status(self, state: str):
        self._last_status = state
        if state == "minimized":
            self.substatus.setText("Restore the class window to continue capturing. It can stay "
                                   "behind other windows or on another monitor.")
        elif state == "recording":
            self.substatus.setText("Slides are saved automatically when they change. You can "
                                   "switch to other apps.")
        elif state == "paused":
            self.substatus.setText("Paused. Press Resume to continue.")
        elif state == "closed":
            self.substatus.setText("The class window was closed, so recording stopped.")
        elif state == "error" and self._core is not None:
            self.substatus.setText(f"Problem: {self._core.error}")
        elif state == "stopped":
            QTimer.singleShot(0, self._after_recording)
        self._update_clock()

    def _on_frame(self, frame):
        self.view.set_frame(frame)

    def _on_captured(self, item: Item, image):
        h, w = image.shape[:2]
        small = image if w <= 352 else __import__("cv2").resize(
            image, (352, max(1, int(h * 352 / w))))
        pix = QPixmap.fromImage(to_qimage(small)).scaled(
            self.last_thumb.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.last_thumb.setPixmap(pix)
        if item.forced:
            self.substatus.setText("Captured the current screen.")
        self._update_clock()

    def _after_recording(self):
        core, thread = self._core, self._thread
        if thread is not None:
            thread.join(5)
        self._core, self._thread = None, None
        self._last_status = ""
        self.status.setStyleSheet("")
        self._set_state("idle")
        if core is not None:
            if core.error:
                QMessageBox.warning(self, APP_NAME,
                                    f"Recording stopped because of a problem:\n{core.error}\n\n"
                                    "Everything captured so far is kept.")
            self.review_and_save(core.session)
        if self._closing:
            self.close()
            return
        self.status.setText("Ready")
        self.substatus.setText("")
        self.refresh_windows()
        self._on_window_changed(self.combo.currentIndex())

    def review_and_save(self, session: Session):
        if not session.items:
            QMessageBox.information(self, APP_NAME,
                                    "No slides or pages were captured in this session.")
            session.discard()
            return
        while True:
            review = ReviewDialog(session, self)
            if review.exec() != ReviewDialog.DialogCode.Accepted:
                if review.discarded:
                    session.discard()
                else:
                    QMessageBox.information(
                        self, APP_NAME, "Your captures are kept. Lectura will offer to save "
                        "them the next time you open it.")
                return
            session.set_items(review.current_items())
            save = SaveDialog(session, session.items, self.settings, self)
            if save.exec() == SaveDialog.DialogCode.Accepted:
                return
            # "Back" -> review again

    def check_recovery(self):
        Session.cleanup_old()
        s = Session.find_unexported()
        if s is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"There are {len(s.items)} unsaved captures from the class on "
                    f"{s.started_at:%d %b %Y, %I:%M %p}.\nDo you want to review and save them?")
        rec = box.addButton("Review && save", QMessageBox.ButtonRole.AcceptRole)
        dis = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is rec:
            self.review_and_save(s)
        elif box.clickedButton() is dis:
            s.discard()

    def _show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------ close
    def closeEvent(self, e):
        if self.recording:
            r = QMessageBox.question(self, APP_NAME, "A class is being recorded. Stop recording "
                                     "and review the captures now?")
            if r == QMessageBox.StandardButton.Yes:
                self._closing = True
                self.stop_recording()
            e.ignore()
            return
        self._stop_preview()
        self.hotkey.stop()
        self.tray.hide()
        super().closeEvent(e)
