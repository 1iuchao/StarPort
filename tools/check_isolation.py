#!/usr/bin/env python
"""隔离自检：验证 Job Object 的孤儿回收真的生效。

    python tools/check_isolation.py

为什么需要这个：星港的核心承诺是"应用崩溃/平台被杀都不会留下乱摊子"，
而这层保证依赖一个 Windows 内核机制（Job Object）。内核机制会在
不同系统版本、不同启动方式下表现不同，所以必须能一键复核，
而不是靠"当时测过"。

做的事（对照实验）：
  1. 起一个"平台"父进程，它拉起一个长命子进程（模拟应用）
  2. 用 taskkill /F **不带 /T** 强杀父进程（避免进程树机制干扰结论）
  3. 看子进程是否被回收

  A 组：把子进程挂进 Job   → 期望：被回收
  B 组：不挂 Job（对照组） → 期望：变成孤儿（这正是要修的问题）

只有 A 回收、B 残留，才说明 Job 机制真的在起作用。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CHILD_CODE = "import time; time.sleep(600)"

# 被测试的"父进程"脚本：模拟平台的启动行为
PARENT_TEMPLATE = '''
import subprocess, sys, time
sys.path.insert(0, r"{root}")
mode = sys.argv[1]
pidfile = sys.argv[2]

if mode == "with-job":
    from core import jobobj
    jobobj.setup()

child = subprocess.Popen([sys.executable, "-c", "{child_code}"])

if mode == "with-job":
    from core import jobobj
    jobobj.PLATFORM_JOB.assign(child)

open(pidfile, "w").write(str(child.pid))
time.sleep(600)
'''


def alive(pid: int) -> bool:
    """中文 Windows 的 tasklist 输出是 GBK，逐行解析第 2 列拿 PID。"""
    raw = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                         capture_output=True).stdout
    for line in raw.decode("gbk", errors="replace").splitlines():
        cells = [c.strip().strip('"') for c in line.split(",")]
        if len(cells) >= 2:
            try:
                if int(cells[1]) == pid:
                    return True
            except ValueError:
                continue
    return False


def run_case(mode: str, parent_script: Path, pidfile: Path) -> bool:
    """返回 True 表示子进程被回收（孤儿未残留）。"""
    if pidfile.exists():
        pidfile.unlink()

    parent = subprocess.Popen([sys.executable, str(parent_script), mode, str(pidfile)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for _ in range(40):
        time.sleep(0.5)
        if pidfile.exists():
            break
    else:
        parent.kill()
        raise RuntimeError(f"[{mode}] 子进程未能启动")

    time.sleep(0.8)
    child_pid = int(pidfile.read_text().strip())

    # ★ 关键：不带 /T。否则进程树机制会替 Job 干活，结论就不成立了
    subprocess.run(["taskkill", "/PID", str(parent.pid), "/F"], capture_output=True)
    time.sleep(3.0)

    collected = not alive(child_pid)
    if not collected:                      # 残留的是孤儿，清理掉
        subprocess.run(["taskkill", "/PID", str(child_pid), "/T", "/F"],
                       capture_output=True)
    return collected


def main() -> int:
    print("=" * 64)
    print(" StarPort 隔离自检 —— Job Object 孤儿回收")
    print("=" * 64)
    print(" 场景：用户关掉启动窗口 / 任务管理器结束平台")
    print("       → 平台进程被强杀，Python 的 finally 完全来不及跑")
    print()

    if os.name != "nt":
        print(" 仅 Windows 需要跑这个自检（其他平台靠进程组语义）。")
        return 0

    from core import jobobj
    print(f"[环境] Job Object 支持："
          f"{'可用' if jobobj.PLATFORM_JOB.create() else '不可用 —— ' + jobobj.PLATFORM_JOB.error}")
    print()

    with tempfile.TemporaryDirectory() as tmp:
        parent_script = Path(tmp) / "_isolation_parent.py"
        parent_script.write_text(
            PARENT_TEMPLATE.format(root=str(ROOT), child_code=CHILD_CODE),
            encoding="utf-8")
        pidfile = Path(tmp) / "child.pid"

        print("[A 组] 挂 Job    … ", end="", flush=True)
        with_job = run_case("with-job", parent_script, pidfile)
        print("子进程被回收 ✓" if with_job else "子进程残留 ✗")

        print("[B 组] 不挂 Job  … ", end="", flush=True)
        no_job = run_case("no-job", parent_script, pidfile)
        print("子进程残留（对照组，符合预期）✓" if not no_job else "子进程被回收（意外）")

    print()
    print("-" * 64)
    if with_job and not no_job:
        print(" 结论：Job Object 生效 —— 平台被杀不会留下孤儿进程。")
        return 0
    if not with_job:
        print(" 结论：✗ Job 回收未生效！应用可能变成孤儿，请排查 jobobj.py。")
        return 1
    print(" 结论：对照异常（不挂 Job 也被回收），本次结论不可信，建议重跑。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
