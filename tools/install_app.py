#!/usr/bin/env python
"""命令行安装 / 卸载应用（平台没在跑也能用，直接写 apps/ 目录）。

    python tools/install_app.py E:/MyApp                 # 从目录安装（需含 manifest.json）
    python tools/install_app.py E:/MyApp/starport.json   # 直接给 manifest 文件
    python tools/install_app.py --list                   # 列出已注册应用
    python tools/install_app.py --remove myapp           # 卸载
    python tools/install_app.py --check                  # 校验所有 manifest
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import paths                       # noqa: E402
from core.registry import MANIFEST_NAME, Registry  # noqa: E402


def cmd_list(reg: Registry) -> int:
    apps = reg.all()
    if not apps:
        print("（还没有应用）")
        return 0
    w = max(len(a.id) for a in apps)
    for a in apps:
        flag = "启用" if a.enabled else "禁用"
        print(f"  {a.id:<{w}}  {a.name:<16} {a.type:<11} [{flag}]  {a.dir}")
        for issue in a.issues:
            print(f"      ! {issue}")
    return 0


def cmd_check(reg: Registry) -> int:
    bad = 0
    for a in reg.all():
        if a.issues:
            bad += 1
            print(f"[有问题的] {a.id}")
            for i in a.issues:
                print(f"   - {i}")
    print("全部通过" if not bad else f"{bad} 个应用有问题")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="StarPort 应用安装工具")
    ap.add_argument("source", nargs="?", help="应用目录或 manifest.json 路径")
    ap.add_argument("--list", action="store_true", help="列出已注册应用")
    ap.add_argument("--check", action="store_true", help="校验 manifest")
    ap.add_argument("--remove", metavar="APP_ID", help="卸载应用")
    ap.add_argument("--keep-files", action="store_true", help="卸载时保留文件")
    args = ap.parse_args()

    paths.ensure_dirs()
    reg = Registry()

    if args.list:
        return cmd_list(reg)
    if args.check:
        return cmd_check(reg)
    if args.remove:
        res = reg.uninstall(args.remove, remove_files=not args.keep_files)
        print(res.get("error") or f"已卸载：{res.get('removed')}")
        return 0 if res.get("ok") else 1
    if not args.source:
        ap.print_help()
        return 1

    src = args.source
    res = reg.install(src)
    if not res.get("ok"):
        print(f"安装失败：{res.get('error')}")
        return 1
    print(f"已安装：{res['id']}  →  {res['dir']}")
    print(f"提示：目录里必须含 {MANIFEST_NAME}；平台重启或点「重新扫描」即可看到。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
