/* StarPort 壳前端 —— 零框架，原生 JS。
   职责：导航 / 搜索 / 置顶 / 应用启停 / 设置 / 心跳。
   应用内容一律交给 iframe 承载，壳不参与应用内部逻辑。 */
'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const S = {
  apps: [],
  settings: { platform: {} },
  state: { pinned: [], recent: [], last_active: null },
  sys: {},
  currentId: null,
  statuses: {},
  filter: '',
};

const STATUS_TEXT = {
  stopped: '未启动', starting: '启动中', running: '运行中',
  crashed: '已崩溃', error: '启动失败',
};

/* 应用类型的"人话解释"。介绍页用 —— 别把 webservice 这种内部术语直接怼给用户 */
const TYPE_INFO = {
  webservice: { label: '独立进程服务',
    how: '平台拉起一个本地进程，健康检查通过后把界面嵌进来。它崩了平台照常跑。' },
  static: { label: '静态页面',
    how: '纯前端页面，由平台直接托管，不额外起进程。' },
  external: { label: '外部原生程序',
    how: '平台只负责启动与回收，界面在系统自己的窗口里，不嵌进星港。' },
};
const typeInfo = (t) => TYPE_INFO[t] || { label: t || '未知类型', how: '' };

/* 10 套页面材质。切换 = 改变量，预览色块靠 CSS 变量继承"活体"渲染。 */
const MATERIALS = [
  { id: 'liquid-glass', name: '液态玻璃', en: 'Liquid Glass' },
  { id: 'glassmorphism', name: '玻璃拟态', en: 'Glassmorphism' },
  { id: 'acrylic', name: '亚克力', en: 'Acrylic' },
  { id: 'mica', name: '云母', en: 'Mica' },
  { id: 'neumorphism', name: '新拟物', en: 'Neumorphism' },
  { id: 'claymorphism', name: '粘土拟态', en: 'Claymorphism' },
  { id: 'holographic', name: '全息虹彩', en: 'Holographic' },
  { id: 'liquid-metal', name: '液态金属', en: 'Liquid Metal' },
  { id: 'brushed-metal', name: '磨砂金属', en: 'Brushed Metal' },
  { id: 'aurora-glass', name: '极光玻璃', en: 'Aurora Glass' },
];

/* 背景预设（第 0 层）。'theme' 表示跟随当前基调的内置背景。 */
const BG_PRESETS = [
  { id: 'theme', name: '跟随主题', css: '' },
  { id: 'deep-sea', name: '深海',
    css: 'radial-gradient(1100px 760px at 12% -8%, #123047 0%, transparent 62%),' +
         'radial-gradient(900px 700px at 98% 100%, #0d2438 0%, transparent 58%), #070d14' },
  { id: 'nebula', name: '星云',
    css: 'radial-gradient(1000px 700px at 20% 0%, #3a1f52 0%, transparent 60%),' +
         'radial-gradient(900px 700px at 95% 95%, #1d2a55 0%, transparent 58%), #0a0a12' },
  { id: 'warm-sand', name: '暖砂',
    css: 'radial-gradient(1100px 760px at 15% -5%, #5a4632 0%, transparent 62%),' +
         'radial-gradient(900px 700px at 100% 100%, #40332a 0%, transparent 58%), #171310' },
];

const BG_DEFAULT = { type: 'preset', value: 'theme' };

/* ────────────────────────────── 网络 ────────────────────────────── */
async function api(path, options) {
  const res = await fetch(path, Object.assign({ headers: {} }, options || {}));
  const text = await res.text();
  try { return JSON.parse(text); } catch (_) { return { ok: false, error: text.slice(0, 300) }; }
}
const post = (path, body) => api(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body || {}),
});

/* ────────────────────────────── 覆盖层 ────────────────────────────── */
function showOverlay(title, desc, opts = {}) {
  $('#ov-title').textContent = title;
  $('#ov-desc').innerHTML = desc || '';
  const log = $('#ov-log');
  if (opts.log) { log.textContent = opts.log; log.hidden = false; }
  else { log.hidden = true; log.textContent = ''; }
  const box = $('#ov-actions');
  box.innerHTML = '';
  (opts.actions || []).forEach(a => {
    const b = document.createElement('button');
    b.className = a.cls || 'ghost';
    b.textContent = a.label;
    b.onclick = a.onClick;
    box.appendChild(b);
  });
  $('#overlay').classList.remove('hidden');
  $('#frame').classList.add('hidden');
}
function hideOverlay() {
  $('#overlay').classList.add('hidden');
  $('#frame').classList.remove('hidden');
}

/* ────────────────────────────── 侧栏渲染 ────────────────────────────── */
function appById(id) { return S.apps.find(a => a.id === id); }
function statusOf(id) { return (S.statuses[id] || {}).status || 'stopped'; }
function initial(name) { return (name || '?').trim().charAt(0).toUpperCase(); }

