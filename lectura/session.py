"""A recording session on disk: captures are written as they happen, so a crash
or closed laptop never loses a class."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from .settings import local_data_dir


def sessions_root() -> Path:
    p = local_data_dir() / "sessions"
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_png(path: Path, img: np.ndarray) -> None:
    ok, buf = cv2.imencode(".png", img, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not ok:
        raise OSError(f"could not encode {path}")
    tmp = path.with_suffix(".tmp")
    buf.tofile(str(tmp))  # tofile handles non-ASCII paths
    tmp.replace(path)


def read_image(path: Path) -> np.ndarray | None:
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


@dataclass
class Item:
    file: str          # file name inside the session folder
    t: float           # seconds since the recording started
    forced: bool = False


class Session:
    def __init__(self, folder: Path, meta: dict):
        self.folder = folder
        self.meta = meta
        self.items: list[Item] = [Item(**i) for i in meta.get("items", [])]
        self._counter = max((int(Path(i.file).stem) for i in self.items
                             if Path(i.file).stem.isdigit()), default=0)

    # ------------------------------------------------------------------ create/load
    @classmethod
    def new(cls, window_title: str = "") -> "Session":
        started = datetime.now()
        folder = sessions_root() / started.strftime("%Y-%m-%d_%H-%M-%S")
        n = 1
        while folder.exists():
            n += 1
            folder = sessions_root() / f"{started:%Y-%m-%d_%H-%M-%S}_{n}"
        folder.mkdir(parents=True)
        meta = {"started_at": started.isoformat(timespec="seconds"),
                "window_title": window_title, "items": [],
                "finished": False, "exported": False}
        s = cls(folder, meta)
        s.save_meta()
        return s

    @classmethod
    def load(cls, folder: Path) -> "Session | None":
        try:
            meta = json.loads((folder / "session.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return cls(folder, meta)

    @classmethod
    def find_unexported(cls) -> "Session | None":
        """Most recent session that has captures but was never saved/exported."""
        for folder in sorted(sessions_root().iterdir(), reverse=True):
            if not folder.is_dir():
                continue
            s = cls.load(folder)
            if s is None or s.meta.get("exported") or s.meta.get("discarded"):
                continue
            if not s.meta.get("finished"):
                s.recover_pending()
            if s.items:
                return s
        return None

    @classmethod
    def cleanup_old(cls, keep_days: int = 14) -> None:
        cutoff = time.time() - keep_days * 86400
        for folder in sessions_root().iterdir():
            try:
                if not folder.is_dir() or folder.stat().st_mtime > cutoff:
                    continue
                s = cls.load(folder)
                if s is None or s.meta.get("exported") or s.meta.get("discarded"):
                    shutil.rmtree(folder, ignore_errors=True)
            except OSError:
                pass

    # ------------------------------------------------------------------ properties
    @property
    def started_at(self) -> datetime:
        return datetime.fromisoformat(self.meta["started_at"])

    @property
    def title(self) -> str:
        return self.meta.get("window_title", "")

    def path_of(self, item: Item) -> Path:
        return self.folder / item.file

    def clock_time(self, item: Item) -> datetime:
        return self.started_at + timedelta(seconds=item.t)

    def caption(self, item: Item) -> str:
        elapsed = int(item.t)
        h, rem = divmod(elapsed, 3600)
        m, s = divmod(rem, 60)
        clock = self.clock_time(item).strftime("%I:%M %p").lstrip("0")
        return f"{clock}  ·  {h:02d}:{m:02d}:{s:02d} into class"

    # ------------------------------------------------------------------ writes
    def save_meta(self) -> None:
        self.meta["items"] = [asdict(i) for i in self.items]
        tmp = self.folder / "session.json.tmp"
        tmp.write_text(json.dumps(self.meta, indent=1), encoding="utf-8")
        tmp.replace(self.folder / "session.json")

    def add(self, image: np.ndarray, t: float, forced: bool = False) -> Item:
        self._counter += 1
        name = f"{self._counter:04d}.png"
        write_png(self.folder / name, image)
        item = Item(name, round(float(t), 2), forced)
        self.items.append(item)
        self.save_meta()
        return item

    def write_pending(self, image: np.ndarray, t: float) -> None:
        write_png(self.folder / "pending.png", image)
        self.meta["pending_t"] = round(float(t), 2)
        self.save_meta()

    def clear_pending(self) -> None:
        (self.folder / "pending.png").unlink(missing_ok=True)
        self.meta.pop("pending_t", None)

    def recover_pending(self) -> None:
        """After a crash: the page that was in progress becomes the last capture."""
        p = self.folder / "pending.png"
        if p.exists():
            img = read_image(p)
            if img is not None:
                from .dedupe import Deduper, is_blank
                d = Deduper()
                for it in self.items:
                    im = read_image(self.path_of(it))
                    if im is not None:
                        d.add(im)
                if not is_blank(img) and not d.is_redundant(img):
                    self.add(img, self.meta.get("pending_t", 0.0))
            self.clear_pending()
        self.meta["finished"] = True
        self.save_meta()

    def mark_finished(self) -> None:
        self.clear_pending()
        self.meta["finished"] = True
        self.save_meta()

    def set_items(self, items: list[Item]) -> None:
        """Apply the review screen's order and deletions."""
        keep = {i.file for i in items}
        for it in self.items:
            if it.file not in keep:
                (self.folder / it.file).unlink(missing_ok=True)
        self.items = list(items)
        self.save_meta()

    def mark_exported(self, paths: list[str]) -> None:
        self.meta["exported"] = True
        self.meta["exported_to"] = paths
        self.save_meta()

    def discard(self) -> None:
        self.meta["discarded"] = True
        self.save_meta()
        shutil.rmtree(self.folder, ignore_errors=True)
