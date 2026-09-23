# StarPort 应用接入标准（界面 + 运行时，给应用开发者）

> **目的**：让接入星港的应用在视觉上与平台保持一致，切换材质/基调时能自动跟随；
> 同时在端口、进程、数据这些运行时约定上不跟平台打架。
> **适用对象**：任何以 `webservice` / `static` 接入的应用。
> **参考实现**：星港自己的壳就是范例 —— `shell/tokens.css`、`shell/materials.css`、`shell/styles.css`；
> 已接入的两个真实应用可直接对照：`E:\Filecleanup`、`E:\starport-formatbay`。
>
> **章节导航**：§1~§6 是界面（§2.5 背景融合、§2.6 窄窗适配是踩坑重灾区），
> §7 是可直接抄的示例，§8 选型，
> **§9 是运行时约定（端口 / 进程 / 数据）—— 做后端接入时同样要看**，
> §10 自检清单。

---

## §0 先理解这条硬约束

星港用 iframe 承载应用，**应用与平台不同源**（平台 `:19000`，应用 `:19100+`）。

浏览器安全模型决定了：

> **平台无法从外部往应用里注入任何 CSS、也无法读写应用的 DOM。**

所以"视觉统一"**不是平台能强制的**，只能靠两件事：

1. 平台主动把当前主题**告诉**应用（已实现，见 §1）；
2. 应用按本标准**自己**把主题用起来。

不遵循标准也能正常跑，只是切换材质时它会是"另一个世界的样子"。

---

## §1 平台如何把主题传给你（两条通道）

### 通道 A：URL 参数（首屏就能读到，推荐）

平台打开应用时，会在你的地址后追加参数：

```
http://127.0.0.1:19100/?sp-theme=dark&sp-material=liquid-glass&sp-source=starport&sp-blend=1&sp-surface=1
```

| 参数 | 取值 | 说明 |
|---|---|---|
| `sp-theme` | `dark` \| `light` | 当前基调 |
| `sp-material` | 见 §3 的 10 个 id | 当前材质 |
| `sp-source` | `starport` | 存在即表示"被星港托管"，可据此切换独立/托管模式 |
| `sp-blend` | `1` \| `0` | **背景融合**：`1` = 请你把自身背景透明，让星港的背景透出来 |
| `sp-surface` | `1` \| `0` | **材质继承**：`1` = 应用区已套用星港材质，你的内容可以只留文字与控件 |

**为什么用 URL 而不是接口**：应用首屏渲染前就能读到，避免"先按默认色画一遍、再闪一下变色"的割裂感。且没有跨域/CORS 问题。
`sp-blend` 尤其必须在首屏读到 —— 否则会先画出自己的底、再变透明，肉眼能看到闪一下。

```js
const qs = new URLSearchParams(location.search);
const theme = qs.get('sp-theme') || 'dark';
const material = qs.get('sp-material') || 'liquid-glass';
document.documentElement.dataset.theme = theme;
if (qs.get('sp-blend') === '1') applyBlend(true);   // 见 §2.5
```

#### ⚠️ 这段脚本必须在样式表**之前**、且是同步的

`sp-blend` / `sp-theme` 要在**第一次绘制之前**落到 DOM 上。所以读取参数的那段
脚本必须放在 `<link rel="stylesheet">` **之前**，同步执行。

放到 `</body>` 前、或等 `DOMContentLoaded`、或用 `defer` 都**晚了** ——
会先按默认色画一遍再改，肉眼能看到闪一下，融合模式下闪得更明显（先白底再透明）。

```html
<head>
  <script>/* ★ 读 sp-* 参数并落到 documentElement.dataset 上 */</script>
  <link rel="stylesheet" href="styles.css">   <!-- 必须在脚本之后 -->
</head>
```

#### 建议在根元素上落的标记（纯约定，方便你自己写 CSS）