function makeItem(app, opts = {}) {
  const el = document.createElement('div');
  el.className = 'app-item' + (app.id === S.currentId ? ' active' : '') +
    (app.enabled ? '' : ' dim');
  el.dataset.id = app.id;

  const dot = document.createElement('span');
  dot.className = 'dot ' + statusOf(app.id);

  let icon;
  if (app.icon) {
    icon = document.createElement('img');
    icon.src = app.icon;
    icon.alt = '';
    icon.className = 'app-icon';
  } else {
    icon = document.createElement('span');
    icon.className = 'app-icon';
    icon.textContent = initial(app.name);
  }

  const text = document.createElement('div');
  text.className = 'app-text';
  const nm = document.createElement('div');
  nm.className = 'app-name';
  nm.textContent = app.name + (app.enabled ? '' : '（已禁用）');
  const meta = document.createElement('div');
  meta.className = 'app-meta';
  meta.textContent = app.description || (STATUS_TEXT[statusOf(app.id)] || '');
  text.append(nm, meta);

  el.append(dot, icon, text);

  if (opts.pin !== false) {
    const acts = document.createElement('div');
    acts.className = 'app-actions';
    const pin = document.createElement('button');
    pin.className = 'pin-btn' + (app.pinned ? ' on' : '');
    pin.textContent = app.pinned ? '★' : '☆';
    pin.title = app.pinned ? '取消置顶' : '置顶';
    pin.onclick = async (e) => {
      e.stopPropagation();
      const r = await post(`/api/apps/${app.id}/pin`, { pinned: !app.pinned });
      if (r.ok) { app.pinned = !app.pinned; renderNav(); }
    };
    /* 连点两下置顶不该变成"启动" —— dblclick 是独立事件，click 里 stopPropagation 拦不住 */
    pin.ondblclick = (e) => e.stopPropagation();
    acts.appendChild(pin);
    el.appendChild(acts);
  }

  /* 单击 = 看介绍（不拉起进程）；双击 = 启动。
     键盘：Enter 启动、空格看介绍 —— 双击对键盘用户不可达，必须留等价入口。 */
  el.title = `${app.name}｜单击看介绍，双击启动`;
  el.tabIndex = 0;
  el.setAttribute('role', 'button');
  el.onclick = () => selectApp(app.id);
  el.ondblclick = (e) => { e.preventDefault(); openApp(app.id); };
  el.onkeydown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); openApp(app.id); }
    else if (e.key === ' ' || e.key === 'Spacebar') { e.preventDefault(); selectApp(app.id); }
  };
  return el;
}

/* 只改高亮，不重建 DOM。
   ⚠️ 这里必须"原地改 class"而不是 renderNav()：双击的第二次点击若落在被重建过的
   节点上，dblclick 有可能不再触发（click 的目标节点已被替换），
   表现就是"双击偶尔失灵"。所以单击路径一律不重建列表。 */
function markActive(id) {
  $$('.app-item').forEach(el => el.classList.toggle('active', el.dataset.id === id));
}

function renderNav() {
  const nav = $('#nav');
  nav.innerHTML = '';
  const kw = S.filter.trim().toLowerCase();
  const match = (a) => !kw ||
    (a.name + ' ' + a.id + ' ' + (a.description || '') + ' ' +
     (a.tags || []).join(' ') + ' ' + (a.category || '')).toLowerCase().includes(kw);

  const list = S.apps.filter(match);

  if (!S.apps.length) {
    nav.innerHTML = '<div class="empty">还没有接入应用。<br>打开「设置 → 应用管理」安装一个。</div>';
    return;
  }
  if (!list.length) {
    nav.innerHTML = '<div class="empty">没有匹配的应用</div>';
    return;
  }

  const group = (title, items) => {
    if (!items.length) return;
    const g = document.createElement('div');
    g.className = 'nav-group';
    const t = document.createElement('div');
    t.className = 'nav-group-title';
    t.innerHTML = `${title} <span class="count">${items.length}</span>`;
    g.appendChild(t);
    items.forEach(a => g.appendChild(makeItem(a)));
    nav.appendChild(g);
  };

  if (!kw) {
    group('置顶', list.filter(a => a.pinned));
    const recent = (S.state.recent || []).map(appById).filter(Boolean)
      .filter(a => !a.pinned && list.includes(a)).slice(0, 4);
    group('最近使用', recent);
    const cats = new Map();
    list.forEach(a => {
      const c = a.category || '未分类';
      if (!cats.has(c)) cats.set(c, []);
      cats.get(c).push(a);
    });
    Array.from(cats.entries()).sort((x, y) => x[0].localeCompare(y[0], 'zh'))
      .forEach(([c, items]) => group(c, items));
  } else {
    group('搜索结果', list);
  }
}

/* ─────────────────── 应用介绍页（单击 = 看，双击 = 启动） ───────────────────
   单击列表项只渲染介绍，绝不拉起进程 —— 避免"随手一点就起一个 Python 进程"。
   介绍页是覆盖在 iframe 之上的一层（z-index 4），iframe 用 visibility 隐藏，
   既不卸载页面、也不打断应用里的状态。 */
function introVisible() {
  const el = $('#intro');
  return !!el && !el.hidden;
}

function showCurrentMeta(app) {
  $('#cur-name').textContent = app.name;
  $('#cur-sub').textContent = app.description || app.category || '';
  $('#cur-icon').textContent = initial(app.name);
}

function selectApp(id) {
  const app = appById(id);
  if (!app) return;
  /* 已经在看这个应用的画面了 → 单击不再把它换成介绍页（省得误触丢掉正在用的界面） */
  if (S.currentId === id && !introVisible() && statusOf(id) === 'running') return;
  S.currentId = id;
  markActive(id);
  showCurrentMeta(app);
  setPill(statusOf(id));
  showIntro(app);
  syncTopbar();
}

function showIntro(app) {
  const el = $('#intro');
  if (!el || !app) return;
  renderIntro(app);
  el.hidden = false;
  $('#overlay').classList.add('hidden');
  $('#frame').classList.add('hidden');
}

function hideIntro() {
  const el = $('#intro');
  if (el) el.hidden = true;
  $('#frame').classList.remove('hidden');
}

