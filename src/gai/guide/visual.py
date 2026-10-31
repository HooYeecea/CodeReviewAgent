"""Self-contained graphical guide, sharing the existing page's theme and language."""

VISUAL_CSS = r"""
  [hidden] { display: none !important; }
  .guide-modes { display: grid; gap: 6px; margin-bottom: 24px; }
  .guide-modes a { padding: 11px 12px; border: 1px solid var(--line); border-radius: 9px; color: var(--muted); text-decoration: none; font-size: 13px; }
  .guide-modes a[aria-current="page"] { color: var(--teal); background: var(--teal-soft); border-color: var(--teal); }
  body[data-guide-view="visual"] .shell { max-width: 1440px; grid-template-columns: 226px minmax(0, 1fr); gap: 32px; }
  body[data-guide-view="visual"] .top-inner { max-width: 1440px; }
  #visual-nav input { width: 100%; box-sizing: border-box; padding: 11px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--ink); font: inherit; font-size: 12px; }
  .v-group { margin: 20px 0 8px; color: var(--muted); font-size: 11px; letter-spacing: .04em; }
  .v-nav-link { display: block; padding: 8px 10px; margin: 2px 0; border-radius: 6px; text-decoration: none; color: var(--ink-soft); font: 12px var(--mono); overflow-wrap: anywhere; }
  .v-nav-link.child { padding-left: 24px; }
  .v-nav-link[aria-current="page"] { background: var(--teal-soft); color: var(--teal); box-shadow: inset 3px 0 var(--teal); }
  .v-nav-link:hover { background: var(--surface-hover); }
  .v-eyebrow { color: var(--teal); font: 11px var(--mono); letter-spacing: .14em; margin: 0 0 12px; }
  .v-hero h1 { font-size: clamp(26px, 3vw, 38px); letter-spacing: -.04em; margin: 0 0 12px; line-height: 1.3; }
  .v-hero p { color: var(--muted); font-size: 13px; line-height: 1.8; margin: 0; }
  .v-shortcuts { display: flex; flex-wrap: wrap; gap: 8px; margin: 22px 0 28px; }
  .v-chip { border: 1px solid var(--line); border-radius: 99px; padding: 8px 13px; font-size: 12px; color: var(--ink-soft); background: var(--surface); text-decoration: none; }
  .v-chip:hover { border-color: var(--teal); color: var(--teal); }
  .v-board { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 28px; }
  .v-breadcrumb { display: flex; flex-wrap: wrap; gap: 8px; font: 12px var(--mono); color: var(--muted); margin-bottom: 14px; }
  .v-breadcrumb a { color: var(--teal); }
  .v-command { font: 600 clamp(22px, 3vw, 32px) var(--mono); margin: 0 0 9px; overflow-wrap: anywhere; }
  .v-description { color: var(--muted); font-size: 13px; line-height: 1.8; margin: 0; }
  .v-caption { display: flex; justify-content: space-between; gap: 12px; margin: 30px 0 15px; font-size: 11px; color: var(--muted); }
  .v-caption strong { color: var(--ink); font-size: 13px; }
  .v-flow { display: grid; grid-template-columns: repeat(var(--step-count), minmax(0, 1fr)); list-style: none; gap: 22px; margin: 0; padding: 0; }
  .v-flow li { position: relative; min-width: 0; }
  .v-flow li:not(:last-child)::after { content: '→'; position: absolute; right: -17px; top: 30px; color: var(--muted); }
  .v-step { width: 100%; min-height: 102px; padding: 14px 11px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface-2); color: var(--ink-soft); cursor: pointer; text-align: left; font: inherit; }
  .v-step[aria-pressed="true"] { background: var(--teal-soft); border-color: var(--teal); color: var(--teal); }
  .v-step span { display: block; font: 11px var(--mono); opacity: .8; margin-bottom: 14px; }
  .v-step strong { font-size: 12px; line-height: 1.5; }
  .v-step-detail { margin-top: 16px; padding: 16px 18px; border-left: 3px solid var(--teal); background: var(--surface-2); border-radius: 0 8px 8px 0; font-size: 13px; line-height: 1.9; color: var(--ink-soft); }
  .v-step-detail p { margin: 4px 0 0; }
  .v-repeat { margin: 12px 0 0; text-align: center; color: var(--teal); font-size: 12px; }
  .v-recovery { margin-top: 24px; border-top: 1px dashed var(--line); padding-top: 18px; display: flex; flex-wrap: wrap; align-items: center; gap: 10px; font-size: 12px; color: var(--muted); }
  .v-recovery a { color: var(--teal); text-decoration: none; }
  .v-columns { display: grid; grid-template-columns: minmax(0, .95fr) minmax(0, 1.05fr); gap: 22px; margin-top: 24px; align-items: start; }
  .v-panel { border: 1px solid var(--line); border-radius: 12px; padding: 22px; background: var(--surface); min-width: 0; margin: 0; animation: none; }
  #visual-examples { scroll-margin-top: 90px; }
  .v-panel h3 { margin: 0 0 8px; font-size: 15px; }
  .v-panel .v-note { color: var(--muted); font-size: 12px; line-height: 1.7; margin: 0 0 16px; }
  .v-param { padding: 13px 0; border-top: 1px solid var(--line); }
  .v-param code { color: var(--teal); font: 12px var(--mono); overflow-wrap: anywhere; }
  .v-param p { color: var(--muted); font-size: 12px; line-height: 1.8; margin: 5px 0 0; }
  .v-badge { display: inline-block; margin-left: 8px; font-size: 10px; color: var(--muted); }
  .v-example { border-top: 1px solid var(--line); padding: 15px 0; }
  .v-example p { font-size: 12px; color: var(--ink-soft); margin: 0 0 9px; line-height: 1.6; }
  .v-code { display: flex; gap: 10px; align-items: flex-start; background: var(--surface-2); border: 1px solid var(--line); border-radius: 8px; padding: 12px; }
  .v-code code { flex: 1; min-width: 0; font: 12px/1.8 var(--mono); color: var(--ink); overflow-wrap: anywhere; user-select: all; }
  .v-copy { border: 1px solid var(--line); border-radius: 5px; color: var(--teal); background: var(--surface); padding: 5px 7px; cursor: pointer; flex-shrink: 0; font: 11px var(--font); }
  .v-children { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }
  #visual-guide :focus-visible, #visual-nav :focus-visible, .guide-modes :focus-visible { outline: 3px solid var(--teal); outline-offset: 3px; }
  #visual-guide { scroll-margin-top: 80px; }
  @media (max-width: 1100px) { .v-columns { grid-template-columns: 1fr; } .v-flow { gap: 16px; } .v-flow li:not(:last-child)::after { right: -14px; } }
  @media (max-width: 780px) {
    body[data-guide-view="visual"] .shell { grid-template-columns: 1fr; gap: 22px; }
    #visual-nav-list { max-height: 190px; overflow: auto; }
    .guide-modes { grid-template-columns: 1fr 1fr; margin-bottom: 14px; }
    .v-board, .v-panel { padding: 18px; }
    .v-flow { grid-template-columns: 1fr; gap: 20px; }
    .v-step { min-height: 0; display: flex; align-items: center; gap: 16px; }
    .v-step span { margin: 0; }
    .v-flow li:not(:last-child)::after { content: '↓'; top: auto; bottom: -19px; right: auto; left: 23px; }
    .v-caption { flex-wrap: wrap; }
  }
"""