| 属性 | 取值 | 说明 |
|---|---|---|
| `data-theme` | `dark` \| `light` | 当前基调 |
| `data-material` | 材质 id | 当前材质 |
| `data-sp-blend` | `1` \| `0` | 当前是否处于背景融合（透明）状态 |
| `data-sp-hosted` | `1` \| `0` | 是否被星港托管 |

**融合相关的 CSS 一律挂在 `[data-sp-blend="1"]` 下**（见 §2.5）。
这样应用脱离星港独立运行时，这些规则一条都不生效，外观完全回到原生 ——
一份代码两种形态，不需要维护两套样式。

### 通道 B：postMessage（运行时实时跟随）

用户在星港里切了材质，平台会向你的窗口推一条消息：

```js
window.addEventListener('message', (e) => {
  const d = e.data;
  if (!d || d.type !== 'starport:theme') return;
  // d.version         1
  // d.theme           'dark' | 'light'
  // d.material        'liquid-glass' | ...
  // d.blend           true | false   —— 是否请应用透明（背景融合）
  // d.materialInherit true | false   —— 是否套用了平台材质
  // d.tokens          { '--sp-bg': '#0e1116', '--sp-text': '...', ... }
  applyTheme(d.theme, d.material, d.tokens);
  applyBlend(!!d.blend);              // 见 §2.5
});
```

`d.tokens` 是平台当前生效的设计 token 值，你可以直接铺到自己的变量上 —— 这样**连色值都不会跟平台跑偏**。

> **安全提示**：消息来自跨域窗口，`e.origin` 会是平台的地址。建议校验 `e.origin` 后再处理；
> 但**不要**只依赖 `e.data` 的字段就执行危险操作（比如导航到 `d.url`）。

### 通道 C（可选）：主动拉取

任何时候都可以拉取主题标识（该端点已开放 CORS，可跨域直接调）：

```
GET http://127.0.0.1:19000/api/theme
→ { "ok": true, "version": 1, "theme": "dark", "material": "liquid-glass",
    "materials": ["liquid-glass", "glassmorphism", ...] }
```

注意这里**只返回主题标识，不返回具体色值** ——
色值以本文档 §3 / §4 的 token 表为准，由应用侧映射。
这样避免平台与应用各存一份色板、久了必然对不上。

> 通常不需要用这条通道：URL 参数（通道 A）+ postMessage（通道 B）已经能覆盖
> 首屏与运行时两种场景。它存在只是为了应对"应用自己重新加载了页面"之类的边缘情况。

---

## §2 三层结构（请照此分层）

```
第 0 层  background  ——  背景图片/视频/渐变，可随时替换，不参与任何材质计算
第 1 层  material    ——  材质层：半透明 + 模糊 + 高光 + 噪点 + 阴影 + 描边
第 2 层  content     ——  文字、按钮、图标等真实内容
```

**硬性要求**：

1. **材质层不得读取背景内容**。不许把背景图当纹理采样、不许按背景计算 UV 偏移、不许为某张背景单独烘焙贴图。材质只允许通过 `backdrop-filter` 这种浏览器原生能力"感知"背后有什么。
2. **内容层文字永远是实色**（允许轻微 `text-shadow`）。**绝不**把文字放进半透明层里靠整体 `opacity` 调节 —— 那会让文字随材质透明度一起糊掉。
3. **材质参数全部走 CSS 变量**，容器只消费变量，不写死数值。

---

## §2.5 背景融合模式（可选，但效果最好）

### 它解决什么

默认情况下，应用自己画背景，于是平台里会出现"外壳是玻璃、主区是一块白板"的割裂感。

星港提供「背景融合」开关：**开启时希望你把自身背景设为透明**，
这样应用区域会直接透出星港的背景（图片/视频）和材质，
而且因为 iframe 就渲染在平台的坐标空间里，**画面是连贯的一整张，不是两边拼接**。

