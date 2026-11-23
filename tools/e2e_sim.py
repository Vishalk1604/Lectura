"""End-to-end check: record tools/class_sim.html in a real Edge window that sits behind
other windows, then export all formats.

    .venv\\Scripts\\python.exe tools\\e2e_sim.py <output-folder>

Sessions are written under <output-folder>, not the real app data folder.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "test_output").resolve()
OUT.mkdir(parents=True, exist_ok=True)
os.environ["LOCALAPPDATA"] = str(OUT / "appdata")  # keep test sessions out of the real app
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from lectura import winlist  # noqa: E402
from lectura.autocrop import detect_content_rect, to_fraction  # noqa: E402
from lectura.capture import open_source  # noqa: E402
from lectura.recorder import RecorderCore  # noqa: E402
from lectura.session import Session  # noqa: E402
from lectura.ui.save_dialog import run_exports  # noqa: E402

TITLE = "Lectura class simulator"
EXPECTED = ["slide1", "slide2", "fade to slide3|revisit slide1", "board page 2|small erase",
            "scroll", "slide4", "done"]


def find_window(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for w in winlist.list_windows():
            if TITLE in w.title:
                return w
        time.sleep(0.5)
    return None


def main():
    winlist.set_dpi_aware()
    url = (ROOT / "tools" / "class_sim.html").as_uri()
    subprocess.Popen(["cmd", "/c", "start", "", "msedge", "--new-window", url])
    w = find_window()
    if w is None:
        print("simulator window not found")
        return 1
    hwnd = w.hwnd
    print("window:", w.label)
    # 1600x950, then send it behind every other window
    ctypes.windll.user32.ShowWindow(hwnd, 9)
    ctypes.windll.user32.SetWindowPos(hwnd, 1, 40, 40, 1600, 950, 0x0010)
    time.sleep(1.5)

    src = open_source(hwnd)
    print("capture backend:", src.name)
    frame = None
    for _ in range(40):
        frame = src.latest()
        if frame is not None:
            break
        time.sleep(0.1)
    assert frame is not None, "no frame"
    rect = detect_content_rect(frame)
    x, y, cw, ch = rect
    vis = frame.copy()
    cv2.rectangle(vis, (x, y), (x + cw, y + ch), (229, 70, 79), 4)
    cv2.imwrite(str(OUT / "autocrop.png"), vis)
    print("frame:", frame.shape, "autocrop:", rect, f"aspect {cw / ch:.3f}")

    session = Session.new(w.title)
    phases = []

    def on_capture(item, img):
        phase = winlist.get_title(hwnd).replace(TITLE, "").split(" - ")[1:2]
        phases.append(phase[0] if phase else "?")
        print(f"  capture {item.file} at {item.t:6.1f}s  phase={phases[-1]}  "
              f"size={img.shape[1]}x{img.shape[0]}{'  (forced)' if item.forced else ''}")

    core = RecorderCore(src, hwnd, session, crop_frac=to_fraction(rect, *frame.shape[1::-1]),
                        on_capture=on_capture, on_status=lambda s: print("  status:", s))
    th = threading.Thread(target=core.run, daemon=True)
    th.start()
    t0 = time.time()
    while time.time() - t0 < 200:
        if "- done" in winlist.get_title(hwnd):
            break
        time.sleep(0.5)
    print(f"timeline finished after {time.time() - t0:.0f}s, moving area "
          f"{core.pipeline.detector.moving_fraction:.1%}")
    core.stop()
    th.join(10)

    items = session.items
    print(f"\n{len(items)} captures (expected 7)")
    # contact sheet
    thumbs = []
    for it in items:
        im = cv2.imread(str(session.path_of(it)))
        im = cv2.resize(im, (480, int(im.shape[0] * 480 / im.shape[1])))
        cv2.putText(im, it.file, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        thumbs.append(im)
    if thumbs:
        rows = [np.hstack(thumbs[i:i + 3] + [np.zeros_like(thumbs[0])] * (3 - len(thumbs[i:i + 3])))
                for i in range(0, len(thumbs), 3)]
        cv2.imwrite(str(OUT / "contact_sheet.png"), np.vstack(rows))

    paths = run_exports(session, items, OUT / "exports", "Sim class", ["pptx", "docx", "pdf"],
                        True, "A4")
    for p in paths:
        print("exported", p.name, f"{p.stat().st_size / 1e6:.1f} MB")

    ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # close the simulator window
    ok = len(items) == 7
    print("RESULT:", "PASS" if ok else "CHECK", phases)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
