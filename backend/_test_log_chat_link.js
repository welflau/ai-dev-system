// 时间轴日志 →「↗ 对话」定位 —— 回归
//   cd backend && node _test_log_chat_link.js
//
// 需求：时间轴上看到一条「ArchitectAgent / architecture_done」，想知道它当时到底说了
// 什么，得自己去「工单对话」里按时间翻。这个链接把两个视角接起来。
//
// 设计上只有一条硬规则：**链接只在对话里真有对应条目时才出现**。
// 判断依据（Feed 收哪些 action）写在 backend/api/chat.py::FEED_LOG_ACTIONS，
// 由 tickets.py 的 /timeline 直接 import 并标成 _chat_anchor，前端只认这个字段。
// 前端自己抄一份 action 白名单 = 两份判据各改各的 —— 「📟 后台记录」链接刚因为
// 这个翻车过（判据和建表规则一致地错，测试全绿，真实 UE 工单一条链接都没有）。
// 所以本测试的第一优先级就是钉死"前端不许自己判断 action"。
//
// Python 侧（锚点标注、llm_call 时间配对、零死链）由 _test_log_chat_link.py 验。

const fs = require('fs');
// app.js 是 CRLF，按 '\n...' 找边界的哨兵都得先归一化
const norm = s => s.replace(/\r\n/g, '\n');
const src = norm(fs.readFileSync('../frontend/app.js', 'utf8'));
const css = norm(fs.readFileSync('../frontend/styles.css', 'utf8'));
const py = norm(fs.readFileSync('api/tickets.py', 'utf8'));
const pyChat = norm(fs.readFileSync('api/chat.py', 'utf8'));

let pass = 0, fail = 0;
function check(name, cond, detail = '') {
    if (cond) { pass++; console.log(`[OK] ${name}${detail ? ' -- ' + detail : ''}`); }
    else { fail++; console.log(`[FAIL] ${name}${detail ? ' -- ' + detail : ''}`); }
}

/** 取函数源码，按声明处缩进找收尾 `}`；截歪了直接抛，不静默退化成"整份文件" */
function body(name) {
    const m = new RegExp(`^([ \\t]*)(?:async )?function ${name}\\(`, 'm').exec(src);
    if (!m) throw new Error(`找不到 ${name}`);
    const close = '\n' + m[1] + '}';
    const end = src.indexOf(close, m.index);
    if (end < 0) throw new Error(`找不到 ${name} 的收尾括号`);
    const b = src.slice(m.index, end + close.length);
    if (b.split('\n').length > 300) throw new Error(`${name} 截取过长（${b.split('\n').length} 行），边界找歪了`);
    return b;
}

// ── 1. 判据只有一份：前端不许自己判断 action ────────────────────────
const linkFn = body('_chatLinkHtml');
check('_chatLinkHtml 只看后端标的 _chat_anchor', /log\._chat_anchor/.test(linkFn));
check('后端没标锚点就不渲染（不留死链）', /if \(!anchor\) return ''/.test(linkFn));
// 钉死：前端不能出现 Feed 白名单里那些 action 名的硬编码判断
for (const act of ['thought_done', 'architecture_done', 'openspec_apply', 'skill_step_done']) {
    check(`前端没把 '${act}' 抄进跳转判据`,
        !new RegExp(`_chat_anchor[\\s\\S]{0,400}${act}|${act}[\\s\\S]{0,200}_chat_anchor`).test(linkFn));
}
check('前端没有第二份 Feed action 白名单', !/FEED_LOG_ACTIONS/.test(src));