> 原理上只有这一条路走得通。另一种想法是"平台把背景图 URL 发给应用、应用自己画"
> —— 实测不可行：两个区域各自 `object-fit: cover`，图片会被各自裁切，
> 接缝处直接断开。只适合纯色或无缝图案。
> 而且平台换背景时还得逐个通知，透明方案则**完全不需要通知**。

### 怎么判定要不要透明

```js
const blend = new URLSearchParams(location.search).get('sp-blend') !== '0';
// 运行时变化走 postMessage 的 d.blend
// （sp-blend 缺省视为开；独立运行时拿不到该参数，也会走"开"）
```

### ⚠️ 别把 `color-scheme: dark` 写在 `:root` 上（实测踩过）

一个必须知道的浏览器行为：**子框架的"已用色彩方案是 dark、且它自身背景透明"时，
Chromium 会把整块画布填成不透明色，平台背景就透不出来了。**

复现（父页任意写 `:root{color-scheme:dark}`）：

```html
<iframe srcdoc="<body style='background:transparent'></body>"></iframe>
<!-- 这块区域是不透明白，不是父页背景 -->
```

后果就是：应用自己明明 `html,body{background:transparent}` 了，星港里看到的
却是一块白板 —— 很容易误判成"融合没接上"。

**正确做法**：

- 需要深色表单控件 / 滚动条时，把 `color-scheme` 写在 **`body`** 上，不要写 `:root`；
- 平台侧已经在 `iframe` 上显式声明了 `color-scheme: normal`（见 `shell/styles.css`），
  你只要不在 `:root` 上再声明一次即可。

```css
body { color-scheme: dark; }      /* ✅ 安全 */
:root { color-scheme: dark; }     /* ❌ 融合会失效 */
```

### 怎么实现（关键：只让最外层透明）

```js
function applyBlend(on) {
  document.documentElement.style.background = on ? 'transparent' : '';
  document.body.style.background = on ? 'transparent' : '';
  document.documentElement.dataset.spBlend = on ? '1' : '0';
}
```

```css
/* 应用内部的卡片 / 工具栏保持不透明 —— 观感是"应用的卡片浮在平台背景上"，
   比整页透明更耐看，也更好保证文字可读。 */
[data-sp-blend="1"] .card { background: var(--sp-panel); }
```

**五条要点（前三条是实测踩出来的坑）**：

1. **不要连内部卡片一起透明**。只让 `html` / `body` 透明即可；
   卡片、工具栏保留自己的底色，形成"浮起"的层次。
2. **对比度责任转移到你身上**。背景可能是任意图片或视频，你那句文字
   可能正好压在最亮的区域。融合模式下请给正文加轻微 `text-shadow`，
   或让承载文字的卡片保留半透明底。
3. **首屏必须靠 `sp-blend` 参数决定**，不能等 postMessage ——
   否则会先画出自己的底再变透明，肉眼能看到闪一下。
4. **融合规则一律挂在 `[data-sp-blend="1"]` 下**。应用独立运行（不被托管）时
   拿不到 `sp-blend`，该选择器不命中，这些规则一条都不生效 ——
   一份代码两种形态，不用维护两套样式。
5. **卡片别太实**。`.card` 用 88% 不透明度时背景只透 12%，肉眼等于没融合；
   实测降到 **66%** 才有明显效果（次要浮层如右键菜单、tooltip 可用 82%，
   它们面积小、且需要更高可读性）。

### 与「材质继承」的关系

星港还有一个「材质继承」开关（`sp-surface` / `d.materialInherit`）：

| 背景融合 | 材质继承 | 应用区实际效果 |
|---|---|---|
| 开 | 开 | 平台背景 + 平台材质 —— 完全一体 |
| 开 | 关 | 平台背景，但不加材质层（纯净背景） |
| 关 | 开 | 被应用自己的底盖住，**材质开关看不见效果** |
| 关 | 关 | 完全独立（就是默认那种样子） |

