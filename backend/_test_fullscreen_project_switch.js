/**
 * 全屏聊天切换项目：上下文切换完整性 + 空白兜底
 *   cd backend && node _test_fullscreen_project_switch.js
 *
 * 背景 bug：全屏聊天里左上角切项目后消息区完全空白，退出全屏内容才出现。
 * 根因：_switchProjectInFullscreen 走轻量路径（只改 currentProjectId +
 * _updateChatPanelForContext），两个缺口 ——
 *   1) SSE/日志面板没切，旧项目事件串台；
 *   2) 刷新恢复流程未走完（_chatWsPersistReady=false）时切进来，
 *      _updateChatPanelForContext 走「只清空不加载」分支，而恢复流程稍后的
 *      加载因 context 已变被 stale 拦截 → 没人再补载 → 空白卡死，
 *      直到退出全屏才被 openRight 的 hasContent 检查救回。
 * 修复：补 SSE/日志切换 + 延迟空白兜底补载（_switchProjectInFullscreen 和
 * _switchToGlobalChat 两处）。
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const norm = s => s.replace(/\r\n/g, '\n');
const app = norm(fs.readFileSync(path.join(ROOT, 'frontend/app.js'), 'utf8'));

let pass = 0, fail = 0;
function check(name, cond, detail = '') {
    if (cond) { pass++; console.log(`[OK] ${name}${detail ? ' -- ' + detail : ''}`); }
    else { fail++; console.log(`[FAIL] ${name}${detail ? ' -- ' + detail : ''}`); }
}

function fnBody(name) {
    const i = app.indexOf(`function ${name}`);
    if (i < 0) return '';
    // 粗略取函数体：从定义处到下一个顶层 function 之间
    const next = app.indexOf('\nfunction ', i + 10);
    const nextAsync = app.indexOf('\nasync function ', i + 10);
    const candidates = [next, nextAsync].filter(n => n > 0);
    const end = candidates.length ? Math.min(...candidates) : i + 4000;
    return app.slice(i, end);
}

const switchFn = fnBody('_switchProjectInFullscreen');
const globalFn = fnBody('_switchToGlobalChat');

// ── 1. SSE / 日志面板切换补齐 ──────────────────────────────
check('切项目时断开旧 SSE', switchFn.includes('disconnectSSE()'));
check('切项目时连新项目 SSE', switchFn.includes('connectSSE(projectId)'));
check('切项目时清空日志面板', switchFn.includes('clearLogPanel()'));
check('切项目时载入新项目日志历史', switchFn.includes('loadLogPanelHistory()'));

// ── 2. 空白兜底（两个切换入口都要有）────────────────────────
for (const [label, body] of [['切项目', switchFn], ['切全局', globalFn]]) {
    check(`${label}兜底：延迟检查存在`, body.includes('setTimeout'));
    check(`${label}兜底：仅全屏下生效（退出后交给 openRight）`,
        body.includes('if (!_chatFullscreen) return;'));
    check(`${label}兜底：空白判定覆盖欢迎页/加载中/消息卡`,
        /\.chat-msg, \.chat-confirm-card, \.chat-action-card, \.chat-welcome, \.chat-typing, \.chat-job-hint/.test(body));
    check(`${label}兜底：流式发送中不补载（避免冲掉正在输出的气泡）`,
        body.includes('!chatSending && !_streamAbortController'));
    check(`${label}兜底：用 _reloadChatForCurrentMode 按模式补载`,
        body.includes('_reloadChatForCurrentMode()'));
}

// ── 3. 不回归：原有的去重逻辑还在（不重复 loadChatHistory，注释行除外）──
const switchCode = switchFn.split('\n').filter(l => !l.trim().startsWith('//')).join('\n');
check('切项目不直接调 loadChatHistory（由 _updateChatPanelForContext 按模式分派）',
    !switchCode.includes('loadChatHistory()'));
check('切项目仍走 _updateChatPanelForContext 按模式分派',
    switchCode.includes('_updateChatPanelForContext()'));

// ── 4. 全局助手标题不能挂磁盘路径 ──────────────────────────
const applyTitle = fnBody('_applyChatPanelTitle');
const looksPath = fnBody('_looksLikeFsPath');
const sessTitle = fnBody('_sessionDisplayTitle');
const ctxFn = fnBody('_updateChatPanelForContext');
const globalCode = globalFn.split('\n').filter(l => !l.trim().startsWith('//')).join('\n');

check('有 _applyChatPanelTitle：无项目时标题带「全局」',
    applyTitle.includes('AI 助手 · 全局'));
check('有 _looksLikeFsPath：识别 Windows 盘符路径',
    looksPath.includes('^[A-Za-z]:[\\\\/]'));
check('_sessionDisplayTitle 把磁盘路径当无效标题',
    sessTitle.includes('_looksLikeFsPath(t)'));
check('切 context 时立刻清掉会话小字（不等异步加载）',
    ctxFn.includes('_clearChatPanelSessionTitle()'));
check('切到全局不再因已经是全局而直接 return（否则路径小字清不掉）',
    !/if\s*\(\s*!currentProjectId\s*\)\s*return\s*;/.test(globalCode));
check('已在全局时仍会 _applyChatPanelTitle',
    globalCode.includes('_applyChatPanelTitle()'));
check('切到全局会 disconnectSSE（不要还挂着上一个项目）',
    globalCode.includes('disconnectSSE()'));
check('项目切换下拉在全局时把「全局 AI 助手」标成当前',
    app.includes("ps-global${currentProjectId ? '' : ' active'}"));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
