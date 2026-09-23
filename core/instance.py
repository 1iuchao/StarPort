"""实例留痕：让"看不见地活着"的平台进程可被发现、可被关闭。

背景（2026-09-23 的 WinError 10048 工单）：
    为了做 UI 取证，曾在 19600 起过一个 `--no-window` 实例。它没有窗口、
    没有托盘图标、没有留任何痕迹，会话结束后也没被清理 —— 用户每次启动
    都撞上它，却完全看不到它是谁。这就是工单里"三环根因"的环 1。

原则：
    **任何能"看不见地活着"的进程，都必须可被发现、可被关闭。**

两样东西：
    data/instances/<port>.json   每个实例都留一份（含 --port 起的第二实例），
                                 供 tools/stop_instance.py 发现与关闭。
    data/.instance.json          只有"主实例"写，用"不存在才创建"原子占位，
                                 供单实例复用判断（已有主实例就把它的窗口
                                 提到前台，本次不再起第二份）。

判活依据是**端口上真有一个星港在应答**（/api/health 返回 platform=StarPort），
不是"文件存在"、也不是"PID 还活着"—— PID 会被系统复用，不可靠；
而陈旧文件在判活时会自动被清掉，所以被强杀留下的痕迹不会误伤下次启动。

零第三方依赖。任何一步失败都静默降级为"当作没有旧实例"。
"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.request
from typing import Any

from . import paths

TIMEOUT = 0.8          # 探测旧实例的超时（秒）：宁可短，别让用户等

INSTANCES_DIR = paths.INSTANCES_DIR
PRIMARY_FILE = paths.PRIMARY_FILE


# ------------------------------------------------------------------ 读写
def _write_json(target, payload: dict[str, Any]) -> bool:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)
        return True
    except BaseException:
        return False


def _read_json(target) -> dict[str, Any] | None:
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except BaseException:
        return None


def _unlink(target) -> None:
    # ★ 用 BaseException：atexit 里跑清理时，任何异常（含 SystemExit）都不该
    #   冒出去打断退出流程 —— 留痕没删掉只是下次自愈，崩在退出路径上更糟。
    try:
        target.unlink()
    except BaseException:
        pass


def _ensure_dir() -> None:
    try:
        INSTANCES_DIR.mkdir(parents=True, exist_ok=True)
    except BaseException:
        pass


# ------------------------------------------------------------------ 判活
def probe(port: int) -> dict[str, Any] | None:
    """端口上真有一个星港在应答吗？是就返回 health，否则 None。"""
    if not port:
        return None
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health",
                                    timeout=TIMEOUT) as r:
            data = json.load(r)
    except BaseException:
        return None
    # 验明正身：别的程序恰好占了同端口也不会被误认成星港
    if isinstance(data, dict) and data.get("platform") == "StarPort":
        return data
    return None


def port_busy(port: int) -> bool:
    """端口上是否有人占着（不管是不是星港），用于确认退出是否干净。"""
    if not port:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def live_all() -> list[dict[str, Any]]:
    """所有活着的实例（含 --port 起的第二实例），顺手清掉陈旧留痕。"""
    out: list[dict[str, Any]] = []
    try:
        files = sorted(INSTANCES_DIR.glob("*.json"))
    except BaseException:
        return out
    for f in files:
        rec = _read_json(f)
        if not rec:
            _unlink(f)
            continue
        if probe(int(rec.get("port") or 0)):
            out.append(rec)
        else:
            _unlink(f)                      # 死了就别留着误导人
    return out


def live_primary() -> dict[str, Any] | None:
    """活着的"主实例"（没有显式 --port 的那个）；没有就 None。"""
    rec = _read_json(PRIMARY_FILE)
    if not rec:
        _unlink(PRIMARY_FILE)
        return None
    if probe(int(rec.get("port") or 0)):
        return rec
    _unlink(PRIMARY_FILE)                   # 陈旧主实例痕迹，清掉自愈
    return None


# ------------------------------------------------------------------ 注册 / 注销
def register(port: int, pid: int, mode: str) -> None:
    """每个实例都留痕（不管是不是第二实例）—— 这是"可被发现"那一半。"""
    _ensure_dir()
    _write_json(INSTANCES_DIR / f"{port}.json", {
        "pid": pid,
        "port": int(port),
        "mode": mode,
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    })


def unregister(port: int) -> None:
    _unlink(INSTANCES_DIR / f"{int(port)}.json")


def acquire_primary(port: int, pid: int, mode: str) -> bool:
    """抢"主实例"位置。True = 我是主实例；False = 已经有一个主实例在跑。

    ★ 用"不存在才创建"（O_EXCL）原子占位：两个实例同时启动时不会互相覆盖，
      谁先创建谁说话，后到的自行退出（run.py 那边会把已有窗口提到前台）。
    """
    for _ in range(2):
        if live_primary() is not None:
            return False
        try:
            fd = os.open(PRIMARY_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue                        # 有人抢先了，重走一遍判活
        except BaseException:
            return False
        payload = {"pid": pid, "port": int(port), "mode": mode,
                   "started": time.strftime("%Y-%m-%d %H:%M:%S")}
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        except BaseException:
            return False
        return True
    return False


def release_primary(pid: int) -> None:
    """只在记录是我自己留的时才删（别把别人的抹了）。"""
    rec = _read_json(PRIMARY_FILE)
    if rec and int(rec.get("pid") or -1) == int(pid):
        _unlink(PRIMARY_FILE)
