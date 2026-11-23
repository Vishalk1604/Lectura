"""Persistent user settings (%APPDATA%\\Lectura\\settings.json)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import APP_NAME


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def local_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_save_folder() -> str:
    docs = Path.home() / "Documents"
    return str(docs if docs.exists() else Path.home())


@dataclass
class Settings:
    sensitivity: float = 0.5
    hotkey: str = "Ctrl+Alt+S"
    crops: dict = field(default_factory=dict)      # site key -> [fx, fy, fw, fh]
    last_folder: str = field(default_factory=default_save_folder)
    formats: list = field(default_factory=lambda: ["pdf"])
    timestamps: bool = True
    page_size: str = "A4"                          # "A4" or "Letter"

    @classmethod
    def path(cls) -> Path:
        return app_data_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
            for k, v in data.items():
                if hasattr(s, k):
                    setattr(s, k, v)
        except (OSError, ValueError):
            pass
        return s

    def save(self) -> None:
        try:
            self.path().write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except OSError:
            pass
