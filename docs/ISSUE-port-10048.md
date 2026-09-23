# 工单：StarPort 启动失败 `[WinError 10048]`（端口被残留实例占用）

- **日期**：2026-09-23
- **严重度**：高 —— 平台完全起不来，用户只能看到"确定"，无从下手
- **一句话**：`--no-window` 起的调试实例无窗口无入口、跑完没清，占住 19600；
  而 `serve()` 在"显式端口"分支不做顺延，直接抛 WinError 10048 并弹框。

---

## ⚠️ 当前仓库状态（先看这段，别重复改）

**2026-09-23 19:28**：修了两处（下文的「修改点 1 / 2」），`core/server.py`、`run.py`。
**2026-09-23 20:30 复查**：那两处确实生效，**但 10048 仍能复现**——
`pick_port()` 的"先探后绑"留了一道并发缝隙。又补了三处（下文的「修改点 3 / 4 / 5」）。

现在的状态：

| # | 改动 | 状态 |
| --- | --- | --- |
| 1 | `serve()` 显式端口也顺延 | ✅ 19:28 修，20:30 复测通过 |
| 2 | `--port` 不写回持久配置 | ✅ 19:28 修，20:30 复测通过 |
| 3 | `bind_platform()` 边试边绑，消灭探绑竞态 | ✅ 20:30 新增 |
| 4 | `core/instance.py` 实例留痕 | ✅ 20:30 新增 |
| 5 | `run.py` 单实例守卫 + `tools/stop_instance.py` | ✅ 20:30 新增 |

- 若你拿到的工作区**已含 1~5** → 不要重复修改，直接跳到「验证方法」跑一遍确认。
- 若拿到的是**干净仓库**（例如从 GitHub clone）→ 按「修改点」依次改。
- 所有修改处都带了 `★` 开头的注释，说明为什么这么改。

---

## 现象

无窗口模式启动时弹系统对话框：

```
StarPort 启动失败
平台启动失败：[WinError 10048] 通常每个套接字地址(协议/网络地址/端口)只允许使用一次。
常见原因：19600 起的连续端口都被占用。
换个端口再试：run.py --port 19500
```

`data/logs/platform.log` 里连续 6 次、每约 60 秒一次：

```
===== StarPort 启动 2026-09-23 19:17:16 (pythonw 无窗口模式) =====
[StarPort] 孤儿进程兜底：已启用（Job Object）
[StarPort] 平台启动失败：[WinError 10048] ...
```

---

## 复现步骤

```powershell
# 1) 先在 19600 起一个后台实例（模拟"残留"）
E:\Python312\python.exe E:\StarPort\run.py --no-window --port 19600

# 2) 再执行一次同样的命令
E:\Python312\python.exe E:\StarPort\run.py --no-window --port 19600

# 修复前：第 2 次必抛 WinError 10048，无窗口模式下弹系统框
# 修复后：第 2 次自动顺延到 19601 并正常服务
```

排查现场当时的状态（`Get-NetTCPConnection`）：

```
127.0.0.1:19600  State=Listen  PID=23056  python.exe  run.py --no-window --port 19600
```

---

## 根因（三环，缺一不可）

### 环 1 —— 幽灵实例：`--no-window` 的进程用户看不见

为做 UI 取证（背景融合 / iframe 透明度），单独在 19600 起过一个后台实例，
避免打扰日常使用的 19000 实例。`--no-window` 的进程：

- 没有窗口、没有托盘图标、没有任何可见入口
- 启动时也没有留下 PID 文件或其它"可被发现"的痕迹
- 会话结束后没被清理，一直活着占着 19600

**用户侧表现**：什么都看不到，却每次启动都失败。

### 环 2 —— 一次性参数被写回持久配置

`run.py` 原文（约第 91 行）：

```python
paths.ensure_dirs()
if args.port:
    CONFIG.platform["port_base"] = args.port      # ← 问题在这一行
```

