# StarPort 应用接入开发规范（Agent 版）

> **给谁看**：负责把一个应用接进星港（StarPort）的 AI agent / 开发者。
> **目标**：让你在**不改星港内核一行代码**的前提下，最快把应用跑起来。
> **读法**：先读 §0 快速路径，再按你的应用类型跳到 §3 对应章节。需要精确细节时查 §2 与 §6。

---

## §0 三十秒快速路径

先判断你的应用属于哪一类，然后照着做：

| 你的应用 | type | 要做的事 | 参考 |
|---|---|---|---|
| 有本地服务，能指定端口 | `webservice` | 加 `--port/--no-browser` 参数 + 一个健康检查接口 + 写 manifest | §3.A |
| 纯前端页面（HTML/CSS/JS） | `static` | 把文件放进 `apps/<id>/`，写 manifest。**没有后端代码就不用写** | §3.B |
| 原生程序 / 绿色版 exe | `external` | 写 manifest，平台负责启停，不嵌入 | §3.C |

**三条硬规则**（违反会导致接入失败）：

1. **必须监听 `127.0.0.1`**，不要绑 `0.0.0.0`，不要用 `localhost`（IPv6 解析问题）。
2. **必须接受平台指定的端口**（通过参数或环境变量），不要硬编码端口。
3. **不要自己弹浏览器**。平台负责展示界面，应用弹浏览器会抢焦点且多开一个窗口。

**如果你只有 5 分钟**：走 `static` 型，只需要一个目录 + 一个 JSON 文件。

---

## §1 平台是什么（模型）

```
用户 → 星港窗口（壳）→ iframe 嵌入应用界面
                    ↓ 平台管理
              [应用子进程 :19100]
```

关键认知，它决定了你所有设计决策：

- 星港是**壳**，不是运行时。它不 import 你的代码，不知道你的内部逻辑。
- 平台与应用的唯一纽带是：**一份 manifest（静态契约）+ 一个 HTTP 端口（运行时契约）**。
- 每个应用是**独立 OS 进程**。你的应用崩溃，只会让那一个 iframe 变灰，平台和其他应用照常。
- 因此：**你不需要为星港做任何架构改造**，只需要满足"能被拉起 + 能被探测 + 能被嵌入"三点。

---

## §2 契约详解：manifest.json

放在 `apps/<id>/manifest.json`，或放在你自己的仓库根目录然后安装（见 §4）。

### 2.1 完整字段表

```jsonc
{
  // ── 基础信息（id 和 name 必填）
  "id": "myapp",                 // 必填。^[a-z0-9][a-z0-9._-]{0,63}$ 全小写
  "name": "我的应用",             // 必填。侧栏显示名
  "version": "1.0.0",            // 默认 "0.0.0"
  "type": "webservice",          // 必填。webservice | static | external
  "category": "系统工具",         // 侧栏分组名，默认「未分类」
  "description": "一句话说明",     // 显示在侧栏副标题 + 参与搜索
  "author": "",
  "icon": "icon.svg",            // 相对应用目录。访问地址 /_apps/<id>/icon.svg
  "tags": ["磁盘", "清理"],       // 参与搜索（名称/简介/标签/分类 都会命中）

  // ── 启动配置（webservice / external 需要）
  "entry": {
    "command": ["{python}", "run.py", "--port", "{port}", "--no-browser"],
    "cwd": "E:/MyApp",           // 不填则用 apps/<id>/
    "env": { "MY_VAR": "value" } // 会与系统环境变量合并
  },

  // ── 就绪判据（webservice 需要；external 不需要）
  "health": {
    "path": "/api/health",       // 探测这个路径，HTTP 200~399 视为就绪
    "timeout": 25,               // 秒，默认 25
    "stdout_port_pattern": "服务已启动：http://127\\.0\\.0\\.1:(\\d+)/"
  },

  // ── 嵌入方式
  "view": { "mode": "iframe", "path": "/" },

  // ── 优雅退出（可选但强烈建议）
  "stop": { "method": "http", "path": "/api/shutdown" }
}
```

