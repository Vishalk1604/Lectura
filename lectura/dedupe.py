"""Blank-frame and near-duplicate checks for committed captures."""

from __future__ import annotations

import cv2
import numpy as np

FP_WIDTH = 320          # fingerprint width (px)
DIFF_T = 30             # gray difference that counts as "different"
CONTENT_T = 30          # gray distance from background that counts as content


def _fingerprint(img: np.ndarray) -> np.ndarray:
    g = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = g.shape
    fh = max(1, round(h * FP_WIDTH / w))
    g = cv2.resize(g, (FP_WIDTH, fh), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(g, (3, 3), 0)


def background_level(g: np.ndarray, mask: np.ndarray | None = None) -> int:
    vals = g[mask] if mask is not None else g.ravel()
    if vals.size == 0:
        return 0
    return int(np.bincount(vals, minlength=256).argmax())


def changed_pixels(a: np.ndarray, b: np.ndarray, mask: np.ndarray | None = None,
                   t: int = DIFF_T) -> np.ndarray:
    """Pixels that differ between two gray frames, after matching brightness.

    If `b` is `a` with an overall brightness/contrast change (a dimming popup, a
    darker video frame), a straight-line fit b ~ k*a + c undoes it. The fitted version
    is only used when it explains the frames better, so genuinely different content
    (which no brightness change can turn into each other) still shows up as changed.
    """
    plain = cv2.absdiff(a, b) > t
    if mask is not None:
        plain &= mask
    xs = (a[mask] if mask is not None else a.ravel())[::7].astype(np.float32)
    ys = (b[mask] if mask is not None else b.ravel())[::7].astype(np.float32)
    if xs.size < 50 or xs.std() < 5:
        return plain
    k, c = np.polyfit(xs, ys, 1)
    if not 0.3 <= k <= 3.0:
        return plain
    mapped = np.clip(a.astype(np.float32) * k + c, 0, 255).astype(np.uint8)
    fitted = cv2.absdiff(mapped, b) > t
    if mask is not None:
        fitted &= mask
    return fitted if fitted.sum() < plain.sum() else plain


def ink_mask(g: np.ndarray, mask: np.ndarray | None = None, k: int | None = None,
             t: int = CONTENT_T) -> np.ndarray:
    """Fine detail: text, handwriting, chalk, thin lines (dark-on-light and light-on-dark).

    Uses morphological top-hats, so large flat areas (page background, black letterbox
    bars, an empty board) never count as content, whatever their colour.
    """
    if k is None:
        k = max(5, int(round(g.shape[1] / 60)) | 1)  # ~11 px at 640 wide
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    dark = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, kernel)   # dark strokes on light
    light = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, kernel)    # light strokes on dark
    c = (dark > t) | (light > t)
    return c & mask if mask is not None else c


def content_mask(g: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    return ink_mask(g, mask)


def is_blank(img: np.ndarray) -> bool:
    """True for empty pages: a uniform frame or one with almost no content."""
    fp = _fingerprint(img)
    if fp.std() < 3:
        return True
    return content_mask(fp).mean() < 0.0015


class Deduper:
    """Remembers committed captures and flags ones that add nothing new.

    A capture is redundant when its content is already present in an earlier
    capture: an identical revisit, or a revisit whose slide build has not finished
    yet (fewer bullets than the earlier capture).
    """

    def __init__(self, tolerance: float = 0.04):
        self.tolerance = tolerance
        self._entries: list[tuple[np.ndarray, np.ndarray, float]] = []  # fp, dilated ink, density

    def __len__(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries.clear()

    def add(self, img: np.ndarray) -> None:
        fp = _fingerprint(img)
        self._entries.append((fp, content_mask(fp), float(content_mask(fp).mean())))

    def remove_at(self, index: int) -> None:
        if 0 <= index < len(self._entries):
            del self._entries[index]

    def is_redundant(self, img: np.ndarray) -> bool:
        """Is every bit of ink in `img` already in one earlier capture?

        Brightness is matched first, so a dimmed or brighter copy of a slide still matches.
        """
        fp = _fingerprint(img)
        ink = content_mask(fp)
        n_ink = int(ink.sum())
        density = n_ink / ink.size
        for old_fp, _old_ink, old_density in self._entries:
            if old_fp.shape != fp.shape:
                if abs(old_fp.shape[0] - fp.shape[0]) > 2:
                    continue  # different aspect ratio: different crop, not comparable
                old_fp = cv2.resize(old_fp, (fp.shape[1], fp.shape[0]),
                                    interpolation=cv2.INTER_AREA)
            diff = changed_pixels(old_fp, fp)
            if n_ink == 0:
                if diff.mean() < 0.005:
                    return True
                continue
            # a busy picture would "contain" almost anything: only compare like with like
            if old_density > max(0.25, 4 * density):
                continue
            missing = int((diff & ink).sum())  # content of the new image not in the old one
            if missing / n_ink < self.tolerance and diff.mean() < 0.35:
                return True
        return False