`--port` 只是"本次用哪个端口"，却被写进了运行时配置对象。
此后只要发生**任意一次配置保存**（例如界面里改设置触发 `POST /api/settings`
→ `Config.save()`），19600 就会**永久落盘**到 `data/config.json`，
从此每次启动都盯着这个端口。

### 环 3 —— `serve()` 在显式端口分支不顺延（真正的 bug）

`core/server.py` 原文（约第 527 行）：

```python
def serve(port: int = 0, background: bool = False) -> tuple[LocalServer, int]:
    base = int(CONFIG.platform.get("port_base") or 19000)
    port = port or pick_port(base)          # ← 只有"没指定端口"才顺延
    httpd = LocalServer(("127.0.0.1", port), Handler)
```

- 传了 `--port 19600` → `port = 19600`（非 0）→ **短路掉 `pick_port`** → 直接 bind
- `LocalServer.allow_reuse_address = False`（这是对的，见下方说明）→ 端口被占即 `WinError 10048`
- 异常被 `run.py` 的 `except` 捕获后，无控制台模式下调 `console.notify()` 弹 MessageBox

**与设计语义自相矛盾**：`core/ports.py` 开头明确写着"端口被占用时自动顺延"，
`pick_port()` 也实现了这个语义 —— 但只在"未指定端口"这一条路上生效。

> 补充：`LocalServer.allow_reuse_address = False` 是**有意为之且正确**的
> （Windows 下 SO_REUSEADDR 会骗人，允许两个进程绑同一端口，
> 反而破坏"占用即顺延"），**不要动它**。

---

## 修改点

### 1. `core/server.py` —— `serve()` 显式端口也顺延

**改前**：

```python
def serve(port: int = 0, background: bool = False) -> tuple[LocalServer, int]:
    base = int(CONFIG.platform.get("port_base") or 19000)
    port = port or pick_port(base)
    httpd = LocalServer(("127.0.0.1", port), Handler)
```

**改后**：

```python
def serve(port: int = 0, background: bool = False) -> tuple[LocalServer, int]:
    base = int(CONFIG.platform.get("port_base") or 19000)
    # ★ 端口被占用一律顺延，显式端口也走同一条路。
    #   以前写法是 `port or pick_port(base)`：只有"没指定端口"时才顺延，
    #   显式端口被占会直接抛 WinError 10048 —— 无窗口启动时就是一个
    #   系统错误框，用户除了"确定"什么也做不了。
    #   顺延才是本平台一贯的语义（见 core/ports.py 开头）。
    port = pick_port(port or base)
    httpd = LocalServer(("127.0.0.1", port), Handler)
```

### 2. `run.py` —— `--port` 不写回持久配置

**改前**（约第 90 行）：

```python
    paths.ensure_dirs()
    if args.port:
        CONFIG.platform["port_base"] = args.port
```

**改后**：

```python
    paths.ensure_dirs()
    # ★ --port 只表示"本次启动优先用这个端口"，不再写回 CONFIG。
    #   写回会被随后任意一次配置保存（/api/settings）带进 data/config.json，
    #   把平台永久钉死在这个端口上 —— 2026-09-23 那次 WinError 10048
    #   （19600 被一个 --no-window 残留实例占住，之后每次启动都撞它）
    #   就是这么形成的。顺延逻辑在 core/server.py::serve()。
```

> 注意：删掉这两行后，`--port` 依然生效 —— `run.py` 里
> `serve(port=args.port or 0, ...)` 已经把值直接传下去了，与 CONFIG 无关。

**这两处之外不要改动其它逻辑。**

---

## 复查：10048 还能不能复现？（2026-09-23 20:30）

**能。** 工单里修的那条（显式端口不顺延）确实是好的，但 `pick_port()` 是
**先探后绑**——拿一个临时 socket 试绑、立刻关掉、再由 `LocalServer` 真绑：

