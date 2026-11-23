"""Write captures to PPTX / DOCX / PDF."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass
class Page:
    path: Path        # PNG on disk
    caption: str      # timestamp text ("" when timestamps are off)

    def size(self) -> tuple[int, int]:
        with Image.open(self.path) as im:
            return im.size


def unique_path(path: Path) -> Path:
    """'Class.pdf' -> 'Class (2).pdf' if it already exists."""
    if not path.exists():
        return path
    n = 2
    while True:
        p = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not p.exists():
            return p
        n += 1


PAGE_SIZES_CM = {"A4": (21.0, 29.7), "Letter": (21.59, 27.94)}


def two_up_layout(page_w: float, page_h: float, aspect: float, margin: float,
                  caption_h: float, gap: float) -> tuple[float, float]:
    """Image (w, h) so that two images + captions fit on one portrait page."""
    usable_w = page_w - 2 * margin
    usable_h = page_h - 2 * margin
    slot_h = (usable_h - gap - 2 * caption_h) / 2
    w = min(usable_w, slot_h * aspect)
    return w, w / aspect
