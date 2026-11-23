"""Capture frames of one window, even when other windows cover it.

Primary backend: Windows Graphics Capture (windows-capture package).
Fallback: PrintWindow with PW_RENDERFULLCONTENT (works for Chrome/Edge on Windows 10+).
Both return BGR uint8 numpy arrays of the whole window.
"""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

import numpy as np

from . import winlist


class CaptureSource:
    name = "base"

    def start(self) -> None: ...

    def latest(self) -> np.ndarray | None:
        """Most recent full-window frame (BGR copy) or None if nothing yet."""
        raise NotImplementedError

    def stop(self) -> None: ...

    @property
    def closed(self) -> bool:
        return False


class WgcSource(CaptureSource):
    """Windows Graphics Capture. Frames arrive only when the window content changes."""

    name = "Windows Graphics Capture"

    def __init__(self, hwnd: int, min_interval_ms: int = 200):
        from windows_capture import WindowsCapture  # imported lazily (heavy)

        self.hwnd = hwnd
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._frame_time = 0.0
        self._closed = False
        self._control = None
        self._error: Exception | None = None

        self._cap = WindowsCapture(
            cursor_capture=False,
            draw_border=False,
            minimum_update_interval=min_interval_ms,
            window_hwnd=hwnd,
        )

        @self._cap.event
        def on_frame_arrived(frame, capture_control):
            buf = frame.frame_buffer
            bgr = np.ascontiguousarray(buf[:, :, :3])  # copy out of the native buffer
            with self._lock:
                self._frame = bgr
                self._frame_time = time.monotonic()

        @self._cap.event
        def on_closed():
            self._closed = True

    def start(self) -> None:
        self._control = self._cap.start_free_threaded()

    def latest(self) -> np.ndarray | None:
        with self._lock:
            return self._frame

    @property
    def frame_age(self) -> float:
        with self._lock:
            return time.monotonic() - self._frame_time if self._frame_time else 1e9

    def stop(self) -> None:
        if self._control is not None:
            try:
                self._control.stop()
            except Exception:
                pass
            self._control = None

    @property
    def closed(self) -> bool:
        if self._control is not None:
            try:
                if self._control.is_finished():
                    return True
            except Exception:
                return True
        return self._closed or not winlist.is_window(self.hwnd)


# ---------------------------------------------------------------- PrintWindow fallback

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
PW_RENDERFULLCONTENT = 0x00000002
DIB_RGB_COLORS = 0
BI_RGB = 0

for _fn, _args, _res in (
    ("GetWindowDC", [wintypes.HWND], wintypes.HDC),
    ("ReleaseDC", [wintypes.HWND, wintypes.HDC], ctypes.c_int),
    ("PrintWindow", [wintypes.HWND, wintypes.HDC, wintypes.UINT], wintypes.BOOL),
):
    getattr(_user32, _fn).argtypes = _args
    getattr(_user32, _fn).restype = _res
for _fn, _args, _res in (
    ("CreateCompatibleDC", [wintypes.HDC], wintypes.HDC),
    ("CreateCompatibleBitmap", [wintypes.HDC, ctypes.c_int, ctypes.c_int], wintypes.HBITMAP),
    ("SelectObject", [wintypes.HDC, wintypes.HGDIOBJ], wintypes.HGDIOBJ),
    ("DeleteObject", [wintypes.HGDIOBJ], wintypes.BOOL),
    ("DeleteDC", [wintypes.HDC], wintypes.BOOL),
    ("GetDIBits", [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT], ctypes.c_int),
):
    getattr(_gdi32, _fn).argtypes = _args
    getattr(_gdi32, _fn).restype = _res


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


def printwindow_grab(hwnd: int) -> np.ndarray | None:
    """One synchronous PrintWindow capture of the full window (BGR)."""
    rect = wintypes.RECT()
    _user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    hwnd_dc = _user32.GetWindowDC(hwnd)
    mem_dc = _gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = _gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    old = _gdi32.SelectObject(mem_dc, bmp)
    try:
        if not _user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT):
            return None
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth, bmi.biHeight = w, -h  # top-down
        bmi.biPlanes, bmi.biBitCount, bmi.biCompression = 1, 32, BI_RGB
        buf = np.empty((h, w, 4), dtype=np.uint8)
        got = _gdi32.GetDIBits(mem_dc, bmp, 0, h, buf.ctypes.data_as(ctypes.c_void_p),
                               ctypes.byref(bmi), DIB_RGB_COLORS)
        if got != h:
            return None
        frame = np.ascontiguousarray(buf[:, :, :3])
    finally:
        _gdi32.SelectObject(mem_dc, old)
        _gdi32.DeleteObject(bmp)
        _gdi32.DeleteDC(mem_dc)
        _user32.ReleaseDC(hwnd, hwnd_dc)
    # Trim the invisible resize border so the frame matches what the user sees.
    vl, vt, vr, vb = winlist.window_rect(hwnd)
    x0, y0 = max(0, vl - rect.left), max(0, vt - rect.top)
    x1, y1 = min(w, x0 + (vr - vl)), min(h, y0 + (vb - vt))
    if x1 - x0 > 50 and y1 - y0 > 50:
        frame = frame[y0:y1, x0:x1].copy()
    return frame


class PrintWindowSource(CaptureSource):
    name = "PrintWindow"

    def __init__(self, hwnd: int):
        self.hwnd = hwnd

    def latest(self) -> np.ndarray | None:
        if not winlist.is_window(self.hwnd) or winlist.is_minimized(self.hwnd):
            return None
        return printwindow_grab(self.hwnd)

    @property
    def closed(self) -> bool:
        return not winlist.is_window(self.hwnd)


def open_source(hwnd: int, wait_s: float = 1.5) -> CaptureSource:
    """Start WGC for the window; fall back to PrintWindow if WGC fails or gives no frame."""
    try:
        src = WgcSource(hwnd)
        src.start()
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            f = src.latest()
            if f is not None and f.size and f.max() > 0:
                return src
            time.sleep(0.05)
        src.stop()
    except Exception:
        pass
    return PrintWindowSource(hwnd)


def grab_once(hwnd: int) -> np.ndarray | None:
    """Single frame for previews/thumbnails (cheap PrintWindow, WGC if that fails)."""
    try:
        f = printwindow_grab(hwnd)
        if f is not None and f.max() > 0:
            return f
    except Exception:
        pass
    try:
        src = WgcSource(hwnd)
        src.start()
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            f = src.latest()
            if f is not None:
                src.stop()
                return f
            time.sleep(0.05)
        src.stop()
    except Exception:
        pass
    return None