/* 从介绍页切回应用画面 */
function showAppView() {
  hideIntro();
  const st = S.currentId && S.statuses[S.currentId];
  const app = S.currentId && appById(S.currentId);
  if (st && st.status === 'running' && st.url) {
    hideOverlay();
  } else if (st && st.status === 'running' && app) {
    /* external 型：没有可嵌入的地址，把"已在外部启动"的说明摆回来 */
    showOverlay('已在外部启动', `${app.name} 是原生程序，已在独立窗口中打开。`,
      { actions: [{ label: '停止', cls: 'danger-btn', onClick: () => stopCurrent() }] });
  }
  syncTopbar();
}

function renderIntro(app) {
  if (!app) return;

  const icon = $('#in-icon');
  icon.innerHTML = '';
  if (app.icon) {
    const im = document.createElement('img');
    im.src = app.icon; im.alt = '';
    icon.appendChild(im);
  } else {
    icon.textContent = initial(app.name);
  }

  $('#in-name').textContent = app.name;
  const bits = ['v' + (app.version || '0.0.0')];
  if (app.author) bits.push('作者 ' + app.author);
  bits.push(app.category || '未分类');
  $('#in-sub').textContent = bits.join(' · ');

  const st = statusOf(app.id);
  const pill = $('#in-status');
  pill.className = 'pill pill-' + st;
  pill.textContent = STATUS_TEXT[st] || st;
  S._introStatus = st;

  $('#in-desc').textContent = app.description || '这个应用还没有填写介绍。';

  const tags = $('#in-tags');
  tags.innerHTML = '';
  (app.tags || []).forEach(t => {
    const s = document.createElement('span');
    s.className = 'badge';
    s.textContent = t;
    tags.appendChild(s);
  });

  const info = typeInfo(app.type);
  const rows = [['类型', info.label], ['运行方式', info.how],
                ['应用标识', app.id], ['目录', app.dir || '—']];
  const url = (S.statuses[app.id] || {}).url;
  if (st === 'running' && url) rows.push(['访问地址', url]);
  if (app.notes) rows.push(['备注', app.notes]);
  const facts = $('#in-facts');
  facts.innerHTML = '';
  rows.forEach(([k, v]) => {
    const dt = document.createElement('dt');
    dt.textContent = k;
    const dd = document.createElement('dd');
    dd.textContent = v || '';
    if (k === '目录' || k === '访问地址') dd.className = 'mono';
    facts.append(dt, dd);
  });

  const iss = $('#in-issues');
  if ((app.issues || []).length) {
    iss.hidden = false;
    iss.innerHTML = '<b>manifest 存在问题：</b><br>' +
      (app.issues || []).map(escapeHtml).join('<br>');
  } else {
    iss.hidden = true;
    iss.innerHTML = '';
  }

  renderIntroActions(app);
}

function renderIntroActions(app) {
  const box = $('#in-actions');
  if (!box) return;
  box.innerHTML = '';
  const st = statusOf(app.id);
  const running = st === 'running';
  const url = (S.statuses[app.id] || {}).url;
  const add = (label, cls, fn) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = cls;
    b.textContent = label;
    b.onclick = fn;
    box.appendChild(b);
  };

  if (!app.enabled) {
    add('已禁用 · 去应用管理', 'primary', () => openSettings('apps'));
  } else if (running) {
    add('返回应用', 'primary', () => showAppView());
    if (url) add('新窗口打开', 'ghost', () => window.open(withThemeParams(url), '_blank'));
    add('停止', 'danger-btn', () => stopCurrent());
  } else {
    add('启动应用', 'primary', () => openApp(app.id));
  }
  add('应用管理', 'ghost', () => openSettings('apps'));
}

/* 顶栏按钮随"在看介绍 / 在看应用 / 应用状态"三者变化 */
function syncTopbar() {
  const app = S.currentId && appById(S.currentId);
  const btnLaunch = $('#btn-launch'), btnRestart = $('#btn-restart');
  const btnStop = $('#btn-stop'), btnPopout = $('#btn-popout');
  if (!app) {
    [btnLaunch, btnRestart, btnStop, btnPopout].forEach(b => { b.hidden = true; });
    return;
  }
  const st = statusOf(app.id);
  const running = st === 'running';
  const url = (S.statuses[app.id] || {}).url;
  const inIntro = introVisible();

  /* 启动按钮只在"正在看介绍"时出现 —— 应用画面已经在眼前时不需要它 */
  btnLaunch.hidden = !inIntro || !app.enabled;
  btnLaunch.textContent = running ? '返回应用' : '启动应用';
  btnLaunch.title = running ? '回到应用画面' : '启动这个应用';
  btnLaunch.onclick = running ? showAppView : () => openApp(app.id);

  btnRestart.hidden = !running || inIntro;
  btnStop.hidden = !running || inIntro;
  btnPopout.hidden = !running || inIntro || !url;
}