所以**背景融合是材质继承的前提**。`sp-surface` 只是告诉你"当前应用区已被套上平台材质"，
你可以据此少画一层自己的底、让内容更轻。

---

## §2.6 窄窗与分屏适配（用户按 Win + ←/→ 时就会遇上）

用户把星港窗口贴到半屏是常态，应用区会被压到 **940px 甚至更窄**
（1920 半屏 = 960，再扣掉侧栏）。布局不设防就会出现"按钮互相压住、标签文字竖着排" ——
这是验收必查项，也是用户最容易抱怨的一条。

**三条必做**：

1. **顶栏容器允许换行**：`flex-wrap: wrap`，并给可伸缩区 `flex: 1 1 0; min-width: 0`。
   `min-width: 0` 是关键 —— flex 子项默认 `min-width: auto`，会被内容顶开而不收缩。
2. **按钮 / 标签不许被压扁**：`flex: 0 0 auto` + `white-space: nowrap`；
   可截断的文字再配 `overflow: hidden; text-overflow: ellipsis`。
3. **给窄窗留断点**：建议 1080 / 820 / 620 三档，逐级隐藏次要控件、收起标签文字。

```css
.toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.toolbar .grow { flex: 1 1 0; min-width: 0; }        /* min-width:0 别漏 */
.tab { flex: 0 0 auto; white-space: nowrap; }
.tab-text { overflow: hidden; text-overflow: ellipsis; }
@media (max-width: 820px) { .toolbar .secondary { display: none; } }
```

**不要**把一行用固定 `px` 宽度顶满（必溢出），
也**不要**靠 `transform: scale()` 缩内容（DPI 下会糊，见 §6）。

---

## §3 10 套材质与 Token 命名

材质 id（`sp-material` 的取值）：

| id | 名称 | 特征 |
|---|---|---|
| `liquid-glass` | 液态玻璃 | blur 26 / sat 180% / 径向高光 / 噪点 |
| `glassmorphism` | 玻璃拟态 | blur 14 / 轻量 / 无高光层 |
| `acrylic` | 亚克力 | blur 18 / 强噪点 / 几乎无边框 |
| `mica` | 云母 | blur 6 / 极低对比 / 大面积柔和阴影 |
| `neumorphism` | 新拟物 | 双阴影 / 无模糊 / 无边框 |
| `claymorphism` | 粘土拟态 | 厚内阴影 / 大圆角 / 偏不透明 |
| `holographic` | 全息虹彩 | conic 彩虹 / overlay 混合 |
| `liquid-metal` | 液态金属 | 多层线性渐变 / 锐利边界 / 无模糊 |
| `brushed-metal` | 磨砂金属 | 单向细条纹 / 中性灰 |
| `aurora-glass` | 极光玻璃 | 径向光晕 / screen 混合 |

**容器消费的统一变量名**（与平台内部一致，便于互相抄）：

```css
.surface {
  background: var(--mat-bg);
  border: var(--mat-border);
  border-radius: var(--mat-radius);
  box-shadow: var(--mat-shadow);
}
.surface--blur {
  backdrop-filter: blur(var(--mat-blur)) saturate(var(--mat-saturate));
}
```

每套材质只定义变量（完整 20 组见 `shell/materials.css`，可直接复制）：

```css
[data-material="liquid-glass"] {
  --mat-bg: linear-gradient(135deg, var(--tint-1), var(--tint-2));
  --mat-blur: 26px;
  --mat-saturate: 180%;
  --mat-border: 1px solid var(--line);
  --mat-radius: 22px;
  --mat-shadow:
    inset 0 1px 1px var(--spec-hi),
    inset 0 -1px 1px var(--shade),
    0 20px 60px var(--drop-1);
}
```

**关键做法：加第 11 套材质只需要加一段变量，不需要动任何选择器逻辑。**

---