```python
def pick_port(base, span=50):
    for i in range(span):
        p = base + i
        with socket.socket(...) as s:
            s.bind((HOST, p))      # ← 探完即关
            return p               # ← 端口此刻是"无主"的
    ...
httpd = LocalServer((HOST, port), Handler)   # ← 真绑，中间隔着上面这段
```

探与绑之间那道缝，够另一个实例插进来。写了个并发探针实测：
**12 个实例同时以 `--port 19900` 启动 → 成功 7、失败 5，失败全是 WinError 10048。**

现实触发：开机自启的实例和用户双击 bat 的实例同时走到这一步。
开机那几秒机器忙，Python 解释器启动又慢，撞上的概率不低。

### 修改点 3 —— `core/server.py`：边试边绑

新增 `bind_platform()`，**绑定动作本身就是探测**，探与绑之间没有缝：

```python
def bind_platform(base: int, span: int = 50) -> tuple[LocalServer, int]:
    last: OSError | None = None
    for i in range(span):
        p = base + i
        try:
            httpd = LocalServer(("127.0.0.1", p), Handler)
        except OSError as exc:
            last = exc
            continue
        return httpd, p
    detail = f"（最后错误：{last}）" if last else ""
    raise RuntimeError(f"平台端口 {base}~{base + span - 1} 均被占用{detail}")


def serve(port: int = 0, background: bool = False):
    base = int(CONFIG.platform.get("port_base") or 19000)
    httpd, port = bind_platform(port or base)      # ← 不再是 pick_port
    ...
```

`pick_port()` 保留但加了警告注释（它是纯探测，别再拿它挑真端口）。
`LocalServer` 构造失败时 `socketserver` 已自行 `server_close()`，无需收摊。

### 修改点 4 —— `core/instance.py`（新文件）：实例留痕

工单「可选加固 2」的落地。原则：**任何能"看不见地活着"的进程，
都必须可被发现、可被关闭。**

- `data/instances/<port>.json` —— **每个**实例都留一份（含 `--port` 起的第二实例）
- `data/.instance.json` —— 只有"主实例"写，用 `O_CREAT|O_EXCL` 原子占位

判活依据是**端口上真有一个星港在应答**（`/api/health` 返回 `platform == "StarPort"`），
**不是**"文件存在"、**也不是**"PID 还活着" —— PID 会被系统复用，靠它判断会误伤。
陈旧留痕在判活时自动被清掉，所以被强杀留下的痕迹不影响下次启动。

### 修改点 5 —— `run.py` 单实例守卫 + `tools/stop_instance.py`

工单「可选加固 1」的落地。`run.py` 在 `serve()` 之前先查：

```python
want_second = bool(args.port) or args.allow_second
if not want_second:
    prev = instance.live_primary()
    if prev:
        print(f"[StarPort] 已有实例在运行：PID {prev['pid']} 端口 {prev['port']} ……")
        if not args.no_window and not focus_window(TITLE):
            console.notify("StarPort 已在运行", "...\n python tools\\stop_instance.py")
        return 0
```

- 已有实例 → 把它的窗口提到前台，本次不重复启动
- 对方是 `--no-window`（找不到窗口）→ 弹一条能看懂的提示，而不是"双击了什么都没发生"
- 显式 `--port`（或 `--allow-second`）视为刻意开第二份，不参与复用 ——
  工单里那个 19600 调试实例就是这么起的

配套 `tools/stop_instance.py`：

```powershell
python tools/stop_instance.py                  # 只报告，不动手
python tools/stop_instance.py --yes            # 关主实例（优雅关）
python tools/stop_instance.py --yes --all      # 关所有
python tools/stop_instance.py --yes --port 19600
python tools/stop_instance.py --yes --force    # 优雅关无效时直接结束进程
```

---

## 验证方法

**关键场景：端口被占时，显式指定该端口仍能起来。**