/* ────────────────────────────── 应用启停 ────────────────────────────── */
async function openApp(id) {
  const app = appById(id);
  if (!app) return;
  S.currentId = id;
  hideIntro();                       // 真的要启动了 → 介绍页收起
  renderNav();
  showCurrentMeta(app);
  syncTopbar();
  setPill('starting');

  if (!app.enabled) {
    showOverlay('应用已被禁用', '在「设置 → 应用管理」里重新启用后即可使用。', {
      actions: [{ label: '去设置', cls: 'primary', onClick: () => openSettings('apps') }],
    });
    setPill('stopped');
    syncTopbar();
    return;
  }

  showOverlay('正在启动…', `${app.name} 正在独立进程中启动，稍等一下。`);
  const r = await post(`/api/apps/${id}/launch`, {});

  if (!r.ok) {
    setPill('error');
    const r2 = await api(`/api/apps/${id}/log`);
    showOverlay('启动失败', escapeHtml(r.error || '未知错误'), {
      log: (r2.log || []).join('\n') || (r.log || ''),
      actions: [
        { label: '重试', cls: 'primary', onClick: () => openApp(id) },
        { label: '查看完整日志', cls: 'ghost', onClick: () => window.open(`/api/apps/${id}/log`) },
      ],
    });
    refreshStatus();
    return;
  }

  S.statuses[id] = Object.assign(S.statuses[id] || {}, { status: 'running', url: r.url });
  setPill('running');
  syncTopbar();

  if (!r.url) {                       // external 型：外部窗口，壳内不嵌入
    showOverlay('已在外部启动', `${app.name} 是原生程序，已在独立窗口中打开。`,
      { actions: [{ label: '停止', cls: 'danger-btn', onClick: () => stopCurrent() }] });
    return;
  }
  const themed = withThemeParams(r.url);
  $('#frame').src = themed;
  $('#btn-popout').onclick = () => window.open(themed, '_blank');
  // 兜底：某些应用不触发 load 事件时，别让"正在启动"一直卡着
  setTimeout(() => {
    if (!$('#overlay').classList.contains('hidden') &&
        (S.statuses[id] || {}).status === 'running') hideOverlay();
  }, 8000);
}

async function stopCurrent() {
  if (!S.currentId) return;
  await post(`/api/apps/${S.currentId}/stop`, {});
  setPill('stopped');
  if (introVisible()) {
    /* 在介绍页里点停止 → 不弹"已停止"覆盖层，把状态刷回介绍页即可 */
    await refreshStatus();
    renderIntro(appById(S.currentId));
    syncTopbar();
    return;
  }
  showOverlay('已停止', '应用进程已回收。',
    { actions: [{ label: '重新启动', cls: 'primary', onClick: () => openApp(S.currentId) }] });
  refreshStatus();
}
async function restartCurrent() {
  if (!S.currentId) return;
  const id = S.currentId;
  await post(`/api/apps/${id}/restart`, {});
  await openApp(id);
}

function setPill(status) {
  const p = $('#cur-status');
  p.hidden = false;
  p.className = 'pill pill-' + status;
  p.textContent = STATUS_TEXT[status] || status;
}

async function refreshStatus() {
  const r = await api('/api/status');
  if (!r.ok) return;
  S.statuses = r.status || {};
  $$('.app-item').forEach(el => {
    const d = el.querySelector('.dot');
    if (d) d.className = 'dot ' + statusOf(el.dataset.id);
  });
  // 当前应用崩溃/停止时，把状态反映到覆盖层
  const cur = S.currentId && S.statuses[S.currentId];
  if (cur && S.currentId) {
    if (cur.status === 'crashed' || cur.status === 'error') {
      setPill(cur.status);
      showOverlay('应用已崩溃',
        '平台本体和其他应用不受影响，可以单独重启它。' +
        (cur.exit_code != null ? `（退出码 ${cur.exit_code}）` : ''), {
        log: (await api(`/api/apps/${S.currentId}/log`)).log?.join('\n') || cur.error || '',
        actions: [
          { label: '重启应用', cls: 'primary', onClick: () => openApp(S.currentId) },
          { label: '停止', cls: 'ghost', onClick: () => stopCurrent() },
        ],
      });
    } else if (cur.status === 'stopped' && !introVisible() &&
               $('#overlay').classList.contains('hidden')) {
      setPill('stopped');
      showOverlay('应用已停止', '需要时重新启动即可。',
        { actions: [{ label: '重新启动', cls: 'primary', onClick: () => openApp(S.currentId) }] });
    }
  }

  /* 介绍页上也挂着状态徽标与按钮 —— 只在状态真的变了时重绘，
     否则每 3 秒刷一次会把鼠标悬停态和阅读位置冲掉。 */
  if (introVisible() && S.currentId) {
    const st = statusOf(S.currentId);
    if (st !== S._introStatus) {
      renderIntro(appById(S.currentId));
      syncTopbar();
    }
  }
  const stat = $('#platform-stat');
  const running = Object.values(S.statuses).filter(s => s.status === 'running').length;
  stat.textContent = `${running} 个运行中 · :${(S.settings.platform && S.settings.platform.port_base) || ''}`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
}