## §4 基调输入变量（亮/暗不该靠"反色"）

材质定义只写一次，亮暗差异由**基调层**提供的输入变量承载 —— 这样 10 套材质 × 2 套基调只需维护 12 份定义，而不是 20 份。

| 变量 | 含义 | 暗色 | 亮色 |
|---|---|---|---|
| `--tint-1` / `--tint-2` | 玻璃渐变两端 | 白 20% → 5% | 白 78% → 52% |
| `--spec-hi` / `--spec-hi-dim` | 镜面高光 | 白 62% / 22% | 白 100% / 85% |
| `--shade` | 暗部 / 内阴影 | 黑 42% | **冷灰 34%** |
| `--line` | 描边 | 白 14% | **冷灰 38%** |
| `--drop-1` / `--drop-2` | 投影 | 黑 52% / 32% | 蓝灰 22% / 14% |
| `--noise-a` | 噪点强度 | .10 | .085 |
| `--neu-base` / `--neu-hi` / `--neu-lo` | 新拟物底/亮侧/暗侧 | … | 暗侧需 **.78** |

**三个亮色专属的坑**（实测踩过）：

1. **白上叠白看不见** —— 亮色下不能靠"白色高光"表达起伏，要用**深色内阴影 + 可见的细边线**（这也是 Windows 11 亮色 Mica 的实际做法）。
2. **白边在浅底上等于隐形** —— `--line` 在亮色下必须换成冷灰（如 `rgba(124,142,170,.38)`），否则卡片边界消失。
3. **新拟物需要同色系背景** —— 这是材质本身的性质：放在高对比彩色壁纸上必然显平。若要主推这套材质，建议配合纯色背景使用。

---

## §5 性能红线

| 约束 | 原因 |
|---|---|
| 同屏 `backdrop-filter` 元素 **≤ 3 个** | 每个模糊元素都要对背后区域做一次采样+模糊，叠加会明显掉帧 |
| 不做全屏大面积模糊 | 同上；星港只给侧栏、顶栏、弹窗加模糊，主区不加 |
| 视频背景时 blur ≤ 24px | 视频逐帧变化会让模糊层持续重算 |
| 不做鼠标跟随 / 悬停变形 | 每帧重绘，代价高且非必要 |

**允许**：`backdrop-filter` 属低成本方案，不视为"实时渲染管线"。
**禁止**：WebGL / WebGPU / Canvas / Fragment Shader / 背景内容采样 / 实时折射。
**禁止**：`vibrancy` / `acrylic` 系统 API / `SetWindowCompositionAttribute` / `DwmSetWindowAttribute` —— 窗口背景必须由应用自己画。

**实现建议**：材质装饰（高光、噪点、虹彩、条纹）统一用 `::before` / `::after` 伪元素 + `z-index:-1`，让它们落在**容器背景之上、真实内容之下**，这样文字天然不会被材质透明度污染。

噪点请用内联 SVG，零依赖：

```css
--noise-img: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='140' height='140' filter='url(%23n)'/%3E%3C/svg%3E");
```

---

## §6 可访问性（验收会查）

1. **对比度**：正文 ≥ 4.5:1，大号文字 ≥ 3:1（WCAG AA）。
   材质是半透明的，所以**必须按最坏情况**（背景最亮/最暗处）验证，别只在纯色底上看。
2. **`prefers-reduced-motion: reduce`** → 关掉所有呼吸/流动动效。
3. **`prefers-reduced-transparency: reduce`** → 材质全部降级为**不透明纯色**，并关闭 `backdrop-filter`：

```css
@media (prefers-reduced-transparency: reduce) {
  .surface {
    background: var(--solid);
    backdrop-filter: none;
    border-color: var(--border);
  }
  .surface::before, .surface::after { display: none; }
}
```

