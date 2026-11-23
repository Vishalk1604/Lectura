"""Synthetic class frames for detector tests."""

from __future__ import annotations

import cv2
import numpy as np

W, H = 1280, 720
FONT = cv2.FONT_HERSHEY_SIMPLEX


def slide(slide_id: int, bullets: int = 3, w: int = W, h: int = H,
          bg=(255, 255, 255), fg=(30, 30, 30)) -> np.ndarray:
    img = np.full((h, w, 3), bg, np.uint8)
    cv2.putText(img, f"Lecture topic {slide_id}: overview", (60, 110), FONT, 1.8, fg, 4)
    rng = np.random.default_rng(slide_id)
    for i in range(bullets):
        y = 220 + i * 110
        words = " ".join("".join(chr(97 + c) for c in rng.integers(0, 26, rng.integers(3, 8)))
                         for _ in range(5))
        cv2.circle(img, (80, y - 12), 8, fg, -1)
        cv2.putText(img, words, (110, y), FONT, 1.3, fg, 3)
    return img


def strokes(n: int, seed: int = 0, w: int = W, h: int = H, top: int = 40) -> list:
    """n handwriting-like strokes laid out in rows."""
    rng = np.random.default_rng(seed)
    out = []
    per_row = 6
    for i in range(n):
        row, col = divmod(i, per_row)
        x0 = 60 + col * 190
        y0 = top + 70 + row * 90
        pts = [(x0, y0)]
        for _ in range(12):
            px, py = pts[-1]
            pts.append((int(px + rng.integers(5, 15)), int(y0 + rng.integers(-25, 25))))
        out.append(np.array(pts, np.int32))
    return out


def board(stroke_list, w: int = W, h: int = H, bg=(250, 250, 250), ink=(20, 20, 160)):
    img = np.full((h, w, 3), bg, np.uint8)
    for s in stroke_list:
        cv2.polylines(img, [s], False, ink, 4, cv2.LINE_AA)
    return img


def with_cursor(img: np.ndarray, t: float) -> np.ndarray:
    out = img.copy()
    x = int(300 + 250 * np.sin(t * 0.7))
    y = int(400 + 150 * np.cos(t * 0.9))
    pts = np.array([(x, y), (x, y + 22), (x + 6, y + 16), (x + 14, y + 16)], np.int32)
    cv2.fillPoly(out, [pts], (0, 0, 0))
    return out


def with_webcam(img: np.ndarray, t: float, rng=None) -> np.ndarray:
    """Moving 'face' video in the bottom-right corner."""
    out = img.copy()
    rng = rng or np.random.default_rng(int(t * 1000))
    h, w = out.shape[:2]
    x0, y0, x1, y1 = w - 260, h - 200, w - 20, h - 20
    patch = rng.integers(60, 200, (y1 - y0, x1 - x0, 3), dtype=np.uint8)
    patch = cv2.GaussianBlur(patch, (9, 9), 0)
    cx = int(120 + 30 * np.sin(t * 3))
    cv2.circle(patch, (cx, 90), 50, (90, 140, 200), -1)
    out[y0:y1, x0:x1] = patch
    return out


def noisy(img: np.ndarray, t: float, amp: int = 5) -> np.ndarray:
    """Video-compression-like noise."""
    rng = np.random.default_rng(int(t * 997) % (2**31))
    n = rng.integers(-amp, amp + 1, img.shape, dtype=np.int16)
    return np.clip(img.astype(np.int16) + n, 0, 255).astype(np.uint8)


def blend(a: np.ndarray, b: np.ndarray, k: float) -> np.ndarray:
    return cv2.addWeighted(a, 1 - k, b, k, 0)


def meet_layout(content: np.ndarray, w: int = 1600, h: int = 1000):
    """A Meet-like browser window: toolbar, dark background, presentation tile with
    letterboxed content, participant tiles, control bar. Returns (frame, content_rect)."""
    frame = np.full((h, w, 3), (36, 33, 32), np.uint8)  # #202124 in BGR-ish
    # browser toolbar
    frame[:88] = (60, 60, 60)
    cv2.rectangle(frame, (120, 50), (900, 78), (90, 90, 90), -1)
    cv2.putText(frame, "meet.google.com/abc-defg-hij", (135, 72), FONT, 0.6, (230, 230, 230), 1)
    # presentation tile 1180x700 at (30,110), black letterbox
    tx, ty, tw, th = 30, 110, 1180, 720
    cv2.rectangle(frame, (tx, ty), (tx + tw - 1, ty + th - 1), (0, 0, 0), -1)
    ch = th
    cw = int(round(ch * content.shape[1] / content.shape[0]))
    if cw > tw:
        cw = tw
        ch = int(round(cw * content.shape[0] / content.shape[1]))
    cx, cy = tx + (tw - cw) // 2, ty + (th - ch) // 2
    frame[cy:cy + ch, cx:cx + cw] = cv2.resize(content, (cw, ch), interpolation=cv2.INTER_AREA)
    # participant tiles
    rng = np.random.default_rng(3)
    for i in range(3):
        px, py = 1240, 110 + i * 240
        tile = rng.integers(40, 160, (200, 330, 3), dtype=np.uint8)
        frame[py:py + 200, px:px + 330] = cv2.GaussianBlur(tile, (15, 15), 0)
    # control bar
    for i in range(7):
        cv2.circle(frame, (560 + i * 70, 930), 24, (70, 70, 75), -1)
    return frame, (cx, cy, cw, ch)
