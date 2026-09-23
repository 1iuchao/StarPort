"""StarPort 应用接入 SDK（可选，纯标准库）。

给"想被星港托管"的应用用。不用它也完全可以——只要满足 manifest 契约即可；
用了它，端口、数据目录、就绪播报这些套路代码可以少写几行。

平台在启动应用时会注入以下环境变量：
    STARPORT_APP_ID      应用 id
    STARPORT_PORT        平台分配的端口
    STARPORT_DATA_DIR    应用私有数据目录（data/apps-data/<id>/）
    STARPORT_PLATFORM_URL（通过 manifest 的 {platform_url} 占位符传递）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ANNOUNCE_PREFIX = "服务已启动：http://127.0.0.1:"
ANNOUNCE_SUFFIX = "/"


def app_id(default: str = "") -> str:
    return os.environ.get("STARPORT_APP_ID", default)


def port(default: int = 0) -> int:
    return int(os.environ.get("STARPORT_PORT", default) or default)


def data_dir(create: bool = True) -> Path:
    p = Path(os.environ.get("STARPORT_DATA_DIR")
             or Path.home() / f".{app_id('app')}")
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def in_starport() -> bool:
    """当前进程是否由星港拉起。应用可以据此切换"独立运行 / 被托管"两种模式。"""
    return bool(os.environ.get("STARPORT_APP_ID"))


def announce(port_no: int) -> None:
    """向标准输出播报服务已就绪。

    平台用正则 `服务已启动：http://127\\.0\\.0\\.1:(\\d+)/` 抓这行，
    从而知道应用最终落在哪个端口上（比如应用自己做了端口顺延）。
    必须 flush，否则平台可能一直等不到。
    """
    print(f"{ANNOUNCE_PREFIX}{port_no}{ANNOUNCE_SUFFIX}", flush=True)


def serve_static(directory: str | Path, port_no: int = 0,
                 open_browser: bool = False) -> None:
    """最简静态服务：一行把某个目录变成可被星港嵌入的应用。"""
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    root = str(directory)

    class StaticHandler(SimpleHTTPRequestHandler):
        """⚠️ 别改成 `class X(functools.partial(Handler, directory=...).func)`。

        子类化 `partial.func` 拿到的只是**原类**，partial 里带的关键字参数会被丢掉，
        于是 `directory` 回落成 None → 按启动时的 CWD 供文件，拷到别处跑就 404。
        （2026-09-23 实测踩到：服务在项目根目录跑得挺好，换个 cwd 就全 404。）
        """

        def __init__(self, *args, **kwargs):
            kwargs["directory"] = root
            super().__init__(*args, **kwargs)

        def log_message(self, fmt, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", port_no or 0), StaticHandler)
    real_port = httpd.server_address[1]
    announce(real_port)
    if open_browser and not in_starport():
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{real_port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    # 自测：python sdk/starport_sdk.py [目录]
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    print(f"app_id={app_id('-')} port={port(0)} data={data_dir(create=False)} "
          f"in_starport={in_starport()}")
    serve_static(target)
