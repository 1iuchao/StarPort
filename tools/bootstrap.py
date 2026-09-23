"""StarPort 启动引导（给 启动 StarPort.bat 调用）。

为什么要有这个文件：
  cmd.exe 在 chcp 生效**之前**就按 ANSI(cp936) 解析了整个 bat，
  所以 bat 里任何中文都会乱码，甚至把注释截断成命令。
  因此 bat 保持纯 ASCII，所有中文提示由本脚本用 Python 打印
  （Python 的 stdout 编码可控，不受 cmd 解析影响）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BANNER = """
  ==========================================================
   StarPort · 星港 —— 本地应用聚合平台
  ==========================================================
"""


def main() -> int:
    if len(sys.argv) < 3:
        print("参数不足（内部脚本，请通过 启动 StarPort.bat 运行）")
        return 2

    entry, py = sys.argv[1], sys.argv[2]

    root = Path(entry).parent

    # 版本校验放在这里做：bat 里嵌套引号太脆，容易 "" unexpected
    if sys.version_info < (3, 10):
        print(BANNER)
        print(f"  [错误] Python 版本过低：{sys.version.split()[0]}")
        print(f"  需要 3.10 或更高版本。当前解释器：{py}")
        print()
        print("  提示：可以在 StarPort 的「设置 → 通用」里手动指定 python_path。")
        return 1

    print(BANNER)
    print(f"   平台目录 : {root}")
    print(f"   Python   : {py}  ({sys.version.split()[0]})")
    print()
    print("   正在启动，稍候应用窗口会自动弹出…")
    print("   关闭本窗口 = 关闭平台（会一并回收所有应用进程）")
    print()
    print("  ----------------------------------------------------------")
    sys.stdout.flush()

    cmd = [py, entry]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(root),
            env={**os.environ,
                 "PYTHONIOENCODING": "utf-8",
                 "PYTHONUNBUFFERED": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            bufsize=1,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as exc:
        print(f"\n  [错误] 启动失败：{exc}")
        return 1

    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
    except KeyboardInterrupt:
        proc.terminate()

    rc = proc.wait()
    print("  ----------------------------------------------------------")
    if rc == 0:
        print("   StarPort 已正常退出。")
    else:
        print(f"   StarPort 退出，返回码 = {rc}")
        print("   若因端口被占用启动失败，可手动运行：")
        print(f"     {py} {Path(entry).name} --port 19500")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
