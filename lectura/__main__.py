"""Entry point: python -m lectura"""

from __future__ import annotations

import sys


def main() -> int:
    from . import APP_NAME, winlist
    winlist.set_dpi_aware()

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from .settings import Settings
    from .ui import app_icon, resource_path
    from .ui.main_window import MainWindow
    from .ui.style import QSS

    try:  # own taskbar icon instead of python's
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Lectura.ClassCapture")
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS.replace("__CHEVRON__", resource_path("assets/chevron.png").as_posix()))
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(True)

    win = MainWindow(Settings.load())
    win.show()
    QTimer.singleShot(400, win.check_recovery)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
