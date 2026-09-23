"""开机自启：写 Windows 当前用户的 Run 注册表项（纯 stdlib winreg）。

不写系统目录、不需要管理员权限，卸载时一键清除。
"""

from __future__ import annotations

import os
import sys
import winreg  # type: ignore[import-not-found]

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "StarPort"


def _startup_shortcut_cmd(command: str) -> str:
    return command


def is_enabled() -> bool:
    if os.name != "nt":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            value, _ = winreg.QueryValueEx(k, VALUE_NAME)
            return bool(value)
    except Exception:
        return False


def enable(command: str) -> tuple[bool, str]:
    if os.name != "nt":
        return False, "仅支持 Windows"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, command)
        return True, "已写入 HKCU\\...\\Run"
    except Exception as exc:
        return False, str(exc)


def disable() -> tuple[bool, str]:
    if os.name != "nt":
        return False, "仅支持 Windows"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, VALUE_NAME)
        return True, "已移除开机自启"
    except FileNotFoundError:
        return True, "本来就没有启用"
    except Exception as exc:
        return False, str(exc)


def current_command() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            value, _ = winreg.QueryValueEx(k, VALUE_NAME)
            return str(value)
    except Exception:
        return ""


def sync(command: str, want: bool) -> tuple[bool, str]:
    return enable(command) if want else disable()
