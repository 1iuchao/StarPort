#!/usr/bin/env python
"""StarPort（星岗）· 本地应用聚合平台 —— 启动入口。

    python run.py                 # 启动平台并打开窗口
    python run.py --port 19500    # 指定平台端口
    python run.py --no-window     # 只起服务，不开窗口（后台模式）
    python run.py --autostarted   # 开机自启时内部使用（不弹额外提示）

平台本体只依赖 Python 标准库；界面用原生窗口承载，数据全在本地。
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import console                                  # noqa: E402

# ★ 必须最早调用：pythonw 无窗口运行时把日志重定向到文件，否则 print 会当场崩
HEADLESS = console.setup()

from core import jobobj, paths                            # noqa: E402
from core.hotkey import HOTKEY                            # noqa: E402
from core.server import CTX, serve                        # noqa: E402
from core.settings import CONFIG                          # noqa: E402
from core.window import TITLE, focus_window, open_window  # noqa: E402

HEARTBEAT_TIMEOUT = 60      # 壳失联超过这个秒数就认为窗口已关，平台自动退出


def _apply_runtime() -> None:
    """配置变更后重新生效的部分：开机自启 + 全局快捷键。"""
    # 开机自启
    try:
        from core import autostart
        from core.window import autostart_command
        want = bool(CONFIG.platform.get("autostart", False))
        ok, msg = autostart.sync(autostart_command(), want)
        if not ok:
            print(f"[StarPort] 开机自启设置失败：{msg}")
    except Exception as exc:
        print(f"[StarPort] 开机自启不可用：{exc}")

    # 全局快捷键
    hk = CONFIG.platform.get("hotkey") or {}
    try:
        if hk.get("enabled", True):
            HOTKEY.start(list(hk.get("modifiers") or ["ctrl", "alt"]),
                         str(hk.get("key") or "S"),
                         lambda: focus_window(TITLE))
        else:
            HOTKEY.stop()
    except Exception as exc:
        print(f"[StarPort] 全局快捷键不可用：{exc}")


def _watchdog(stop_event: threading.Event) -> None:
    """壳心跳监视：用户关掉窗口 = 退出平台（连带回收所有应用进程）。"""
    while not stop_event.is_set():
        stop_event.wait(5)
        if not CTX.heartbeat_seen:
            continue
        if time.time() - CTX.last_heartbeat > HEARTBEAT_TIMEOUT:
            print("[StarPort] 壳已失联，平台自动退出")
            stop_event.set()
            break


def main() -> int:             # noqa: C901
    parser = argparse.ArgumentParser(
        prog="StarPort",
        description="StarPort · 星港：本地应用聚合平台（插件化、离线、进程隔离）")
    parser.add_argument("--port", type=int, default=0, help="平台监听端口（0=自动）")
    parser.add_argument("--no-window", action="store_true", help="只起服务不开窗口")
    parser.add_argument("--autostarted", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if sys.version_info < (3, 10):
        msg = "需要 Python 3.10 或更高版本"
        print(msg)
        if HEADLESS:
            console.notify("StarPort 启动失败", msg)
        return 1

    paths.ensure_dirs()
    if args.port:
        CONFIG.platform["port_base"] = args.port

    # ★ 建立 Job Object：平台一旦退出（含被任务管理器强杀），
    #   OS 会连带回收所有应用进程，不留孤儿占端口
    job_ok = jobobj.setup()
    print(f"[StarPort] 孤儿进程兜底："
          f"{'已启用（Job Object）' if job_ok else '不可用 —— ' + jobobj.PLATFORM_JOB.error}")

    try:
        httpd, port = serve(port=args.port or 0, background=True)
    except Exception as exc:
        base = CONFIG.platform.get("port_base")
        msg = (f"平台启动失败：{exc}\n\n"
               f"常见原因：{base} 起的连续端口都被占用。\n"
               f"换个端口再试：run.py --port 19500")
        print(f"[StarPort] {msg}")
        if HEADLESS:
            console.notify("StarPort 启动失败", msg)
        return 1

    CTX.apply_runtime = _apply_runtime
    print(f"[StarPort] 平台已启动：http://127.0.0.1:{port}/  "
          f"(应用数 {len(CTX.registry.all())})")

    _apply_runtime()

    url = f"http://127.0.0.1:{port}/"
    if not args.no_window:
        mode = open_window(url)
        print(f"[StarPort] 窗口模式：{mode}")
        if mode == "none":
            print(f"[StarPort] 没能起窗口，请手动打开：{url}")

    stop_event = threading.Event()
    CTX.on_shutdown = stop_event.set
    threading.Thread(target=_watchdog, args=(stop_event,),
                     daemon=True, name="watchdog").start()

    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[StarPort] 收到中断信号")

    print("[StarPort] 正在回收应用进程…")
    try:
        CTX.supervisor.stop_all()          # type: ignore[union-attr]
    except Exception:
        pass
    HOTKEY.stop()
    try:
        httpd.shutdown()
        httpd.server_close()
    except Exception:
        pass
    # 关闭 job 句柄：此刻 job 内若还有漏网进程，会被 OS 立即回收
    jobobj.PLATFORM_JOB.close()
    print("[StarPort] 已退出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