### 2.2 占位符（command / cwd / env 三处都可用）

| 占位符 | 运行时替换为 |
|---|---|
| `{python}` | 平台设置里的 Python 解释器路径 |
| `{port}` | 平台分配的端口 |
| `{app_dir}` | 应用目录绝对路径（`apps/<id>/`） |
| `{app_data}` | 应用私有数据目录（`data/apps-data/<id>/`） |
| `{app_id}` | 应用 id |
| `{platform_port}` | 平台自身端口 |
| `{platform_url}` | `http://127.0.0.1:<platform_port>/` |

### 2.3 平台自动注入的环境变量

除了你声明的 `env`，平台还会注入：

```
STARPORT_APP_ID      应用 id
STARPORT_PORT        平台分配的端口
STARPORT_DATA_DIR    应用私有数据目录
PYTHONIOENCODING=utf-8     ← 中文输出不会乱码
PYTHONUNBUFFERED=1         ← 日志实时可见，不会被缓冲卡住
```

**推荐做法**：用 `STARPORT_DATA_DIR` 存放应用自己的配置/缓存，不要往平台 `data/` 根目录写。

### 2.4 `_validate()` 会检查什么

平台注册时会校验，**有问题不阻断注册，但会在界面上标黄提示**（`issues` 字段）。会被记 issue 的情况：

- `id` 不符合正则
- `type` 不在三个合法值里
- `webservice` 类型但 `entry.command` 缺失/为空
- `icon` 声明的文件不存在（此时 icon 被清空，前端回落到首字图标）

自查命令：

```bash
python tools/install_app.py --check
```

### 2.5 ⚠️ 两条容易踩的注册规则（实测确认）

**规则一：应用 id 以 manifest 里的 `id` 为准，不是目录名。**

```
apps/tmplverify/manifest.json  →  {"id": "tmpltest", ...}
```

注册出来的应用 id 是 **`tmpltest`**，调用 API 必须用
`/api/apps/tmpltest/launch`，用 `/api/apps/tmplverify/launch` 会返回
`{"ok": false, "error": "应用不存在"}`。

> **强烈建议目录名和 `id` 保持一致**，否则排查起来很费时间。
> 改名时**两处都要改**：目录名 + manifest 的 `id`。

**规则二：`apps/` 下以 `.` 或 `_` 开头的目录会被跳过。**

`registry.scan()` 明确过滤 `child.name.startswith((".", "_"))`。
所以 `apps/_tmpl_test/`、`apps/_wip/` 这类目录**不会被注册** ——
可以拿来做草稿区，但别指望它被扫到。


---

## §3 三种接入场景（按你的应用类型选）

### §3.A `webservice` —— 有本地服务的应用（最常用）

**典型**：Python/Node 写的工具，本身就有个 HTTP 服务。

**你要做的 4 件事**：

**① 支持指定端口**，二选一：

```python
import argparse, os
ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8770)))
ap.add_argument("--no-browser", action="store_true")
```

**② 提供健康检查接口**（必须）：

```python
# GET /api/health  →  200 + JSON
{"ok": true, "version": "1.0.0"}
```

不要让它做重活。平台启动时会轮询它（默认每 0.35 秒一次，最长 25 秒）。

**③ 播报真实端口**（关键，容易漏）：

如果你的应用**会自行顺延端口**（比如 8770 被占用就试 8771），
平台必须知道它最终落在哪 —— 因为平台分配端口和实际监听端口可能不一致。

在服务真正开始监听**之后**，往 **stdout** 打这一行：

```python
print(f"服务已启动：http://127.0.0.1:{port}/", flush=True)
```

`flush=True` 不能省。平台用正则 `服务已启动：http://127\.0\.0\.1:(\d+)/` 抓它，
抓到的端口会覆盖平台的初始分配值。

> 用 SDK 的话一行搞定：`starport_sdk.announce(port)`（见 §5）。

