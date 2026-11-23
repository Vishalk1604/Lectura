"""The recording loop: sample the window, crop, detect page changes, save captures."""

from __future__ import annotations

import threading
import time
from typing import Callable

import numpy as np

from . import winlist
from .autocrop import from_fraction
from .capture import CaptureSource
from .detector import Capture, CapturePipeline
from .session import Item, Session

FULL = (0.0, 0.0, 1.0, 1.0)


class RecorderCore:
    """Runs in a worker thread. All callbacks are called from that thread."""

    def __init__(self, source: CaptureSource, hwnd: int, session: Session,
                 crop_frac=FULL, sensitivity: float = 0.5, fps: float = 2.0,
                 on_capture: Callable[[Item, np.ndarray], None] | None = None,
                 on_status: Callable[[str], None] | None = None,
                 on_frame: Callable[[np.ndarray], None] | None = None):
        self.source = source
        self.hwnd = hwnd
        self.session = session
        self.crop_frac = tuple(crop_frac)
        self.interval = 1.0 / fps
        self.pipeline = CapturePipeline(sensitivity=sensitivity)
        self.on_capture = on_capture or (lambda item, img: None)
        self.on_status = on_status or (lambda s: None)
        self.on_frame = on_frame or (lambda f: None)

        self._stop = threading.Event()
        self._paused = False
        self._force = threading.Event()
        self._lock = threading.Lock()
        self._state = ""
        self.window_closed = False
        self.started = time.monotonic()
        self.error = ""

    # ------------------------------------------------------------------ controls
    def stop(self) -> None:
        self._stop.set()

    def request_capture(self) -> None:
        self._force.set()

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = paused
            if not paused:
                self.pipeline.detector.reset_motion()

    @property
    def paused(self) -> bool:
        return self._paused

    def set_crop(self, frac) -> None:
        with self._lock:
            self.crop_frac = tuple(frac)

    def set_sensitivity(self, s: float) -> None:
        with self._lock:
            self.pipeline.detector.set_sensitivity(s)

    @property
    def count(self) -> int:
        return len(self.session.items)

    # ------------------------------------------------------------------ loop
    def _status(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.on_status(state)

    def _save(self, cap: Capture | None) -> None:
        if cap is None:
            return
        item = self.session.add(cap.image, cap.t, cap.forced)
        self.on_capture(item, cap.image)

    def _crop(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        x, y, cw, ch = from_fraction(self.crop_frac, w, h)
        return frame[y:y + ch, x:x + cw]

    def run(self) -> None:
        last_pending_version, last_pending_write = -1, 0.0
        last_frame_emit = 0.0
        try:
            next_tick = time.monotonic()
            while not self._stop.is_set():
                now = time.monotonic()
                if now < next_tick:
                    self._stop.wait(min(0.05, next_tick - now))
                    continue
                next_tick = max(next_tick + self.interval, now)
                t = now - self.started

                if self.source.closed or not winlist.is_window(self.hwnd):
                    self.window_closed = True
                    self._status("closed")
                    break
                frame = self.source.latest()
                if now - last_frame_emit > 0.5 and frame is not None:
                    self.on_frame(frame)
                    last_frame_emit = now

                with self._lock:
                    if self._force.is_set() and frame is not None:
                        self._force.clear()
                        # make the detector see the newest frame first
                        self.pipeline.detector._latest = self._crop(frame)
                        self.pipeline.detector._latest_t = t
                        self._save(self.pipeline.force())
                    if self._paused:
                        self._status("paused")
                        continue
                    if winlist.is_minimized(self.hwnd):
                        self._status("minimized")
                        self.pipeline.detector.reset_motion()
                        continue
                    if frame is None:
                        self._status("waiting")
                        continue
                    self._status("recording")
                    crop = self._crop(frame)
                    for cap in self.pipeline.feed(crop, t):
                        self._save(cap)

                    det = self.pipeline.detector
                    if (det.page_version != last_pending_version and det.page_frame is not None
                            and now - last_pending_write > 3.0):
                        self.session.write_pending(det.page_frame, t)
                        last_pending_version, last_pending_write = det.page_version, now
        except Exception as e:  # keep what we have; report the problem
            self.error = f"{type(e).__name__}: {e}"
            self._status("error")
        finally:
            try:
                self._save(self.pipeline.finish())
            except Exception as e:
                self.error = self.error or f"{type(e).__name__}: {e}"
            self.session.mark_finished()
            try:
                self.source.stop()
            except Exception:
                pass
            self._status("stopped")
