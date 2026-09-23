# StarPort · 星港

**本地应用聚合平台**：把散落在机器上的独立应用（本地工具 / Web 页面 / 内部功能模块）
收进同一个壳里，统一注册、启动、切换、禁用、卸载。
全部数据落在本地，不联网、离线可用、配置可导入导出。

仓库地址：https://github.com/1iuchao/StarPort

**启动方式**：双击根目录的 `启动 StarPort.bat`（需 Python 3.10+，会自动探测解释器）。

当前版本已接入 2 个示例应用：**FileCleanup**（外部 Python 应用）+ **星港便笺**（内置静态模块）。

> 📘 **要把应用接进来？直接看 [`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md)。**
> 那份文档面向 agent / 开发者，包含字段表、三种场景的完整模板（**已实测可跑**）、
> REST API 速查、排错表和自检清单。本文档主要讲平台自身的架构与选型。

---

## 一、技术选型与理由

| 层次 | 选择 | 为什么不用别的 |
|---|---|---|
| 内核 | **Python 3.10+ 标准库**（`http.server` / `subprocess` / `json` / `winreg` / `ctypes`） | 零第三方依赖 = 零安装风险、离线可用、能跟着系统 Python 走；换台机器拷过去就能跑 |
| 界面 | **原生窗口 + HTML/CSS/JS**（无构建、无 npm） | Electron 要下 ~100MB 二进制 + 一整套 npm 依赖；Tauri 要 Rust 工具链。本机两者都不具备，且它们引入的是**构建链**而非功能 |
| 窗口 | Edge/Chrome `--app` 模式（可选 pywebview） | 系统自带，开出的是无浏览器 UI 的独立窗口；装了 pywebview 就自动升级为真原生窗口 |
| 应用承载 | **iframe + 独立进程 + 独立端口** | 进程级隔离是唯一能真正做到"一个应用崩了不影响别人"的方式 |

一句话概括选型逻辑：**平台本体做薄，能力交给插件；插件靠进程边界而不是靠约定来保证隔离。**

---

## 二、架构

```
                    ┌─────────────────────────────────────────┐
                    │  原生窗口（Edge --app / pywebview）       │
                    │  ┌──────────┬─────────────────────────┐ │
                    │  │ 侧栏     │  主区 iframe            │ │
                    │  │ 搜索/分类│  ← 当前应用界面          │ │
                    │  │ 置顶/最近│                         │ │
                    │  └──────────┴─────────────────────────┘ │
                    └───────────────┬─────────────────────────┘
                                    │ HTTP (127.0.0.1:19000)
                    ┌───────────────▼─────────────────────────┐
                    │            平台内核 core/                │
                    │  server  registry  supervisor  ports     │
                    │  settings  state  hotkey  autostart      │
                    └───┬───────────┬───────────┬─────────────┘
                        │           │           │   子进程 + 独立端口
              ┌─────────▼──┐ ┌─────▼─────┐ ┌───▼────────┐
              │ FileCleanup│ │  便笺      │ │ 未来的应用  │
              │ :19100     │ │ (静态托管) │ │ :19102 ... │
              └────────────┘ └───────────┘ └────────────┘
                    ▲ 崩溃只影响自己那个 iframe
```

**目录结构**

```
StarPort/
├── 启动 StarPort.bat        # ★ 双击启动（纯 ASCII bat + Python 引导）
├── run.py                  # 平台入口（--port / --no-window / --autostarted）
├── requirements.txt        # 核心零依赖（pywebview 可选）
│
├── core/                   # 内核：不认识任何具体应用，只认识 manifest 契约
│   ├── paths.py            # 路径常量与运行时目录
│   ├── console.py          # 控制台 UTF-8 修复（Windows 中文日志安全）
│   ├── settings.py         # data/config.json 读写 + 导入导出
│   ├── state.py            # data/state.json 置顶 / 最近使用 / 上次打开
│   ├── registry.py         # 扫描 apps/、注册 / 启用 / 禁用 / 卸载 / 安装
│   ├── supervisor.py       # ★ 进程托管：启动 / 健康检查 / 停止 / 崩溃监视
│   ├── ports.py            # 端口分配与释放
│   ├── server.py           # 壳静态资源 + 管理 REST API
│   ├── window.py           # 窗口启动与聚焦
│   ├── hotkey.py           # 全局快捷键（ctypes，无需 pywin32）
│   └── autostart.py        # 开机自启（HKCU Run，无需管理员权限）
│
├── shell/                  # 界面壳（原生 HTML/CSS/JS，无构建）
│   ├── index.html
│   ├── styles.css          # CSS 变量驱动主题（深色 / 浅色）
│   └── shell.js
│
├── apps/                   # 已安装应用（一个目录 = 一个插件）
│   ├── filecleanup/        #   manifest.json + icon.svg
│   └── notepad/            #   manifest.json + index.html
│
├── sdk/starport_sdk.py     # 可选 SDK：端口 / 数据目录 / 就绪播报
├── tools/install_app.py    # 命令行安装 / 卸载 / 校验
├── tools/bootstrap.py      # bat 调用的启动引导（中文输出都在这）
├── docs/
│   ├── AGENT_GUIDE.md      # ★ 应用接入开发规范（给 agent / 开发者的）
│   └── ...
│
├── 启动 StarPort.bat       # 双击启动
└── data/                   # 运行时数据（唯一真源，可整个拷走）
    ├── config.json         #   设置 + 应用启用状态
    ├── state.json          #   置顶 / 最近使用
    ├── logs/<app>.log      #   每个应用一份日志
    └── apps-data/<app>/    #   应用私有数据目录
```

---

## 三、应用接入契约

**一个应用 = 一个目录 + 一份 `manifest.json`。** 内核不 import 任何应用代码，
所以新增应用**不需要改动 core/ 里任何一行**。

### manifest 字段

```jsonc
{
  "id": "filecleanup",            // 必填，小写字母/数字/._-
  "name": "FileCleanup",          // 显示名
  "version": "1.0.0",
  "type": "webservice",           // webservice | static | external
  "category": "系统工具",          // 侧栏分组
  "description": "…",
  "icon": "icon.svg",             // 相对应用目录，访问路径 /_apps/<id>/icon.svg
  "tags": ["磁盘", "清理"],        // 参与搜索

  "entry": {                      // webservice / external 必填
    "command": ["{python}", "run.py", "--port", "{port}", "--no-browser"],
    "cwd": "E:/Filecleanup",
    "env": { "FC_MAX_DEPTH": "256" }
  },

  "health": {                     // webservice：怎么判断"起来了"
    "path": "/api/health",
    "timeout": 25,
    "stdout_port_pattern": "服务已启动：http://127\\.0\\.0\\.1:(\\d+)/"
  },

  "view": { "mode": "iframe", "path": "/" },   // 嵌入哪个路径

  "stop": { "method": "http", "path": "/api/shutdown" }   // 优雅退出接口
}
```

**占位符**（command / cwd / env 里都能用）：

| 占位符 | 含义 |
|---|---|
| `{python}` | 设置里指定的 Python 解释器 |
| `{port}` | 平台分配的端口 |
| `{app_dir}` | 应用目录（apps/<id>/） |
| `{app_data}` | 应用私有数据目录 |
| `{app_id}` | 应用 id |
| `{platform_port}` / `{platform_url}` | 平台自身端口 / 地址 |

### 三种类型

| type | 场景 | 平台做什么 |
|---|---|---|
| `webservice` | 自带本地服务的程序（Python/Node/exe 均可） | 拉起进程 → 等健康检查 → iframe 嵌入 → 退出时调 stop 接口 |
| `static` | 纯前端页面 | 平台直接托管静态文件，iframe 嵌入，无子进程 |
| `external` | 原生程序 / 绿色版 exe | 平台负责启动与回收，不做嵌入（壳内提示"已在外部启动"） |

---

## 四、隔离与稳定（四层）

1. **进程隔离** —— 每个应用一个独立子进程，内核从不 import 应用代码；
2. **端口隔离** —— 平台统一分配端口并记账，停止即释放，避免抢端口；
3. **视图隔离** —— 应用界面跑在带 `sandbox` 的 iframe 里，DOM 与 JS 全局互不可见；
4. **故障隔离** —— 应用崩溃只把那一个 iframe 标记为 crashed，
   平台本体与其他应用照常运行，可一键重启。

实测（强杀 FileCleanup 进程后）：

```
filecleanup → crashed (exit 1)
notepad     → running      ← 不受影响
平台         → 健康检查正常
```

补充保障：每个 HTTP 请求单独 try/except；配置写盘用原子替换（写坏会回滚到默认）；
`taskkill /T /F` 收进程树，不留孤儿进程。

---

## 五、使用

**双击启动（推荐）**：直接双击根目录的 **`启动 StarPort.bat`**。
它会自动探测本机 Python（优先用平台设置里已选的），校验版本 ≥ 3.10，
打印中文启动信息并拉起平台。关掉那个黑窗口 = 关闭平台。

```bash
E:/Python312/python.exe run.py                # 启动并开窗口
E:/Python312/python.exe run.py --no-window    # 只起服务
E:/Python312/python.exe run.py --port 19500   # 指定端口
```

界面能力：

- **导航** —— 侧栏按「置顶 / 最近使用 / 分类」分组，`Ctrl+K` 聚焦搜索（名称、简介、标签、分类都参与）
- **置顶** —— 应用条目右侧 ☆/★ 一键切换，存 `data/state.json`
- **设置** —— 主题（深/浅）、窗口模式、Python 解释器、平台端口、开机自启、
  全局快捷键（默认 `Ctrl+Alt+S` 唤起窗口）、崩溃自动重启、关闭窗口是否退出平台
- **应用管理** —— 启用/禁用、卸载（含文件）、从目录或 manifest 直接安装、重新扫描
- **数据** —— 一键导出/导入 `starport-config.json`（设置 + 置顶 + 启用状态 + 各应用 manifest）

---

## 六、接入更多应用：具体步骤

### 场景 A：自带本地服务的程序（推荐，示例：FileCleanup）

1. 让程序支持两个参数：`--port <端口>` 和 `--no-browser`（不要自己弹浏览器）；
2. 提供一个健康检查接口，如 `GET /api/health` 返回 200；
3. 提供优雅退出接口（可选），如 `POST /api/shutdown`；
4. 启动后往 stdout 打一行 `服务已启动：http://127.0.0.1:<端口>/`（平台据此抓真实端口；
   用 `sdk/starport_sdk.py` 的 `announce(port)` 即可）；
5. 写 manifest，放到 `apps/<id>/manifest.json`；
6. 平台点「设置 → 应用管理 → 重新扫描」，或直接
   `python tools/install_app.py E:/你的应用目录`。

### 场景 B：纯前端页面（`static`）

把 HTML/CSS/JS 放进 `apps/<id>/`，manifest 写成：

```json
{ "id": "myapp", "name": "我的应用", "type": "static",
  "category": "内置模块", "view": { "mode": "iframe", "path": "index.html" } }
```

无需任何后端代码。参考 `apps/notepad/`。

### 场景 C：原生程序 / 绿色版 exe（`external`）

```json
{ "id": "mytool", "name": "我的工具", "type": "external",
  "category": "工具", "entry": { "command": ["E:/tools/MyTool.exe"] } }
```

平台负责拉起与回收，壳内显示"已在外部启动"并提供停止按钮。

### 场景 D：程序不在平台目录里

完全没问题。`entry.cwd` 写绝对路径（FileCleanup 就是这么接的：`E:/Filecleanup`），
平台只负责拉起进程，不要求代码搬进 `apps/`。
也可以把 `manifest.json` 直接放进应用自己的仓库，然后
`python tools/install_app.py E:/Filecleanup/manifest.json`。

---

## 七、已知边界

- `static` 型应用由平台进程托管静态文件，**隔离弱于** webservice 型（若需要强隔离，
  用 `sdk/starport_sdk.py` 的 `serve_static()` 把它变成 webservice）；
- 全局快捷键与开机自启目前只支持 Windows（其他平台自动降级，不影响运行）；
- 关掉窗口默认退出平台（可在设置里关掉，让平台留在后台）；
- 应用之间不提供互相调用的 API —— 这是刻意的，跨应用通信会重新把进程边界打破。

---

MIT License。第三方组件：无（内核与壳均为自研，零第三方依赖）。
