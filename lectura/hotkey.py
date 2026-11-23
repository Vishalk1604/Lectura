"""System-wide hotkey (works while another app is focused) via Win32 RegisterHotKey."""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

_MODS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT,
         "shift": MOD_SHIFT, "win": MOD_WIN}
_KEYS = {**{f"f{i}": 0x6F + i for i in range(1, 25)},
         "space": 0x20, "pause": 0x13, "insert": 0x2D, "home": 0x24, "end": 0x23,
         "pageup": 0x21, "pagedown": 0x22, "printscreen": 0x2C}


def parse(combo: str) -> tuple[int, int]:
    """'Ctrl+Alt+S' -> (modifiers, virtual key code)."""
    mods, vk = 0, 0
    for part in (p.strip().lower() for p in combo.split("+") if p.strip()):
        if part in _MODS:
            mods |= _MODS[part]
        elif part in _KEYS:
            vk = _KEYS[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        else:
            raise ValueError(f"Unknown key '{part}' in hotkey '{combo}'")
    if not vk:
        raise ValueError(f"No key in hotkey '{combo}'")
    return mods, vk


class GlobalHotkey:
    """Calls `callback` (from a background thread) when the combo is pressed."""

    def __init__(self, combo: str, callback: Callable[[], None]):
        self.combo = combo
        self.callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self.ok = False
        self.error = ""

    def start(self) -> bool:
        try:
            mods, vk = parse(self.combo)
        except ValueError as e:
            self.error = str(e)
            return False
        self._thread = threading.Thread(target=self._run, args=(mods, vk), daemon=True)
        self._thread.start()
        self._ready.wait(2)
        return self.ok

    def _run(self, mods: int, vk: int) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        self.ok = bool(user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk))
        if not self.ok:
            self.error = f"{self.combo} is already used by another app"
        self._ready.set()
        if not self.ok:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                try:
                    self.callback()
                except Exception:
                    pass
        user32.UnregisterHotKey(None, 1)

    def stop(self) -> None:
        if self._thread and self._thread.is_alive() and self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(1)
        self._thread = None
