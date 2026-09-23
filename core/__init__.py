"""StarPort 平台内核。

分层原则（与 FileCleanup 一致的一贯思路）：
  - 内核不认识任何具体应用，只认识 manifest 契约；
  - 应用之间只通过「进程 + 端口 + HTTP」通信，内核不 import 应用代码；
  - 新增应用 = 丢一个目录进 apps/，不改本文件。
"""

__all__ = ["paths", "settings", "ports", "registry", "supervisor", "server"]

VERSION = "0.1.0"
PLATFORM_NAME = "StarPort"
PLATFORM_TITLE = "StarPort · 星港"
