"""控制台与日志：保证在任何 Windows 运行方式下输出都不会丢、不会崩。

三种运行方式都要兜住：
  1. 双击 bat（有控制台）          → 修 UTF-8，日志直接打在窗口上
  2. pythonw 无窗口启动（日常推荐） → 没有 stdout，重定向到 data/logs/platform.log
  3. 命令行 python run.py          → 同 1

为什么必须有这个模块：pythonw.exe 下 sys.stdout 是 **None**，
任何 print() 都会抛 AttributeError，平台会当场起不来。
"""

from __future__ import annotations

import io
import sys
import time
from pathlib import Path

MAX_LOG_BYTES = 2 * 1024 * 1024        # 单份日志上限 2MB，超过就轮转
ROTATED_SUFFIX = ".1"


def _default_log_path() -> Path:
    root = Path(__file__).resolve().parent.parent
    return root / "data" / "logs" / "platform.log"


def _rotate(path: Path) -> None:
    """简单轮转：超限就把当前日志挪成 .1（覆盖旧 .1）。不抛异常。"""
    try:
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            backup = path.with_suffix(path.suffix + ROTATED_SUFFIX)
            if backup.exists():
                backup.unlink()
            path.replace(backup)
    except Exception:
        pass


def _to_utf8(stream) -> None:
    """把已有流换成 UTF-8 包装（Windows 控制台常见问题）。"""
    enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
    if enc.startswith("utf8"):
        return
    try:
        buf = getattr(stream, "buffer", None)
        if buf is None:
            return
        name = "stdout" if stream is sys.stdout else "stderr"
        setattr(sys, name, io.TextIOWrapper(
            buf, encoding="utf-8", errors="replace", line_buffering=True))
    except Exception:
        # 换不动就算了，绝不能因此让平台起不来
        pass


def _has_console() -> bool:
    """当前进程是否真的有一个可见的控制台窗口。

    为什么不用 `sys.stdout is None` 判断：pythonw.exe 启动时，
    如果父进程把 std 句柄传了下来（bat 的 start 就会），sys.stdout 是**存在**的，
    只是指向一个用户看不见的地方 —— 日志会静默丢失。
    GetConsoleWindow() 才是可靠判据：没有控制台它返回 0。
    """
    if sys.platform != "win32":
        return sys.stdout is not None
    try:
        import ctypes
        return ctypes.windll.kernel32.GetConsoleWindow() != 0
    except Exception:
        return sys.stdout is not None


def setup(log_file: str | Path | None = None, force: bool = True) -> bool:
    """初始化输出。返回 True 表示当前是**无控制台**环境（已重定向到日志文件）。

    在入口最早期调用，之后再 import 其他模块。
    """
    if sys.platform != "win32":
        if not force:
            return False
        for name in ("stdout", "stderr"):
            s = getattr(sys, name, None)
            if s is not None:
                _to_utf8(s)
        return False

    headless = not _has_console()

    if headless:
        path = Path(log_file) if log_file else _default_log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _rotate(path)
            f = open(path, "a", encoding="utf-8", errors="replace", buffering=1)
            f.write(f"\n===== StarPort 启动 {time.strftime('%Y-%m-%d %H:%M:%S')} "
                    f"(pythonw 无窗口模式) =====\n")
            f.flush()
            sys.stdout = f
            sys.stderr = f
        except Exception:
            # 日志都开不了也得让平台跑起来：塞个黑洞
            class _Null:
                encoding = "utf-8"

                def write(self, *_a):
                    return 0

                def flush(self):
                    pass

            sys.stdout = _Null()          # type: ignore[assignment]
            sys.stderr = sys.stdout
        return True

    _to_utf8(sys.stdout)
    _to_utf8(sys.stderr)
    return False


def notify(title: str, message: str, error: bool = True) -> None:
    """用系统弹窗告知用户（无控制台时才有意义）。

    纯 Win32 MessageBoxW，不依赖 Ask/COM，也不会被安全策略拦。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        MB_OK = 0x0
        MB_ICONERROR = 0x10
        MB_ICONINFORMATION = 0x40
        MB_SETFOREGROUND = 0x10000
        flags = MB_OK | (MB_ICONERROR if error else MB_ICONINFORMATION) | MB_SETFOREGROUND
        ctypes.windll.user32.MessageBoxW(None, str(message), str(title), flags)
    except Exception:
        pass


def safe_print(*args, **kwargs) -> None:
    """兜底打印：任何情况下都不抛异常。"""
    try:
        print(*args, **kwargs)
    except Exception:
        pass