VISUAL_NAV = """
      <div class="guide-modes" aria-label="Guide view">
        <a id="mode-classic" href="#overview">文字指南</a>
        <a id="mode-visual" href="#visual">图形化指南</a>
      </div>
      <nav id="visual-nav" hidden aria-label="Commands">
        <input type="search" id="visual-search" autocomplete="off" />
        <div id="visual-search-status" role="status"></div>
        <div id="visual-nav-list"></div>
      </nav>
"""

VISUAL_HTML = """
      <div id="visual-guide" hidden>
        <div class="v-hero">
          <div class="v-eyebrow">GAI / COMMAND MAP</div>
          <h1 id="visual-title"></h1>
          <p id="visual-intro"></p>
        </div>
        <div class="v-shortcuts" id="visual-shortcuts"></div>
        <div class="v-board" id="visual-board"></div>
        <div class="v-columns">
          <section class="v-panel" id="visual-parameters"></section>
          <section class="v-panel" id="visual-examples"></section>
        </div>
      </div>
"""

# Inserted inside the page's existing IIFE; theme, copy and language stay shared.
VISUAL_JS = r"""
  const catalog = DATA.catalog;
  let visualId = 'splitflow';
  let visualStep = 0;
  const vSearch = document.getElementById('visual-search');
  const vText = (cn, en) => lang === 'cn' ? cn : en;
  const localized = value => value[lang] || value.en || '';
  const visualURL = id => '#visual/' + id.split(' ').map(encodeURIComponent).join('/');
  function vElement(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function vLink(id, label, className = 'v-chip') {
    const link = vElement('a', className, label || 'gai ' + id);
    link.href = visualURL(id);
    return link;
  }
  function renderVisualNav() {
    const list = document.getElementById('visual-nav-list');
    list.replaceChildren();
    const query = vSearch.value.trim().toLowerCase();
    let count = 0;
    for (const group of catalog.groups) {
      const matches = catalog.commands.filter(c => c.group === group.id &&
        (!query || JSON.stringify([c.id, c.title, c.description, c.options, c.arguments]).toLowerCase().includes(query)));
      if (!matches.length) continue;
      list.append(vElement('h2', 'v-group', localized(group)));
      for (const cmd of matches) {
        const link = vLink(cmd.id, cmd.id, 'v-nav-link' + (cmd.parent ? ' child' : ''));
        if (cmd.id === visualId) link.setAttribute('aria-current', 'page');
        list.append(link);
        count++;
      }
    }
    document.getElementById('visual-search-status').textContent = query ?
      (count ? vText(count + ' 个匹配命令', count + ' matching commands') : vText('没有匹配命令，请尝试其他关键词。', 'No matching commands. Try another keyword.')) : '';
  }
  function renderVisual() {
    document.getElementById('mode-classic').textContent = vText('文字指南', 'Text guide');
    document.getElementById('mode-visual').textContent = vText('图形化指南', 'Visual guide');
    document.querySelector('.guide-modes').setAttribute('aria-label', vText('指南视图', 'Guide view'));
    document.getElementById('visual-nav').setAttribute('aria-label', vText('命令导航', 'Command navigation'));
    vSearch.placeholder = vText('搜索命令、用途或参数 /', 'Find commands or flags /');
    vSearch.setAttribute('aria-label', vText('搜索图形化命令指南', 'Search visual command guide'));
    document.getElementById('visual-title').textContent = vText('找到命令，看懂下一步。', 'Find a command. See what comes next.');
    document.getElementById('visual-intro').textContent = vText(
      catalog.commands.length + ' 个命令入口 · 点选流程节点了解用法，再复制示例到终端运行。',
      catalog.commands.length + ' command entries · Explore the steps, then copy an example to your terminal.');
    const shortcuts = document.getElementById('visual-shortcuts');
    shortcuts.replaceChildren();
    for (const [id, cn, en] of [['devflow','日常开发','Daily development'], ['splitflow','分批提交','Split commits'], ['flow status','中断恢复','Resume a flow'], ['log','浏览历史','Explore history']]) {
      shortcuts.append(vLink(id, vText(cn, en) + ' ↗'));
    }
    renderVisualNav();
    renderVisualCommand();
  }
  function renderVisualCommand() {
    const cmd = catalog.commands.find(c => c.id === visualId) || catalog.commands[0];
    const board = document.getElementById('visual-board');
    board.replaceChildren();
    const breadcrumb = vElement('div', 'v-breadcrumb');
    breadcrumb.append(vElement('span', '', 'gai'), vElement('span', '', '/'));
    if (cmd.parent) breadcrumb.append(vLink(cmd.parent, cmd.parent, ''), vElement('span', '', '/'));
    breadcrumb.append(vElement('span', '', cmd.id.split(' ').at(-1)));
    board.append(breadcrumb, vElement('h2', 'v-command', 'gai ' + cmd.id), vElement('p', 'v-description', localized(cmd.description)));
    const caption = vElement('div', 'v-caption');
    caption.append(vElement('strong', '', vText('操作流程', 'How it works')), vElement('span', '', vText('点击节点查看说明 · 用法示意', 'Select a step · Usage illustration')));
    board.append(caption);
    const flow = vElement('ol', 'v-flow');
    flow.style.setProperty('--step-count', cmd.steps.length);
    const detail = vElement('div', 'v-step-detail');
    detail.id = 'visual-step-detail';
    detail.setAttribute('aria-live', 'polite');
    visualStep = Math.min(visualStep, cmd.steps.length - 1);
    function selectStep(index) {
      visualStep = index;
      flow.querySelectorAll('button').forEach((b, i) => b.setAttribute('aria-pressed', String(i === index)));
      detail.replaceChildren(vElement('strong', '', localized(cmd.steps[index].title)), vElement('p', '', localized(cmd.steps[index].body)));
    }
    cmd.steps.forEach((step, i) => {
      const item = vElement('li');
      const button = vElement('button', 'v-step');
      button.type = 'button';
      button.setAttribute('aria-controls', detail.id);
      button.append(vElement('span', '', String(i + 1).padStart(2, '0')), vElement('strong', '', localized(step.title)));
      button.addEventListener('click', () => selectStep(i));
      item.append(button); flow.append(item);
    });
    board.append(flow, detail);
    selectStep(visualStep);
    if (cmd.id === 'splitflow') board.append(vElement('p', 'v-repeat', vText('↶ 暂存 → 审查 → 提交：逐批重复，最后统一推送', '↶ Stage → review → commit for each batch, then push once')));
    if (cmd.children.length) {
      const children = vElement('div', 'v-children');
      cmd.children.forEach(id => children.append(vLink(id)));
      board.append(children);
    }
    if (['splitflow', 'devflow'].includes(cmd.id)) {
      const recovery = vElement('div', 'v-recovery');
      recovery.append(vElement('span', '', vText('流程中断？', 'Interrupted?')), vLink('flow status', vText('检查恢复状态', 'Check recovery'), ''), vElement('span', '', '→'));
      const resume = vElement('a', '', 'gai ' + cmd.id + ' --resume');
      resume.href = '#visual-examples';
      resume.addEventListener('click', e => { e.preventDefault(); const target = document.getElementById('visual-examples'); target.scrollIntoView({block:'start'}); target.tabIndex = -1; target.focus({preventScroll:true}); });
      recovery.append(resume); board.append(recovery);
    }
    const parameters = document.getElementById('visual-parameters');
    parameters.replaceChildren(vElement('h3', '', vText('参数与选项', 'Arguments & options')), vElement('p', 'v-note', vText('必填项已标记；选项可按需要组合。', 'Required inputs are marked; combine options as needed.')));
    for (const [rows, isArgument] of [[cmd.arguments, true], [cmd.options, false]]) {
      for (const row of rows) {
        const item = vElement('div', 'v-param');
        const label = isArgument ? '<' + row.name + '>' : row.flags.join(', ');
        item.append(vElement('code', '', label + (!isArgument && !row.flag ? ' <value>' : '')));
        item.append(vElement('span', 'v-badge', row.required ? vText('必填', 'Required') : vText('可选', 'Optional')));
        item.append(vElement('p', '', localized(row.help) || vText('详见命令 --help。', 'See command --help.')));
        parameters.append(item);
      }
    }
    if (!cmd.arguments.length && !cmd.options.length) parameters.append(vElement('p', 'v-note', vText('选择一个子命令继续。', 'Choose a subcommand to continue.')));
    const examples = document.getElementById('visual-examples');
    examples.replaceChildren(vElement('h3', '', vText('用法示例', 'Try an example')), vElement('p', 'v-note', vText('复制后在终端运行；替换示例中的路径和分支名。', 'Copy to your terminal; replace sample paths and branch names.')));
    for (const example of cmd.examples) {
      const item = vElement('div', 'v-example');
      const code = vElement('div', 'v-code');
      const text = vElement('code', '', example.command);
      const copy = vElement('button', 'v-copy', vText('复制', 'Copy'));
      copy.type = 'button';
      copy.setAttribute('aria-label', vText('复制命令：', 'Copy command: ') + example.command);
      copy.addEventListener('click', async () => {
        try { await copyText(example.command); showToast(vText('已复制', 'Copied')); }
        catch (_) {
          const selection = window.getSelection(); const range = document.createRange(); range.selectNodeContents(text); selection.removeAllRanges(); selection.addRange(range);
          showToast(vText('请按 Ctrl+C / ⌘C 复制选中内容', 'Press Ctrl+C / ⌘C to copy the selection'));
        }
      });
      code.append(text, copy); item.append(vElement('p', '', localized(example.description)), code); examples.append(item);
    }
  }
  function applyVisualHash() {
    const hash = location.hash.slice(1);
    const visual = hash === 'visual' || hash.startsWith('visual/');
    document.body.dataset.guideView = visual ? 'visual' : 'classic';
    document.getElementById('classic-guide').hidden = visual;
    document.getElementById('side-nav').hidden = visual;
    document.querySelector('.nav-label').hidden = visual;
    document.getElementById('visual-guide').hidden = !visual;
    document.getElementById('visual-nav').hidden = !visual;
    for (const mode of ['visual', 'classic']) {
      const link = document.getElementById('mode-' + mode);
      if ((mode === 'visual') === visual) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    }
    if (!visual) return false;
    if (openId) closeDrawer({clearHash:false});
    let requested = '';
    try { requested = hash.split('/').slice(1).map(decodeURIComponent).join(' '); } catch (_) {}
    if (catalog.commands.some(c => c.id === requested) && requested !== visualId) { visualId = requested; visualStep = 0; }
    renderVisual();
    return true;
  }
  vSearch.addEventListener('input', renderVisualNav);
"""
