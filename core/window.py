"""窗口启动：给平台一个"像原生应用"的壳。

优先级（auto 模式）：
  1. pywebview  —— 若已安装，得到真正的独立窗口
  2. Edge / Chrome 的 --app 模式 —— 系统自带、零安装、无浏览器 UI
  3. 系统默认浏览器
  4. none       —— 不起窗口（适合开机自启只跑后台服务时用）

全程只用标准库，装不装 pywebview 都能跑。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from . import paths
from .settings import CONFIG

TITLE = "StarPort · 星港"

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
]


def _first_existing(cands: list[str]) -> str | None:
    for c in cands:
        p = Path(os.path.expandvars(c))
        if p.is_file():
            return str(p)
    return None


def find_edge() -> str | None:
    return _first_existing(EDGE_CANDIDATES) or shutil.which("msedge")


def find_chrome() -> str | None:
    return _first_existing(CHROME_CANDIDATES) or shutil.which("chrome")


def _chromium_app(exe: str, url: str, profile: Path,
                  width: int = 1280, height: int = 820) -> bool:
    """用 Chromium 系浏览器的 --app 模式开出无浏览器 UI 的窗口。"""
    profile.mkdir(parents=True, exist_ok=True)
    args = [
        exe,
        f"--app={url}",
        f"--user-data-dir={profile}",
        f"--window-size={width},{height}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-component-update",
        "--disable-background-networking",
        "--disable-sync",
        "--no-proxy-server",          # 本地回环不走任何代理
    ]
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception:
        return False


def open_window(url: str, mode: str | None = None) -> str:
    """返回实际使用的模式名，便于日志与界面提示。"""
    mode = (mode or CONFIG.platform.get("window_mode") or "auto").lower()

    if mode in ("auto", "pywebview"):
        try:
            import webview  # type: ignore
            webview.create_window(TITLE, url, width=1280, height=820,
                                  min_size=(900, 600))
            threading_start = getattr(webview, "start", None)
            import threading as _t
            _t.Thread(target=threading_start, daemon=True,
                      name="starport-webview").start()
            return "pywebview"
        except Exception:
            if mode == "pywebview":
                raise
            # auto → 继续降级

    if mode in ("auto", "edge"):
        exe = find_edge()
        if exe and _chromium_app(exe, url, paths.EDGE_PROFILE):
            return "edge"

    if mode in ("auto", "chrome"):
        exe = find_chrome()
        if exe and _chromium_app(exe, url, paths.EDGE_PROFILE / "chrome"):
            return "chrome"

    if mode in ("auto", "browser"):
        import webbrowser
        webbrowser.open(url)
        return "browser"

    return "none"


# ------------------------------------------------------------------ 窗口聚焦
def focus_window(title_substr: str = TITLE) -> bool:
    """把标题包含关键字的窗口提到前台（供全局快捷键唤醒）。

    纯 ctypes 实现，不需要 pywin32。非 Windows 返回 False。
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        EnumWindows = user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool,
                                             wintypes.HWND, wintypes.LPARAM)
        found: list[int] = []

        def _cb(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if title_substr.lower() in buf.value.lower():
                found.append(hwnd)
                return False
            return True

        EnumWindows(EnumWindowsProc(_cb), 0)
        if not found:
            return False
        hwnd = found[0]
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)          # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def autostart_command(python: str | None = None) -> str:
    """开机自启用的命令行。"""
    py = python or CONFIG.platform.get("python_path") or sys.executable
    run_py = str(paths.ROOT / "run.py")
    return f'"{py}" "{run_py}" --autostarted'
