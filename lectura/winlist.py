"""Enumerate capturable top-level windows and query their state (Win32 via ctypes)."""

from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes
from dataclasses import dataclass

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
DWMWA_CLOAKED = 14
DWMWA_EXTENDED_FRAME_BOUNDS = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GW_OWNER = 4

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    process: str  # executable name, lower case, e.g. "chrome.exe"

    @property
    def label(self) -> str:
        proc = self.process.removesuffix(".exe")
        return f"{self.title}  ({proc})"


def set_dpi_aware() -> None:
    """Use physical pixels for all window coordinates (call before any UI)."""
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass


def get_title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def is_window(hwnd: int) -> bool:
    return bool(user32.IsWindow(hwnd))


def is_minimized(hwnd: int) -> bool:
    return bool(user32.IsIconic(hwnd))


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Visible window bounds (left, top, right, bottom) without the invisible resize border."""
    rect = wintypes.RECT()
    if dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS,
                                    ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def _is_cloaked(hwnd: int) -> bool:
    cloaked = wintypes.DWORD()
    res = dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_CLOAKED,
                                       ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    return res == 0 and cloaked.value != 0


def process_name(hwnd: int) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def list_windows(exclude_pid: int | None = None) -> list[WindowInfo]:
    """Visible, titled, non-tool top-level windows that can be captured."""
    if exclude_pid is None:
        exclude_pid = os.getpid()
    found: list[WindowInfo] = []

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, GW_OWNER):
            return True
        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if ex & WS_EX_TOOLWINDOW or ex & WS_EX_NOACTIVATE:
            return True
        if _is_cloaked(hwnd):
            return True
        title = get_title(hwnd).strip()
        if not title:
            return True
        if window_pid(hwnd) == exclude_pid:
            return True
        left, top, right, bottom = window_rect(hwnd)
        if (right - left) < 200 or (bottom - top) < 150:
            if not is_minimized(hwnd):
                return True
        proc = process_name(hwnd)
        if proc in ("textinputhost.exe", "shellexperiencehost.exe", "searchhost.exe",
                    "startmenuexperiencehost.exe", "applicationframehost.exe") and not title:
            return True
        found.append(WindowInfo(int(hwnd), title, proc))
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return found


GW_HWNDPREV = 3
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000


def covered_fraction(hwnd: int, grid: tuple[int, int] = (64, 36)) -> float:
    """Share of the window hidden behind windows above it in the z-order (0..1).

    Browsers may stop drawing a window that is completely covered, so the recorder
    uses this to warn the user.
    """
    import numpy as np

    l, t, r, b = window_rect(hwnd)
    if r <= l or b <= t:
        return 0.0
    gw, gh = grid
    xs = l + (np.arange(gw) + 0.5) * (r - l) / gw
    ys = t + (np.arange(gh) + 0.5) * (b - t) / gh
    covered = np.zeros((gh, gw), bool)
    other = user32.GetWindow(hwnd, GW_HWNDPREV)
    steps = 0
    while other and steps < 500:
        steps += 1
        if (user32.IsWindowVisible(other) and not user32.IsIconic(other)
                and not _is_cloaked(other)):
            ex = user32.GetWindowLongPtrW(other, GWL_EXSTYLE)
            if not (ex & WS_EX_TRANSPARENT and ex & WS_EX_LAYERED):
                ol, ot, orr, ob = window_rect(other)
                if orr - ol > 1 and ob - ot > 1:
                    cx = (xs >= ol) & (xs < orr)
                    cy = (ys >= ot) & (ys < ob)
                    covered |= cy[:, None] & cx[None, :]
                    if covered.all():
                        return 1.0
        other = user32.GetWindow(other, GW_HWNDPREV)
    return float(covered.mean())


_KNOWN_SITES = ("meet", "classroom", "kiteroom", "zoom", "teams", "webex", "youtube")


def site_key(process: str, title: str) -> str:
    """Stable key for remembering the crop box of a site/app, e.g. 'chrome.exe|meet'."""
    low = title.lower()
    for site in _KNOWN_SITES:
        if site in low:
            return f"{process}|{site}"
    # Fall back to the last " - " part of the title (often the site/app name), digits removed.
    part = low.rsplit(" - ", 1)[-1] if " - " in low else low
    part = re.sub(r"[\d:]+", "", part).strip()[:40]
    return f"{process}|{part}"
