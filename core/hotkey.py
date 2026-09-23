"""全局快捷键（Windows）：用 ctypes 直接调 Win32，不依赖 pywin32。

在独立线程里注册热键 + 跑消息循环；触发后把平台窗口提到前台。
非 Windows 平台或注册失败时静默降级，不影响平台运行。
"""

from __future__ import annotations

import ctypes
import os
import threading
from typing import Callable

WM_HOTKEY = 0x0312
MOD = {"alt": 0x0001, "ctrl": 0x0002, "shift": 0x0004, "win": 0x0008}

# 常用键名 → 虚拟键码（够用即可，未列出的单字符按键用 ord() 兜底）
VK = {
    "SPACE": 0x20, "ENTER": 0x0D, "TAB": 0x09, "ESC": 0x1B,
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74,
    "F6": 0x75, "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79,
    "F11": 0x7A, "F12": 0x7B,
}


def _to_vk(key: str) -> int:
    k = (key or "").strip().upper()
    if k in VK:
        return VK[k]
    if len(k) == 1:
        return ord(k)
    return ord("S")


class HotKey:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def supported(self) -> bool:
        return os.name == "nt"

    def start(self, modifiers: list[str], key: str,
              callback: Callable[[], None]) -> bool:
        if not self.supported:
            return False
        self.stop()
        mods = 0
        for m in modifiers or []:
            mods |= MOD.get(str(m).lower(), 0)
        vk = _to_vk(key)
        self._stop.clear()

        def _loop() -> None:
            try:
                user32 = ctypes.windll.user32
                if not user32.RegisterHotKey(None, 1, mods, vk):
                    return
                msg = ctypes.wintypes.MSG()
                try:
                    while not self._stop.is_set():
                        r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                        if r in (0, -1):
                            break
                        if msg.message == WM_HOTKEY:
                            try:
                                callback()
                            except Exception:
                                pass
                finally:
                    user32.UnregisterHotKey(None, 1)
            except Exception:
                return

        self._thread = threading.Thread(target=_loop, daemon=True, name="hotkey")
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            try:
                ctypes.windll.user32.PostThreadMessageW(
                    ctypes.windll.kernel32.GetCurrentThreadId(), 0x0012, 0, 0)
            except Exception:
                pass
        self._thread = None


HOTKEY = HotKey()
