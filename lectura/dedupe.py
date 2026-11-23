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


def content_mask(g: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    bg = background_level(g, mask)
    c = np.abs(g.astype(np.int16) - bg) > CONTENT_T
    return c & mask if mask is not None else c


def is_blank(img: np.ndarray) -> bool:
    """True for empty pages: a uniform frame or one with almost no content."""
    fp = _fingerprint(img)
    if fp.std() < 3:
        return True
    return content_mask(fp).mean() < 0.002


class Deduper:
    """Remembers committed captures and flags ones that add nothing new.

    A capture is redundant when its content is already present in an earlier
    capture: an identical revisit, or a revisit whose slide build has not finished
    yet (fewer bullets than the earlier capture).
    """

    def __init__(self, tolerance: float = 0.04):
        self.tolerance = tolerance
        self._fps: list[np.ndarray] = []

    def __len__(self) -> int:
        return len(self._fps)

    def clear(self) -> None:
        self._fps.clear()

    def add(self, img: np.ndarray) -> None:
        self._fps.append(_fingerprint(img))

    def remove_at(self, index: int) -> None:
        if 0 <= index < len(self._fps):
            del self._fps[index]

    def is_redundant(self, img: np.ndarray) -> bool:
        fp = _fingerprint(img)
        content = content_mask(fp)
        n_content = int(content.sum())
        for old in self._fps:
            if old.shape != fp.shape:
                if abs(old.shape[0] - fp.shape[0]) > 2:
                    continue  # different aspect ratio: different crop, not comparable
                old = cv2.resize(old, (fp.shape[1], fp.shape[0]), interpolation=cv2.INTER_AREA)
            diff = cv2.absdiff(fp, old) > DIFF_T
            if n_content == 0:
                if diff.mean() < 0.005:
                    return True
                continue
            missing = int((diff & content).sum())  # content of the new image not in the old one
            if missing / n_content < self.tolerance and diff.mean() < 0.35:
                return True
        return False
