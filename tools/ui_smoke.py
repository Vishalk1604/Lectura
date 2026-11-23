"""Drive the real Lectura window end to end against tools/class_sim.html.

    .venv\\Scripts\\python.exe tools\\ui_smoke.py <out-folder> main
    .venv\\Scripts\\python.exe tools\\ui_smoke.py <out-folder> crash     (kills itself mid-recording)
    .venv\\Scripts\\python.exe tools\\ui_smoke.py <out-folder> recover   (relaunch: recovery prompt)

Settings, sessions and saved files all go under <out-folder>, never the real app data.
Screenshots of every screen are written there as <phase>_NN_name.png.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

OUT = Path(sys.argv[1]).resolve()
PHASE = sys.argv[2] if len(sys.argv) > 2 else "main"
OUT.mkdir(parents=True, exist_ok=True)
os.environ["LOCALAPPDATA"] = str(OUT / "local")     # sessions
os.environ["APPDATA"] = str(OUT / "roaming")        # settings.json
os.environ["LECTURA_DEBUG"] = "1"
(OUT / f"frames_{PHASE}").mkdir(exist_ok=True)
os.environ["LECTURA_DUMP_FRAMES"] = str(OUT / f"frames_{PHASE}")  # replay: tools/replay.py
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lectura import winlist  # noqa: E402

winlist.set_dpi_aware()

from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from lectura.settings import Settings  # noqa: E402
from lectura.ui import app_icon, resource_path  # noqa: E402
from lectura.ui.main_window import MainWindow  # noqa: E402
from lectura.ui.review_dialog import ImageViewer, ReviewDialog  # noqa: E402
from lectura.ui.save_dialog import SaveDialog  # noqa: E402
from lectura.ui.style import QSS  # noqa: E402

TITLE = "Lectura class simulator"
LOG = open(OUT / f"{PHASE}.log", "w", encoding="utf-8")
PROBLEMS: list[str] = []
_shot_n = [0]


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.write(s + "\n")
    LOG.flush()


def check(ok: bool, what: str):
    log(("  OK   " if ok else "  FAIL ") + what)
    if not ok:
        PROBLEMS.append(what)


def shot(widget, name: str):
    _shot_n[0] += 1
    widget.grab().save(str(OUT / f"{PHASE}_{_shot_n[0]:02d}_{name}.png"))


def modal():
    return QApplication.activeModalWidget()


def button(widget, starts: str) -> QPushButton:
    for b in widget.findChildren(QPushButton):
        if b.text().replace("&", "").startswith(starts):
            return b
    raise LookupError(starts)


def fmt(frac):
    return "(" + ", ".join(f"{v:.3f}" for v in frac) + ")"


def launch_sim() -> int:
    url = (ROOT / "tools" / "class_sim.html").as_uri()
    subprocess.Popen(["cmd", "/c", "start", "", "msedge", f"--user-data-dir={OUT / 'edge-profile'}",
                      "--no-first-run", "--no-default-browser-check",
                      "--disable-features=CalculateNativeWinOcclusion",
                      "--disable-backgrounding-occluded-windows", "--new-window", url])
    for _ in range(60):
        for w in winlist.list_windows():
            if TITLE in w.title:
                ctypes.windll.user32.SetWindowPos(w.hwnd, 0, 40, 40, 1600, 950, 0x0004 | 0x0010)
                return w.hwnd
        time.sleep(0.5)
    raise SystemExit("simulator window not found")


def close_sim(hwnd):
    if hwnd:
        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)


def select_sim(win: MainWindow):
    win.refresh_windows()
    idx = next(i for i, w in enumerate(win._windows) if TITLE in w.title)
    win.combo.setCurrentIndex(idx)


def press_hotkey():
    keys = (0x11, 0x12, 0x53)  # Ctrl, Alt, S
    for vk in keys:
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(keys):
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)


def save_via_dialog(formats: list[str], name: str):
    sd = modal()
    check(isinstance(sd, SaveDialog), "save dialog opens after review")
    for key, cb in sd.checks.items():
        cb.setChecked(key in formats)
    sd.folder.setText(str(OUT / "saved"))
    sd.name.setText(name)
    shot(sd, "save_dialog")
    sd.btn_save.click()


# ---------------------------------------------------------------------- scripts

def main_script(win: MainWindow, app, sim):
    select_sim(win)
    yield 4000
    shot(win, "preview_autocrop")
    c0 = win.view.crop()
    log("crop after auto-detect", fmt(c0))
    check(0.05 < c0[2] < 0.95 and 0.05 < c0[3] < 0.95, "auto-detect picks an inner area")

    v = win.view
    p0 = v._crop_rect().bottomRight().toPoint() - QPoint(1, 1)
    p1 = p0 - QPoint(80, 50)
    QTest.mousePress(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p0)
    for k in range(1, 6):
        QTest.mouseMove(v, p0 + (p1 - p0) * k / 5)
    QTest.mouseRelease(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p1)
    yield 400
    c1 = win.view.crop()
    log("crop after dragging the corner", fmt(c1))
    shot(win, "crop_dragged")
    check(c1[2] < c0[2] - 0.02 and c1[3] < c0[3] - 0.02 and abs(c1[0] - c0[0]) < 0.005,
          "dragging the corner resizes the box")
    win.btn_detect.click()
    yield 600
    log("crop after Auto-detect again", fmt(win.view.crop()))
    check(max(abs(a - b) for a, b in zip(win.view.crop(), c0)) < 0.01, "Auto-detect restores the box")

    win.btn_start.click()
    yield 20000
    shot(win, "recording")
    log("status:", win.status.text())
    check("Recording" in win.status.text(), "status shows Recording")
    check(win._core.count >= 1, f"captures while recording ({win._core.count})")

    win.btn_pause.click()
    yield 2500
    shot(win, "paused")
    log("status:", win.status.text())
    check("Paused" in win.status.text() and win.btn_pause.text() == "Resume", "Pause works")
    win.btn_pause.click()
    yield 1500
    check("Recording" in win.status.text(), "Resume works")

    before = win._core.count
    if win.hotkey.ok:
        press_hotkey()
        log("pressed Ctrl+Alt+S")
    else:
        log("hotkey not registered:", win.hotkey.error)
        win.btn_capture.click()
    yield 2500
    forced = [i for i in win._core.session.items if i.forced]
    check(win._core.count == before + 1 and len(forced) == 1, "Capture-now hotkey saves the screen")
    yield 14000

    win.btn_stop.click()
    yield 3500
    rv = modal()
    check(isinstance(rv, ReviewDialog), "review opens after Stop")
    n0 = rv.list.count()
    log("review shows", n0, "captures")
    shot(rv, "review")
    row = next(i for i in range(n0) if rv.list.item(i).data(Qt.ItemDataRole.UserRole).forced)
    rv.list.clearSelection()
    rv.list.setCurrentRow(row)
    rv.activateWindow()
    rv.list.setFocus()
    QTest.keyClick(rv.list, Qt.Key.Key_Delete)
    yield 400
    if rv.list.count() == n0:
        log("  (Delete key did not reach the dialog; using the button)")
        rv.btn_delete.click()
        yield 300
    check(rv.list.count() == n0 - 1, "deleting the manual capture")
    first_before = rv.list.item(0).data(Qt.ItemDataRole.UserRole).file
    moved = rv.list.takeItem(rv.list.count() - 1)
    rv.list.insertItem(0, moved)
    rv.renumber()
    yield 300
    shot(rv, "review_edited")
    check(rv.list.item(1).data(Qt.ItemDataRole.UserRole).file == first_before
          and rv.list.item(0).text().startswith("1"), "reorder + renumber")

    QTimer.singleShot(0, lambda: rv.open_viewer(rv.list.item(0)))
    yield 1500
    vw = modal()
    check(isinstance(vw, ImageViewer), "double-click opens the viewer")
    shot(vw, "viewer")
    QTest.keyClick(vw, Qt.Key.Key_Right)
    yield 500
    check(vw.index == 1, "arrow key moves to the next capture")
    shot(vw, "viewer_next")
    vw.close()
    yield 500
    order = [rv.list.item(i).data(Qt.ItemDataRole.UserRole).file for i in range(rv.list.count())]

    rv.btn_save.click()
    yield 1200
    save_via_dialog(["pptx", "docx", "pdf"], "Walkthrough class")
    yield 7000
    box = modal()
    shot(box, "saved_message")
    log("message:", box.text().replace("\n", " | "))
    button(box, "Done").click()
    yield 1500
    saved = sorted(p.name for p in (OUT / "saved").iterdir())
    log("saved files:", saved)
    check(saved == ["Walkthrough class.docx", "Walkthrough class.pdf", "Walkthrough class.pptx"],
          "all three files saved")
    session = win.settings  # noqa: F841 - settings persisted?
    s2 = Settings.load()
    check(s2.formats == ["pptx", "docx", "pdf"] and s2.last_folder == str(OUT / "saved"),
          "save choices remembered")
    sessions = list((OUT / "local" / "Lectura" / "sessions").iterdir())
    import json
    meta = json.loads((sessions[0] / "session.json").read_text(encoding="utf-8"))
    check(meta.get("exported") and [i["file"] for i in meta["items"]] == order,
          "session marked saved, review order kept")
    shot(win, "back_to_ready")
    close_sim(sim)
    win.close()
    yield 800
    app.quit()


def crash_script(win: MainWindow, app, sim):
    select_sim(win)
    yield 4000
    win.btn_start.click()
    yield 26000
    sess = win._core.session
    log("captures before the crash:", win._core.count,
        "| in-progress page on disk:", (sess.folder / "pending.png").exists())
    close_sim(sim)
    LOG.flush()
    os._exit(3)  # simulate the app being killed mid-class


def recover_script(win: MainWindow, app, sim):
    QTimer.singleShot(0, win.check_recovery)
    yield 2000
    box = modal()
    check(box is not None and "unsaved captures" in box.text(), "recovery prompt on relaunch")
    shot(box, "recovery_prompt")
    log("prompt:", box.text().replace("\n", " | "))
    button(box, "Review").click()
    yield 2000
    rv = modal()
    check(isinstance(rv, ReviewDialog), "recovered captures open in review")
    log("recovered captures:", rv.list.count())
    shot(rv, "recovered_review")
    rv.btn_save.click()
    yield 1200
    save_via_dialog(["pdf"], "Recovered class")
    yield 5000
    box = modal()
    button(box, "Done").click()
    yield 1000
    check((OUT / "saved" / "Recovered class.pdf").exists(), "recovered class saved as PDF")
    win.close()
    yield 500
    app.quit()


def main() -> int:
    sim = launch_sim() if PHASE in ("main", "crash") else 0
    if sim:
        time.sleep(2.5)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS.replace("__CHEVRON__", resource_path("assets/chevron.png").as_posix()))
    app.setWindowIcon(app_icon())
    win = MainWindow(Settings.load())
    win.show()
    script = {"main": main_script, "crash": crash_script, "recover": recover_script}[PHASE]
    gen = script(win, app, sim)

    def tick():
        try:
            delay = next(gen)
        except StopIteration:
            return
        except Exception as e:  # report and stop
            import traceback
            log("SCRIPT ERROR:", "".join(traceback.format_exception(e)))
            PROBLEMS.append(f"script error: {e}")
            close_sim(sim)
            app.quit()
            return
        QTimer.singleShot(delay, tick)

    QTimer.singleShot(500, tick)
    app.exec()
    log(f"\n{PHASE}: {'PASS' if not PROBLEMS else 'PROBLEMS: ' + '; '.join(PROBLEMS)}")
    return 0 if not PROBLEMS else 2


if __name__ == "__main__":
    sys.exit(main())
