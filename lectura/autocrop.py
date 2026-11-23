"""Find the shared-screen / slide rectangle inside a window, and trim letterbox bars."""

from __future__ import annotations

import cv2
import numpy as np

Rect = tuple[int, int, int, int]  # x, y, w, h

STANDARD_RATIOS = (4 / 3, 16 / 9, 16 / 10, 3 / 2, 5 / 4, 21 / 9, 1.0)


# ------------------------------------------------------------------ letterbox trim

def _uniform_run(lines: np.ndarray, tol: float) -> int:
    """Number of leading lines (rows of `lines`) that are uniform and of one colour."""
    if len(lines) == 0:
        return 0
    ref = np.median(lines[0])
    n = 0
    for line in lines:
        if line.std() > tol or abs(float(np.median(line)) - ref) > 6:
            break
        n += 1
    return n


def _bar_width(lines: np.ndarray, tol: float, max_skip: int = 2) -> int:
    """Width of a uniform bar at the start of `lines`, ignoring up to `max_skip`
    blended boundary lines (anti-aliasing from scaling)."""
    for skip in range(max_skip + 1):
        n = _uniform_run(lines[skip:], tol)
        if n >= 3:
            return skip + n
    return 0


def _near_standard(ratio: float, tol: float = 0.03) -> bool:
    return any(abs(ratio - r) / r <= tol for r in STANDARD_RATIOS)


def find_letterbox(img: np.ndarray, tol: float = 3.0) -> Rect | None:
    """Inner content rect if the image has symmetric uniform bars around a
    standard-ratio picture (black bars of a shared screen); otherwise None.

    The symmetry + standard-ratio rule stops it from cropping a whiteboard or
    blackboard down to the ink.
    """
    g = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = g.astype(np.float32)
    h, w = g.shape
    if h < 40 or w < 40:
        return None
    top = _bar_width(g, tol)
    bottom = _bar_width(g[::-1], tol)
    left = _bar_width(g.T, tol)
    right = _bar_width(g.T[::-1], tol)
    if top >= h // 2 or left >= w // 2:
        return None  # whole image uniform

    def symmetric(a: int, b: int, size: int) -> bool:
        return a > 2 and b > 2 and abs(a - b) <= max(4, int(0.02 * size))

    options: list[Rect] = []
    lr = symmetric(left, right, w)
    tb = symmetric(top, bottom, h)
    if lr:
        options.append((left, 0, w - left - right, h))
    if tb:
        options.append((0, top, w, h - top - bottom))
    if lr and tb:
        options.append((left, top, w - left - right, h - top - bottom))
    best = None
    for x, y, rw, rh in options:
        if rw * rh < 0.35 * w * h or rw <= 0 or rh <= 0:
            continue
        if not _near_standard(rw / rh):
            continue
        if best is None or rw * rh < best[2] * best[3]:
            best = (x, y, rw, rh)
    return best


def trim_uniform_border(img: np.ndarray) -> np.ndarray:
    box = find_letterbox(img)
    if box is None:
        return img
    x, y, w, h = box
    return img[y:y + h, x:x + w].copy()


# ------------------------------------------------------------------ content rect