4. **DPI 缩放**：100% / 125% / 150% / 200% 下不得出现接缝、模糊错位或边框断裂。
   - 描边用 `border` / `outline`，**不要**用伪元素画细线（亚像素渲染容易断）
   - `border-radius` 用 `px`，不要用百分比
   - 避免在材质容器内部使用 `transform: scale()`

---

## §7 最小接入示例（可直接抄）

```html
<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark" data-material="glassmorphism">
<head>
<meta charset="utf-8">

<!-- ★ 首屏引导：必须在样式表之前、且同步执行（见 §1）。
     放在 </body> 前就晚了 —— 会先按默认色画一遍再改，肉眼看到闪一下。 -->
<script>
(function () {
  var qs = new URLSearchParams(location.search);
  var d = document.documentElement;
  var hosted = qs.get('sp-source') === 'starport' || qs.has('sp-blend');

  d.dataset.spHosted = hosted ? '1' : '0';
  if (qs.get('sp-theme'))    d.dataset.theme = qs.get('sp-theme');
  if (qs.get('sp-material')) d.dataset.material = qs.get('sp-material');

  /* sp-blend 缺省视为开（独立运行时拿不到该参数，也走"开"） */
  var blend = qs.get('sp-blend') !== '0';
  d.dataset.spBlend = blend ? '1' : '0';
  /* 怎么透明交给 CSS 的 [data-sp-blend="1"] 规则，这里只落标记 */
})();
</script>

<style>
  :root {
    /* 平台通过 postMessage 下发的 token 会覆盖这里 */
    --sp-bg: #0e1116;   --sp-text: #e6ebf2;  --sp-text-dim: #8b97a8;
    --sp-accent: #6ea8fe; --sp-border: #262e3b; --sp-panel: #171d27;
    --radius: 12px;
  }
  [data-theme="light"] {
    --sp-bg: #f4f6fa; --sp-text: #17202c; --sp-text-dim: #5b6779;
    --sp-accent: #2f6fdb; --sp-border: #dde3ec; --sp-panel: #ffffff;
  }
  /* ★ color-scheme 只能写 body。写 :root 会让背景融合失效（见 §2.5） */
  body { color-scheme: dark; }
  :root[data-theme="light"] body { color-scheme: light; }

  body {
    margin: 0; padding: 16px;
    background: var(--sp-bg); color: var(--sp-text);
    font: 14px/1.6 "Microsoft YaHei UI", sans-serif;
  }
  .card {
    padding: 14px 16px; border-radius: var(--radius);
    background: color-mix(in srgb, var(--sp-panel) 82%, transparent);
    border: 1px solid var(--sp-border);
    backdrop-filter: blur(14px) saturate(140%);
  }
  .dim { color: var(--sp-text-dim); }        /* 实色降级，不用 opacity */

  /* 融合态：让平台背景透出来 —— 用选择器声明即可，
     不必等 JS 摸到 body（body 在 <head> 里还不存在） */
  html[data-sp-blend="1"], html[data-sp-blend="1"] body { background: transparent; }
  [data-sp-blend="1"] .card {
    background: color-mix(in srgb, var(--sp-panel) 66%, transparent);  /* 66% 是实测有效值 */
  }
  [data-sp-blend="1"] body { text-shadow: 0 1px 2px rgba(0,0,0,.35); }

  @media (prefers-reduced-transparency: reduce) {
    .card { background: var(--sp-panel); backdrop-filter: none; }
    [data-sp-blend="1"] .card { background: var(--sp-panel); }
  }
</style>
</head>
<body>
  <div class="card">
    <b>跟随星港主题的卡片</b>
    <div class="dim">切换平台的材质与基调，这里会一起变。</div>
  </div>

<script>
/* ① 首屏已经在 <head> 里做过，这里只处理「运行时的实时变更」 */
function applyTheme(theme, material, tokens) {
  const d = document.documentElement;
  if (theme)    d.dataset.theme = theme;
  if (material) d.dataset.material = material;
  if (tokens) {
    for (const [k, v] of Object.entries(tokens)) {
      if (k && v) d.style.setProperty(k, v);
    }
  }
}
/* 只需切标记，具体怎么透明由 CSS 的 [data-sp-blend="1"] 决定 */
function applyBlend(on) {
  document.documentElement.dataset.spBlend = on ? '1' : '0';
}

/* ② 接收平台的实时主题 / 融合开关变更 */
window.addEventListener('message', (e) => {
  const d = e.data;
  if (!d || d.type !== 'starport:theme') return;
  document.documentElement.dataset.spHosted = '1';
  applyTheme(d.theme, d.material, d.tokens);
  applyBlend(d.blend !== false);
});
</script>
</body>
</html>
```