如果你**不**做端口顺延（严格使用 `{port}`），可以省略这一步和
`stdout_port_pattern` 字段，平台自己知道端口。

**④ 提供优雅退出接口**（可选但建议）：

```python
# POST /api/shutdown  →  先返回 200，再异步关闭
{"ok": true}
```

平台停止应用时会先调它（最多等 3 秒），超时才 `terminate` + `taskkill /T /F`。
有了它，你的应用有机会写完配置、关掉句柄再退。

> ⚠️ **注意**：`shutdown()` 不能直接在请求线程里调用（会和 `serve_forever` 死锁）。
> 正确做法：先把 HTTP 响应发回，再用独立线程延迟关闭。FileCleanup 的
> `server.py::request_shutdown()` 就是这个模式，可以直接抄。

**完整 manifest 示例**（FileCleanup 的实例，可直接对照）：

```json
{
  "id": "filecleanup",
  "name": "FileCleanup",
  "version": "1.0.0",
  "type": "webservice",
  "category": "系统工具",
  "description": "磁盘空间分析：递归扫描 → 横向树状图 → 挑出大文件 → 二次确认后清理",
  "icon": "icon.svg",
  "tags": ["磁盘", "清理", "扫描", "空间", "大文件"],
  "entry": {
    "command": ["{python}", "run.py", "--port", "{port}", "--no-browser"],
    "cwd": "E:/Filecleanup"
  },
  "health": {
    "path": "/api/health",
    "timeout": 25,
    "stdout_port_pattern": "服务已启动：http://127\\.0\\.0\\.1:(\\d+)/"
  },
  "view": { "mode": "iframe", "path": "/" },
  "stop": { "method": "http", "path": "/api/shutdown" }
}
```

注意 `entry.cwd` 是 **`E:/Filecleanup`** —— 应用代码**不在**平台目录里。
这正是设计意图：平台只负责拉起，不要求你搬家。

---

### §3.B `static` —— 纯前端模块（最简单）

**适合**：内部小工具、面板、便笺、计算器这类没有后端的页面。

```json
{
  "id": "mytool",
  "name": "我的工具",
  "version": "0.1.0",
  "type": "static",
  "category": "内置模块",
  "description": "纯前端小工具",
  "view": { "mode": "iframe", "path": "index.html" }
}
```

把 `index.html` / `styles.css` / `app.js` 放进 `apps/mytool/` 即可。
平台直接托管这些文件，`view.path` 就是入口页。

**数据存哪**：`localStorage`（每个应用独立 origin，互不干扰）。

**⚠️ 隔离性的重要提醒**：

`static` 型由**平台进程**托管静态文件，**没有独立子进程** —— 它的隔离性弱于 `webservice` 型
（一个死循环的 JS 仍会卡住它自己那个 iframe，但不会影响平台本体）。

如果这个应用需要**强隔离**（可能崩溃、吃内存、跑重活），
用 SDK 把它变成 webservice 型，一行代码：

```python
# mytool/server.py
from starport_sdk import serve_static, port
serve_static("web", port_no=port(8770))
```

manifest 改成：

```json
{
  "id": "mytool", "type": "webservice",
  "entry": { "command": ["{python}", "{app_dir}/server.py"] },
  "health": { "path": "/" },
  "view": { "mode": "iframe", "path": "/" }
}
```

---

### §3.C `external` —— 原生程序

**适合**：绿色版 exe、系统工具、不想/不能改的第三方程序。

```json
{
  "id": "mytool",
  "name": "我的工具",
  "type": "external",
  "category": "工具",
  "entry": { "command": ["E:/tools/MyTool.exe", "--some-arg"] }
}
```

平台做的事：拉起进程 → 等约 1.2 秒确认没立刻死掉 → 标记 running。
**不做嵌入**（壳内显示"已在外部启动"+ 停止按钮）。

停止时用 `taskkill /PID <pid> /T /F` 收整个进程树，不留孤儿。

