/**
 * 右侧面板开关：常驻标题栏 + 显示/隐藏（Cursor 风格）
 *   cd backend && node _test_right_panel_toggle.js
 *
 * 要钉住的核心是"面板关了之后还能再打开"——原来那个 ✕ 只存在于面板自己的
 * 工具栏里，点完连按钮一起消失，用户只能绕道点工单/AI 才能把面板叫回来。
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const norm = s => s.replace(/\r\n/g, '\n');
const app = norm(fs.readFileSync(path.join(ROOT, 'frontend/app.js'), 'utf8'));
const html = norm(fs.readFileSync(path.join(ROOT, 'frontend/index.html'), 'utf8'));
const css = norm(fs.readFileSync(path.join(ROOT, 'frontend/styles.css'), 'utf8'));

let pass = 0, fail = 0;
function check(name, cond, detail = '') {
    if (cond) { pass++; console.log(`[OK] ${name}${detail ? ' -- ' + detail : ''}`); }
    else { fail++; console.log(`[FAIL] ${name}${detail ? ' -- ' + detail : ''}`); }
}

// ── 1. 标题栏里那个是常驻的 ──────────────────────────────────────
const tabbar = html.slice(html.indexOf('id="mainWsTabBar"'), html.indexOf('id="mainWsHost"'));
check('开关在主舞台标题栏里（面板关了也还在）', /id="mainWsRightToggle"/.test(tabbar));
check('标题栏的开关调 adsShell.toggleRight()',
    /id="mainWsRightToggle"[\s\S]{0,200}onclick="adsShell\.toggleRight\(\)"/.test(html));
// 图标要是 Cursor 那种"右半边实心的面板方框"，不是 ✕
check('用的是面板方框图标而不是文字符号',
    /id="mainWsRightToggle"[\s\S]{0,400}<svg[\s\S]{0,400}<rect/.test(html));
check('图标右半边实心（表示右侧面板那一侧）',
    /id="mainWsRightToggle"[\s\S]{0,700}<path[^>]*fill="currentColor"/.test(html));

// ── 2. 面板工具栏里的 ✕ 换成同一个开关 ───────────────────────────
const rwToolbar = html.slice(html.indexOf('id="rwToolbar"'), html.indexOf('id="rwBody"'));
check('面板工具栏里也有一个开关', /id="rwToggleBtn"/.test(rwToolbar));
check('面板里的开关走同一个 toggleRight',
    /id="rwToggleBtn"[\s\S]{0,200}onclick="adsShell\.toggleRight\(\)"/.test(html));
// 老的 ✕ 只会关不会开，必须没了
check('旧的 rwCloseBtn（✕）已移除', !/rwCloseBtn/.test(html) && !/rwCloseBtn/.test(app));
check('工具栏里不再有裸的 ✕ 按钮', !/>✕<\/button>/.test(rwToolbar));
check('分屏按钮保留', /id="rwSplitBtn"/.test(rwToolbar));
// 标题栏 + 面板工具栏这两个（顶栏那个在第 7 节单独数）
check('项目内两个开关共用一个 class',
    /id="mainWsRightToggle"/.test(html) && /id="rwToggleBtn"/.test(html)
    && /class="[^"]*ws-right-toggle[^"]*" id="mainWsRightToggle"/.test(html)
    && /class="[^"]*ws-right-toggle[^"]*" id="rwToggleBtn"/.test(html));

// ── 3. toggleRight 的行为 ───────────────────────────────────────
const tr = app.slice(app.indexOf('function toggleRight()'), app.indexOf('function _syncRightToggleBtns'));
check('toggleRight 存在', tr.length > 0);
check('开着就关', /if \(state\.rightOpen\) \{\s*\n\s*closeRight\(\{ persist: true \}\)/.test(tr));
check('关着就开', /\} else \{\s*\n\s*openRight\(\{/.test(tr));
// 恢复上次的 Tab 和分屏状态，而不是每次都跳回工单
check('重新打开时恢复上次的 Tab', /tab: state\.rightTab \|\| 'ticket'/.test(tr));
check('重新打开时恢复上次的分屏状态', /split: state\.rightMode === 'split'/.test(tr));
check('收起状态要持久化（刷新后仍是收起的）', /persist: true/.test(tr));
check('toggleRight 挂到 adsShell 上（onclick 要够得着）',
    /^\s*toggleRight,$/m.test(app));

// ── 4. 两个按钮的状态同步 ───────────────────────────────────────
const sync = app.slice(app.indexOf('function _syncRightToggleBtns'),
                       app.indexOf('function toggleRightSplit'));
check('同步函数同时管两个按钮',
    /\['mainWsRightToggle', 'rwToggleBtn'\]/.test(sync));
check('同步 aria-expanded', /setAttribute\('aria-expanded'/.test(sync));
check('同步 title（显示/隐藏文案要跟着变）',
    /'隐藏右侧面板' : '显示右侧面板'/.test(sync));
// openRight/closeRight 也可能从别处被调用（点工单、点 AI、退出全屏），
// 不在那里同步的话按钮状态会和面板对不上
check('openRight 里同步按钮状态',
    /function openRight[\s\S]{0,1400}_syncRightToggleBtns\(\)/.test(app));
check('closeRight 里同步按钮状态',
    /function closeRight[\s\S]{0,1200}_syncRightToggleBtns\(\)/.test(app));
check('进入项目时同步一次（恢复上次开关状态）',
    /_applySidebarToLayout\(\);\s*\n\s*_syncRightToggleBtns\(\);/.test(app));

// ── 5. CSS：两个位置不能同时出现 ────────────────────────────────
check('.ws-right-toggle 有样式', /^\.ws-right-toggle \{/m.test(css));
// 面板开着时，标题栏和面板工具栏在同一视觉行上，两个都显示会像两个不同功能
check('面板打开时隐藏标题栏那个',
    /\.project-layout\.right-open #mainWsRightToggle \{[\s\S]{0,60}display: none/.test(css));
check('非项目壳层（列表页）不显示开关',
    /body:not\(\.shell-project\) #mainWsRightToggle \{[\s\S]{0,60}display: none/.test(css));
check('开关钉在标题栏最右', /#mainWsRightToggle \{[\s\S]{0,60}margin-left: auto/.test(css));
check('开关不被 flex 压缩', /\.ws-right-toggle \{[\s\S]{0,300}flex-shrink: 0/.test(css));
// 原来 .main-ws-tabbar 整条 overflow-x:auto，文档 Tab 一多就把开关滚出视区
check('滚动条移到 .main-ws-tabs 上（开关不跟着滚走）',
    /\.main-ws-tabbar \{[\s\S]{0,420}overflow: hidden/.test(css)
    && /\.main-ws-tabs \{[\s\S]{0,200}overflow-x: auto/.test(css));
check('.main-ws-tabs 占满中间空间', /\.main-ws-tabs \{[\s\S]{0,200}flex: 1/.test(css));
check('开着时有高亮态', /\.ws-right-toggle\.active \{/.test(css));

// ── 6. 顶栏那个「💬 AI 助手」按钮已被这个开关取代 ────────────────
// 项目内它和 ws-right-toggle 是同一件事（都开右侧对话），留着是两个入口两种行为
check('顶栏 chatToggleBtn 已移除', !/chatToggleBtn/.test(html));
check('顶栏没有残留的「💬 AI 助手」文案', !/💬 AI 助手/.test(html));
// 三处 getElementById('chatToggleBtn') 都是 ?. 空安全的，删元素不会报错，
// 但留着就是死代码 —— 一起清掉
check('app.js 里没有 chatToggleBtn 的死查询', !/chatToggleBtn/.test(app));
check('styles.css 里没有 .chat-toggle-btn 的死样式', !/chat-toggle-btn/.test(css));
// toggleChatPanel 本身还有 5 个程序化调用方（定位消息、新建项目后自动开、
// 工单评论定位…），函数必须留着
check('toggleChatPanel 函数保留', /function toggleChatPanel\(\)/.test(app));
check('toggleChatPanel 仍有其他调用方',
    (app.match(/[^n] toggleChatPanel\(\)|= toggleChatPanel\(\)|\) toggleChatPanel\(\)/g) || []).length > 0
    || (app.match(/toggleChatPanel\(\);/g) || []).length >= 4);

// ── 7. 列表页（全局）也要有同一个开关 ───────────────────────────
// 项目内是 mainWsRightToggle，列表页没有右侧工作台，AI 走 fixed 面板，
// 但用户看到的应该是同一个按钮在同一个位置
const topbar = html.slice(html.indexOf('<div class="top-bar-right">'), html.indexOf('</header>'));
check('顶栏有 AI 面板开关', /id="topbarChatToggle"/.test(topbar));
check('顶栏开关调 toggleChatPanel', /id="topbarChatToggle"[\s\S]{0,200}onclick="toggleChatPanel\(\)"/.test(topbar));
check('顶栏开关和项目内那个用同一个 class',
    /class="[^"]*ws-right-toggle[^"]*" id="topbarChatToggle"/.test(topbar));
check('顶栏开关用同一个面板方框 SVG（不是 emoji）',
    /id="topbarChatToggle"[\s\S]{0,500}<rect[\s\S]{0,300}<path[^>]*fill="currentColor"/.test(topbar)
    && !/💬/.test(topbar));
check('现在一共三个 ws-right-toggle（标题栏 / 面板工具栏 / 顶栏）',
    (html.match(/class="[^"]*ws-right-toggle/g) || []).length === 3);
// 项目内两个开关同时出现会互相解释不清
check('进项目后顶栏那个被藏掉',
    /body\.shell-project #topbarChatToggle \{[\s\S]{0,60}display: none/.test(css));
// chatPanelOpen 被好几条路径改，只在 toggleChatPanel 里更新按钮会对不上
const tct = app.slice(app.indexOf('function _syncTopbarChatToggle'),
                      app.indexOf('function toggleChatPanel'));
check('顶栏开关有独立的状态同步函数', tct.length > 0);
check('同步 active / aria-expanded / title',
    /classList\.toggle\('active'/.test(tct)
    && /aria-expanded/.test(tct)
    && /'隐藏 AI 助手面板' : '显示 AI 助手面板'/.test(tct));
check('toggleChatPanel 结尾同步顶栏开关',
    /document\.body\.classList\.remove\('chat-open'\);\s*\n\s*\}\s*\n\s*_syncTopbarChatToggle\(\);/.test(app));
check('壳层 _syncChatOpenFlag 也同步（退回列表页时状态要对）',
    /function _syncChatOpenFlag[\s\S]{0,600}_syncTopbarChatToggle\(\)/.test(app));
check('退出全屏后同步（全屏时顶栏是藏着的）',
    /_syncTopbarChatToggle\(\);\s*\n\}\s*\n\s*\nfunction _initChatSplitContainer/.test(app));
check('刷新恢复后同步（恢复出来可能就是打开状态）',
    /_restoreChatWorkspace[\s\S]{0,2600}_syncTopbarChatToggle\(\)/.test(app));
// 顶栏原本没有 .top-bar-right 规则，按钮和 LLM 胶囊会上下摞成两行
check('.top-bar-right 横向排布', /\.top-bar-right \{[\s\S]{0,120}display: flex/.test(css));

console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
process.exit(fail ? 1 : 0);