/* ────────────────────────────── 设置面板 ────────────────────────────── */
function openSettings(tab) {
  fillSettings();
  $('#settings').hidden = false;
  if (tab) switchTab(tab);
}
function closeSettings() { $('#settings').hidden = true; }
function switchTab(name) {
  $$('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  $$('.tabpage').forEach(p => p.classList.toggle('active', p.dataset.page === name));
}

function fillSettings() {
  const p = S.settings.platform || {};
  $('#s-theme').value = p.theme || 'dark';
  $('#s-window').value = p.window_mode || 'auto';
  $('#s-python').value = p.python_path || '';
  $('#s-port').value = p.port_base || 19000;
  $('#s-autostart').checked = !!p.autostart;
  $('#s-autorestart').checked = !!p.auto_restart_on_crash;
  $('#s-closeexit').checked = p.close_exits_platform !== false;

  const hk = p.hotkey || {};
  $('#s-hotkey-en').checked = hk.enabled !== false;
  const mods = hk.modifiers || ['ctrl', 'alt'];
  ['ctrl', 'alt', 'shift', 'win'].forEach(m => { $('#hk-' + m).checked = mods.includes(m); });
  $('#hk-key').value = hk.key || 'S';

  const hint = $('#autostart-hint');
  if (S.sys.autostart_registered) {
    hint.textContent = '已注册：' + (S.sys.autostart_command || '');
  } else if (S.sys.hotkey_supported === false) {
    hint.textContent = '当前系统不是 Windows，开机自启不可用';
  } else {
    hint.textContent = '写入 HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run，不需要管理员权限';
  }
  $('#hotkey-hint').textContent = S.sys.hotkey_supported === false
    ? '全局快捷键仅支持 Windows'
    : '按下后把 StarPort 窗口提到前台';

  renderSysInfo();
  renderAppAdmin();
  renderMaterialGrid();
  renderBgPresets();
  $('#s-blend').checked = appBlendOn();
  $('#s-appmat').checked = appMaterialOn();
}

function renderSysInfo() {
  const s = S.sys || {};
  $('#sys-info').innerHTML = [
    ['Python', `${s.python || '—'}（${s.executable || '—'}）`],
    ['平台根目录', s.root || '—'],
    ['窗口模式', s.window_mode || '—'],
    ['Edge', s.edge || '未找到'],
    ['Chrome', s.chrome || '未找到'],
    ['开机自启', s.autostart_registered ? '已启用' : '未启用'],
  ].map(([k, v]) => `<div><b>${k}：</b>${escapeHtml(String(v))}</div>`).join('');
}

function renderAppAdmin() {
  const box = $('#app-admin');
  box.innerHTML = '';
  if (!S.apps.length) { box.innerHTML = '<div class="empty">暂无应用</div>'; return; }
  S.apps.forEach(app => {
    const row = document.createElement('div');
    row.className = 'admin-item';
    row.innerHTML = `
      <span class="dot ${statusOf(app.id)}"></span>
      <div>
        <div class="admin-name">${escapeHtml(app.name)} <span class="badge">${app.type}</span></div>
        <div class="admin-meta">${escapeHtml(app.id)} · v${escapeHtml(app.version)} · ${escapeHtml(app.category)} · ${escapeHtml(app.dir)}</div>
      </div>`;
    const ops = document.createElement('div');
    ops.className = 'admin-ops';

    const sw = document.createElement('label');
    sw.className = 'switch';
    const cb = document.createElement('input');
    cb.type = 'checkbox'; cb.checked = app.enabled;
    cb.onchange = async () => {
      await post(`/api/apps/${app.id}/enable`, { enabled: cb.checked });
      await reloadApps();
      renderAppAdmin();
    };
    sw.append(cb, document.createTextNode(app.enabled ? '启用' : '禁用'));

    const open = document.createElement('button');
    open.className = 'tbtn'; open.textContent = '打开';
    open.onclick = () => { closeSettings(); openApp(app.id); };

    const del = document.createElement('button');
    del.className = 'danger-btn'; del.textContent = '卸载';
    del.onclick = async () => {
      if (!confirm(`确定卸载「${app.name}」吗？\n\n将删除：${app.dir}`)) return;
      const r = await post(`/api/apps/${app.id}/uninstall`, { remove_files: true });
      if (r.ok) { await reloadApps(); renderAppAdmin(); }
      else alert('卸载失败：' + r.error);
    };

    ops.append(sw, open, del);
    row.appendChild(ops);
    box.appendChild(row);
  });
}

async function saveSettings() {
  const p = {
    theme: $('#s-theme').value,
    window_mode: $('#s-window').value,
    python_path: $('#s-python').value.trim(),
    port_base: parseInt($('#s-port').value, 10) || 19000,
    autostart: $('#s-autostart').checked,
    auto_restart_on_crash: $('#s-autorestart').checked,
    close_exits_platform: $('#s-closeexit').checked,
    hotkey: {
      enabled: $('#s-hotkey-en').checked,
      modifiers: ['ctrl', 'alt', 'shift', 'win'].filter(m => $('#hk-' + m).checked),
      key: ($('#hk-key').value.trim() || 'S').toUpperCase(),
    },
  };
  const r = await post('/api/settings', { patch: { platform: p } });
  const msg = $('#save-msg');
  if (r.ok) {
    S.settings = r.settings;
    applyTheme();
    msg.className = 'save-msg';
    msg.textContent = '已保存';
    setTimeout(() => { msg.textContent = ''; }, 2500);
  } else {
    msg.className = 'save-msg err';
    msg.textContent = '保存失败：' + (r.error || '');
  }
  fillSettings();
}

/* 应用区融合的两项开关（默认都开）。
   注意它们的因果顺序：应用若不透明，材质层会被 iframe 完全盖住 ——
   所以「背景融合」是「材质继承」的前提，关闭后者只在应用透明时看得出效果。 */
function appBlendOn() {
  const p = S.settings.platform || {};
  return p.appBlend !== false;
}
function appMaterialOn() {
  const p = S.settings.platform || {};
  return p.appMaterial !== false;
}

function applyTheme() {
  const p = S.settings.platform || {};
  const root = document.documentElement;
  root.dataset.theme = p.theme || 'dark';
  const mat = p.material || 'liquid-glass';
  root.dataset.material = MATERIALS.some(m => m.id === mat) ? mat : 'liquid-glass';
  applyBackground(p.background || BG_DEFAULT);

  /* 应用区材质：控制 .stage 是否挂 .surface。
     摘掉之后 stage 退化为纯透明，应用区只会露出第 0 层背景（= 只要背景、不要材质）。 */
  const stage = document.querySelector('.stage');
  if (stage) stage.classList.toggle('surface', appMaterialOn());

  pushThemeToApp();
}

/* 把当前主题推给已打开的应用（跨域 iframe 允许 postMessage）。
   应用侧的接收方式见 docs/UI_STANDARD.md —— 这是"平台与第三方应用视觉一致"的通道。 */
function currentTokens() {
  const p = S.settings.platform || {};
  try {
    const cs = getComputedStyle(document.documentElement);
    const pick = (n) => (cs.getPropertyValue(n) || '').trim();
    return {
      '--sp-bg': pick('--bg'),
      '--sp-surface': pick('--solid'),
      '--sp-text': pick('--text'),
      '--sp-text-dim': pick('--text-dim'),
      '--sp-text-faint': pick('--text-faint'),
      '--sp-accent': pick('--accent'),
      '--sp-border': pick('--border'),
      '--sp-panel': pick('--panel'),
      '--sp-radius': pick('--radius-md'),
      '--sp-font': pick('--font'),
      '--sp-material-radius': pick('--mat-radius'),
    };
  } catch (_) {
    return {};
  }
}

function pushThemeToApp() {
  const f = $('#frame');
  if (!f || !f.src || !/^https?:/i.test(f.src)) return;
  try {
    const p = S.settings.platform || {};
    f.contentWindow.postMessage({
      type: 'starport:theme',
      version: 1,
      theme: p.theme || 'dark',
      material: p.material || 'liquid-glass',
      /* 融合开关：应用据此决定"让自身背景透明、透出平台"还是"保持自己的外观" */
      blend: appBlendOn(),
      materialInherit: appMaterialOn(),
      tokens: currentTokens(),
    }, '*');
  } catch (_) {
    /* 应用没监听也无所谓，不影响平台 */
  }
}

/* 打开应用时把主题写进 URL —— 应用可以在首屏渲染前就读到，
   避免"先按默认色渲染再闪一下"的割裂感。

   ⚠️ 这里**不区分 webservice / static**：static 型是站内路径（/_apps/<id>/...），
   以前直接原样返回 → 它首屏读不到 sp-*，只能等 postMessage，比 webservice 型
   慢一拍、且按文档 `if (qs.get('sp-blend') === '1')` 写的应用会永远不透明。
   站内路径用 location.origin 补成绝对地址即可，语义不变。 */
function withThemeParams(rawUrl) {
  if (!rawUrl) return rawUrl;
  try {
    const u = new URL(rawUrl, location.origin);
    if (u.origin !== location.origin && !/^https?:$/i.test(u.protocol)) return rawUrl;
    const p = S.settings.platform || {};
    u.searchParams.set('sp-theme', p.theme || 'dark');
    u.searchParams.set('sp-material', p.material || 'liquid-glass');
    u.searchParams.set('sp-source', 'starport');
    /* 首屏就要能判断要不要透明 —— 否则会先按自己的底画一遍再变透明，闪一下 */
    u.searchParams.set('sp-blend', appBlendOn() ? '1' : '0');
    u.searchParams.set('sp-surface', appMaterialOn() ? '1' : '0');
    return u.toString();
  } catch (_) {
    return rawUrl;
  }
}

/* ──────────────────────  第 0 层：背景（独立接口）  ──────────────────────
   背景与材质完全解耦。材质只靠 backdrop-filter 感知"背后有什么"，
   从不读取背景内容，所以换背景图 / 换背景视频时，材质层零改动、零错位。 */
function applyBackground(spec) {
  const el = $('#stage-bg');
  if (!el) return;
  const bg = spec || BG_DEFAULT;
  el.innerHTML = '';
  el.style.background = '';

  if (bg.type === 'file' && bg.url) {
    if (bg.kind === 'video') {
      const v = document.createElement('video');
      v.src = bg.url;
      v.autoplay = true; v.muted = true; v.loop = true; v.playsInline = true;
      el.appendChild(v);
    } else {
      const img = document.createElement('img');
      img.src = bg.url;
      img.alt = '';
      el.appendChild(img);
    }
    return;
  }

  if (bg.type === 'preset' && bg.value && bg.value !== 'theme') {
    const preset = BG_PRESETS.find(p => p.id === bg.value);
    if (preset && preset.css) el.style.background = preset.css;
  }
  /* 其余情况留空 → 由 CSS 的 var(--stage-bg) 按当前基调渲染 */
}

/* 对外接口：setBackground({type:'preset'|'file', ...})
   调用后材质层与内容层完全不受影响。 */
function setBackground(spec) {
  applyBackground(spec);
  S.settings.platform = S.settings.platform || {};
  S.settings.platform.background = spec;
  /* 刚上传的新素材不在缓存里 → 下次渲染重新拉一次列表 */
  if (spec.type === 'file' && !(BG_FILES || []).some(f => f.file === spec.file)) BG_FILES = null;
  quickSave();
  renderBgPresets();
}

/* 背景选择器：两组 —— 内置预设 + 「我的背景」（历史上传过的素材）。
   以前只把"当前那一个"自定义背景画进列表，一换成预设它就从列表里消失，
   想切回去只能重新挑文件；现在 data/background/ 里的素材一直列着。 */
let BG_FILES = null;          // 素材列表缓存
let BG_SEQ = 0;               // 渲染序号，防止异步结果乱序覆盖

async function loadBgFiles(force) {
  if (BG_FILES && !force) return BG_FILES;
  const r = await api('/api/background/list');
  BG_FILES = r.ok ? (r.items || []) : [];
  return BG_FILES;
}

function currentBg() {
  return (S.settings.platform && S.settings.platform.background) || BG_DEFAULT;
}

function bgIsActive(type, key) {
  const cur = currentBg();
  if (type === 'preset') return cur.type === 'preset' && cur.value === key;
  return cur.type === 'file' && (cur.file === key || cur.url === key);
}

function bgThumb(url, kind) {
  if (kind === 'video') {
    const v = document.createElement('video');
    v.src = url; v.muted = true; v.autoplay = true; v.loop = true;
    v.setAttribute('playsinline', '');
    return v;
  }
  const i = document.createElement('img');
  i.src = url; i.alt = '';
  return i;
}

function bgGroup(title, count) {
  const g = document.createElement('div');
  g.className = 'bg-group';
  const t = document.createElement('div');
  t.className = 'bg-group-title';
  t.innerHTML = title + (count == null ? '' : ` <span class="count">${count}</span>`);
  const row = document.createElement('div');
  row.className = 'bg-presets';
  g.append(t, row);
  return { g, row };
}

async function renderBgPresets() {
  const box = $('#bg-presets');
  if (!box) return;
  const seq = ++BG_SEQ;
  box.innerHTML = '<span class="bg-empty">读取背景素材…</span>';
  const files = await loadBgFiles();
  if (seq !== BG_SEQ) return;              // 已有更新的一次渲染，丢弃本次

  box.innerHTML = '';

  /* 1) 内置预设 */
  const g1 = bgGroup('内置背景');
  BG_PRESETS.forEach(p => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'bg-item' + (bgIsActive('preset', p.id) ? ' active' : '');
    b.title = p.name;
    b.style.background = p.css || 'var(--stage-bg)';
    b.onclick = () => setBackground({ type: 'preset', value: p.id });
    g1.row.appendChild(b);
  });
  box.appendChild(g1.g);

  /* 2) 我的背景：历史素材常驻，随时切回 */
  const g2 = bgGroup('我的背景', files.length);
  if (!files.length) {
    const e = document.createElement('span');
    e.className = 'bg-empty';
    e.textContent = '还没上传过背景图 / 视频';
    g2.row.appendChild(e);
  }
  files.forEach(f => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'bg-item' + (bgIsActive('file', f.file) ? ' active' : '');
    b.title = f.file + (f.kind === 'video' ? '（视频）' : '');
    b.appendChild(bgThumb(f.url, f.kind));
    if (f.kind === 'video') {
      const tag = document.createElement('span');
      tag.className = 'bg-tag'; tag.textContent = '视频';
      b.appendChild(tag);
    }
    b.onclick = () => setBackground({ type: 'file', url: f.url, file: f.file, kind: f.kind });

    const del = document.createElement('button');
    del.type = 'button'; del.className = 'bg-del'; del.textContent = '✕';
    del.title = '从素材库里删除这个文件';
    del.onclick = async (e) => {
      e.stopPropagation();
      if (!confirm(`确定删除背景素材「${f.file}」吗？\n\n` +
                   `文件将从 data/background/ 中移除，不可恢复。`)) return;
      const r = await post('/api/background/delete', { file: f.file });
      if (!r.ok) { alert('删除失败：' + (r.error || '')); return; }
      if (f.file === (currentBg().file || '')) setBackground(BG_DEFAULT);
      BG_FILES = null;
      renderBgPresets();
    };
    b.appendChild(del);
    g2.row.appendChild(b);
  });
  box.appendChild(g2.g);
}

