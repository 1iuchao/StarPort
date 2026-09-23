#!/usr/bin/env python
"""关掉正在运行的 StarPort 实例 —— 尤其是 `--no-window` 那种看不见的。

    python tools/stop_instance.py                 # 只报告，不动手
    python tools/stop_instance.py --yes           # 关闭主实例（优雅关）
    python tools/stop_instance.py --yes --all     # 关闭所有实例
    python tools/stop_instance.py --yes --port 19600   # 关闭指定端口那个
    python tools/stop_instance.py --yes --force   # 优雅关无效时直接结束进程

为什么需要它：
    2026-09-23 的 WinError 10048 工单里，元凶是一个 `--no-window` 的调试实例：
    没窗口、没托盘、没痕迹，用户既看不见也关不掉，只能眼睁睁看它占着端口。
    原则是——**任何能"看不见地活着"的进程，都必须可被发现、可被关闭**。
    现在每个实例都会在 data/instances/<port>.json 留痕，本工具就是配套的
    "发现 + 关闭"那一半。

零第三方依赖。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import instance                                 # noqa: E402


def _graceful(port: int) -> bool:
    """走平台自己的退出流程（停应用、关 job、删留痕）。"""
    print(f"  请求 {port} 优雅退出…")
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/platform/shutdown",
            data=b"{}", method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3):
            pass
    except Exception as exc:
        print(f"    请求失败（可能正在退出）：{exc}")
    for i in range(20):                        # 最多等 10 秒
        time.sleep(0.5)
        if not instance.port_busy(port):
            print(f"    端口 {port} 已释放（等了 {(i + 1) * 0.5:.1f}s）。")
            return True
    return False


def _force(rec: dict) -> bool:
    pid = int(rec.get("pid") or 0)
    if not pid:
        return False
    cmd = ["taskkill", "/PID", str(pid), "/T", "/F"] if os.name == "nt" \
        else ["kill", "-TERM", str(pid)]
    print("  执行：", " ".join(cmd))
    if subprocess.run(cmd, capture_output=True).returncode != 0 and os.name == "nt":
        # /T 对某些进程树会失败，退一步只杀主进程
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    time.sleep(1.0)
    return not instance.port_busy(int(rec.get("port") or 0))


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="stop_instance", description="关闭正在运行的 StarPort 实例")
    parser.add_argument("--yes", action="store_true", help="真的动手（默认只报告）")
    parser.add_argument("--all", action="store_true", help="对所有实例生效")
    parser.add_argument("--port", type=int, default=0, help="只关这个端口上的实例")
    parser.add_argument("--force", action="store_true",
                        help="优雅关不掉时直接结束进程（会连带结束它启动的应用）")
    args = parser.parse_args()

    live = instance.live_all()                 # 顺带清掉陈旧留痕
    if args.port:
        live = [r for r in live if int(r.get("port") or 0) == args.port]
        if not live:
            print(f"端口 {args.port} 上没有在运行的星港（留痕也一并清了）。")
            return 0

    if not live:
        print("当前没有在运行的 StarPort 实例。")
        print("若仍有端口被占，用 Get-NetTCPConnection -State Listen 查是谁。")
        return 0

    print(f"在运行的实例：{len(live)} 个")
    for r in live:
        print(f"  PID {r.get('pid')}  端口 {r.get('port')}  "
              f"模式 {r.get('mode')}  启动于 {r.get('started')}")

    if len(live) > 1 and not args.all and not args.port:
        print("\n有多个实例。加 --all 全关，或用 --port <端口> 指定一个。")
        return 0

    if not args.yes:
        print("\n以上是全部信息（未动手）。加 --yes 关闭。")
        return 0

    rc = 0
    for r in live:
        port = int(r.get("port") or 0)
        print(f"\n-- 关闭 {port} --")
        if not _graceful(port):
            print("  优雅关没有生效。")
            if not args.force:
                print("  加 --force 可直接结束进程。")
                rc = 1
                continue
            if not _force(r):
                print(f"  端口 {port} 仍被占用，请手动检查。")
                rc = 1
                continue
        instance.unregister(port)
        print("  已关闭。")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
