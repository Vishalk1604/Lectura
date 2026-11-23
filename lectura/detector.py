"""Decide when a slide / whiteboard page is finished and should be saved.

Rule: keep the latest *settled* frame of the current page (P). When a settled frame
shows that the page was replaced (new slide, cleared board, new board page, a scroll
that hides the old writing), commit P - the fullest version of the old page - and
start a new page. Additions (bullets appearing, ink being written) and small erases
just update P, so nothing is captured while the teacher is still writing.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np

from .autocrop import trim_uniform_border
from .dedupe import Deduper, is_blank

DIFF_T = 25        # gray-level change that counts as a changed pixel
CONTENT_T = 30     # distance from background colour that counts as content (ink/text)


@dataclass
class Capture:
    image: np.ndarray   # full-resolution BGR
    t: float            # seconds since recording started when this page first settled
    forced: bool = False


def _lerp(a: float, b: float, s: float) -> float:
    return a + (b - a) * s


class SlideChangeDetector:
    def __init__(self, sensitivity: float = 0.5, analysis_width: int = 640,
                 settle_s: float = 1.5, block: int = 16,
                 motion_window: int = 20, motion_ratio: float = 0.6):
        self.analysis_width = analysis_width
        self.settle_s = settle_s
        self.block = block
        self.motion_window = motion_window
        self.motion_ratio = motion_ratio
        self.set_sensitivity(sensitivity)

        self._prev: np.ndarray | None = None
        self._anchor: np.ndarray | None = None
        self._stable_since = 0.0
        self._history: deque[np.ndarray] = deque(maxlen=motion_window)
        self._moving_blocks: np.ndarray | None = None

        self._latest: np.ndarray | None = None
        self._latest_t = 0.0
        self._page: np.ndarray | None = None        # full-res P
        self._page_g: np.ndarray | None = None      # analysis-res P
        self._page_t = 0.0
        self.page_version = 0                       # bumps whenever P changes

    # ------------------------------------------------------------------ config
    def set_sensitivity(self, s: float) -> None:
        """0 = only obvious changes, 1 = capture readily. 0.5 is the default."""
        s = min(1.0, max(0.0, s))
        self.sensitivity = s
        self.lost_threshold = _lerp(0.45, 0.12, s)       # share of old content gone
        self.lost_abs_threshold = _lerp(0.008, 0.002, s)  # ...and of the whole frame
        self.global_threshold = _lerp(0.6, 0.35, s)      # share of all pixels changed
        self.scroll_threshold = _lerp(0.2, 0.06, s)      # share of content scrolled away
        self.settle_threshold = 0.003

    # ------------------------------------------------------------------ helpers
    def _prep(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        aw = min(self.analysis_width, w)
        ah = max(8, round(h * aw / w))
        g = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        g = cv2.resize(g, (aw, ah), interpolation=cv2.INTER_AREA)
        return cv2.GaussianBlur(g, (3, 3), 0)

    def _block_sum(self, mask: np.ndarray) -> np.ndarray:
        b = self.block
        h, w = mask.shape
        m = np.pad(mask, ((0, -h % b), (0, -w % b)))
        return m.reshape(m.shape[0] // b, b, m.shape[1] // b, b).sum(axis=(1, 3))

    def _pixel_mask(self, shape) -> np.ndarray:
        """True where pixels are used (not inside a constantly-moving area)."""
        if self._moving_blocks is None or not self._moving_blocks.any():
            return np.ones(shape, bool)
        b = self.block
        m = np.repeat(np.repeat(self._moving_blocks, b, 0), b, 1)
        return ~m[: shape[0], : shape[1]]

    def reset_motion(self) -> None:
        """Forget short-term state (after pause/resume or a resize). Keeps the page."""
        self._prev = None
        self._anchor = None
        self._history.clear()
        self._moving_blocks = None

    # ------------------------------------------------------------------ main loop
    def feed(self, frame: np.ndarray, t: float) -> list[Capture]:
        """Process one sampled frame (BGR, already cropped). Returns committed pages."""
        g = self._prep(frame)
        self._latest, self._latest_t = frame, t
        if self._prev is not None and self._prev.shape != g.shape:
            self.reset_motion()

        # 1) constantly-moving areas (webcam bubble, video) -> ignored
        if self._prev is not None:
            changed = cv2.absdiff(g, self._prev) > DIFF_T
            self._history.append(self._block_sum(changed) > 4)
            if len(self._history) >= self.motion_window // 2:
                activity = np.mean(np.stack(self._history), axis=0)
                moving = (activity >= self.motion_ratio).astype(np.uint8)
                if moving.any():
                    moving = cv2.dilate(moving, np.ones((3, 3), np.uint8))
                self._moving_blocks = moving.astype(bool)
        self._prev = g
        use = self._pixel_mask(g.shape)
        n_use = int(use.sum())

        # 2) settled? (no real change versus the start of the stable run)
        if self._anchor is None or n_use < 0.25 * g.size:
            self._anchor, self._stable_since = g, t
            return []
        drift = int(((cv2.absdiff(g, self._anchor) > DIFF_T) & use).sum()) / n_use
        if drift > self.settle_threshold:
            self._anchor, self._stable_since = g, t
            return []
        if t - self._stable_since < self.settle_s:
            return []

        # 3) settled frame S: same page or a new one?
        return self._on_settled(frame, g, use, t)

    def _set_page(self, frame: np.ndarray, g: np.ndarray, t: float, new_page: bool) -> None:
        self._page, self._page_g = frame, g
        if new_page:
            self._page_t = t
        self.page_version += 1

    def _on_settled(self, frame, g, use, t) -> list[Capture]:
        if self._page_g is None:
            self._set_page(frame, g, t, True)
            return []
        P = self._page_g
        if P.shape != g.shape:
            # crop/size changed: different page geometry, save the old page
            out = [Capture(self._page, self._page_t)]
            self._set_page(frame, g, t, True)
            return out

        if self._page_is_new(P, g, use):
            out = [Capture(self._page, self._page_t)]
            self._set_page(frame, g, t, True)
            return out
        if not np.array_equal(P, g):
            self._set_page(frame, g, t, False)
        return []

    def _page_is_new(self, P: np.ndarray, S: np.ndarray, use: np.ndarray) -> bool:
        n_use = max(1, int(use.sum()))
        bg_p = int(np.bincount(P[use], minlength=256).argmax())
        bg_s = int(np.bincount(S[use], minlength=256).argmax())
        content = (np.abs(P.astype(np.int16) - bg_p) > CONTENT_T) & use
        n_content = int(content.sum())
        if n_content < 0.002 * n_use:
            return False  # old page is (nearly) blank: nothing worth saving
        diff = (cv2.absdiff(P, S) > DIFF_T) & use
        changed_all = int(diff.sum()) / n_use
        lost_px = int((diff & content).sum())
        lost = lost_px / n_content
        lost_abs = lost_px / n_use

        big = (changed_all >= self.global_threshold
               or abs(bg_p - bg_s) > CONTENT_T and changed_all > 0.2
               or (lost >= self.lost_threshold and lost_abs >= self.lost_abs_threshold))
        if not big:
            return False

        scroll = self._detect_vertical_scroll(P, S, content, use)
        if scroll is not None:
            dy = scroll
            h = P.shape[0]
            # content of P that left the view
            if dy < 0:
                gone = content[: -dy]
            else:
                gone = content[h - dy:]
            gone_frac = int(gone.sum()) / n_content
            return gone_frac >= self.scroll_threshold
        return True

    def _detect_vertical_scroll(self, P, S, content, use) -> int | None:
        """Return dy if S is P scrolled vertically (S[y] ~ P[y - dy]), else None."""
        h, w = P.shape
        bg = int(np.bincount(P[use], minlength=256).argmax())
        prof_p = (np.abs(P.astype(np.int16) - bg) * use).mean(axis=1)
        prof_s = (np.abs(S.astype(np.int16) - bg) * use).mean(axis=1)
        prof_p = prof_p - prof_p.mean()
        prof_s = prof_s - prof_s.mean()
        min_overlap = int(0.1 * h)
        scores = []
        for dy in range(-(h - min_overlap), h - min_overlap + 1):
            if abs(dy) < max(3, int(0.02 * h)):
                continue
            if dy < 0:
                a, b = prof_p[-dy:], prof_s[: h + dy]
            else:
                a, b = prof_p[: h - dy], prof_s[dy:]
            denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
            if denom <= 1e-6:
                continue
            ncc = float((a * b).sum()) / denom
            # prefer large overlaps: tiny overlaps correlate well by chance
            scores.append((ncc * np.sqrt((h - abs(dy)) / h), ncc, dy))
        if not scores:
            return None
        scores.sort(reverse=True)
        best_dy, best_mis = None, 1.0
        for _, ncc, dy in scores[:12]:
            if ncc < 0.5:
                continue
            if dy < 0:
                p_part, s_part, c_part = P[-dy:], S[: h + dy], content[-dy:]
            else:
                p_part, s_part, c_part = P[: h - dy], S[dy:], content[: h - dy]
            n_c = int(c_part.sum())
            if n_c < 0.001 * P.size:
                continue
            mis = int(((cv2.absdiff(p_part, s_part) > DIFF_T) & c_part).sum()) / n_c
            if mis < best_mis:
                best_mis, best_dy = mis, dy
        if best_dy is not None and best_mis < 0.15:
            return best_dy
        return None

    # ------------------------------------------------------------------ controls
    def force(self) -> Capture | None:
        """Capture the latest frame right now (hotkey)."""
        if self._latest is None:
            return None
        return Capture(self._latest, self._latest_t, forced=True)

    def finish(self) -> Capture | None:
        """End of recording: the current page is complete."""
        if self._page is None:
            return None
        cap = Capture(self._page, self._page_t)
        self._page = self._page_g = None
        return cap

    @property
    def page_frame(self) -> np.ndarray | None:
        return self._page

    @property
    def moving_fraction(self) -> float:
        if self._moving_blocks is None:
            return 0.0
        return float(self._moving_blocks.mean())


class CapturePipeline:
    """Detector + letterbox trim + blank filter + duplicate filter."""

    def __init__(self, sensitivity: float = 0.5, trim: bool = True, **kw):
        self.detector = SlideChangeDetector(sensitivity=sensitivity, **kw)
        self.deduper = Deduper()
        self.trim = trim

    def _accept(self, cap: Capture | None) -> Capture | None:
        if cap is None:
            return None
        img = trim_uniform_border(cap.image) if self.trim else cap.image
        if is_blank(img):
            return None
        if not cap.forced and self.deduper.is_redundant(img):
            return None
        self.deduper.add(img)
        return Capture(np.ascontiguousarray(img), cap.t, cap.forced)

    def feed(self, frame: np.ndarray, t: float) -> list[Capture]:
        return [c for c in (self._accept(x) for x in self.detector.feed(frame, t)) if c]

    def force(self) -> Capture | None:
        return self._accept(self.detector.force())

    def finish(self) -> Capture | None:
        return self._accept(self.detector.finish())
