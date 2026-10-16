/**
 * AI 助手切项目串台
 *   cd backend && node _test_chat_context_switch.js
 *
 * 复现的 bug：从项目 A 切到项目 B，右侧「对话」里显示的还是 A 的聊天记录，
 * 手动切一下 AI助手/工单 Tab 才会刷新。
 *
 * 两层成因，第二层是第一次修完**仍然会串**的原因：
 *
 * 1. _chatMessagesHasContent() 只问"DOM 里有没有气泡"，不问"这些气泡是谁的"。
 *    切项目时右侧面板往往是关着的，A 的气泡原地留着，等用户打开面板，
 *    这个检查看到一堆气泡就判定"已加载过"，跳过重载。
 *
 * 2. **迟到的响应会伪造归属标识。** 所有加载函数都是 async，_markChatRendered()
 *    在它们结尾执行，读的是那一刻的全局变量：A 的请求在路上时用户切到 B，
 *    A 的响应后返回 → 铺完 A 的气泡 → 盖上 B 的戳。hasContent() 从此返回 true，
 *    再也不会重载。所以标识必须绑在"哪一次加载"上，用递增代号 + 起飞凭证。
 *
 * 这里在沙箱里跑真实函数，用假 DOM 走一遍切项目的时序（含乱序返回），
 * 而不是只匹配源码字符串。
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

// ── 从 app.js 里切出这几个真函数，放进沙箱跑 ─────────────────────
function extract(sig) {
    const start = app.indexOf(sig);
    if (start < 0) throw new Error(`找不到 ${sig}`);
    // 从函数头开始数花括号，取到配平为止
    let i = app.indexOf('{', start), depth = 0;
    for (let j = i; j < app.length; j++) {
        if (app[j] === '{') depth++;
        else if (app[j] === '}') { depth--; if (depth === 0) return app.slice(start, j + 1); }
    }
    throw new Error(`${sig} 花括号不配平`);
}

const SRC = [
    'function _chatContextToken()',
    'function _chatCtxTick()',
    'function _chatLoadStart()',
    'function _chatLoadStale(tok)',
    'function _markChatRendered(tok)',
    'function _chatMessagesHasContent()',
    'function _reloadChatForCurrentMode()',
].map(extract).join('\n\n');

// 这些变量要能被抽出来的函数读写，所以统一 let 在沙箱作用域里声明
const LOCALS = ['chatMode', 'currentProjectId', 'chatCurrentTicketId', 'chatSending',
                '_chatRenderedFor', '_chatReloadSuppressed', '_chatCtxGen', '_chatCtxSeen'];

function makeEnv() {
    const calls = [];
    // 假 #chatMessages：只需要 querySelector 能回答"有没有气泡"
    const box = {
        bubbles: 0,
        querySelector(sel) { return this.bubbles > 0 ? { sel } : null; },
    };
    const sandbox = {
        _streamAbortController: null,
        document: { getElementById: id => (id === 'chatMessages' ? box : null) },
        loadChatHistory() { calls.push('global'); },
        loadAllTicketConversations() { calls.push('job'); },
        loadGroupChat() { calls.push('group'); },
    };
    const names = Object.keys(sandbox);
    const body = `
        ${SRC}
        return {
            token: () => _chatContextToken(),
            mark: tok => _markChatRendered(tok),
            has: () => _chatMessagesHasContent(),
            reload: () => _reloadChatForCurrentMode(),
            start: () => _chatLoadStart(),
            stale: tok => _chatLoadStale(tok),
            tick: () => _chatCtxTick(),
            get gen() { return _chatCtxGen; },
            get renderedFor() { return _chatRenderedFor; },
            set renderedFor(v) { _chatRenderedFor = v; },
            setMode: m => { chatMode = m; },
            setProject: p => { currentProjectId = p; },
            setTicket: t => { chatCurrentTicketId = t; },
            setSending: v => { chatSending = v; },
            setSuppressed: v => { _chatReloadSuppressed = v; },
        };
    `;
    const fn = new Function(...names,
        `let chatMode = 'global', currentProjectId = null, chatCurrentTicketId = null,
             chatSending = false, _chatRenderedFor = null, _chatReloadSuppressed = false,
             _chatCtxGen = 0, _chatCtxSeen = null;
         ${body}`);
    const api = fn(...names.map(n => sandbox[n]));
    return { api, box, calls };
}

// ── 1. token 能区分项目 / 模式 / 工单 ────────────────────────────
{
    const { api } = makeEnv();
    api.setProject('proj-A');
    const tA = api.token();
    api.setProject('proj-B');
    check('不同项目的 token 不同', tA !== api.token(), `${tA} vs ${api.token()}`);

    api.setProject('proj-A');
    check('同项目的 token 稳定（不会每次都判脏）', api.token() === tA);

    api.setMode('job');
    check('不同模式的 token 不同', api.token() !== tA);

    api.setTicket('T-1');
    const t1 = api.token();
    api.setTicket('T-2');
    check('job 模式下不同工单的 token 不同', api.token() !== t1);

    api.setMode('global');
    api.setTicket('T-9');
    api.setProject('proj-A');
    check('global 模式忽略工单（换工单不该让全局对话判脏）', api.token() === tA);
}

// ── 2. 核心场景：面板关着的时候切项目 ────────────────────────────
{
    const { api, box } = makeEnv();
    // 在项目 A 里看过对话
    api.setProject('proj-A');
    box.bubbles = 12;
    api.mark();
    check('A 项目加载完后 hasContent=true（不该反复重载）', api.has() === true);

    // 切到项目 B——注意这里没有任何 DOM 清理，气泡还是 A 的那 12 条
    api.setProject('proj-B');
    check('切到 B 后 hasContent=false（认出装的是 A 的内容）', api.has() === false,
        'DOM 里仍有 12 条 A 的气泡');

    // 打开面板 → 重新加载 → 标记
    api.mark();
    check('B 加载完后 hasContent 恢复 true', api.has() === true);

    // 再切回 A
    api.setProject('proj-A');
    check('切回 A 同样判脏（不会拿 B 的内容充数）', api.has() === false);
}

// ── 3. 空消息区不会被误判成"有内容" ──────────────────────────────
{
    const { api, box } = makeEnv();
    api.setProject('proj-A');
    box.bubbles = 0;
    api.mark();
    check('token 对上但 DOM 为空时 hasContent=false', api.has() === false);
}

// ── 4. 重载走当前模式，不是写死 loadChatHistory ──────────────────
{
    const { api, calls } = makeEnv();
    api.setProject('proj-A');

    api.setMode('global'); api.reload();
    api.setMode('job');    api.reload();
    api.setMode('group');  api.reload();
    check('三种模式各走各的加载函数',
        JSON.stringify(calls) === JSON.stringify(['global', 'job', 'group']),
        JSON.stringify(calls));
}

// ── 5. 流式中 / 抑制期不重载（会冲掉正在输出的气泡）──────────────
{
    const { api, calls } = makeEnv();
    api.setProject('proj-A');
    api.setSending(true);
    api.reload();
    check('流式发送中不重载', calls.length === 0);

    api.setSending(false);
    api.setSuppressed(true);
    api.reload();
    check('抑制期内不重载（调用方自己马上要加载）', calls.length === 0);

    api.setSuppressed(false);
    api.reload();
    check('解除后恢复重载', calls.length === 1);
}

// ── 5b. 迟到的响应不许伪造归属标识（第一次修完仍然串台的原因）────────
{
    const { api, box } = makeEnv();
    api.setProject('proj-A');

    // A 的加载起飞，拿一张凭证
    const tokA = api.start();

    // 响应还在路上，用户点了 B
    api.setProject('proj-B');
    // B 的加载也起飞了
    const tokB = api.start();

    check('切项目后旧凭证过期', api.stale(tokA) === true);
    check('新凭证不过期', api.stale(tokB) === false);

    // A 的响应**后**返回，铺完气泡想盖戳
    box.bubbles = 12;
    api.mark(tokA);
    check('A 的迟到响应盖不上戳（这才是串台的根因）',
        api.renderedFor !== api.token(),
        `renderedFor=${api.renderedFor} 当前=${api.token()}`);
    check('所以 hasContent 仍为 false —— 后面还会重载',
        api.has() === false, 'DOM 里是 A 的 12 条气泡');

    // B 的响应回来，正常盖戳
    api.mark(tokB);
    check('B 的响应能正常盖戳', api.has() === true);
}

// ── 5c. A→B→A 转回来时，在途的那个 A 请求依然作废 ────────────────
// 只比较 token 字符串的实现会在这里失手：转一圈回来 token 又相等了
{
    const { api, box } = makeEnv();
    api.setProject('proj-A');
    const tokA1 = api.start();          // 第一次在 A 的加载起飞

    api.setProject('proj-B');
    api.tick();
    api.setProject('proj-A');           // 又切回 A，token 和起飞时一样
    const tokA2 = api.start();

    check('转一圈回来 token 相同', tokA1.ctx === tokA2.ctx, tokA1.ctx);
    check('但代号不同，旧请求依然作废（光比 token 会在这里失手）',
        tokA1.gen !== tokA2.gen && api.stale(tokA1) === true,
        `gen ${tokA1.gen} vs ${tokA2.gen}`);

    box.bubbles = 5;
    api.mark(tokA1);
    check('第一次那批内容盖不上戳', api.has() === false);
    api.mark(tokA2);
    check('第二次（当前）那批可以', api.has() === true);
}

// ── 5d. 不传凭证时保持老行为（渲染即当前内容，如欢迎页）───────────
{
    const { api, box } = makeEnv();
    api.setProject('proj-A');
    box.bubbles = 1;
    api.mark();                          // 无凭证：同步渲染路径
    check('无凭证调用仍按当前 context 盖戳（欢迎页等同步渲染）',
        api.has() === true);
}

// ── 6. 源码层面：该调的地方都调了 ───────────────────────────────
// 光有函数没用，得真的接在切项目的那几条路径上
check('_updateChatPanelForContext 里清掉上一个项目的工单选择',
    /_cliClearMem\(\);[\s\S]{0,300}chatCurrentTicketId = null;[\s\S]{0,120}chatCurrentTicketTitle = '';/.test(app));
check('面板关着时不只作废标识，还要真清 DOM',
    /\} else if \(!chatSending && !_streamAbortController\) \{[\s\S]{0,600}_chatRenderedFor = null;\s*\n\s*if \(msgContainer\) msgContainer\.innerHTML = '';/.test(app));
check('切 context 时推进代号（作废所有在途请求）',
    /_currentChatSessionId = null;[\s\S]{0,200}_chatCtxTick\(\);\s*\n\s*_chatRenderedFor = null;/.test(app));
check('群聊容器也清（loadGroupChat 只看 children.length）',
    /getElementById\('groupChatMessages'\);\s*\n\s*if \(groupBox && !chatSending && !_streamAbortController\) groupBox\.innerHTML = '';/.test(app));
check('hasContent 检查时顺手推进代号',
    /function _chatMessagesHasContent\(\)[\s\S]{0,300}_chatCtxTick\(\);/.test(app));
check('openRight 补载走 _reloadChatForCurrentMode',
    /function openRight[\s\S]{0,1800}_reloadChatForCurrentMode\(\)/.test(app));
check('setRightTab 补载走 _reloadChatForCurrentMode',
    /function setRightTab[\s\S]{0,900}_reloadChatForCurrentMode\(\)/.test(app));
// 原来这两处写着 chatMode === 'global' 才补载，停在工单 Tab 时切项目就不刷新
check('openRight / setRightTab 不再只在 global 模式下补载',
    !/chatMode === 'global'\s*\n\s*&& typeof loadChatHistory === 'function'/.test(app));
check('toggleChatPanel 补载走 _reloadChatForCurrentMode',
    /function toggleChatPanel[\s\S]{0,1600}_reloadChatForCurrentMode\(\)/.test(app));
// 全屏切项目原来是 _updateChatPanelForContext + loadChatHistory 两次加载抢写
check('全屏切项目不再重复加载一次',
    !/_updateChatPanelForContext\(\);\s*\n\s*\/\/ 全屏状态不跳转页面[\s\S]{0,80}loadChatHistory\(\);/.test(app));

// ── 6b. 四个 async 加载函数都必须带凭证起飞、验凭证落地 ───────────
for (const fnName of ['loadChatHistory', 'switchChatSession',
                      'loadTicketConversations', 'loadAllTicketConversations']) {
    const src = extract(`async function ${fnName}(`);
    check(`${fnName} 起飞时取凭证`, /const _tok = _chatLoadStart\(\);/.test(src));
    check(`${fnName} 落地前验过期`, /_chatLoadStale\(_tok\)/.test(src));
    check(`${fnName} 打标带上凭证`, /_markChatRendered\(_tok\)/.test(src));
    // 过期的失败响应不能画欢迎页/错误页，会抹掉新项目刚加载好的内容
    check(`${fnName} 的 catch 也验过期`,
        /catch[\s\S]{0,400}_chatLoadStale\(_tok\)/.test(src));
}

// 渲染完成的出口都要打标，漏一个就会无限重载
for (const [name, re] of [
    ['showChatWelcome', /function showChatWelcome[\s\S]{0,200}_markChatRendered\(\);/],
    ['_loadGlobalChatFromStorage', /container\.innerHTML = data\.dom;\s*\n\s*_markChatRendered\(\);/],
]) {
    check(`${name} 渲染后打标`, re.test(app));
}

// selectTicketForChat：模式要在 openRight 之前定，否则 openRight 会按 global
// 拉一遍全局历史，和随后的工单请求抢着写同一个容器
const stfc = app.slice(app.indexOf('function selectTicketForChat'),
                       app.indexOf('function selectTicketForChat') + 1400);
// 注意不能用 indexOf('openRight')——注释里也提到了它
check('selectTicketForChat 先定模式再开面板',
    stfc.indexOf("chatMode = 'job';") < stfc.indexOf('adsShell.openRight('));
check('selectTicketForChat 抑制 openRight 的顺手补载',
    /_withChatReloadSuppressed\(\(\) => \{[\s\S]{0,300}openRight/.test(stfc));

console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
process.exit(fail ? 1 : 0);
