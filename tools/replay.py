"""Replay frames saved with LECTURA_DUMP_FRAMES through the detector, with the debug log.

    .venv\\Scripts\\python.exe tools\\replay.py <frames-folder> [out-folder] [sensitivity]

File names are the sample times (e.g. 000012.50.png). Prints every page decision and
writes the accepted captures (and a contact sheet) to out-folder.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from lectura.detector import CapturePipeline  # noqa: E402
from lectura.session import read_image, write_png  # noqa: E402


def main() -> int:
    frames = sorted(Path(sys.argv[1]).glob("*.png"), key=lambda p: float(p.stem))
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(sys.argv[1]).parent / "replay"
    sens = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
    out.mkdir(parents=True, exist_ok=True)
    pipe = CapturePipeline(sensitivity=sens, log=print)
    caps = []
    for f in frames:
        img = read_image(f)
        if img is not None:
            caps += pipe.feed(img, float(f.stem))
    last = pipe.finish()
    if last:
        caps.append(last)
    thumbs = []
    for i, c in enumerate(caps, 1):
        write_png(out / f"{i:04d}.png", c.image)
        th = cv2.resize(c.image, (480, int(c.image.shape[0] * 480 / c.image.shape[1])))
        cv2.putText(th, f"{i} t={c.t:.0f}", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        thumbs.append(th)
    if thumbs:
        blank = np.zeros_like(thumbs[0])
        rows = [np.hstack((thumbs[i:i + 3] + [blank] * 3)[:3]) for i in range(0, len(thumbs), 3)]
        cv2.imwrite(str(out / "contact_sheet.png"), np.vstack(rows))
    print(f"\n{len(frames)} frames -> {len(caps)} captures in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