**限制**：`external` 型无法被 iframe 嵌入，用户看到的是外部窗口。
如果你希望**界面在星港里**，就得用 `webservice` 型给程序套一个本地 HTTP 服务。

---

## §4 部署方式（三条路，随便挑）

**方式一：放进平台目录**（最简单）

```
apps/<id>/manifest.json  +  你的文件
```

然后界面点「设置 → 应用管理 → 重新扫描 `apps/`」。

**方式二：命令行安装**（应用代码不搬进平台）

```bash
# 从目录（目录里要有 manifest.json）
python tools/install_app.py E:/MyApp

# 或直接给 manifest 文件（会拷贝其所在目录）
python tools/install_app.py E:/MyApp/manifest.json

# 查看 / 校验 / 卸载
python tools/install_app.py --list
python tools/install_app.py --check
python tools/install_app.py --remove myapp
```

**方式三：界面安装**（POST `/api/apps/install`）

```jsonc
{ "source": "E:/MyApp" }          // 或
{ "manifest": "{...完整的 JSON 字符串...}" }
```

> **方式二/三的注意点**：如果应用**已经在平台外部**（比如 `E:/Filecleanup`），
> 用 `entry.cwd` 指向它即可，**不要**用安装命令去拷贝 —— 那会复制一份代码，
> 后续两边不同步。FileCleanup 就是这么接的。

---

## §5 可选 SDK 用法

`sdk/starport_sdk.py`，纯标准库。**用了省事，不用也行** —— 它只是把套路代码封了一下。

```python
import sys
sys.path.insert(0, "E:/StarPort/sdk")     # 或把 sdk 拷进你的项目
from starport_sdk import port, data_dir, announce, in_starport, serve_static

PORT = port(8770)          # 平台分配的端口；独立运行时回落 8770
DATA = data_dir()          # 应用私有数据目录，自动创建
print(DATA)
print("是否被星港托管：", in_starport())

# 服务开始监听后：
announce(PORT)             # 等价于 print("服务已启动：http://127.0.0.1:<PORT>/", flush=True)

# 最省事：把一个静态目录变成可嵌入应用
# serve_static("web", port_no=PORT)
```

API 一览：

| 函数 | 作用 |
|---|---|
| `app_id(default="")` | 读 `STARPORT_APP_ID` |
| `port(default=0)` | 读 `STARPORT_PORT`，独立运行时用默认值 |
| `data_dir(create=True)` | 应用私有数据目录 |
| `in_starport()` | 当前是否被平台拉起（用于切换独立/托管模式） |
| `announce(port)` | 播报就绪端口（**必须 flush**） |
| `serve_static(dir, port_no)` | 一行启动静态服务 |

---

## §6 平台 REST API 速查（供 agent 自动化运维）

平台自身监听 `127.0.0.1:19000`（可配置）。全部返回 JSON，`ok` 字段表示成败。

### 读取

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 平台存活 |
| GET | `/api/bootstrap` | 一次拿全：平台信息+设置+状态+应用列表（**壳启动就调这个**） |
| GET | `/api/apps` | 应用列表（含 status / port / pinned） |
| GET | `/api/status` | 各应用运行时状态 + 端口占用表 |
| GET | `/api/settings` | 完整配置 |
| GET | `/api/state` | 置顶 / 最近使用 / 上次打开 |
| GET | `/api/system` | Python 版本、平台根目录、自启状态、Edge/Chrome 路径 |
| GET | `/api/apps/<id>/log?n=80` | 应用日志尾部（**排查启动失败先看这个**） |
| GET | `/api/config/export` | 下载配置（含各应用 manifest） |

### 操作应用

