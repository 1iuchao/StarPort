"""应用进程托管（隔离的核心）。

隔离策略（四层，逐层兜底）：
  1. 进程隔离 —— 每个应用一个独立 OS 子进程，内核从不 import 应用代码；
  2. 端口隔离 —— 平台统一分配端口，应用之间不会抢；
  3. 视图隔离 —— 应用界面跑在 iframe 里（带 sandbox），DOM 与 JS 全局互不可见；
  4. 故障隔离 —— 应用崩溃只把那一个 iframe 标记为 crashed，
     平台本体与其他应用不受影响，可一键重启。
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import jobobj, paths, ports
from .registry import (TYPE_EXTERNAL, TYPE_STATIC, TYPE_WEBSERVICE,
                       AppMeta, Registry)
from .settings import CONFIG

PLACEHOLDERS = ("{python}", "{port}", "{app_dir}", "{app_data}",
                "{app_id}", "{platform_port}", "{platform_url}")

STATUS_STOPPED = "stopped"
STATUS_STARTING = "starting"
STATUS_RUNNING = "running"
STATUS_CRASHED = "crashed"
STATUS_ERROR = "error"


def _render(value: Any, ctx: dict[str, str]) -> Any:
    """递归替换命令 / 环境变量里的占位符。"""
    if isinstance(value, str):
        out = value
        for k, v in ctx.items():
            out = out.replace(k, str(v))
        return out
    if isinstance(value, list):
        return [_render(x, ctx) for x in value]
    if isinstance(value, dict):
        return {k: _render(v, ctx) for k, v in value.items()}
    return value


def _tail(path: Path, n: int = 40) -> str:
    try:
        lines = path.read_text("utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return ""


def _http_ok(url: str, timeout: float = 1.5) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except Exception:
        return False


def _tcp_open(port: int, timeout: float = 0.6) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False


@dataclass
class AppRuntime:
    app_id: str
    status: str = STATUS_STOPPED
    port: int | None = None
    url: str | None = None
    pid: int | None = None
    started_at: float | None = None
    exit_code: int | None = None
    error: str | None = None
    restarts: int = 0
    proc: subprocess.Popen | None = field(default=None, repr=False)
    log: Path | None = None


class Supervisor:
    def __init__(self, registry: Registry, platform_port: int) -> None:
        self.registry = registry
        self.platform_port = platform_port
        self._rt: dict[str, AppRuntime] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------ 上下文
    def _ctx(self, meta: AppMeta, port: int) -> dict[str, str]:
        return {
            "{python}": CONFIG.platform.get("python_path") or sys.executable,
            "{port}": str(port),
            "{app_dir}": str(meta.dir),
            "{app_data}": str(paths.app_data_dir(meta.id)),
            "{app_id}": meta.id,
            "{platform_port}": str(self.platform_port),
            "{platform_url}": f"http://127.0.0.1:{self.platform_port}/",
        }

    def runtime(self, app_id: str) -> AppRuntime:
        with self._lock:
            return self._rt.setdefault(app_id, AppRuntime(app_id=app_id))

    # ------------------------------------------------------------ 启动
    def launch(self, app_id: str) -> dict[str, Any]:
        meta = self.registry.get(app_id)
        if meta is None:
            return {"ok": False, "error": "应用不存在"}
        if not meta.enabled:
            return {"ok": False, "error": "应用已被禁用"}
        if meta.issues and meta.type == TYPE_WEBSERVICE and not meta.entry.get("command"):
            return {"ok": False, "error": "；".join(meta.issues)}

        rt = self.runtime(app_id)
        with self._lock:
            if rt.status in (STATUS_RUNNING, STATUS_STARTING):
                return {"ok": True, "already": True, "status": rt.status,
                        "url": rt.url, "port": rt.port}

            if meta.type == TYPE_STATIC:
                # 纯前端：无需子进程，由平台静态托管
                rt.status = STATUS_RUNNING
                rt.started_at = time.time()
                rt.error = None
                rt.port = None
                rt.url = f"/_apps/{meta.id}/{meta.view.get('path') or 'index.html'}"
                return {"ok": True, "status": rt.status, "url": rt.url,
                        "port": None, "pid": None}

            port = ports.allocate(app_id, int(CONFIG.platform.get("app_port_base", 19100)))
            ctx = self._ctx(meta, port)
            cmd = _render(list(meta.entry.get("command") or []), ctx)
            if not cmd:
                ports.release(port)
                return {"ok": False, "error": "entry.command 为空"}
            cwd = _render(meta.entry.get("cwd") or str(meta.dir), ctx)
            env = dict(os.environ)
            env.update({str(k): str(_render(v, ctx))
                        for k, v in (meta.entry.get("env") or {}).items()})
            # 让子进程能识别自己身处星港
            env["STARPORT_APP_ID"] = meta.id
            env["STARPORT_PORT"] = str(port)
            env["STARPORT_DATA_DIR"] = str(paths.app_data_dir(meta.id))
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUNBUFFERED"] = "1"

            log_path = paths.app_log_path(app_id)
            try:
                logf = open(log_path, "w", encoding="utf-8", errors="replace")
            except Exception:
                logf = subprocess.DEVNULL  # type: ignore[assignment]

            flags = 0
            if os.name == "nt":
                flags |= subprocess.CREATE_NEW_PROCESS_GROUP   # 不传染 Ctrl+C

            try:
                proc = subprocess.Popen(
                    cmd, cwd=str(cwd), env=env,
                    stdout=logf, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=flags,
                )
            except Exception as exc:
                ports.release(port)
                if logf is not subprocess.DEVNULL:
                    logf.close()
                rt.status = STATUS_ERROR
                rt.error = f"启动失败：{exc}"
                return {"ok": False, "error": rt.error}

            rt.proc, rt.port, rt.log = proc, port, log_path
            rt.status, rt.error, rt.exit_code = STATUS_STARTING, None, None
            rt.pid, rt.started_at = proc.pid, time.time()

            # ★ 挂进平台的 Job Object：平台若被强杀，OS 会连带回收这个进程，
            #   避免它变成孤儿继续占端口（详见 core/jobobj.py）
            jobobj.PLATFORM_JOB.assign(proc)

            ok = self._wait_ready(meta, rt)
            if not ok:
                detail = rt.error or "启动超时或进程提前退出"
                self.stop(app_id, force=True)
                return {"ok": False, "error": detail,
                        "log": _tail(rt.log) if rt.log else ""}

            rt.status = STATUS_RUNNING
            threading.Thread(target=self._watch, args=(app_id, proc),
                             daemon=True, name=f"watch-{app_id}").start()
            return {"ok": True, "status": rt.status, "url": rt.url,
                    "port": rt.port, "pid": rt.pid}

    # ------------------------------------------------------------ 就绪探测
    def _wait_ready(self, meta: AppMeta, rt: AppRuntime) -> bool:
        h = meta.health
        timeout = float(h.get("timeout") or 25)
        path = h.get("path") or ("/api/health" if meta.type == TYPE_WEBSERVICE else "")
        pattern = h.get("stdout_port_pattern")
        rx = re.compile(pattern) if pattern else None

        if meta.type == TYPE_EXTERNAL:
            # 原生程序：只等一小会儿确认没立刻死掉
            time.sleep(1.2)
            if rt.proc is not None and rt.proc.poll() is not None:
                rt.error = f"进程立即退出（code={rt.proc.returncode}）"
                return False
            rt.url = None
            return True

        deadline = time.time() + timeout
        port = rt.port or 0
        while time.time() < deadline:
            if rt.proc is not None and rt.proc.poll() is not None:
                rt.error = (f"进程提前退出（code={rt.proc.returncode}）\n"
                            + _tail(rt.log, 25))
                return False

            # 应用自己换了端口（如 FileCleanup 会顺延）→ 从 stdout 里抓真实端口
            if rx and rt.log and rt.log.exists():
                m = rx.search(rt.log.read_text("utf-8", errors="replace"))
                if m:
                    newp = int(m.group(1))
                    if newp != port:
                        ports.release(port)
                        port = newp
                        ports.reserve(port, meta.id)
                        rt.port = newp

            if path:
                url = f"http://127.0.0.1:{port}{path}"
                if _http_ok(url, timeout=1.2):
                    rt.url = self._view_url(meta, port)
                    return True
            elif _tcp_open(port):
                rt.url = self._view_url(meta, port)
                return True

            time.sleep(0.35)

        rt.error = f"等待就绪超时（{timeout:.0f}s）"
        return False

    @staticmethod
    def _view_url(meta: AppMeta, port: int) -> str:
        p = meta.view.get("path") or "/"
        return f"http://127.0.0.1:{port}{p}"

    # ------------------------------------------------------------ 崩溃监视
    def _watch(self, app_id: str, proc: subprocess.Popen) -> None:
        rc = proc.wait()
        rt = self._runtime_nocreate(app_id)
        if rt is None or rt.proc is not proc:
            return                                  # 已被 stop/restart 接管
        with self._lock:
            if rt.status == STATUS_STOPPED:
                return                              # 正常停止，不算崩溃
            rt.exit_code = rc
            rt.status = STATUS_CRASHED if rc not in (0, None) else STATUS_STOPPED
            rt.error = _tail(rt.log, 30) if rt.log else None
            ports.release(rt.port)
            rt.port, rt.url, rt.pid = None, None, None

        auto = bool(CONFIG.platform.get("auto_restart_on_crash", False))
        if auto and rt.status == STATUS_CRASHED and rt.restarts < 3:
            rt.restarts += 1
            time.sleep(1.0)
            self.launch(app_id)

    def _runtime_nocreate(self, app_id: str) -> AppRuntime | None:
        with self._lock:
            return self._rt.get(app_id)

    # ------------------------------------------------------------ 停止
    def stop(self, app_id: str, force: bool = False) -> dict[str, Any]:
        meta = self.registry.get(app_id)
        rt = self.runtime(app_id)
        with self._lock:
            proc, port = rt.proc, rt.port

            # 优先走应用声明的优雅退出接口
            if (not force) and meta and meta.stop.get("method") == "http":
                spath = meta.stop.get("path") or "/api/shutdown"
                if port:
                    try:
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{port}{spath}", data=b"{}",
                            headers={"Content-Type": "application/json"},
                            method="POST")
                        urllib.request.urlopen(req, timeout=2).close()
                    except Exception:
                        pass
                    for _ in range(30):             # 最多等 3s 让它自己收摊
                        if proc is None or proc.poll() is not None:
                            break
                        time.sleep(0.1)

            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except Exception:
                    pass
            if proc is not None and proc.poll() is None:
                self._kill_tree(proc.pid)

            rt.status = STATUS_STOPPED
            rt.proc, rt.pid, rt.url = None, None, None
            rt.error = None
            ports.release(port)
            rt.port = None
            return {"ok": True, "status": rt.status}

    @staticmethod
    def _kill_tree(pid: int) -> None:
        """Windows 下 terminate 只杀单个进程，用 taskkill /T 收掉整个进程树。"""
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=8,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            try:
                os.kill(pid, 9)
            except Exception:
                pass

    def restart(self, app_id: str) -> dict[str, Any]:
        self.stop(app_id)
        return self.launch(app_id)

    def stop_all(self) -> None:
        for app_id in list(self._rt.keys()):
            try:
                self.stop(app_id)
            except Exception:
                pass

    # ------------------------------------------------------------ 状态
    def status(self, app_id: str) -> dict[str, Any]:
        meta = self.registry.get(app_id)
        rt = self._runtime_nocreate(app_id) or AppRuntime(app_id=app_id)
        return {
            "id": app_id,
            "status": rt.status,
            "port": rt.port,
            "url": rt.url,
            "pid": rt.pid,
            "exit_code": rt.exit_code,
            "error": rt.error,
            "restarts": rt.restarts,
            "uptime": (int(time.time() - rt.started_at)
                       if rt.started_at and rt.status == STATUS_RUNNING else 0),
            "log": str(rt.log) if rt.log else "",
            "type": meta.type if meta else None,
        }