function renderMaterialGrid() {
  const box = $('#material-grid');
  if (!box) return;
  const cur = (S.settings.platform && S.settings.platform.material) || 'liquid-glass';
  box.innerHTML = '';
  MATERIALS.forEach(m => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'material-item' + (m.id === cur ? ' active' : '');
    /* 色块自己挂 data-material，直接继承那套材质的变量 —— 等于活体预览，
       加第 11 套材质时这里不需要改一行代码。 */
    b.innerHTML =
      '<div class="material-swatch" data-material="' + m.id + '"></div>' +
      '<div class="material-name">' + m.name + '</div>' +
      '<div class="material-en">' + m.en + '</div>';
    b.onclick = () => {
      S.settings.platform = S.settings.platform || {};
      S.settings.platform.material = m.id;
      applyTheme();                 // 即时生效，不等"保存并应用"
      quickSave();
      renderMaterialGrid();
    };
    box.appendChild(b);
  });
}

/* 视觉类设置的即时落盘（材质/背景/基调），不走底部的保存按钮 */
async function quickSave() {
  if (window.__SP_PREVIEW__) return;     // URL 预览模式下不污染真实配置
  try {
    await post('/api/settings', { patch: { platform: S.settings.platform || {} } });
  } catch (_) {
    /* 保存失败不影响当前会话的视觉，静默即可 */
  }
}

