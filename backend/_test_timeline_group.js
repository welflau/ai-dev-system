// 验证时间轴自动折叠：拿 TK-20260817-39e0d4 的真实 1815 条日志跑
//   node _test_timeline_group.js
// 只测分组算法（纯函数），不碰 DOM。

const fs = require('fs');

// ---- 从 app.js 里抽出被测函数，避免复制一份走样 ----
const src = fs.readFileSync('../frontend/app.js', 'utf8');
function extract(name) {
    const start = src.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`找不到 ${name}`);
    let depth = 0, i = src.indexOf('{', start);
    const from = i;
    for (; i < src.length; i++) {
        if (src[i] === '{') depth++;
        else if (src[i] === '}') { depth--; if (depth === 0) break; }
    }
    return src.slice(start, i + 1);
}
const _TL_MAX_PERIOD = 8;
eval(extract('_timelineSignature'));
eval(extract('_groupTimelineItems'));
eval(extract('_timelineGroupLabel'));

let pass = 0, fail = 0;
function check(name, cond, detail = '') {
    if (cond) { pass++; console.log(`[OK] ${name}${detail ? ' — ' + detail : ''}`); }
    else { fail++; console.log(`[FAIL] ${name}${detail ? ' — ' + detail : ''}`); }
}

// ================= 1. 真实数据 =================
const items = JSON.parse(fs.readFileSync('_tl.json', 'utf8'));
const groups = _groupTimelineItems(items);
const cycles = groups.filter(g => g.type === 'cycle');
const collapsed = cycles.reduce((n, g) => n + g.items.length, 0);

console.log(`\n真实数据: ${items.length} 条 -> ${groups.length} 行`
    + ` (${cycles.length} 个折叠组, 收纳 ${collapsed} 条)`);
console.log(`压缩率: ${(100 - groups.length * 100 / items.length).toFixed(1)}%\n`);

check('条目零丢失',
    groups.reduce((n, g) => n + (g.type === 'single' ? 1 : g.items.length), 0) === items.length);
check('顺序不变', (() => {
    const flat = [];
    for (const g of groups) g.type === 'single' ? flat.push(g.item) : flat.push(...g.items);
    return flat.every((x, i) => x.id === items[i].id);
})());
check('折叠后行数大幅下降', groups.length < items.length * 0.3,
    `${items.length} -> ${groups.length}`);
check('识别出主循环', cycles.some(g => g.repeats >= 100),
    `最大 ${Math.max(...cycles.map(g => g.repeats))}x`);

const top = cycles.slice().sort((a, b) => b.items.length - a.items.length)[0];
const lbl = _timelineGroupLabel(top);
console.log(`\n最大组: ${top.repeats}x ${top.period} 步 = ${top.items.length} 条`);
console.log(`  ${lbl.who} | ${lbl.steps}\n`);
check('最大组周期合理', top.period >= 1 && top.period <= _TL_MAX_PERIOD, `period=${top.period}`);

// ================= 2. 合成用例 =================
const mk = (a, act, msg = '', extra = {}) =>
    ({ agent_type: a, action: act, _message: msg, level: 'info', _type: 'log', ...extra });

// 单周期重复
let g = _groupTimelineItems([mk('A', 'x'), mk('A', 'x'), mk('A', 'x')]);
check('单条重复 3 次 -> 1 组', g.length === 1 && g[0].repeats === 3 && g[0].period === 1);

// 4 步循环 x3
const cyc = [];
for (let i = 0; i < 3; i++) cyc.push(mk('A', 'p'), mk('A', 'q'), mk('A', 'r'), mk('A', 's'));
g = _groupTimelineItems(cyc);
check('4 步循环 x3 -> 1 组', g.length === 1 && g[0].period === 4 && g[0].repeats === 3,
    g.length === 1 ? `period=${g[0].period} repeats=${g[0].repeats}` : `${g.length} 组`);

// 不重复的不该折叠
g = _groupTimelineItems([mk('A', 'a'), mk('B', 'b'), mk('C', 'c')]);
check('无重复 -> 全部单条', g.every(x => x.type === 'single') && g.length === 3);

// 只出现 1 次不折叠（至少 2 轮）
g = _groupTimelineItems([mk('A', 'x'), mk('B', 'y')]);
check('各 1 次 -> 不折叠', g.every(x => x.type === 'single'));

// 数字归一化：0ms / 184698ms 视为同类
g = _groupTimelineItems([
    mk('A', 'llm_call', 'AI调用 0ms, tokens: 1'),
    mk('A', 'llm_call', 'AI调用 184698ms, tokens: 99'),
]);
check('数字归一化后能合并', g.length === 1 && g[0].repeats === 2);

// 不同 agent 不能合并
g = _groupTimelineItems([mk('A', 'x'), mk('B', 'x')]);
check('不同 agent 不合并', g.every(x => x.type === 'single'));

// 不同 level 不合并（error 要单独可见）
g = _groupTimelineItems([mk('A', 'x', '', { level: 'info' }), mk('A', 'x', '', { level: 'error' })]);
check('不同 level 不合并', g.every(x => x.type === 'single'));

