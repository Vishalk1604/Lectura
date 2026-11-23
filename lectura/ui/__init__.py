"""Qt user interface."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PySide6.QtGui import QIcon, QImage


def resource_path(rel: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / rel


def app_icon() -> QIcon:
    p = resource_path("assets/lectura.ico")
    return QIcon(str(p)) if p.exists() else QIcon()


def to_qimage(bgr: np.ndarray) -> QImage:
    bgr = np.ascontiguousarray(bgr)
    h, w = bgr.shape[:2]
    return QImage(bgr.data, w, h, 3 * w, QImage.Format.Format_BGR888).copy()