/* ────────────────────────────── 配置导入导出 ────────────────────────────── */
function doExport() {
  const a = document.createElement('a');
  a.href = '/api/config/export';
  a.download = 'starport-config.json';
  a.click();
}
async function doImport(file) {
  try {
    const payload = JSON.parse(await file.text());
    const r = await post('/api/config/import', { payload, merge: true });
    if (!r.ok) throw new Error(r.error);
    await boot(false);
    alert('导入完成');
  } catch (e) { alert('导入失败：' + e.message); }
}

/* ────────────────────────────── 安装应用 ────────────────────────────── */
async function doInstall() {
  const source = $('#inst-source').value.trim();
  const manifest = $('#inst-manifest').value.trim();
  const msg = $('#install-msg');
  if (!source && !manifest) { msg.className = 'inline-msg err'; msg.textContent = '填路径或 manifest'; return; }
  const r = await post('/api/apps/install', { source: source || null, manifest: manifest || null });
  if (r.ok) {
    msg.className = 'inline-msg';
    msg.textContent = `已安装：${r.id}`;
    $('#inst-source').value = ''; $('#inst-manifest').value = '';
    await reloadApps(); renderAppAdmin(); renderNav();
  } else {
    msg.className = 'inline-msg err';
    msg.textContent = '安装失败：' + r.error;
  }
}
async function reloadApps() {
  const r = await api('/api/apps');
  if (r.ok) S.apps = r.apps;
  const st = await api('/api/state');
  if (st.ok) S.state = st.state;
}

