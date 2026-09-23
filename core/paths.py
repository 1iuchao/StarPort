"""路径常量：所有数据与状态都落在平台目录内，不写系统目录、不联网。

目录约定（可整体拷走，换台电脑即用）：
    StarPort/
    ├── apps/      应用插件（每个子目录一个 manifest.json）
    ├── data/      运行时状态（config.json / state.json / logs / apps-data）
    └── shell/     壳前端
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 冻结态（将来若打包成 exe）优先取可执行文件旁的真实目录
if getattr(sys, "frozen", False):                       # pragma: no cover
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent.parent

APPS_DIR = ROOT / "apps"
DATA_DIR = ROOT / "data"
LOG_DIR = DATA_DIR / "logs"
APP_DATA_DIR = DATA_DIR / "apps-data"          # 各应用私有数据根目录
SHELL_DIR = ROOT / "shell"
SDK_DIR = ROOT / "sdk"

CONFIG_FILE = DATA_DIR / "config.json"
STATE_FILE = DATA_DIR / "state.json"

EDGE_PROFILE = DATA_DIR / "shell-profile"      # Edge --app 模式独立 profile


def ensure_dirs() -> None:
    """保证运行时目录存在（首次启动自动创建）。"""
    for d in (APPS_DIR, DATA_DIR, LOG_DIR, APP_DATA_DIR, SHELL_DIR):
        d.mkdir(parents=True, exist_ok=True)


def app_dir(app_id: str) -> Path:
    return APPS_DIR / app_id


def app_data_dir(app_id: str) -> Path:
    p = APP_DATA_DIR / app_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def app_log_path(app_id: str) -> Path:
    return LOG_DIR / f"{app_id}.log"


def rel_to_root(p: os.PathLike | str) -> str:
    """把绝对路径显示成相对平台根目录的形式，便于配置迁移。"""
    try:
        return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")
    except Exception:
        return str(p)
