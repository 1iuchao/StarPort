"""本地配置读写。

单一真源是 data/config.json；全部本地，无任何云端交互。
支持整体导出 / 导入（便于换机或备份）。
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import paths

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "platform": {
        "port_base": 19000,        # 平台自身端口；被占用自动顺延
        "app_port_base": 19100,    # 应用端口池起点
        "theme": "dark",           # dark | light
        "python_path": sys.executable,
        "window_mode": "auto",     # auto | edge | chrome | browser | pywebview | none
        "autostart": False,
        "hotkey": {
            "enabled": True,
            "modifiers": ["ctrl", "alt"],
            "key": "S",
        },
        "auto_restart_on_crash": False,
        "close_exits_platform": True,     # 关掉窗口即退出平台（含回收应用进程）
        "confirm_before_uninstall": True,
        # 启动时是否自动拉起上次打开的应用。默认关：
        # 开个平台就顺手起一个应用进程，对多数人是负担而不是贴心。
        "auto_launch_last": False,
    },
    # 应用级覆盖：enabled(启用/禁用) / category(分类) / pinned 由 state 管
    "apps": {},
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    """进程内单例：读→改内存→落盘。"""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self.load()

    # ------------------------------------------------------------ 生命周期
    def load(self) -> None:
        paths.ensure_dirs()
        raw: dict[str, Any] = {}
        if paths.CONFIG_FILE.exists():
            try:
                raw = json.loads(paths.CONFIG_FILE.read_text("utf-8"))
            except Exception:
                # 配置损坏不应拖垮平台：备份后回落到默认
                try:
                    paths.CONFIG_FILE.replace(
                        paths.CONFIG_FILE.with_suffix(".corrupt.json"))
                except Exception:
                    pass
                raw = {}
        self._data = _deep_merge(DEFAULT_CONFIG, raw)

    def save(self) -> None:
        paths.ensure_dirs()
        tmp = paths.CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, paths.CONFIG_FILE)   # 原子替换，避免写一半断电

    # ------------------------------------------------------------ 访问
    @property
    def data(self) -> dict[str, Any]:
        return self._data

    @property
    def platform(self) -> dict[str, Any]:
        return self._data.setdefault("platform", {})

    def set(self, dotted: str, value: Any) -> None:
        """按 a.b.c 路径写入。"""
        cur = self._data
        parts = dotted.split(".")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value

    def get(self, dotted: str, default: Any = None) -> Any:
        cur: Any = self._data
        for p in dotted.split("."):
            if not isinstance(cur, dict) or p not in cur:
                return default
            cur = cur[p]
        return cur

    # ------------------------------------------------------------ 应用覆盖项
    def app_overrides(self, app_id: str) -> dict[str, Any]:
        return self._data.setdefault("apps", {}).setdefault(app_id, {})

    def is_enabled(self, app_id: str, default: bool = True) -> bool:
        return bool(self.app_overrides(app_id).get("enabled", default))

    def set_enabled(self, app_id: str, enabled: bool) -> None:
        self.app_overrides(app_id)["enabled"] = bool(enabled)

    def forget_app(self, app_id: str) -> None:
        self._data.setdefault("apps", {}).pop(app_id, None)

    # ------------------------------------------------------------ 导入导出
    def export_payload(self, include_state: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": "starport-config",
            "version": 1,
            "config": copy.deepcopy(self._data),
        }
        if include_state and paths.STATE_FILE.exists():
            try:
                payload["state"] = json.loads(paths.STATE_FILE.read_text("utf-8"))
            except Exception:
                pass
        return payload

    def import_payload(self, payload: dict[str, Any],
                       merge: bool = True) -> dict[str, Any]:
        """导入配置。返回 {'ok':bool,'error':str}。"""
        try:
            incoming = payload.get("config")
            if not isinstance(incoming, dict):
                return {"ok": False, "error": "文件里没有 config 字段"}
            self._data = _deep_merge(self._data, incoming) if merge else \
                _deep_merge(DEFAULT_CONFIG, incoming)
            self.save()
            state = payload.get("state")
            if isinstance(state, dict):
                paths.STATE_FILE.write_text(
                    json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


CONFIG = Config()
