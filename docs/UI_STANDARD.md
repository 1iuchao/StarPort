# StarPort 界面统一标准（给应用开发者）

> **目的**：让接入星港的应用在视觉上与平台保持一致，切换材质/基调时能自动跟随。
> **适用对象**：任何以 `webservice` / `static` 接入的应用。
> **参考实现**：星港自己的壳就是范例 —— `shell/tokens.css`、`shell/materials.css`、`shell/styles.css`。

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

**三个必须注意的点**：

1. **不要连内部卡片一起透明**。只让 `html` / `body` 透明即可；
   卡片、工具栏保留自己的底色，形成"浮起"的层次。
2. **对比度责任转移到你身上**。背景可能是任意图片或视频，你那句文字
   可能正好压在最亮的区域。融合模式下请给正文加轻微 `text-shadow`，
   或让承载文字的卡片保留半透明底。
3. **首屏必须靠 `sp-blend` 参数决定**，不能等 postMessage ——
   否则会先画出自己的底再变透明，肉眼能看到闪一下。

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
  @media (prefers-reduced-transparency: reduce) {
    .card { background: var(--sp-panel); backdrop-filter: none; }
  }
</style>
</head>
<body>
  <div class="card">
    <b>跟随星港主题的卡片</b>
    <div class="dim">切换平台的材质与基调，这里会一起变。</div>
  </div>

<script>
/* ① 首屏：从 URL 参数读，避免闪色 */
const qs = new URLSearchParams(location.search);
function applyTheme(theme, material, tokens) {
  if (theme)   document.documentElement.dataset.theme = theme;
  if (material) document.documentElement.dataset.material = material;
  if (tokens) {
    for (const [k, v] of Object.entries(tokens)) {
      if (k && v) document.documentElement.style.setProperty(k, v);
    }
  }
}
/* 背景融合：让平台背景透出来（只动最外层） */
function applyBlend(on) {
  document.documentElement.style.background = on ? 'transparent' : '';
  document.body.style.background = on ? 'transparent' : '';
}

applyTheme(qs.get('sp-theme'), qs.get('sp-material'));
applyBlend(qs.get('sp-blend') !== '0');        // 缺省视为开

/* ② 运行时：接收平台的实时主题变更 */
window.addEventListener('message', (e) => {
  const d = e.data;
  if (!d || d.type !== 'starport:theme') return;
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

## §9 自检清单

- [ ] 首屏从 `sp-theme` / `sp-material` URL 参数初始化，无闪色
- [ ] 监听 `starport:theme` 消息，切材质/基调时实时跟随
- [ ] 支持背景融合：首屏读 `sp-blend` 决定透明，避免闪白
- [ ] 融合模式下**只让 `html`/`body` 透明**，内部卡片保持不透明
- [ ] 融合模式下正文有 `text-shadow` 或半透明底，保证任意背景下的对比度
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

---

**参考实现**：平台的 `shell/tokens.css`（token 与基调）、`shell/materials.css`（10 套材质）、
`shell/styles.css`（三层装配）。这三份文件就是标准的"活文档"，可直接对照或复制。
