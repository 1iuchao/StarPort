"""应用注册表：扫描 apps/ 下的 manifest.json，完成注册 / 启用 / 禁用 / 卸载。

★ 关键约束：内核只解析 manifest，不 import 任何应用代码。
  新增应用 = 在 apps/ 下放一个目录，平台重启（或热重载）即可见。
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths
from .settings import CONFIG

MANIFEST_NAME = "manifest.json"

# 支持的应用类型
#   webservice : 拉起一个本地服务进程（Python/Node/exe 均可），健康检查通过后 iframe 嵌入
#   static     : 纯前端页面（HTML/JS），由平台静态托管后 iframe 嵌入，无需子进程
#   external   : 原生程序（绿色版 exe / 系统工具），平台负责启动与回收，不做嵌入
TYPE_WEBSERVICE = "webservice"
TYPE_STATIC = "static"
TYPE_EXTERNAL = "external"
VALID_TYPES = (TYPE_WEBSERVICE, TYPE_STATIC, TYPE_EXTERNAL)

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


@dataclass
class AppMeta:
    """一个已注册应用的元信息（不含运行时状态）。"""

    id: str
    name: str
    type: str
    dir: Path
    version: str = "0.0.0"
    category: str = "未分类"
    description: str = ""
    author: str = ""
    icon: str = ""
    tags: list[str] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    # -------------------------------------------------- 便捷读取
    @property
    def enabled(self) -> bool:
        return CONFIG.is_enabled(self.id, True)

    @property
    def entry(self) -> dict[str, Any]:
        return self.manifest.get("entry") or {}

    @property
    def health(self) -> dict[str, Any]:
        return self.manifest.get("health") or {}

    @property
    def view(self) -> dict[str, Any]:
        return self.manifest.get("view") or {}

    @property
    def stop(self) -> dict[str, Any]:
        return self.manifest.get("stop") or {}

    @property
    def icon_url(self) -> str:
        """图标访问地址；没有图标文件时返回空串（前端回落到首字图标）。"""
        if not self.icon:
            return ""
        return f"/_apps/{self.id}/{self.icon}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "type": self.type,
            "category": CONFIG.app_overrides(self.id).get("category", self.category),
            "description": self.description,
            "author": self.author,
            "tags": self.tags,
            "icon": self.icon_url,
            "enabled": self.enabled,
            "embeddable": self.type in (TYPE_WEBSERVICE, TYPE_STATIC),
            "issues": self.issues,
            "dir": str(self.dir),
        }


# ------------------------------------------------------------------ 解析
def _validate(raw: dict[str, Any], app_dir: Path) -> tuple[dict[str, Any], list[str]]:
    """补全默认值并收集问题（有问题不阻断注册，界面上标黄提示）。"""
    issues: list[str] = []
    aids = str(raw.get("id") or app_dir.name).strip()
    if not _ID_RE.match(aids):
        issues.append(f"id '{aids}' 不合法（只允许小写字母/数字/._-，且以字母或数字开头）")

    atype = str(raw.get("type") or "").strip()
    if atype not in VALID_TYPES:
        issues.append(f"type '{atype}' 不支持（可用：{', '.join(VALID_TYPES)}）")
        atype = atype or TYPE_WEBSERVICE

    out = dict(raw)
    out["id"] = aids
    out["type"] = atype
    out.setdefault("name", aids)
    out.setdefault("version", "0.0.0")
    out.setdefault("category", "未分类")
    out.setdefault("description", "")
    out.setdefault("author", "")

    if atype == TYPE_WEBSERVICE and not (out.get("entry") or {}).get("command"):
        issues.append("webservice 类型缺少 entry.command")

    icon = str(out.get("icon") or "")
    if icon and not (app_dir / icon).is_file():
        issues.append(f"图标文件不存在：{icon}")
        out["icon"] = ""

    return out, issues


def _load_one(app_dir: Path) -> AppMeta | None:
    mf = app_dir / MANIFEST_NAME
    if not mf.is_file():
        return None
    try:
        raw = json.loads(mf.read_text("utf-8"))
    except Exception as exc:
        return AppMeta(id=app_dir.name, name=app_dir.name, type=TYPE_WEBSERVICE,
                       dir=app_dir, issues=[f"manifest 解析失败：{exc}"])
    if not isinstance(raw, dict):
        return None
    raw, issues = _validate(raw, app_dir)
    return AppMeta(
        id=raw["id"],
        name=raw["name"],
        type=raw["type"],
        dir=app_dir,
        version=str(raw.get("version", "0.0.0")),
        category=str(raw.get("category", "未分类")),
        description=str(raw.get("description", "")),
        author=str(raw.get("author", "")),
        icon=str(raw.get("icon") or ""),
        tags=list(raw.get("tags") or []),
        manifest=raw,
        issues=issues,
    )


def scan() -> dict[str, AppMeta]:
    """扫描 apps/ 目录（每次调用都重新读盘，支持热插拔）。"""
    paths.ensure_dirs()
    out: dict[str, AppMeta] = {}
    for child in sorted(paths.APPS_DIR.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "_")):
            continue
        meta = _load_one(child)
        if meta is None:
            continue
        out[meta.id] = meta
    return out


class Registry:
    def __init__(self) -> None:
        self._apps: dict[str, AppMeta] = {}
        self.refresh()

    def refresh(self) -> None:
        self._apps = scan()

    def all(self) -> list[AppMeta]:
        return list(self._apps.values())

    def get(self, app_id: str) -> AppMeta | None:
        return self._apps.get(app_id)

    def meta_or_404(self, app_id: str) -> AppMeta:
        m = self.get(app_id)
        if m is None:
            raise KeyError(f"未注册的应用：{app_id}")
        return m

    # ------------------------------------------------------------ 写操作
    def set_enabled(self, app_id: str, enabled: bool) -> None:
        CONFIG.set_enabled(app_id, enabled)
        CONFIG.save()

    def set_category(self, app_id: str, category: str) -> None:
        CONFIG.app_overrides(app_id)["category"] = category
        CONFIG.save()

    def uninstall(self, app_id: str, remove_files: bool = True) -> dict[str, Any]:
        meta = self.get(app_id)
        if meta is None:
            return {"ok": False, "error": "应用不存在"}
        if remove_files:
            try:
                shutil.rmtree(meta.dir)
            except Exception as exc:
                return {"ok": False, "error": f"删除目录失败：{exc}"}
        CONFIG.forget_app(app_id)
        CONFIG.save()
        self._apps.pop(app_id, None)
        # 顺手清掉残留数据目录？保守起见保留，界面上提供单独清理入口
        return {"ok": True, "removed": str(meta.dir)}

    def install(self, source: str | Path,
                manifest_text: str | None = None) -> dict[str, Any]:
        """安装应用。

        source        可以是：应用目录 / manifest.json 路径 / 含 manifest.json 的 zip（暂未支持）
        manifest_text 直接给一段 manifest JSON 文本（此时 source 作为内容目录）
        """
        src = Path(source) if source else None
        if manifest_text:
            try:
                raw = json.loads(manifest_text)
            except Exception as exc:
                return {"ok": False, "error": f"manifest 不是合法 JSON：{exc}"}
            app_id = str(raw.get("id") or "").strip()
            if not app_id:
                return {"ok": False, "error": "manifest 缺少 id"}
            target = paths.app_dir(app_id)
            target.mkdir(parents=True, exist_ok=True)
            (target / MANIFEST_NAME).write_text(manifest_text, "utf-8")
        else:
            if src.is_file() and src.name == MANIFEST_NAME:
                mf, content_dir = src, src.parent
            elif src.is_dir() and (src / MANIFEST_NAME).is_file():
                mf, content_dir = src / MANIFEST_NAME, src
            else:
                return {"ok": False, "error": f"找不到 {MANIFEST_NAME}：{src}"}
            try:
                raw = json.loads(mf.read_text("utf-8"))
            except Exception as exc:
                return {"ok": False, "error": f"manifest 解析失败：{exc}"}
            app_id = str(raw.get("id") or "").strip()
            if not app_id:
                return {"ok": False, "error": "manifest 缺少 id"}
            target = paths.app_dir(app_id)
            if target.resolve() == content_dir.resolve():
                pass                                   # 就地安装，无需拷贝
            else:
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(content_dir, target)

        CONFIG.app_overrides(app_id).setdefault("enabled", True)
        CONFIG.save()
        self.refresh()
        return {"ok": True, "id": app_id, "dir": str(target)}