| 方法 | 路径 | Body |
|---|---|---|
| POST | `/api/apps/<id>/launch` | `{}` → 返回 `{url, port, pid}` |
| POST | `/api/apps/<id>/stop` | `{}` |
| POST | `/api/apps/<id>/restart` | `{}` |
| POST | `/api/apps/<id>/enable` | `{"enabled": true\|false}`（禁用会先停进程） |
| POST | `/api/apps/<id>/pin` | `{"pinned": true}`，不传则切换 |
| POST | `/api/apps/<id>/category` | `{"category": "工具"}` |
| POST | `/api/apps/<id>/uninstall` | `{"remove_files": true}` ⚠️ 会删目录 |

### 平台控制

| 方法 | 路径 | Body |
|---|---|---|
| POST | `/api/apps/install` | `{"source": "..."}` 或 `{"manifest": "{...}"}` |
| POST | `/api/registry/reload` | 重新扫描 `apps/` |
| POST | `/api/settings` | `{"patch": {"platform": {"theme": "light"}}}` |
| POST | `/api/config/import` | `{"payload": {...}, "merge": true}` |
| POST | `/api/platform/shutdown` | 退出平台（回收所有应用进程） |

**curl 示例**：

```bash
curl -X POST -H "Content-Type: application/json" -d '{}' \
     http://127.0.0.1:19000/api/apps/myapp/launch
```

---

## §7 调试与排错

### 启动失败的排查顺序

1. **看返回的 error**。`launch` 失败会同时返回 `error`、`log`（日志尾部）：
   ```jsonc
   { "ok": false, "error": "等待就绪超时（25s）", "log": "..." }
   ```
2. **看完整日志**：`GET /api/apps/<id>/log?n=200`，或直接读
   `data/logs/<id>.log`。应用的 stdout/stderr 都在这。
3. **手动跑一遍 command**。把 manifest 里的占位符换成真实值，在命令行里执行，
   看能否起来。90% 的问题在这一步暴露。
4. **确认端口没被占**：`data/logs` 里如果出现"端口已被占用"之类信息，
   说明应用没用 `{port}` 而是自己硬编码了。
5. **确认健康检查真的返回 200**：
   ```bash
   curl -i http://127.0.0.1:19100/api/health
   ```

### 常见坑

| 症状 | 原因 | 解决 |
|---|---|---|
| 等就绪超时 25s | 健康检查路径写错 / 服务没真的起来 | 手动 curl 那个 path |
| 进程提前退出 code=1 | 命令行参数不对、依赖缺失 | 看 `data/logs/<id>.log` |
| `应用不存在` | 用了**目录名**而不是 manifest 的 `id` | 用 `GET /api/apps` 看真实 id（见 §2.5） |
| reload 后应用没出现 | 目录以 `.` 或 `_` 开头被跳过 | 重命名目录（见 §2.5） |
| 端口对不上 | 应用自行顺延了端口 | 加 `stdout_port_pattern` + 打播报行 |
| 界面白屏但服务正常 | `view.path` 不对，或页面有 `X-Frame-Options` | 改 path；或去掉该响应头 |
| 页面能开但样式全丢 | 应用用了绝对路径资源且路径写死 | 用相对路径 |
| 中文日志乱码 | 没设编码 | 平台已注入 `PYTHONIOENCODING=utf-8`；应用内部写文件时也要显式 `encoding="utf-8"` |
| 停止后进程还在 | 应用起了子进程 | 平台会 `taskkill /T /F` 收树；若应用自己 spawn 了脱离进程，需自行处理 |
| 刚停止就探测端口仍通 | 正常竞态：进程退出与端口关闭有毫秒级延迟 | 等 1 秒再探测；平台状态以 `/api/status` 为准 |


### 关于 iframe 嵌入的两个前提

平台用 `<iframe sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-downloads allow-modals">` 承载。

1. **不要设 `X-Frame-Options: DENY/SAMEORIGIN`**，也不要设
   `Content-Security-Policy: frame-ancestors 'none'`，否则浏览器拒绝嵌入。
2. 应用**不能依赖 `window.top`**（跨 origin 拿不到），也不要试图与壳通信 ——
   这是刻意的隔离边界。

---

## §8 接入自检清单

提交前逐条打勾：