// 人写的评论永不合并 —— 人写的东西不能被折叠掉。
// DB 实测 author_type 只有三种：agent 181 / system 47 / **human** 8。
// 这里必须用真实值 'human' 断言 —— 早先按 'user' 写豁免，等于把唯一
// 该豁免的那类漏进折叠里。
g = _groupTimelineItems([
    { _type: 'comment', id: 'c1', author_type: 'human', _message: '同样的话' },
    { _type: 'comment', id: 'c2', author_type: 'human', _message: '同样的话' },
]);
check("author_type=human 的评论永不合并", g.every(x => x.type === 'single'), `${g.length} 组`);
for (const at of ['', 'user', 'unknown_future_value']) {
    g = _groupTimelineItems([
        { _type: 'comment', id: 'c1', author_type: at, _message: '同样的话' },
        { _type: 'comment', id: 'c2', author_type: at, _message: '同样的话' },
    ]);
    check(`author_type='${at}' 按人处理（白名单外一律不折）`,
        g.every(x => x.type === 'single'), `${g.length} 组`);
}
g = _groupTimelineItems([
    { _type: 'comment', id: 'c1', _message: '同样的话' },
    { _type: 'comment', id: 'c2', _message: '同样的话' },
]);
check('评论缺 author_type 时按人处理（不合并）', g.every(x => x.type === 'single'), `${g.length} 组`);

// 机器发的评论**必须**参与合并 —— 里程碑评论是 Agent 每轮自动发的，
// 早先把它们当人写的豁免掉，直接导致 TK-20260918-23a48b 的 5 步周期
// 每轮签名都不同、613 条一条没折（压缩率 0.0%）。
for (const at of ['agent', 'system']) {
    g = _groupTimelineItems([
        { _type: 'comment', id: 'm1', author: 'DevAgent', author_type: at, phase: 'develop', content: '完成 1 个文件' },
        { _type: 'comment', id: 'm2', author: 'DevAgent', author_type: at, phase: 'develop', content: '完成 2 个文件' },
    ]);
    check(`author_type=${at} 的评论参与合并`, g.length === 1 && g[0].repeats === 2,
        g.length === 1 ? `repeats=${g[0].repeats}` : `${g.length} 组`);
}

// agent 和 system 的评论不能互相合并（签名要带 author_type）
g = _groupTimelineItems([
    { _type: 'comment', id: 'm1', author: 'DevAgent', author_type: 'agent', phase: 'develop', content: '一样的话' },
    { _type: 'comment', id: 'm2', author: 'DevAgent', author_type: 'system', phase: 'develop', content: '一样的话' },
]);
check('agent 与 system 评论不互相合并', g.every(x => x.type === 'single'), `${g.length} 组`);

// 机器评论夹在循环中间时，整段要能折起来（真机就是这个形状）
const withComment = [];
for (let i = 0; i < 4; i++) {
    withComment.push(
        mk('DevAgent', 'thought_start'),
        mk('DevAgent', 'thought_done'),
        mk('DevAgent', 'complete'),
        { _type: 'comment', id: `k${i}`, author: 'DevAgent', author_type: 'agent', phase: 'develop', content: `第 ${i} 轮` },
        mk('DevAgent', 'checkpoint'),
    );
}
g = _groupTimelineItems(withComment);
check('评论夹在循环中间仍能折叠', g.length === 1 && g[0].period === 5 && g[0].repeats === 4,
    g.length === 1 ? `period=${g[0].period} repeats=${g[0].repeats}` : `${g.length} 组`);
check('摘要里评论不显示成 ?', g.length === 1 && !_timelineGroupLabel(g[0]).steps.includes('?'),
    g.length === 1 ? _timelineGroupLabel(g[0]).steps : 'n/a');

// 重复段前后的独立条目要保留
g = _groupTimelineItems([mk('A', 'head'), mk('A', 'x'), mk('A', 'x'), mk('A', 'tail')]);
check('循环前后条目保留',
    g.length === 3 && g[0].type === 'single' && g[1].type === 'cycle' && g[2].type === 'single',
    g.map(x => x.type).join(','));

// 边界
check('空数组', _groupTimelineItems([]).length === 0);
check('单条', _groupTimelineItems([mk('A', 'x')]).length === 1);

// 长周期不该被误判（超过 MAX_PERIOD 的循环退化为单条，但不能崩）
const long = [];
for (let i = 0; i < 2; i++) for (let k = 0; k < 12; k++) long.push(mk('A', 'a' + k));
g = _groupTimelineItems(long);
check('超长周期不崩', g.length > 0 && g.reduce((n, x) => n + (x.type === 'single' ? 1 : x.items.length), 0) === 24);

// 性能：真实规模不能卡
const t0 = Date.now();
_groupTimelineItems(items);
const ms = Date.now() - t0;
check('性能可接受', ms < 2000, `${items.length} 条耗时 ${ms}ms`);

console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
process.exit(fail ? 1 : 0);