---

## §8 接入选型建议

| 关注点 | 建议 |
|---|---|
| 材质实现 | 优先纯 CSS 变量 + 伪元素。要加第 N 套材质时只加变量段，别改结构 |
| 主题存储 | 牢记"平台是主题的**唯一真源**"，应用不要自己持久化主题，否则会和平台打架 |
| 独立运行 | 用 `sp-source` / `location.search` 判断是否被托管；不托管时用自带默认主题 |
| 依赖 | 不引入任何样式框架或渲染库来"顺便"实现材质 —— 与平台的零依赖取向保持一致 |

---

## §9 运行时约定（端口 / 进程 / 数据）

界面之外，这几条决定你的应用能不能被星港**稳定地拉起和收摊**。

### 端口：用平台给你的那个，别自己挑

manifest 的 `entry.command` 里写 `{port}` 占位符，平台会替换成它分配给你的端口：

```json
"entry": { "command": ["{python}", "run.py", "--port", "{port}", "--no-browser"] }
```

- 你的程序**必须**接受 `--port` 并在该端口上监听；
- 该端口由平台分配并保证空闲，直接 bind 即可，**不要再自己"找一个空闲端口"**；
- 如果你确实换了端口（例如自己做顺延），**必须把最终端口播报出来**：

```python
print(f"服务已启动：http://127.0.0.1:{real_port}/", flush=True)   # ★ 必须 flush
```

平台用 `health.stdout_port_pattern` 抓这行来知道你最终落在哪儿。
不播报就只能靠 `health.path` 轮询，慢且容易误判成启动失败。

> ⚠️ **如果你一定要自己挑端口：必须「边试边绑」，不能「先探后绑」。**
>
> 先用一个临时 socket 试绑、关掉、再由服务真绑 —— 中间的缝隙足以让另一个进程抢走
> 同一个端口，结果就是 `WinError 10048`（实测 12 个并发里挂 5 个，
> 详见 `docs/ISSUE-port-10048.md`）。
> 正确做法是让 bind 动作本身承担探测：
>
> ```python
> for p in range(base, base + span):
>     try:
>         srv = HTTPServer(("127.0.0.1", p), Handler); break
>     except OSError:
>         continue
> ```

另外：**Windows 下别开 `SO_REUSEADDR`**（Python 的 `allow_reuse_address = True`）。
它在本平台语义下会撒谎 —— 允许两个进程绑同一端口，反而破坏"占用即顺延"。

### 进程：能被优雅地收摊

- manifest 里声明 `stop: {"method": "http", "path": "/api/shutdown"}` 时，
  平台退出前会先调它 —— 请在这里存盘、收线程，然后自行退出；
- 平台用 Job Object 兜底：即使平台被强杀，你的进程也会被 OS 一起回收。
  所以**不要假设"下次启动时上次的我还活着"**，启动时请容忍脏状态；
- 反过来也成立：**你的进程不能靠"看不见地活着"**。
  若你以服务形式常驻，请留一份可发现的痕迹（PID + 端口），并提供关闭入口 ——
  星港自己的做法是 `data/instances/<port>.json` + `tools/stop_instance.py`。