- [ ] 应用只监听 `127.0.0.1`（不是 `0.0.0.0` / `localhost`）
- [ ] 端口来自 `--port` 参数或 `STARPORT_PORT` 环境变量，没有硬编码
- [ ] 有 `--no-browser` 之类的开关，或默认不弹浏览器
- [ ] 健康检查接口存在且轻量，路径与 manifest 一致
- [ ] 若自行顺延端口：已加 `stdout_port_pattern` + 打了 `服务已启动：...` 行（带 `flush=True`）
- [ ] 有优雅退出接口，且不在请求线程里直接 `shutdown()`
- [ ] 响应头没有 `X-Frame-Options` / `frame-ancestors`
- [ ] 前端资源用相对路径
- [ ] 应用数据写在 `STARPORT_DATA_DIR` 或自己的目录，不污染平台 `data/`
- [ ] `python tools/install_app.py --check` 通过
- [ ] **手动 kill 掉应用进程后**，平台和其他应用仍正常（验证隔离）
- [ ] `id` 全小写、符合 `^[a-z0-9][a-z0-9._-]{0,63}$`
- [ ] **目录名与 manifest 的 `id` 一致**，且目录不以 `.` / `_` 开头（§2.5）

---

## §8.5 本文档的模板已实测

§9 的两份模板**不是纸上示例，已实际接入跑通**（2026-09-23 于本机验证）：

```
注册        → GET /api/apps  含 tmpltest，issues=[]
启动        → POST /api/apps/tmpltest/launch
             {"ok": true, "port": 19100, "pid": 30864}
播报行      → data/logs/tmpltest.log 内有
             "服务已启动：http://127.0.0.1:19100/"   ← 正则抓到，端口对齐
健康检查    → GET :19100/api/health → {"ok": true, "version": "0.1.0"}
嵌入前提    → 无 X-Frame-Options / CSP frame-ancestors   ✓
优雅退出    → POST /api/apps/tmpltest/stop → {"ok": true, "status": "stopped"}
端口释放    → 19100 已释放，端口占用表归空
```

也就是说：**把 §9.A 的两个文件复制出来，改掉 id 和 name，就能直接跑。**

---

## §9 最小可跑模板（直接抄）

### webservice 型

**`apps/myapp/manifest.json`**

```json
{
  "id": "myapp",
  "name": "我的应用",
  "version": "0.1.0",
  "type": "webservice",
  "category": "工具",
  "description": "最小 webservice 模板",
  "entry": { "command": ["{python}", "{app_dir}/server.py"] },
  "health": { "path": "/api/health", "timeout": 20 },
  "view": { "mode": "iframe", "path": "/" },
  "stop": { "method": "http", "path": "/api/shutdown" }
}
```

**`apps/myapp/server.py`**

```python
"""最小可跑 webservice 应用模板。复制走改改就能用。"""
import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "E:/StarPort/sdk")          # 生产环境请把 sdk 拷进项目
from starport_sdk import port, announce        # noqa: E402

HOST = "127.0.0.1"
PORT = port(8770)
HTTPD = None


class Handler(BaseHTTPRequestHandler):
    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/health"):
            return self._json({"ok": True, "version": "0.1.0"})
        # 你的界面：这里返回 HTML。注意不要设 X-Frame-Options
        html = "<!doctype html><meta charset=utf-8><h1>你好，星港</h1>"
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.startswith("/api/shutdown"):
            self._json({"ok": True})
            # 关键：先发响应，再在独立线程里关，避免与 serve_forever 死锁
            threading.Thread(target=_shutdown, daemon=True).start()
            return
        self.send_error(404)

    def log_message(self, fmt, *args):
        pass


def _shutdown():
    time.sleep(0.35)
    if HTTPD:
        HTTPD.shutdown()


def _free(p):
    with socket.socket() as s:
        try:
            s.bind((HOST, p))
            return True
        except OSError:
            return False


def main():
    global HTTPD, PORT
    while not _free(PORT):          # 端口顺延（演示用）
        PORT += 1
    HTTPD = ThreadingHTTPServer((HOST, PORT), Handler)
    announce(PORT)                  # ★ 必须：告诉平台真实端口
    try:
        HTTPD.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        HTTPD.server_close()


if __name__ == "__main__":
    main()
```

