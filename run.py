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
import atexit
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import console                                  # noqa: E402

# ★ 必须最早调用：pythonw 无窗口运行时把日志重定向到文件，否则 print 会当场崩
HEADLESS = console.setup()

from core import instance, jobobj, paths                  # noqa: E402
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


def _release_instance(port: int, pid: int) -> None:
    """退出时抹掉自己的留痕。atexit 兜底，任何异常都不许冒出去。"""
    try:
        instance.unregister(port)
        instance.release_primary(pid)
    except BaseException:
        pass


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
    parser.add_argument("--allow-second", action="store_true",
                        help="允许再起一个实例（调试用；默认已有实例时直接复用它）")
    parser.add_argument("--autostarted", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    # 显式 --port 视为"刻意要开第二份"，不参与单实例复用（工单里那个
    # 19600 调试实例就是这么起的）。其余情况只允许一个星港。
    want_second = bool(args.port) or args.allow_second

    if sys.version_info < (3, 10):
        msg = "需要 Python 3.10 或更高版本"
        print(msg)
        if HEADLESS:
            console.notify("StarPort 启动失败", msg)
        return 1

    paths.ensure_dirs()

    # ★ 单实例复用：已经有星港在跑，就把它的窗口提到前台，本次不再起第二份。
    #   判据是"端口上真有一个星港在应答"（core/instance.py），不是 PID，
    #   所以被强杀留下的陈旧记录不会误伤 —— 也不会再攒出"看不见的幽灵实例"。
    if not want_second:
        prev = instance.live_primary()
        if prev:
            print(f"[StarPort] 已有实例在运行：PID {prev.get('pid')} "
                  f"端口 {prev.get('port')} 启动于 {prev.get('started')} —— 本次不再重复启动")
            if not args.no_window and not focus_window(TITLE):
                # 窗口没找到（对方多半是 --no-window 实例）：弹一条能看懂的提示，
                # 否则用户双击了却什么都没发生，又是一笔糊涂账。
                console.notify(
                    "StarPort 已在运行",
                    f"PID {prev.get('pid')}　端口 {prev.get('port')}\n"
                    f"启动于 {prev.get('started')}\n\n"
                    f"本次没有重复启动。要重启请先关掉它：\n"
                    f"　python tools\\stop_instance.py",
                    error=False)
            return 0

    # ★ --port 只表示"本次启动优先用这个端口"，不再写回 CONFIG。
    #   写回会被随后任意一次配置保存（/api/settings）带进 data/config.json，
    #   把平台永久钉死在这个端口上 —— 2026-09-23 那次 WinError 10048
    #   （19600 被一个 --no-window 残留实例占住，之后每次启动都撞它）
    #   就是这么形成的。顺延逻辑在 core/server.py::serve()。

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

    # ★ 留痕：让这个实例可被发现、可被关闭（data/instances/<port>.json）。
    #   每个实例都留（包括 --port 起的第二实例）—— 看不见的进程必须留得下痕迹。
    mode = "no-window" if args.no_window else "window"
    instance.register(port, os.getpid(), mode)
    atexit.register(_release_instance, port, os.getpid())

    if not want_second:
        if instance.acquire_primary(port, os.getpid(), mode):
            atexit.register(instance.release_primary, os.getpid())
            print(f"[StarPort] 主实例留痕：PID {os.getpid()} 端口 {port}")

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
    # ★ 在这里显式删掉自己的留痕，别只指望 atexit：解释器关闭阶段某些操作
    #   （开线程、部分文件操作）已经不可靠了，atexit 里的删除有可能是空跑。
    #   两条路都留着：这里是正常路径，atexit 兜底异常路径。
    _release_instance(port, os.getpid())
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
