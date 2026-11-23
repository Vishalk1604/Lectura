"""Live preview of the class window with a draggable / resizable crop box."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import to_qimage
from .style import ACCENT

HANDLE = 9
MIN_SIZE = 30


class CropView(QWidget):
    cropChanged = Signal(tuple)  # (fx, fy, fw, fh) fractions of the window frame

    def __init__(self, parent=None):
        super().__init__(parent)
        self._img: QImage | None = None
        self._frac = (0.0, 0.0, 1.0, 1.0)
        self._mode = None          # "move", "new", or a set of edges like {"l","t"}
        self._press = QPointF()
        self._start_rect = QRectF()
        self.placeholder = "Pick the class window above to see it here"
        self.editable = True
        self.setMouseTracking(True)
        self.setMinimumSize(520, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    # ------------------------------------------------------------------ API
    def set_frame(self, bgr: np.ndarray | None) -> None:
        if bgr is None:
            self._img = None
        else:
            h, w = bgr.shape[:2]
            if w > 1600:  # downscale for cheap drawing
                import cv2
                bgr = cv2.resize(bgr, (1600, int(h * 1600 / w)), interpolation=cv2.INTER_AREA)
            self._img = to_qimage(bgr)
        self.update()

    def has_frame(self) -> bool:
        return self._img is not None

    def set_crop(self, frac, emit: bool = False) -> None:
        self._frac = tuple(float(v) for v in frac)
        self.update()
        if emit:
            self.cropChanged.emit(self._frac)

    def crop(self) -> tuple:
        return self._frac

    # ------------------------------------------------------------------ geometry
    def _img_rect(self) -> QRectF:
        if self._img is None:
            return QRectF(self.rect())
        iw, ih = self._img.width(), self._img.height()
        W, H = self.width() - 4, self.height() - 4
        s = min(W / iw, H / ih)
        w, h = iw * s, ih * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _crop_rect(self) -> QRectF:
        r = self._img_rect()
        fx, fy, fw, fh = self._frac
        return QRectF(r.x() + fx * r.width(), r.y() + fy * r.height(),
                      fw * r.width(), fh * r.height())

    def _set_from_rect(self, cr: QRectF) -> None:
        r = self._img_rect()
        cr = cr.normalized().intersected(r)
        if r.width() <= 0 or r.height() <= 0:
            return
        self._frac = ((cr.x() - r.x()) / r.width(), (cr.y() - r.y()) / r.height(),
                      cr.width() / r.width(), cr.height() / r.height())
        self.update()

    def _edges_at(self, p: QPointF) -> set:
        cr = self._crop_rect()
        edges = set()
        inside_y = cr.top() - HANDLE <= p.y() <= cr.bottom() + HANDLE
        inside_x = cr.left() - HANDLE <= p.x() <= cr.right() + HANDLE
        if inside_y and abs(p.x() - cr.left()) <= HANDLE:
            edges.add("l")
        if inside_y and abs(p.x() - cr.right()) <= HANDLE:
            edges.add("r")
        if inside_x and abs(p.y() - cr.top()) <= HANDLE:
            edges.add("t")
        if inside_x and abs(p.y() - cr.bottom()) <= HANDLE:
            edges.add("b")
        return edges

    # ------------------------------------------------------------------ painting
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#1c1d24"))
        if self._img is None:
            p.setPen(QColor("#9ea3b5"))
            f = QFont(self.font())
            f.setPointSize(11)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.placeholder)
            return
        r = self._img_rect()
        p.drawImage(r, self._img)
        cr = self._crop_rect()
        shade = QPainterPath()
        shade.addRect(r)
        hole = QPainterPath()
        hole.addRect(cr)
        p.fillPath(shade.subtracted(hole), QColor(0, 0, 0, 140))
        pen = QPen(QColor(ACCENT), 2)
        p.setPen(pen)
        p.drawRect(cr)
        if self.editable:
            p.setBrush(QColor("white"))
            p.setPen(QPen(QColor(ACCENT), 2))
            for pt in (cr.topLeft(), cr.topRight(), cr.bottomLeft(), cr.bottomRight()):
                p.drawEllipse(pt, 5, 5)

    # ------------------------------------------------------------------ mouse
    def _cursor_for(self, edges: set):
        if edges in ({"l", "t"}, {"r", "b"}):
            return Qt.CursorShape.SizeFDiagCursor
        if edges in ({"r", "t"}, {"l", "b"}):
            return Qt.CursorShape.SizeBDiagCursor
        if edges & {"l", "r"}:
            return Qt.CursorShape.SizeHorCursor
        if edges & {"t", "b"}:
            return Qt.CursorShape.SizeVerCursor
        return None

    def mousePressEvent(self, e):
        if not self.editable or self._img is None or e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position()
        self._press = pos
        self._start_rect = self._crop_rect()
        edges = self._edges_at(pos)
        if edges:
            self._mode = edges
        elif self._start_rect.contains(pos):
            self._mode = "move"
        elif self._img_rect().contains(pos):
            self._mode = "new"
        else:
            self._mode = None

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._mode is None:
            if self.editable and self._img is not None:
                cur = self._cursor_for(self._edges_at(pos))
                if cur is None and self._crop_rect().contains(pos):
                    cur = Qt.CursorShape.SizeAllCursor
                self.setCursor(cur or Qt.CursorShape.CrossCursor)
            return
        r = self._img_rect()
        d = pos - self._press
        sr = QRectF(self._start_rect)
        if self._mode == "move":
            sr.translate(d)
            dx = max(r.left() - sr.left(), 0) + min(r.right() - sr.right(), 0)
            dy = max(r.top() - sr.top(), 0) + min(r.bottom() - sr.bottom(), 0)
            sr.translate(dx, dy)
        elif self._mode == "new":
            sr = QRectF(self._press, pos).normalized()
        else:
            if "l" in self._mode:
                sr.setLeft(min(sr.left() + d.x(), sr.right() - MIN_SIZE))
            if "r" in self._mode:
                sr.setRight(max(sr.right() + d.x(), sr.left() + MIN_SIZE))
            if "t" in self._mode:
                sr.setTop(min(sr.top() + d.y(), sr.bottom() - MIN_SIZE))
            if "b" in self._mode:
                sr.setBottom(max(sr.bottom() + d.y(), sr.top() + MIN_SIZE))
        self._set_from_rect(sr)

    def mouseReleaseEvent(self, e):
        if self._mode is None:
            return
        mode = self._mode
        self._mode = None
        cr = self._crop_rect()
        if mode == "new" and (cr.width() < MIN_SIZE or cr.height() < MIN_SIZE):
            self._set_from_rect(self._start_rect)  # a click, not a drag
            return
        self.cropChanged.emit(self._frac)
