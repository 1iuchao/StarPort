"""端口分配：平台端口 + 应用端口池。

核心诉求：应用之间不抢端口；端口被占用时自动顺延；分配结果记在内存里，
停止应用即释放，避免"看起来空闲其实马上要被占用"的竞态。
"""

from __future__ import annotations

import socket
import threading

HOST = "127.0.0.1"

_lock = threading.Lock()
_in_use: dict[int, str] = {}          # port -> owner(app_id / 'platform')


def is_free(port: int) -> bool:
    """真实探测：尝试绑定一次（Windows 下 SO_REUSEADDR 会骗人，所以显式试绑）。"""
    if port in _in_use:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((HOST, port))
            return True
        except OSError:
            return False


def allocate(owner: str, base: int, span: int = 200) -> int:
    """从 base 开始找一个空闲端口并占位。"""
    with _lock:
        for i in range(span):
            p = base + i
            if p in _in_use:
                continue
            if is_free(p):
                _in_use[p] = owner
                return p
        raise RuntimeError(f"端口池 {base}~{base + span - 1} 已耗尽")


def reserve(port: int, owner: str) -> None:
    with _lock:
        _in_use[port] = owner


def release(port: int | None) -> None:
    if port is None:
        return
    with _lock:
        _in_use.pop(port, None)


def release_owner(owner: str) -> None:
    with _lock:
        for p in [p for p, o in _in_use.items() if o == owner]:
            _in_use.pop(p, None)


def snapshot() -> dict[str, list[int]]:
    with _lock:
        out: dict[str, list[int]] = {}
        for p, o in sorted(_in_use.items(), key=lambda kv: kv[0]):
            out.setdefault(o, []).append(p)
        return out
