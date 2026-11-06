// 后台任务：来源回溯 + 停止按钮
//   cd backend && node _test_tasks_source_stop.js
//
// 全局聊天会把别的项目 pending 工单糊进当前对话分组；没有来源入口
// 也没有就地停止，只能干看着沙漏。这里钉死：
//   1. 工单/CI 按 project:{id} 分组，不跟 CLI session_key 混
//   2. 面板有「来源」「停止」
//   3. 项目组「全部停止」走 cancel-active，不回滚代码

const fs = require('fs');
const norm = s => s.replace(/\r\n/g, '\n');
const src = norm(fs.readFileSync('../frontend/app.js', 'utf8'));
const css = norm(fs.readFileSync('../frontend/styles.css', 'utf8'));
const html = norm(fs.readFileSync('../frontend/index.html', 'utf8'));

let pass = 0, fail = 0;
function check(name, cond, detail = '') {
    if (cond) { pass++; console.log(`[OK] ${name}${detail ? ' -- ' + detail : ''}`); }
    else { fail++; console.log(`[FAIL] ${name}${detail ? ' -- ' + detail : ''}`); }
}

function body(name) {
    const m = new RegExp(`^([ \\t]*)(?:async )?function ${name}\\(`, 'm').exec(src);
    if (!m) throw new Error(`找不到 ${name}`);
    const close = '\n' + m[1] + '}';
    const end = src.indexOf(close, m.index);
    if (end < 0) throw new Error(`找不到 ${name} 的收尾括号`);
    const b = src.slice(m.index, end + close.length);
    if (b.split('\n').length > 450) throw new Error(`${name} 截取过长（${b.split('\n').length} 行）`);
    return b;
}

check('_taskGroupKey 对工单/CI 用 project:{id}',
    /t\.type === 'ticket' \|\| t\.type === 'ci_build'/.test(body('_taskGroupKey'))
    && /project:\$\{t\.project_id\}/.test(body('_taskGroupKey')));
check('_taskGroupKey 对 CLI 才用 session_key',
    /return t\.session_key/.test(body('_taskGroupKey')));

const inner = body('_refreshTasksPanelInner');
check('刷新时用 _taskGroupKey 分组，而不是裸 session_key',
    /const gk = _taskGroupKey\(t\)/.test(inner));
check('新组条件是 gk !== curGroup.key（工单不会粘到当前对话）',
    /gk && gk !== curGroup\.key/.test(inner));
check('组标签走 _taskGroupLabel',
    /_taskGroupLabel\(t\)/.test(inner));
check('组头有「来源」按钮', /tasks-grp-source/.test(inner) && /_openTaskGroupSource/.test(inner));
check('组头有「全部停止」', /tasks-grp-stop/.test(inner) && /_stopTaskGroup/.test(inner));
check('条目有停止按钮', /tpi-stop/.test(inner) && /_stopBackgroundTask/.test(inner));
check('条目上来源 chip 打开项目', /tpi-source/.test(inner) && /_openTaskSource/.test(inner));
check('点选不把整份任务 JSON 塞进 onclick（CI log_tail 会撑爆属性）',
    ! /JSON\.stringify\(t\)/.test(inner)
    && /_selectTaskItem\(_taskFromRow\(this\)\)/.test(inner));
check('停止按钮把 this 交给回查，不依赖可能被清空的内存表',
    /_stopBackgroundTask\(this\)/.test(inner));

const srcFn = body('_openTaskSource');
check('工单来源进入项目并打开工单抽屉',
    /showProjectDetail\(t\.project_id\)/.test(srcFn) && /openTicketDrawer/.test(srcFn));
check('CI 来源进交付页', /switchTab\('cicd'\)/.test(srcFn));

check('_taskCanStop 工单走 _ticketStatusIsStoppable',
    /_ticketStatusIsStoppable/.test(body('_taskCanStop')));
check('_ticketStatusIsStoppable 认 *_in_progress',
    /_in_progress/.test(body('_ticketStatusIsStoppable')));
check('_taskFilterBucket 把 *_in_progress 算进进行中',
    /_in_progress/.test(body('_taskFilterBucket')));

const stopFn = body('_stopBackgroundTask');
check('停止工单走 DELETE（不带 revert，不回滚）',
    /method: 'DELETE'/.test(stopFn) && !/revert=true/.test(stopFn));
check('合成 titk 任务停止也走工单 DELETE，不打 /cli-tasks',
    /_isSyntheticTicketRun/.test(stopFn) && /method: 'DELETE'/.test(stopFn));
check('停止 CI 走 /ci/builds/.../cancel',
    /\/ci\/builds\//.test(stopFn) && /cancel/.test(stopFn));
check('停止 CLI 会 abort 当前流式对话',
    /abortChatStreaming/.test(stopFn));
check('停止 CLI 调 /cli-tasks/{id}/cancel',
    /cli-tasks\/\$\{/.test(stopFn) || /cli-tasks\//.test(stopFn));

const grpStop = body('_stopTaskGroup');
check('项目组全部停止走 cancel-active',
    /tickets\/cancel-active/.test(grpStop));
check('全部停止确认文案说明不回滚',
    /不回滚/.test(grpStop));

check('输出区 header 接收来源/停止 HTML',
    /sourceHtml/.test(body('_renderTaskOutput')) && /actionsHtml/.test(body('_renderTaskOutput')));
check('工单详情分支带上来源和停止',
    /sourceHtml: _taskSourceHtml\(task\)/.test(body('_selectTaskItem'))
    && /actionsHtml: _taskStopHtml\(task\)/.test(body('_selectTaskItem')));

check('CSS 有来源/停止按钮样式',
    /\.tpi-stop/.test(css) && /\.tpi-source/.test(css)
    && /\.cto-stop-btn/.test(css) && /\.tasks-grp-source/.test(css));

check('筛选 tab 后面有条数',
    /function _updateTasksFilterCounts/.test(src)
    && /tasks-tab-count/.test(html)
    && /_updateTasksFilterCounts\(allUnfiltered\)/.test(inner)
    && /_taskMatchesFilter/.test(inner));
check('进行中把 pending 也算进去，和沙漏工单对得上',
    /pending/.test(body('_taskFilterBucket')) && /queued/.test(body('_taskFilterBucket')));

console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
process.exit(fail ? 1 : 0);