### 数据：只写平台给你的目录

- 环境变量 `STARPORT_DATA_DIR`（或 SDK 的 `sdk.starport_sdk.data_dir()`）
  是你的私有目录，平台保证它存在；
- **不要往应用代码目录里写运行时数据**。应用目录可能被共享或只读，
  而且把整份 venv / 数据拷进 `apps/<id>/` 只是白白占空间 ——
  `entry.cwd` 可以直接指向仓库外的真实目录，
  星港就是这么接 FileCleanup（`E:\Filecleanup`）与格式仓（`E:\starport-formatbay`）的：
  `apps/<id>/` 下只留 `manifest.json` 和图标，几十 MB 而不是几百 MB。

### 环境变量速查

| 变量 | 含义 |
|---|---|
| `STARPORT_APP_ID` | 应用 id |
| `STARPORT_PORT` | 平台分配的端口 |
| `STARPORT_DATA_DIR` | 应用私有数据目录（`data/apps-data/<id>/`） |
| `STARPORT_PLATFORM_URL` | 平台地址（经 manifest 的 `{platform_url}` 占位符传递） |

---

## §10 自检清单

**界面**

- [ ] 首屏从 `sp-theme` / `sp-material` URL 参数初始化，无闪色
- [ ] 读参数的脚本放在样式表**之前**且同步执行（§1）
- [ ] 监听 `starport:theme` 消息，切材质/基调时实时跟随
- [ ] 支持背景融合：首屏读 `sp-blend` 决定透明，避免闪白
- [ ] 融合模式下**只让 `html`/`body` 透明**，内部卡片保持不透明
- [ ] 融合规则挂在 `[data-sp-blend="1"]` 下，独立运行时一条都不生效
- [ ] 融合态卡片透明度 ≈ 66%（不是 88%），正文有 `text-shadow` 或半透明底
- [ ] `color-scheme` 写在 **`body`** 上，没写在 `:root` 上（§2.5）
- [ ] 响应 postMessage 里的 `blend` 变化（用户随时可切开关）
- [ ] 严格三层：材质层不读背景内容，文字不与材质做透明度叠加
- [ ] 材质参数全部走 CSS 变量，容器不写死数值
- [ ] 亮色下白边/白高光已替换为深色内阴影 + 冷灰边线
- [ ] 同屏 `backdrop-filter` 元素 ≤ 3 个
- [ ] 无 WebGL / Canvas / Shader / 系统透明 API
- [ ] 正文对比度 ≥ 4.5:1（按最坏背景验证）
- [ ] `prefers-reduced-transparency` 下降级为不透明纯色
- [ ] `prefers-reduced-motion` 下无动效
- [ ] 100% / 125% / 150% / 200% DPI 下无接缝、无边框断裂
- [ ] 更换背景（图片/视频）时材质层零改动、无错位
- [ ] **940px 宽（Win+← 半屏）下顶栏不重叠、标签不竖排**（§2.6）

**运行时**

- [ ] 接受 `{port}` 并在该端口监听，不自己另找端口
- [ ] 若自行顺延端口，已 `flush` 播报 `服务已启动：http://127.0.0.1:<port>/`
- [ ] 若自行挑端口，用的是"边试边绑"而不是"先探后绑"
- [ ] 未开启 `SO_REUSEADDR`（Windows 下会破坏"占用即顺延"）
- [ ] manifest 声明了 `stop`，优雅收摊时存盘并退出
- [ ] 运行时数据只写 `STARPORT_DATA_DIR`，不写应用代码目录
- [ ] `apps/<id>/` 下只有 `manifest.json` 和图标，没有把整个仓库拷贝进去

---

**参考实现**：平台的 `shell/tokens.css`（token 与基调）、`shell/materials.css`（10 套材质）、
`shell/styles.css`（三层装配）。这三份文件就是标准的"活文档"，可直接对照或复制。
