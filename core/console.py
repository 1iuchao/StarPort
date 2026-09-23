"""StarPort 控制台输出编码修复（在 Windows 上 import 即生效）。

背景：cmd.exe 默认代码页是 cp936(GBK)，Python 的 stdout 若按 GBK 输出
中文，遇到生僻字符会抛 UnicodeEncodeError；而 bat 里 chcp 65001 之后
又可能与 Python 自身编码不一致。

做法：把 stdout/stderr 强制切到 UTF-8，并对无法编码的字符降级替换，
保证日志永远打得出来，不会因为一个字符把整个平台带崩。

用法（在入口最前面调用一次）：
    from core import console
    console.setup()
"""

from __future__ import annotations

import io
import sys


def setup(force: bool = True) -> None:
    """把标准输出/错误切到 UTF-8。非 Windows 或已就绪时安全跳过。"""
    if not force and sys.platform != "win32":
        return

    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        # 已经是 UTF-8 就别包第二层
        enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if enc.startswith("utf8"):
            continue
        try:
            buf = getattr(stream, "buffer", None)
            if buf is None:
                continue
            setattr(sys, name, io.TextIOWrapper(
                buf, encoding="utf-8", errors="replace", line_buffering=True))
        except Exception:
            # 换不动就算了，绝不能因此让平台起不来
            pass


def safe_print(*args, **kwargs) -> None:
    """兜底打印：任何情况下都不抛异常。"""
    try:
        print(*args, **kwargs)
    except Exception:
        try:
            text = " ".join(str(a) for a in args)
            sys.__stdout__.write(text.encode("ascii", "replace").decode("ascii") + "\n")
        except Exception:
            pass
