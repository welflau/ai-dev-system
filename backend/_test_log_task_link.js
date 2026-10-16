// 时间轴日志 →「📟 后台记录」链接 —— 回归
//   cd backend && node _test_log_task_link.js
//
// 这条链接的全部价值在于**点下去一定有东西**。
//
// 第一版是手写一份判据去"预测" _buildTicketTasksFromLogs 的建表规则，测试也确实
// 证明了两边一致 —— 然后真实数据打脸：规则本身只认 tool_done（全库 43 条）和
// 带文件的 complete，UE 工单的 UBT 编译（action=complete，带 command **无文件**）、
// ToolError（401 条）全都不建任务，于是截图里箭头指的那条恰恰没有链接。
// 判据和规则"一致地错"，测试照样全绿。
//
// 现在改成：建表时顺带产出 logId → taskId 索引，链接只查索引。只有一份规则，
// 判据不可能再脱节。本测试的重心也随之转移 ——
// 不再比对两份判据，而是**用真实 DB 数据**跑建表函数，断言那几类关键日志确实建出了任务。

const fs = require('fs');
const path = require('path');
// app.js 是 CRLF，所有按 '\n...' 找边界的哨兵都得先归一化（见 _test_tasks_main_tab.js）
const norm = s => s.replace(/\r\n/g, '\n');
const src = norm(fs.readFileSync('../frontend/app.js', 'utf8'));
const css = norm(fs.readFileSync('../frontend/styles.css', 'utf8'));

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
    if (b.split('\n').length > 400) throw new Error(`${name} 截取过长（${b.split('\n').length} 行），边界找歪了`);
    return b;
}

