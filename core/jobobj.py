"""Job Object：应用进程的"总闸"。

解决的问题（真实场景）：
    用户不小心关掉启动窗口 → 平台进程被 Windows 强杀 →
    run.py 的 finally / stop_all() 根本来不及执行 →
    应用子进程（如 FileCleanup）变成**孤儿**，继续占着 19100 端口，
    界面却没了。结果就是"星港还在却不能用"，还得去任务管理器手动杀。

机制：
    把每个应用进程挂进一个 Job Object，并设置
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE。这个 flag 的含义是
    「只要 job 的句柄一关（进程死了句柄自然关），OS 立刻杀掉 job 内所有进程」。
    于是无论平台怎么死 —— 正常退出、被任务管理器结束、蓝屏前的崩溃 ——
    应用进程都会被系统一并回收，**不留孤儿**。

    这是内核级保证，比在 Python 里写 finally 可靠得多：进程被 TerminateProcess
    时根本没有任何 Python 代码会执行。

纯 ctypes 实现，零第三方依赖。任何一步失败都静默降级，绝不影响平台运行。
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

# ---------------------------------------------------------------- Win32 常量
JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

_is_windows = os.name == "nt"

if _is_windows:
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.restype = wintypes.BOOL
    _k32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _k32.AssignProcessToJobObject.restype = wintypes.BOOL
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.TerminateJobObject.restype = wintypes.BOOL
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.CloseHandle.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]


class JobGuard:
    """一个 Job Object 句柄的持有者。

    ⚠️ 必须让实例长期存活（模块级单例）：句柄一旦被 GC 关闭，
    kill-on-close 立刻触发，所有应用会被当场杀掉。
    """

    def __init__(self) -> None:
        self.handle: Any = None
        self.ok = False
        self.error = ""
        self.members = 0

    def create(self) -> bool:
        if not _is_windows:
            self.error = "仅支持 Windows"
            return False
        try:
            h = _k32.CreateJobObjectW(None, None)
            if not h:
                self.error = f"CreateJobObject 失败 (err={ctypes.get_last_error()})"
                return False

            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            ok = _k32.SetInformationJobObject(
                h, JobObjectExtendedLimitInformation,
                ctypes.byref(info), ctypes.sizeof(info))
            if not ok:
                _k32.CloseHandle(h)
                self.error = (f"SetInformationJobObject 失败 "
                              f"(err={ctypes.get_last_error()})")
                return False

            self.handle = h
            self.ok = True
            return True
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            return False

    def assign(self, proc: subprocess.Popen | int) -> bool:
        """把进程挂进 job。传 Popen 或 pid 都行。"""
        if not self.ok or not self.handle:
            return False
        try:
            if isinstance(proc, int):
                # 只有 pid 时自己开带权限的句柄
                PROCESS_SET_QUOTA, PROCESS_TERMINATE = 0x0100, 0x0001
                h = _k32.OpenProcess(
                    PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, proc)
                if not h:
                    self.error = f"OpenProcess 失败 (err={ctypes.get_last_error()})"
                    return False
                try:
                    return self._assign_handle(h)
                finally:
                    _k32.CloseHandle(h)
            ph = getattr(proc, "_handle", None)
            if ph is None:
                return self.assign(proc.pid)
            return self._assign_handle(int(ph))
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            return False

    def _assign_handle(self, handle: int) -> bool:
        ok = _k32.AssignProcessToJobObject(self.handle,
                                           ctypes.c_void_p(handle))
        if ok:
            self.members += 1
            return True
        err = ctypes.get_last_error()
        self.error = f"AssignProcessToJobObject 失败 (err={err})"
        # 122 = ERROR_INSUFFICIENT_BUFFER 之类的历史坑，最常见是
        # 已在某个不允许嵌套的 job 里（Win7）。此时平台照常跑，只是没兜底。
        return False

    def terminate_all(self) -> None:
        """主动收掉 job 内所有进程（正常退出时不必调，close 即可）。"""
        if self.ok and self.handle:
            try:
                _k32.TerminateJobObject(self.handle, 0)
            except Exception:
                pass

    def close(self) -> None:
        if self.handle:
            try:
                _k32.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None
            self.ok = False

    @property
    def available(self) -> bool:
        return self.ok


# 模块级单例：必须长期持有，否则句柄被 GC 就触发全杀
PLATFORM_JOB = JobGuard()


def setup() -> bool:
    """在平台启动时调用一次。失败也不影响平台运行，只是少一层兜底。"""
    return PLATFORM_JOB.create()


def is_orphan_cleanup_available() -> bool:
    return PLATFORM_JOB.available


if __name__ == "__main__":
    # 自测：起一个长命进程，挂进 job，然后什么都不做看它会不会被回收
    print("Job 可用:", setup(), PLATFORM_JOB.error)
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    print("assign:", PLATFORM_JOB.assign(p), PLATFORM_JOB.error)
    print("子进程 pid:", p.pid)
    print("现在手动 kill 本脚本，观察子进程是否一起消失")
    time_sleep = __import__("time").sleep
    time_sleep(30)