### static 型

**`apps/mytool/manifest.json`**

```json
{
  "id": "mytool",
  "name": "我的小工具",
  "version": "0.1.0",
  "type": "static",
  "category": "内置模块",
  "description": "纯前端页面，无后端",
  "view": { "mode": "iframe", "path": "index.html" }
}
```

**`apps/mytool/index.html`**

```html
<!doctype html>
<meta charset="utf-8">
<title>我的小工具</title>
<style>
  body { font: 14px/1.6 "Microsoft YaHei UI", sans-serif; padding: 20px;
         background: #0e1116; color: #e6ebf2; }
</style>
<h1>你好，星港</h1>
<p id="n">0</p>
<button onclick="document.getElementById('n').textContent =
  (+document.getElementById('n').textContent) + 1">+1</button>
<script>
  // 应用私有数据：localStorage 按 origin 隔离，不会和其他应用串
  const n = document.getElementById('n');
  n.textContent = localStorage.getItem('count') || 0;
  setInterval(() => localStorage.setItem('count', n.textContent), 500);
</script>
```

---

## §10 推荐技术栈与设计取向

不是强制，但这样最省事：

| 关注点 | 推荐 | 理由 |
|---|---|---|
| 后端语言 | **Python（标准库）** | 平台本体就是，`{python}` 占位符直接可用；标准库自带 `http.server`，零依赖 |
| HTTP 服务 | `ThreadingHTTPServer`（而非 `HTTPServer`） | 平台会轮询健康检查，单线程服务器会被轮询阻塞 |
| Node 也算合 | `entry.command` 写 `["node", "server.js"]` | 平台不关心你用什么跑，只要能吃 `{port}` 就行 |
| 前端 | **原生 HTML/CSS/JS，无构建** | 和平台壳同构；无 npm 依赖，离线可用 |
| 前端框架 | 真要上框架，用**单文件 ESM 版**（如 Vue/Petite-Vue） | 避免引入打包器；引 CDN 会破坏离线要求 → **必须把库文件放本地** |
| 状态存储 | 后端用 `STARPORT_DATA_DIR`；前端用 `localStorage` | 都按应用隔离，不互相污染 |
| 通信 | **只走应用自己的 HTTP 端口** | 不要尝试与平台壳通信（跨 origin 拿不到 `window.top`） |

**三条设计取向**（平台已按这些原则建，接入时保持一致最省事）：

1. **离线优先**：任何外部 CDN 依赖都是缺陷。库文件一律本地化。
2. **本地回环**：只监听 `127.0.0.1`，不开外网端口，数据不出机器。
3. **不越界**：应用不 import 平台代码，平台不 import 应用代码；跨进程通信是刻意的隔离边界，别绕开它。

---

## 附：平台侧已知边界

老实说清楚，免得你踩到：

- `static` 型隔离性弱于 `webservice` 型（共享平台进程）；
- `external` 型无法嵌入，只能外部窗口；
- 应用之间**不提供互相调用的 API**（刻意的，跨应用调用会重新打破进程边界）；
- 全局快捷键与开机自启**仅 Windows**（其他平台自动降级，不影响运行）；
- 平台不实现应用依赖管理 —— 你的应用自己保证运行环境（或自带绿色版）；
- zip 安装**尚未实现**（`registry.install` 预留了分支）。

有问题先查 `data/logs/<id>.log`，再去 `README.md`（架构与选型）和
`apps/filecleanup/`（真实接入实例）。

---

*StarPort v0.1.0 · 本文档面向 agent，字段与行为严格对齐 `core/registry.py`、
`core/supervisor.py`、`core/server.py` 的实际实现。*