// ── 1. 两个渲染器都挂上了链接 ─────────────────────────────────────
// 时间轴有两套渲染：普通条目 renderLogItem、分层视图 _renderLayerLogItem。
// 只改一个的话，用户切到另一种视图链接就没了。
for (const fn of ['renderLogItem', '_renderLayerLogItem']) {
    const b = body(fn);
    check(`${fn} 渲染了后台记录链接`, /\$\{_taskLinkHtml\(log\)\}/.test(b));
    // .log-time 自带 margin-left:auto，链接必须排在它**前面**才会贴着时间戳左侧
    check(`${fn} 里链接排在 .log-time 之前`,
        b.indexOf('_taskLinkHtml(log)') < b.indexOf('class="log-time"'));
}
// 日志条目本身可能带 onclick（展开/折叠），不拦截就会既跳面板又折叠
check('链接吃掉冒泡（否则同时触发条目自身的展开/折叠）',
    /event\.stopPropagation\(\);openTaskFromLog\(/.test(body('_taskLinkHtml')));

// ── 2. 只有一份判据：链接查索引，不自己猜规则 ──────────────────────
// 这是第一版翻车的根因，钉死它
check('已删除手写判据 _logHasBackgroundTask（判据只能有一份）',
    !/_logHasBackgroundTask/.test(src));
check('_taskLinkHtml 查索引决定渲不渲染', /_logTaskId\(log\)/.test(body('_taskLinkHtml')));
check('索引由建表函数顺带产出', /_TICKET_TASK_INDEX\[ticketId\] = index/.test(body('_buildTicketTasksFromLogs')));
// 时间轴渲染远早于用户打开任务面板；不在渲染时建索引，链接一个都不会出现
check('时间轴渲染时就把索引建好（不等用户开面板）',
    /_buildTicketTasksFromLogs\(\[\.\.\.items\]\.reverse\(\)\)/.test(body('_renderUnifiedTimeline')));
check('索引构建失败不炸掉整个时间轴', /catch \(e\) \{ console\.warn/.test(body('_renderUnifiedTimeline')));

// ── 3. 用真实 DB 数据跑建表函数 ───────────────────────────────────
// 光用构造数据测，测的是"我以为日志长什么样"。上一版就是这么错的。
const build = new Function(`
    let _currentTimelineTicketId = null;
    const _TICKET_TASK_INDEX = {};
    ${body('_buildTicketTasksFromLogs')}
    return { build: _buildTicketTasksFromLogs, index: _TICKET_TASK_INDEX };
`)();

const FIX = path.join(__dirname, '_fixture_ticket_logs.json');
if (!fs.existsSync(FIX)) {
    console.log(`\n[跳过] 缺少真实日志样本 ${path.basename(FIX)}，先跑 _dump_log_fixture.py 生成`);
} else {
    const fixture = JSON.parse(fs.readFileSync(FIX, 'utf8'));
    for (const [tid, info] of Object.entries(fixture)) {
        // DB 存的是 ASC，接口给前端是 DESC，建表函数内部再 reverse
        const tasks = build.build([...info.logs].reverse());
        const idx = build.index[tid] || {};
        const byAction = {};
        for (const l of info.logs) {
            if (idx[l.id]) (byAction[l.action] = byAction[l.action] || []).push(l);
        }
        const kinds = Object.keys(byAction).sort().join(',');
        check(`[真实数据] ${tid} 建出任务`, tasks.length >= info.expect_min,
            `${tasks.length} 条任务（期望 ≥${info.expect_min}）· 有链接的 action: ${kinds || '无'}`);

        // 索引里每个 taskId 都得真的在任务表里 —— 死链的唯一可能来源
        const ids = new Set(tasks.map(t => t.id));
        const dead = Object.entries(idx).filter(([, v]) => !ids.has(v));
        check(`[真实数据] ${tid} 索引无死链`, dead.length === 0,
            dead.length ? dead.slice(0, 3).map(d => d.join('→')).join(' ') : `${Object.keys(idx).length} 个链接`);

        // 逐条核对期望的 action 类型确实拿到了链接
        for (const act of info.expect_actions || []) {
            const total = info.logs.filter(l => (l.action || '').startsWith(act)).length;
            const linked = info.logs.filter(l => (l.action || '').startsWith(act) && idx[l.id]).length;
            check(`[真实数据] ${tid} 的 ${act} 有链接`, linked > 0, `${linked}/${total} 条`);
        }
    }
}

// ── 4. 关键日志形态：UE 那几类必须建出任务 ────────────────────────
// 截图里箭头指的就是第一条。UBT 编译的 complete **没有文件列表**，
// 拿"有没有文件"当门槛就会漏掉它 —— 这是上一版的原始 bug，钉死。
const T = n => `2026-07-22T01:${String(n).padStart(2, '0')}:00`;
const LOGS = [
    { id: 'UBT', ticket_id: 'TK-X', action: 'complete', created_at: T(1),
      detail: JSON.stringify({ message: 'UBT 编译通过（497s，target=TestFPSEditor）', exit_code: 0, duration_ms: 497870, products: [], command: 'UnrealBuildTool.exe TestFPSEditor Win64' }) },
    { id: 'PT', ticket_id: 'TK-X', action: 'complete', created_at: T(2),
      detail: JSON.stringify({ message: 'Playtest 通过（1/1，296s）', exit_code: 0, duration_ms: 296435, summary: { total: 1, passed: 1, failed: 0, skipped: 0 }, screenshots: [], command: 'UnrealEditor-Cmd.exe' }) },
    { id: 'FAILBUILD', ticket_id: 'TK-X', action: 'complete', created_at: T(3),
      detail: JSON.stringify({ message: 'UBT 编译失败', exit_code: 6, command: 'UnrealBuildTool.exe' }) },
    { id: 'TE', ticket_id: 'TK-X', action: 'ToolError:agent:DevAgent.develop', created_at: T(4),
      detail: JSON.stringify({ tool_name: 'agent:DevAgent.develop', error: 'LLM 输出无效', duration_ms: 0, agent_type: 'DevAgent' }) },
    { id: 'DEV', ticket_id: 'TK-X', action: 'complete', created_at: T(5),
      detail: JSON.stringify({ message: '开发完成', file_paths: ['Source/A.cpp'], git_files: [] }) },
    { id: 'DEPLOY', ticket_id: 'TK-X', action: 'complete', created_at: T(6),
      detail: JSON.stringify({ message: '部署完成', git_commit: null, git_files: [], preview_url: null }) },
    { id: 'TS', ticket_id: 'TK-X', action: 'tool_start', created_at: T(7),
      detail: JSON.stringify({ message: '开始 run_engine_compile' }) },
    { id: 'TD', ticket_id: 'TK-X', action: 'tool_done', created_at: T(8),
      detail: JSON.stringify({ message: '完成 run_engine_compile (1486ms) status=compile_failed' }) },
    { id: 'THIN', ticket_id: 'TK-X', action: 'thought_done', created_at: T(9),
      detail: JSON.stringify({ message: '[PlannerAgent] 完成 write_prd (16951ms) status=success' }) },
    { id: 'FAT', ticket_id: 'TK-X', action: 'thought_done', created_at: T(10),
      detail: JSON.stringify({ message: '[DevAgent] 完成 develop (165964ms) status=success', file_paths: ['B.h'], elapsed_ms: 165964, status: 'success' }) },
    { id: 'NOISE', ticket_id: 'TK-X', action: 'thought_start', created_at: T(11), detail: '{}' },
    { id: 'LLM', ticket_id: 'TK-X', action: 'llm_call', created_at: T(12), detail: '{}' },
];
const tasks2 = build.build([...LOGS].reverse());
const idx2 = build.index['TK-X'] || {};
const has = id => !!idx2[id];
const taskOf = id => tasks2.find(t => t.id === idx2[id]);

check('UBT 编译（complete 带 command、无文件）有链接 ← 截图里那条', has('UBT'));
check('Playtest（complete 带 summary/screenshots）有链接', has('PT'));
check('编译失败的 complete 标记为 error 状态',
    taskOf('FAILBUILD')?.status === 'error', `status=${taskOf('FAILBUILD')?.status}`);
check('ToolError 有链接（失败也是一次执行）', has('TE'));
check('ToolError 任务是 error 状态', taskOf('TE')?.status === 'error');
check('带文件产出的 complete 有链接', has('DEV'));
check('「部署完成」这种空 complete 无链接（既无产出也无命令）', !has('DEPLOY'));
check('tool_done 有链接', has('TD'));
check('tool_start 指向配对后的同一个任务（不是自己单独建一条）',
    has('TS') && idx2['TS'] === idx2['TD'], `TS→${idx2['TS']} TD→${idx2['TD']}`);
check('纯一行 message 的 thought_done 无链接（不把面板灌成噪音）', !has('THIN'));
check('带文件产出的 thought_done 有链接', has('FAT'));
check('thought_start / llm_call 无链接', !has('NOISE') && !has('LLM'));

// UBT 任务的输出得真有内容可看，否则点进去是空的，等于白跳
const ubt = taskOf('UBT');
check('UBT 任务输出含命令行与退出码',
    !!ubt && ubt.output.includes('UnrealBuildTool.exe') && ubt.output.includes('exit_code = 0'));
check('UBT 任务带上了耗时（列表里显示成 497870ms）', ubt?.duration_ms === 497870);
check('Playtest 任务输出含用例统计',
    taskOf('PT')?.output.includes('通过 1'));

// 索引里的每个 taskId 都得在任务表里 —— 死链检查
const ids2 = new Set(tasks2.map(t => t.id));
check('构造数据下索引无死链',
    Object.values(idx2).every(v => ids2.has(v)),
    `${Object.keys(idx2).length} 个链接 / ${tasks2.length} 个任务`);

// thought_done 与紧随其后的 complete 报同一批文件时不能建两条
const DUP = [
    { id: 'D1', ticket_id: 'TK-D', action: 'thought_done', created_at: T(1),
      detail: JSON.stringify({ message: '[DevAgent] 完成 develop (100ms)', file_paths: ['a.js', 'b.js'] }) },
    { id: 'D2', ticket_id: 'TK-D', action: 'complete', created_at: T(2),
      detail: JSON.stringify({ message: '开发完成', file_paths: ['a.js', 'b.js'], result_summary: '更全' }) },
];
const dupTasks = build.build([...DUP].reverse());
check('thought_done 与紧随的 complete 报同一批文件时只建一条',
    dupTasks.length === 1, `${dupTasks.length} 条`);
check('保留信息更全的那条（complete）',
    dupTasks[0]?.output.includes('更全'));

// ── 5. 跳转时序：读内存表之前必须等刷新落地 ────────────────────────
const open = body('openTaskFromLog');
check('跳转时走索引取 taskId（tool_start 指向的不是自己）',
    /_TICKET_TASK_INDEX\[ticketId\]/.test(open));
check('先 await 开面板，再读 _CLI_TASKS_MEM',
    open.indexOf('await _openTicketTasksPanel') < open.indexOf('_CLI_TASKS_MEM[taskId]'));
// 挂载函数不是 async，里面的 _refreshTasksPanel 是 fire-and-forget；
// 不在 _openTicketTasksPanel 里补一次 await，就会读到空表 →"点了说找不到"
check('_openTicketTasksPanel 补了 await _refreshTasksPanel()',
    /await _refreshTasksPanel\(\)/.test(body('_openTicketTasksPanel')));
// mem 里有、列表里没有 = 被状态 tab 挡住（建表在过滤之前），自动拨回「全部」
check('任务在内存但行被状态 tab 挡住时，自动切回「全部」',
    /tasks-tab\[data-filter="all"\]/.test(open) && /await _refreshTasksPanel\(\)/.test(open));
check('选中后把行滚进视野', /scrollIntoView/.test(open));

// ── 6. 刷新去重不能吞掉过滤切换 ───────────────────────────────────
const refresh = body('_refreshTasksPanel');
check('在途去重存在', /_tasksRefreshInFlight/.test(refresh));
check('在途期间改了过滤条件会补跑一轮（不能只复用旧 Promise）',
    /_tasksRefreshAgain = true/.test(refresh) && /while \(_tasksRefreshAgain\)/.test(refresh));
check('原函数体搬到 _refreshTasksPanelInner，没被递归调用',
    /async function _refreshTasksPanelInner\(\)/.test(src)
    && !/_refreshTasksPanel\(\)/.test(body('_refreshTasksPanelInner')));

// ── 7. 样式：别和 .log-time 抢那个 margin-left:auto ────────────────
// 选择器可能和 .log-chat-link 合并成一组（两个链接样式完全一样），
// 所以别死认 `.log-task-link {`，允许它出现在逗号选择器里
const rule = /(?:^|,)\s*\.log-task-link\s*(?:,[^{]*)?\{([^}]*)\}/m.exec(css)
          || /\.log-task-link\s*\{([^}]*)\}/.exec(css);
check('.log-task-link 样式已定义', !!rule);
// .log-time 自带 margin-left:auto；两个 auto 兄弟会把剩余空间对半分，
// 链接就飘在 header 正中而不是贴着时间戳
check('.log-task-link 不抢 margin-left:auto', !!rule && !/margin-left:\s*auto/.test(rule[1]));
check('.log-task-link 不参与收缩（窄窗口下不被挤没）',
    !!rule && /flex-shrink:\s*0/.test(rule[1]));
check('有 hover 反馈（否则看不出可点）', /\.log-task-link:hover/.test(css));

console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
process.exit(fail ? 1 : 0);
