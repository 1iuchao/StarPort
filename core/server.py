"""平台 HTTP 服务：托管壳前端 + 提供管理 REST API。

只监听 127.0.0.1。所有 handler 都做了异常兜底——
单个请求出错只影响该请求，不会把平台进程带死。
"""

from __future__ import annotations

import json
import mimetypes
import os
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from . import paths, ports
from .registry import Registry
from .settings import CONFIG
from .state import STATE
from .supervisor import Supervisor

MIME_FIX = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}


class PlatformContext:
    """把平台各组件串起来，供 handler 使用。"""

    def __init__(self) -> None:
        self.registry = Registry()
        self.port = 0
        self.supervisor: Supervisor | None = None
        self.on_shutdown: Callable[[], None] | None = None
        self.apply_runtime: Callable[[], None] | None = None
        self.last_heartbeat = 0.0
        self.heartbeat_seen = False

    def settings_changed(self) -> None:
        """配置被改后需要"重新生效"的部分（开机自启、快捷键等）。"""
        if self.apply_runtime:
            try:
                self.apply_runtime()
            except Exception:
                pass

    def attach(self, port: int) -> None:
        self.port = port
        self.supervisor = Supervisor(self.registry, port)


CTX = PlatformContext()


def _within_root(path: Path) -> bool:
    """静态文件只允许从平台目录内取，防止路径穿越。"""
    try:
        return str(path.resolve()).startswith(str(paths.ROOT.resolve()))
    except Exception:
        return False


