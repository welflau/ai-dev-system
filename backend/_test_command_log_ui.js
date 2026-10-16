// 工单命令记录 → 后台面板：前端接线回归
//   cd backend && node _test_command_log_ui.js
//
// 后端现在会把工单执行期跑过的真命令落进 ticket_command_log，并在 timeline 上
// 给对应日志标 `_task_ref`。前端要做的就三件事：优先认那个字段、把真记录并进
// 任务列表、刷新后还能按 id 拉回来。这里对 app.js 源码做正则断言（沿用
// _test_log_task_link.js / _test_tasks_main_tab.js 的既有风格）。

const fs = require('fs');
// app.js 是 CRLF，按 '\n...' 找边界的哨兵都得先归一化
const norm = s => s.replace(/\r\n/g, '\n');
const src = norm(fs.readFileSync('../frontend/app.js', 'utf8'));

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

// ── 1. 真记录优先，伪任务兜底 ──────────────────────────────────────
// 顺序是关键：后端标的 _task_ref 指向真命令（真 argv / exit_code / 完整输出），
// _TICKET_TASK_INDEX 指向前端现编的伪任务（只有日志那句散文）。反过来的话，
// 有真记录的日志仍然点开伪任务，这次改动等于白做。
const lt = body('_logTaskId');
check('_logTaskId 认后端标的 _task_ref', /log\._task_ref/.test(lt));
check('_task_ref 出现在 _TICKET_TASK_INDEX 之前（真记录优先）',
    lt.indexOf('_task_ref') < lt.indexOf('_TICKET_TASK_INDEX'));
check('伪任务兜底路径仍在（40035 条历史日志靠它）',
    /_TICKET_TASK_INDEX\[tid\]/.test(lt));
check('_buildTicketTasksFromLogs 没被删（旧工单链接全靠它）',
    /function _buildTicketTasksFromLogs\(/.test(src));

// openTaskFromLog 只拿得到 (ticketId, logId)，拿不到 item 本身，所以得有索引
check('存在 _TICKET_CMD_REF 索引', /const _TICKET_CMD_REF = \{\}/.test(src));
check('渲染时间轴时填充 _TICKET_CMD_REF',
    /_TICKET_CMD_REF\[tid\] = _TICKET_CMD_REF\[tid\] \|\| \{\}/.test(body('_renderUnifiedTimeline')));
const otl = body('openTaskFromLog');
check('openTaskFromLog 也先查真记录', /_TICKET_CMD_REF\[ticketId\]/.test(otl));
check('openTaskFromLog 里真记录排在伪任务之前',
    otl.indexOf('_TICKET_CMD_REF') < otl.indexOf('_TICKET_TASK_INDEX'));

// ── 2. 列表合并：拉真记录 + 按 log_id 去重 ──────────────────────────
const rp = body('_refreshTasksPanelInner');
check('工单模式拉 /command-logs', /\/command-logs/.test(rp));
check('真记录经 _recordToTask 映射', /_recordToTask\)/.test(rp) || /map\(_recordToTask\)/.test(rp));
// 同一次执行两边都建了项，不去重就显示成两行
check('按 log_id 去重（一次执行不能出现两行）',
    /coveredLogIds/.test(rp) && /dropIds/.test(rp));
check('合并后按时间排序', /localeCompare/.test(rp));

// ── 3. 映射成 cli_task 形状（复用整套渲染的全部理由）────────────────
// 新开一个 type 意味着 _selectTaskItem 的分支、_renderTaskOutput、_formatCliLines、
// _colorLine、复制/显示全部按钮、CSS 全要再写一遍，然后两份渲染各自演化。
const rt = body('_recordToTask');
check('_recordToTask 产出 type:cli_task', /type:\s*'cli_task'/.test(rt));
for (const f of ['id:', 'title:', 'status:', 'output:', 'cmd:', 'duration_ms:', 'created_at:', 'ts:']) {
    check(`_recordToTask 带字段 ${f}`, rt.includes(f));
}
check('_recordToTask 输出里有真命令行（$ 前缀）', /\$ \$\{r\.command/.test(rt));
check('_recordToTask 标注截断', /r\.truncated/.test(rt));
check('timeout 状态单独显示', /timeout/.test(rt));
// 状态只有 running/success/error 三种被列表图标和 tab 过滤认，timeout 得归一
check('timeout/error 都归到 error（列表 tab 只认三种状态）',
    /status === 'success' \? 'success' : 'error'/.test(rt));

// ── 4. 刷新页面后仍能拉回全量 ──────────────────────────────────────
// 内存表刷新就空了，而 /chat/cli-tasks/{id} 查不到 TCMD 记录
const st = body('_selectTaskItem');
check('_selectTaskItem 有 TCMD- 分支', /startsWith\('TCMD-'\)/.test(st));
check('TCMD 分支打 /ticket-command-logs/', /\/ticket-command-logs\//.test(st));
check('TCMD 分支同步进内存表', /_CLI_TASKS_MEM\[task\.id\] = _recordToTask\(/.test(st));
// 分支顺序：内存命中最优先，其次 TCMD，最后才是老的 cli-tasks 接口
check('内存命中仍排在最前', st.indexOf('_CLI_TASKS_MEM[task.id]') < st.indexOf("startsWith('TCMD-')"));
check('TCMD 分支排在 cli-tasks 兜底之前',
    st.indexOf("startsWith('TCMD-')") < st.indexOf('/cli-tasks/'));

console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
process.exit(fail ? 1 : 0);
