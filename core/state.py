"""轻量运行时状态：置顶、最近使用、上次打开的应用。

与 config.json 分开存放（data/state.json），因为它是"使用痕迹"而非"配置"，
导出配置时可以自由选择要不要带上。
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from . import paths

DEFAULT_STATE: dict[str, Any] = {
    "pinned": [],          # 置顶应用 id（有序）
    "recent": [],          # 最近打开（有序，最新在前）
    "last_active": None,
    "updated_at": 0,
}


class State:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: dict[str, Any] = dict(DEFAULT_STATE)
        self.load()

    def load(self) -> None:
        paths.ensure_dirs()
        if paths.STATE_FILE.exists():
            try:
                raw = json.loads(paths.STATE_FILE.read_text("utf-8"))
                if isinstance(raw, dict):
                    self._data.update(raw)
            except Exception:
                pass

    def save(self) -> None:
        paths.ensure_dirs()
        self._data["updated_at"] = int(time.time())
        tmp = paths.STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, paths.STATE_FILE)

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    # ------------------------------------------------------------ 置顶
    def toggle_pin(self, app_id: str, pinned: bool | None = None) -> list[str]:
        pins: list[str] = self._data.setdefault("pinned", [])
        with self._lock:
            want = (app_id not in pins) if pinned is None else bool(pinned)
            if want and app_id not in pins:
                pins.append(app_id)
            elif not want:
                pins = [p for p in pins if p != app_id]
                self._data["pinned"] = pins
            self.save()
            return list(self._data["pinned"])

    # ------------------------------------------------------------ 最近使用
    def touch(self, app_id: str, keep: int = 12) -> None:
        with self._lock:
            recent: list[str] = self._data.setdefault("recent", [])
            recent = [r for r in recent if r != app_id]
            recent.insert(0, app_id)
            self._data["recent"] = recent[:keep]
            self._data["last_active"] = app_id
            self.save()

    def forget(self, app_id: str) -> None:
        with self._lock:
            self._data["pinned"] = [p for p in self._data.get("pinned", [])
                                    if p != app_id]
            self._data["recent"] = [r for r in self._data.get("recent", [])
                                    if r != app_id]
            if self._data.get("last_active") == app_id:
                self._data["last_active"] = None
            self.save()


STATE = State()