```powershell
# 用 Python 占住 19600，另开一个进程执行：
E:\Python312\python.exe E:\StarPort\run.py --port 19600 --no-window
```

**期望**：

```
[StarPort] 平台已启动：http://127.0.0.1:19601/  (应用数 3)
```

`GET http://127.0.0.1:19601/api/health` → **200**。

实测结果（2026-09-23 19:28）：占住 19600 后启动 → 顺延到 **19601**，
`/api/health` 返回 **200**；验证进程退出后 19600 / 19601 均正常释放。

### 回归检查（2026-09-23 20:30 复测，全部通过）

| 场景 | 期望 | 实测 |
| --- | --- | --- |
| 显式 19600 被占 | 顺延 19601 | ✅ 19601，health 200 |
| 不传端口、基准空闲 | 起在基准 | ✅ 19500，health 200 |
| 不传端口、基准被占 | 顺延 | ✅ 19501，health 200 |
| 显式端口空闲 | 就用它 | ✅ 19700，health 200 |
| 整段 19800~19849 全占 | `RuntimeError`（非 WinError） | ✅ `平台端口 19800~19849 均被占用（最后错误：[WinError 10048] …）` |
| **12 个实例并发启动** | 全部成功、无 10048 | 修复前 7 成功 / **5 失败**；修复后 **12 成功 / 0 失败** |
| `port_base` 是否被 `--port` 改动 | 不变 | ✅ 19000 → 19000 |
| 二次启动（已有实例） | 不重复起，复用已有 | ✅ 退出码 0，19001 未被占，日志「已有实例在运行…」 |
| 显式 `--port 19600` | 允许第二份，且留痕 | ✅ 起在 19600，`instances/` 两份 |
| `stop_instance.py --yes --port 19600` | 优雅关，端口释放 | ✅ 1.0s 释放，另一实例不受影响 |
| `stop_instance.py --yes` | 关主实例 | ✅ 1.5s 释放，进程退出 |
| 全关后再跑 | 报告"没有实例"，陈旧留痕自愈 | ✅ `instances/` 空、可直接再启动 |

### 残留风险（已知，未处理）

两个实例在**同一瞬间**（毫秒级）首次启动，且都还没来得及写 `.instance.json` 时，
仍可能都通过判活、各占一个端口 —— 但**不会再抛 10048**（修改点 3 保证），
最坏是出现两个窗口，用户关掉一个即可。要彻底消掉得引入跨进程锁，
代价高于收益，暂不做。

---

## 可选加固（已于 2026-09-23 20:30 全部落地）

1. ✅ **单实例检测** → 修改点 5。判据是"端口上真有一个星港在应答"，
   不是 PID（PID 会被系统复用）。
2. ✅ **`--no-window` 实例留痕** → 修改点 4 + `tools/stop_instance.py`。
   原则不变：**任何能"看不见地活着"的进程，都必须可被发现、可被关闭。**
3. **启动前检测"这两个文件是否被改过"**——不需要，仅记录。

---

## 附：现场证据

| 证据 | 位置 |
| --- | --- |
| 失败实例日志（与存活实例写同一份文件） | `data/logs/platform.log` |
| 占用进程命令行 | `run.py --no-window --port 19600`（PID 23056） |
| 调试脚本时间线（与 6 次失败一一对应） | `data/_probe5.mjs`=19:17 … `data/_probe10.mjs`=19:23 |
| 判据：`--port` 是否被传入 | 报错文本里的 `base` 来自 `CONFIG.platform["port_base"]`，为 19600 说明是显式传入 |

### 一个容易误判的点

`console._has_console()` 用 `GetConsoleWindow()` 判断，所以
**日志头写「(pythonw 无窗口模式)」不能反推启动方式就是 pythonw** ——
任何无控制台的启动（自动化工具、计划任务、服务）都会长这样。
排查时不要靠这一行下结论。