/* ────────────────────────────── 启动 ────────────────────────────── */
async function boot(autoLaunch = true) {
  const r = await api('/api/bootstrap');
  if (!r.ok) {
    showOverlay('无法连接平台', escapeHtml(r.error || ''));
    return;
  }
  S.apps = r.apps || [];
  S.settings = r.settings || { platform: {} };
  S.state = r.state || S.state;

  /* URL 参数预览：?sp-theme=light&sp-material=acrylic
     仅供预览与自动化截图使用，不回写配置。
     这套参数名同时也是平台向应用传递主题的约定（见 docs/UI_STANDARD.md），
     平台与壳用同一套命名，避免两套标准。 */
  const qs = new URLSearchParams(location.search);
  const qTheme = qs.get('sp-theme');
  const qMat = qs.get('sp-material');
  if (qTheme) S.settings.platform.theme = qTheme;
  if (qMat) S.settings.platform.material = qMat;
  window.__SP_PREVIEW__ = !!(qTheme || qMat);

  applyTheme();
  const sys = await api('/api/system');
  if (sys.ok) S.sys = sys.system || {};

  renderNav();
  refreshStatus();
  setInterval(refreshStatus, 3000);
  setInterval(() => api('/api/heartbeat').catch(() => {}), 10000);
  api('/api/heartbeat').catch(() => {});

  if (autoLaunch && S.state.last_active && appById(S.state.last_active)) {
    openApp(S.state.last_active);
  }
}

function bind() {
  $('#search').addEventListener('input', (e) => { S.filter = e.target.value; renderNav(); });
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault(); $('#search').focus(); $('#search').select();
    }
    if (e.key === 'Escape' && !$('#settings').hidden) closeSettings();
  });

  $('#btn-settings').onclick = () => openSettings();
  $('#btn-restart').onclick = restartCurrent;
  $('#btn-stop').onclick = stopCurrent;

  $$('.tab').forEach(t => t.onclick = () => switchTab(t.dataset.tab));
  $$('[data-close]').forEach(el => el.onclick = closeSettings);
  $('#btn-save').onclick = saveSettings;

  $('#btn-export').onclick = doExport;
  $('#btn-import').onclick = () => $('#file-import').click();
  $('#file-import').onchange = (e) => {
    if (e.target.files[0]) doImport(e.target.files[0]);
    e.target.value = '';
  };
  $('#btn-install').onclick = doInstall;
  $('#btn-reload').onclick = async () => { await reloadApps(); renderNav(); renderAppAdmin(); };

  /* ---- 应用区融合开关：即时生效并推给已打开的应用 ---- */
  $('#s-blend').onchange = (e) => {
    S.settings.platform = S.settings.platform || {};
    S.settings.platform.appBlend = e.target.checked;
    /* 刻意不重载 iframe：重载会丢掉用户在应用里的操作状态。
       改为靠 postMessage 让应用自己切换（见 UI_STANDARD），应用没实现监听则
       下次打开该应用时才生效 —— 这是可接受的降级，不该用"打断用户"来兜底。 */
    applyTheme();
    quickSave();
  };
  $('#s-appmat').onchange = (e) => {
    S.settings.platform = S.settings.platform || {};
    S.settings.platform.appMaterial = e.target.checked;
    applyTheme();
    quickSave();
  };

  /* ---- 背景：本地文件 → 交给平台托管（前端不直接读本地路径） ---- */
  $('#btn-bg-file').onclick = () => $('#bg-file').click();
  $('#btn-bg-reset').onclick = () => setBackground(BG_DEFAULT);
  $('#bg-file').onchange = async (e) => {
    const f = e.target.files && e.target.files[0];
    e.target.value = '';
    if (!f) return;
    if (f.size > 40 * 1024 * 1024) { alert('文件超过 40MB 上限'); return; }
    try {
      const bytes = new Uint8Array(await f.arrayBuffer());
      let bin = '';
      const CH = 0x8000;                       // 分块避免参数过多爆栈
      for (let i = 0; i < bytes.length; i += CH) {
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
      }
      const r = await post('/api/background/upload',
                           { filename: f.name, data: btoa(bin) });
      if (!r.ok) { alert('背景设置失败：' + (r.error || '')); return; }
      setBackground({
        type: 'file', url: r.url, file: r.file,
        kind: /\.(mp4|webm|mov|m4v)$/i.test(f.name) ? 'video' : 'image',
      });
    } catch (err) {
      alert('背景设置失败：' + err.message);
    }
  };

  $('#frame').addEventListener('load', () => {
    if ($('#frame').src) { hideOverlay(); pushThemeToApp(); }
  });

  window.addEventListener('beforeunload', () => {
    const close = (S.settings.platform || {}).close_exits_platform !== false;
    if (close) navigator.sendBeacon('/api/platform/shutdown');
  });
}

bind();
boot(true);