// ── 2. 后端：单一来源 + 挂进 /timeline ─────────────────────────────
check('FEED_LOG_ACTIONS 定义在 chat.py 模块级（Feed 和标注共用）',
    /^FEED_LOG_ACTIONS = \{/m.test(pyChat));
check('Feed 端点用的就是这个常量，没有内联字面量',
    /LOG_ACTIONS_SHOW = FEED_LOG_ACTIONS/.test(pyChat));
check('tickets.py import 同一个集合，而不是复制',
    /from api\.chat import FEED_LOG_ACTIONS/.test(py));
check('_annotate_chat_anchors 挂进了 /timeline 返回前',
    /items = await _annotate_chat_anchors\(ticket_id, items\)/.test(py));
// 标注要在 sort 之后：llm_call 配对按时间取邻居，乱序会配错
const tlFn = py.slice(py.indexOf('async def get_ticket_timeline'));
check('锚点标注在排序之后',
    tlFn.indexOf('items.sort(') < tlFn.indexOf('_annotate_chat_anchors(ticket_id, items)'));
// 导入失败/查库失败都不能让整个时间轴 500
check('标注失败时退回"没有链接"而不是抛异常',
    /except Exception as e:[\s\S]{0,200}return items/.test(py));

// ── 3. 对话侧有锚点可落 ───────────────────────────────────────────
// 事件条目两种形态（compact 单行 / 详情卡）都得带 data-log-id，
// 只给一种的话，另一种 action 的链接点下去找不到目标
const evFn = body('_buildTicketEventEl');
const anchorSets = evFn.match(/dataset\.logId = msg\.id/g) || [];
check('事件条目两种形态都带 data-log-id', anchorSets.length >= 2,
    `找到 ${anchorSets.length} 处`);
// llm_call 的锚点是 '<conv_id>_resp'，正是 assistant 气泡的 msg.id
check('LLM 回复气泡也带 data-log-id（llm_call 的落点）',
    /msgEl\.dataset\.logId = msg\.id/.test(body('loadTicketConversations')));

// ── 4. 跳转：切换 + 等渲染 + 高亮 ──────────────────────────────────
const openFn = body('openChatFromLog');
// 面板可能没开、停在别的 tab、或开着别的工单，三种都要先切过去
check('工单不同或不在 job 模式时先切过去',
    /chatCurrentTicketId !== ticketId\) \|\| chatMode !== 'job'/.test(openFn));
check('切换走 selectTicketForChat（复用开面板+进 job+加载那套）',
    /selectTicketForChat\(ticketId/.test(openFn));
// 这是关键：对话是异步渲染的，固定 setTimeout 在 500 条日志的工单上会赌输
check('等锚点出现再滚，而不是固定 setTimeout',
    /await _waitForChatAnchor\(/.test(openFn) && !/setTimeout\(\s*\(\)\s*=>\s*\{[\s\S]*scrollIntoView/.test(openFn));
check('切换后给更长的等待预算（要重新拉接口）',
    /needSwitch \? \d{3,} : \d+/.test(openFn));
check('滚进视野并高亮', /scrollIntoView/.test(openFn) && /tfc-comment-highlight/.test(openFn));
check('高亮会自己撤掉（否则永久留一块底色）',
    /setTimeout\(\(\) => [\s\S]{0,60}classList\.remove\('tfc-comment-highlight'\)/.test(openFn));
check('等不到锚点时提示而不是静默失败', /showToast\(/.test(openFn));

const waitFn = body('_waitForChatAnchor');
check('锚点只在 #chatMessages 里找（避免撞上左侧属性面板的同 id 元素）',
    /#chatMessages \[data-log-id=/.test(waitFn));
check('用 CSS.escape 转义（锚点含 - 和 _，也可能来自后端拼接）',
    /CSS\.escape\(anchor\)/.test(waitFn));
check('轮询会超时退出（拿不到就不要挂着定时器）',
    /clearInterval\(timer\)/.test(waitFn) && /Date\.now\(\) - t0 > timeoutMs/.test(waitFn));

// ── 5. 两个渲染器都挂上了 ─────────────────────────────────────────
for (const fn of ['renderLogItem', '_renderLayerLogItem']) {
    const b = body(fn);
    check(`${fn} 渲染了对话链接`, /\$\{_chatLinkHtml\(log\)\}/.test(b));
    // .log-time 自带 margin-left:auto，链接必须排在它前面才会贴着时间戳
    check(`${fn} 里链接排在 .log-time 之前`,
        b.indexOf('_chatLinkHtml(log)') < b.indexOf('class="log-time"'));
}
check('链接吃掉冒泡（否则同时触发条目自身的展开/折叠）',
    /event\.stopPropagation\(\);openChatFromLog\(/.test(linkFn));
// 分层渲染器右边已经有个 💬 是"评论此记录"，跳转链接不能也用 💬，否则两个挨着分不清
check('图标不和"评论此记录"的 💬 撞车', !/>💬 /.test(linkFn));

// ── 6. 样式 ──────────────────────────────────────────────────────
const rule = /(?:^|,)\s*\.log-chat-link\s*(?:,[^{]*)?\{([^}]*)\}/m.exec(css)
          || /\.log-chat-link\s*\{([^}]*)\}/.exec(css);
check('.log-chat-link 样式已定义', !!rule);
// .log-time 自带 margin-left:auto；两个 auto 兄弟会把剩余空间对半分
check('.log-chat-link 不抢 margin-left:auto', !!rule && !/margin-left:\s*auto/.test(rule[1]));
check('.log-chat-link 不参与收缩（窄窗口下不被挤没）',
    !!rule && /flex-shrink:\s*0/.test(rule[1]));
check('有 hover 反馈（否则看不出可点）', /\.log-chat-link:hover/.test(css));

console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
process.exit(fail ? 1 : 0);