def _candidates(gray: np.ndarray) -> list[Rect]:
    h, w = gray.shape
    rects: list[Rect] = []

    # 1) Regions that differ from the window background colour (Meet tiles, slide boxes).
    border = np.concatenate([gray[0], gray[-1], gray[:, 0], gray[:, -1]])
    for bg in {int(np.bincount(border, minlength=256).argmax()),
               int(np.bincount(gray[h // 8:].ravel(), minlength=256).argmax())}:
        fg = (np.abs(gray.astype(np.int16) - bg) > 10).astype(np.uint8)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        n, _, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=4)
        for i in range(1, n):
            x, y, rw, rh, area = stats[i]
            rects.append((int(x), int(y), int(rw), int(rh)))

    # 2) Strong straight-edged rectangles.
    edges = cv2.Canny(gray, 40, 120)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for c in contours:
        x, y, rw, rh = cv2.boundingRect(c)
        if rw * rh < 0.1 * w * h:
            continue
        approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(approx) == 4:
            rects.append((x, y, rw, rh))
    return rects


def _edge_support(gray: np.ndarray, r: Rect) -> float:
    """How strongly the rectangle's outline is visible (0..1)."""
    x, y, rw, rh = r
    h, w = gray.shape
    g = gray.astype(np.int16)
    scores = []
    if y >= 2:
        scores.append(np.mean(np.abs(g[y, x:x + rw] - g[y - 2, x:x + rw]) > 8))
    if y + rh + 1 < h:
        scores.append(np.mean(np.abs(g[y + rh - 1, x:x + rw] - g[y + rh + 1, x:x + rw]) > 8))
    if x >= 2:
        scores.append(np.mean(np.abs(g[y:y + rh, x] - g[y:y + rh, x - 2]) > 8))
    if x + rw + 1 < w:
        scores.append(np.mean(np.abs(g[y:y + rh, x + rw - 1] - g[y:y + rh, x + rw + 1]) > 8))
    return float(np.mean(scores)) if scores else 0.0


def detect_content_rect(frame: np.ndarray) -> Rect:
    """Best guess of the slide / shared-screen area in a full window frame."""
    h0, w0 = frame.shape[:2]
    scale = min(1.0, 960 / w0)
    small = cv2.resize(frame, (max(1, int(w0 * scale)), max(1, int(h0 * scale))),
                       interpolation=cv2.INTER_AREA) if scale < 1 else frame
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
    h, w = gray.shape

    def expanded():
        """Each candidate, plus the picture inside it if it has letterbox bars
        (a tall black Meet tile holding a 16:9 slide is itself not slide-shaped)."""
        for r in _candidates(gray):
            yield r, False
            x, y, rw, rh = r
            inner = find_letterbox(gray[y:y + rh, x:x + rw])
            if inner is not None:
                ix, iy, iw, ih = inner
                yield (x + ix, y + iy, iw, ih), True

    best, best_score = None, 0.0
    seen = set()
    for r, from_letterbox in expanded():
        x, y, rw, rh = r
        key = (x // 4, y // 4, rw // 4, rh // 4)
        if key in seen:
            continue
        seen.add(key)
        area = rw * rh / (w * h)
        if area < (0.06 if from_letterbox else 0.15) or area > 0.98:
            continue
        ratio = rw / rh
        if not 0.9 <= ratio <= 2.6:
            continue
        support = _edge_support(gray, r)
        ratio_bonus = 1.15 if _near_standard(ratio, 0.04) else 1.0
        score = area * (0.4 + support) * ratio_bonus
        # The whole web-page area (touching the window's sides and bottom) is almost never
        # the slide itself; prefer a tile inside it.
        touches = sum((x <= 3, y <= 3, x + rw >= w - 3, y + rh >= h - 3))
        if touches >= 3:
            score *= 0.12
        if score > best_score:
            best, best_score = r, score

    if best is None:
        return (0, 0, w0, h0)
    x, y, rw, rh = best
    # back to full resolution
    x, y = int(round(x / scale)), int(round(y / scale))
    rw, rh = int(round(rw / scale)), int(round(rh / scale))
    x, y = max(0, x), max(0, y)
    rw, rh = min(rw, w0 - x), min(rh, h0 - y)
    inner = find_letterbox(frame[y:y + rh, x:x + rw])
    if inner is not None:
        ix, iy, iw, ih = inner
        x, y, rw, rh = x + ix, y + iy, iw, ih
    return (x, y, rw, rh)


# ------------------------------------------------------------------ relative rects

def to_fraction(rect: Rect, frame_w: int, frame_h: int) -> tuple[float, float, float, float]:
    x, y, w, h = rect
    return (x / frame_w, y / frame_h, w / frame_w, h / frame_h)


def from_fraction(frac, frame_w: int, frame_h: int) -> Rect:
    fx, fy, fw, fh = frac
    x, y = int(round(fx * frame_w)), int(round(fy * frame_h))
    w, h = int(round(fw * frame_w)), int(round(fh * frame_h))
    x, y = min(max(0, x), frame_w - 1), min(max(0, y), frame_h - 1)
    return (x, y, max(1, min(w, frame_w - x)), max(1, min(h, frame_h - y)))