# ------------------------------------------------------------------ handler
class Handler(BaseHTTPRequestHandler):
    server_version = "StarPort/0.1"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------ 工具
    def _json(self, data: Any, code: int = 200) -> None:
        try:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        except Exception as exc:                       # 序列化失败也要给响应
            body = json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
            code = 500
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _text(self, text: str, ctype: str = "text/plain; charset=utf-8") -> None:
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, cache: str = "no-cache") -> None:
        if not path.is_file():
            self.send_error(404)
            return
        ctype = MIME_FIX.get(path.suffix.lower()) or \
            mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if ctype.startswith("text/") and "charset" not in ctype:
            ctype += "; charset=utf-8"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            out = json.loads(raw.decode("utf-8"))
            return out if isinstance(out, dict) else {}
        except Exception:
            return {}

    def log_message(self, fmt: str, *args) -> None:
        msg = fmt % args
        if "/api/heartbeat" in msg or "/api/status" in msg:
            return
        sys.stderr.write(f"[StarPort] {self.log_date_time_string()} {msg}\n")

    def handle_one_request(self) -> None:
        """吞掉客户端半途断开导致的 ConnectionAbortedError。

        浏览器预连接/取消请求时会 RST 掉连接，socketserver 默认会把整个
        traceback 打到控制台 —— 那是噪音，不是故障。这里静默处理。
        """
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True
        except OSError as exc:
            if getattr(exc, "winerror", None) in (10053, 10054, 10058):
                self.close_connection = True
            else:
                raise

    # ------------------------------------------------------------ GET
    def do_HEAD(self) -> None:
        """浏览器（尤其 Edge/Chromium）会对资源发 HEAD 探测。

        BaseHTTPRequestHandler 默认返回 501，虽然不影响后续 GET，
        但在日志里很吵，也会让个别客户端判定站点异常——这里补一个正确的实现。
        """
        try:
            path = urlparse(self.path).path
            target: Path | None = None
            if path in ("/", "/index.html"):
                target = paths.SHELL_DIR / "index.html"
            elif path.startswith("/shell/"):
                target = paths.SHELL_DIR / unquote(path[len("/shell/"):])
            elif path.startswith("/_apps/"):
                rest = unquote(path[len("/_apps/"):])
                app_id, _, rel = rest.partition("/")
                meta = CTX.registry.get(app_id)
                if meta is not None:
                    cand = (meta.dir / rel).resolve()
                    if str(cand).startswith(str(meta.dir.resolve())):
                        target = cand

            if target is None or not target.is_file() or not _within_root(target):
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            ctype = MIME_FIX.get(target.suffix.lower()) or \
                mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if ctype.startswith("text/") and "charset" not in ctype:
                ctype += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(target.stat().st_size))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
        except Exception:
            try:
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.end_headers()
            except Exception:
                pass

    def do_GET(self) -> None:                          # noqa: C901
        try:
            self._route_get()
        except Exception as exc:
            try:
                self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)
            except Exception:
                pass

    def _route_get(self) -> None:
        url = urlparse(self.path)
        path, query = url.path, parse_qs(url.query)

        # ---- 壳前端
        if path in ("/", "/index.html"):
            return self._file(paths.SHELL_DIR / "index.html")
        if path.startswith("/shell/"):
            return self._file(paths.SHELL_DIR / unquote(path[len("/shell/"):]))

        # ---- 应用静态资源（图标 / static 型应用页面）
        if path.startswith("/_apps/"):
            rest = unquote(path[len("/_apps/"):])
            app_id, _, rel = rest.partition("/")
            meta = CTX.registry.get(app_id)
            if meta is None:
                return self._json({"ok": False, "error": "应用不存在"}, 404)
            target = (meta.dir / rel).resolve()
            if not str(target).startswith(str(meta.dir.resolve())):
                return self._json({"ok": False, "error": "非法路径"}, 403)
            return self._file(target, cache="no-cache")

        # ---- API
        if path == "/api/health":
            return self._json({"ok": True, "platform": "StarPort",
                               "port": CTX.port})
        if path == "/api/heartbeat":
            CTX.last_heartbeat = time.time()
            CTX.heartbeat_seen = True
            return self._json({"ok": True})
        if path == "/api/bootstrap":
            return self._json({"ok": True, **self._bootstrap()})
        if path == "/api/apps":
            return self._json({"ok": True, "apps": self._apps_payload()})
        if path == "/api/status":
            return self._json({"ok": True,
                               "status": self._status_payload(),
                               "ports": ports.snapshot()})
        if path.startswith("/api/apps/") and path.endswith("/log"):
            app_id = path[len("/api/apps/"):-len("/log")]
            n = int((query.get("n") or ["80"])[0])
            p = paths.app_log_path(app_id)
            return self._json({"ok": True,
                               "log": p.read_text("utf-8", errors="replace").splitlines()[-n:]
                               if p.exists() else []})
        if path == "/api/settings":
            return self._json({"ok": True, "settings": CONFIG.data})
        if path == "/api/state":
            return self._json({"ok": True, "state": STATE.data})
        if path == "/api/system":
            from . import autostart, hotkey, window
            return self._json({
                "ok": True,
                "system": {
                    "python": sys.version.split()[0],
                    "executable": sys.executable,
                    "platform": sys.platform,
                    "root": str(paths.ROOT),
                    "autostart_registered": autostart.is_enabled(),
                    "autostart_command": autostart.current_command(),
                    "hotkey_supported": hotkey.HOTKEY.supported,
                    "window_mode": CONFIG.platform.get("window_mode", "auto"),
                    "edge": window.find_edge(),
                    "chrome": window.find_chrome(),
                },
            })
        if path == "/api/config/export":
            payload = CONFIG.export_payload(True)
            payload["apps"] = [m.manifest for m in CTX.registry.all()]
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition",
                             'attachment; filename="starport-config.json"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_error(404)

    # ------------------------------------------------------------ POST
    def do_POST(self) -> None:                         # noqa: C901
        try:
            self._route_post()
        except Exception as exc:
            try:
                self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)
            except Exception:
                pass

    def _route_post(self) -> None:                     # noqa: C901
        path = urlparse(self.path).path
        data = self._body()
        sup = CTX.supervisor
        assert sup is not None

        if path == "/api/apps/install":
            src = data.get("source")
            text = data.get("manifest")
            if not src and not text:
                return self._json({"ok": False, "error": "需要 source 或 manifest"}, 400)
            return self._json(CTX.registry.install(src, text))

        # /api/apps/<id>/<action>
        if path.startswith("/api/apps/") and path.count("/") >= 4:
            parts = path.split("/")            # ['', 'api', 'apps', id, action]
            app_id, action = parts[3], parts[4]

            if action == "launch":
                res = sup.launch(app_id)
                if res.get("ok"):
                    STATE.touch(app_id)
                return self._json(res)
            if action == "stop":
                return self._json(sup.stop(app_id))
            if action == "restart":
                return self._json(sup.restart(app_id))
            if action == "enable":
                enabled = bool(data.get("enabled", True))
                if not enabled:
                    sup.stop(app_id)
                CTX.registry.set_enabled(app_id, enabled)
                return self._json({"ok": True, "enabled": enabled})
            if action == "pin":
                pinned = data.get("pinned")
                return self._json({"ok": True,
                                   "pinned": STATE.toggle_pin(app_id, pinned)})
            if action == "category":
                CTX.registry.set_category(app_id, str(data.get("category") or "未分类"))
                return self._json({"ok": True})
            if action == "uninstall":
                remove = bool(data.get("remove_files", True))
                sup.stop(app_id)
                res = CTX.registry.uninstall(app_id, remove)
                if res.get("ok"):
                    STATE.forget(app_id)
                return self._json(res)
            return self._json({"ok": False, "error": f"未知动作 {action}"}, 404)

        if path == "/api/settings":
            patch = data.get("patch") or {}
            for k, v in patch.items():
                if k == "platform" and isinstance(v, dict):
                    CONFIG.platform.update(v)
                else:
                    CONFIG.set(k, v)
            CONFIG.save()
            if CTX.apply_runtime:
                CTX.apply_runtime()
            return self._json({"ok": True, "settings": CONFIG.data})

        if path == "/api/state":
            patch = data.get("patch") or {}
            for k, v in patch.items():
                STATE.data[k] = v
            STATE.save()
            return self._json({"ok": True, "state": STATE.data})

        if path == "/api/config/import":
            res = CONFIG.import_payload(data.get("payload") or data,
                                        merge=bool(data.get("merge", True)))
            if res.get("ok"):
                CTX.registry.refresh()
            return self._json(res)

        if path == "/api/registry/reload":
            CTX.registry.refresh()
            return self._json({"ok": True, "apps": self._apps_payload()})

        if path == "/api/platform/shutdown":
            self._json({"ok": True})
            threading.Thread(target=self._shutdown_soon, daemon=True).start()
            return

        if path == "/api/platform/open-window":
            url = data.get("url") or f"http://127.0.0.1:{CTX.port}/"
            try:
                webbrowser.open(url)
            except Exception:
                pass
            return self._json({"ok": True})

        self.send_error(404)

    def _shutdown_soon(self) -> None:
        time.sleep(0.4)
        if CTX.on_shutdown:
            CTX.on_shutdown()

    # ------------------------------------------------------------ 组装
    def _bootstrap(self) -> dict[str, Any]:
        return {
            "platform": {"name": "StarPort", "title": "StarPort · 星港",
                         "port": CTX.port},
            "settings": CONFIG.data,
            "state": STATE.data,
            "apps": self._apps_payload(),
        }

    def _apps_payload(self) -> list[dict[str, Any]]:
        sup = CTX.supervisor
        out = []
        for meta in CTX.registry.all():
            item = meta.to_dict()
            if sup:
                item.update({
                    "status": sup.status(meta.id)["status"],
                    "port": sup.status(meta.id)["port"],
                })
            item["pinned"] = meta.id in STATE.data.get("pinned", [])
            out.append(item)
        return out

    def _status_payload(self) -> dict[str, Any]:
        sup = CTX.supervisor
        assert sup is not None
        return {m.id: sup.status(m.id) for m in CTX.registry.all()}


# ------------------------------------------------------------------ 服务器
class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False     # Windows 下关掉，保证"端口占用即顺延"真的生效
    daemon_threads = True


def pick_port(base: int, span: int = 50) -> int:
    for i in range(span):
        p = base + i
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError(f"平台端口 {base}~{base + span - 1} 均被占用")


def serve(port: int = 0, background: bool = False) -> tuple[LocalServer, int]:
    base = int(CONFIG.platform.get("port_base") or 19000)
    port = port or pick_port(base)
    httpd = LocalServer(("127.0.0.1", port), Handler)
    CTX.attach(port)
    if background:
        threading.Thread(target=httpd.serve_forever, daemon=True,
                         name="starport-http").start()
    return httpd, port
