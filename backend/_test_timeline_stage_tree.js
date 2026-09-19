// 验证时间轴阶段树：拿 TK-20260918-23a48b 的真实 630 条（后端已标 _stage）跑
//   node _test_timeline_stage_tree.js
// 只测纯函数（分段 / 默认展开 / 折叠组 id 回查），不碰 DOM。
//
// fixture 用 _tl_stage.json（含 timeline + stage_groups），由
//   python -c "... get_ticket_timeline('TK-20260918-23a48b') ..." 生成。

const fs = require('fs');

const src = fs.readFileSync('../frontend/app.js', 'utf8');
function extract(name) {
    const start = src.indexOf(`function ${name}(`);
    if (start < 0) throw new Error(`找不到 ${name}`);
    let depth = 0, i = src.indexOf('{', start);
    for (; i < src.length; i++) {
        if (src[i] === '{') depth++;
        else if (src[i] === '}') { depth--; if (depth === 0) break; }
    }
    return src.slice(start, i + 1);
}
const _TL_MAX_PERIOD = 8;
let _lastStageGroups = [];
let _lastTimelineItems = null;
let _stageOpenState = {};
let _expandedTimelineGroups = new Set();
const escHtml = s => String(s == null ? '' : s).replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
eval(extract('_timelineSignature'));
eval(extract('_groupTimelineItems'));
eval(extract('_timelineGroupLabel'));
eval(extract('_renderTimelineGrouped'));
eval(extract('_renderTimelineCycle'));
eval(extract('renderTimelineItem'));
eval(extract('_fmtTime'));
eval(extract('_timelineStageSegments'));
eval(extract('_renderTimelineStageTree'));
eval(extract('_stageDefaultOpen'));
eval(extract('_renderTimelineStage'));
eval(extract('_timelineStagePool'));
eval(extract('_findTimelineGroupById'));
// renderTimelineItem 里会调到的渲染函数：这里只关心分组算法，桩掉即可
function renderCommentBubble(c) { return `<div class="cmt">${escHtml(c.content || '')}</div>`; }
function renderLogItem(l) { return `<div class="log-item">${escHtml(l._message || '')}</div>`; }

let pass = 0, fail = 0;
function check(name, cond, detail = '') {
    if (cond) { pass++; console.log(`[OK] ${name}${detail ? ' — ' + detail : ''}`); }
    else { fail++; console.log(`[FAIL] ${name}${detail ? ' — ' + detail : ''}`); }
}

// ================= 1. 真实数据 =================
const raw = JSON.parse(fs.readFileSync('_tl_stage.json', 'utf8'));
_lastTimelineItems = raw.timeline;
_lastStageGroups = raw.stage_groups;
const primary = raw.timeline.filter(i => i._tier === 'primary' || i._type === 'comment');
const segs = _timelineStageSegments(primary);

console.log(`\n真实数据: ${primary.length} 条主轴 -> ${segs.length} 个阶段段落`);
for (const s of segs) {
    console.log(`  [${s.groupName || '未归类'}] ${s.stageName.padEnd(10)} ${String(s.items.length).padStart(4)} 条`);
}
console.log();

check('条目零丢失', segs.reduce((n, s) => n + s.items.length, 0) === primary.length,
    `${segs.reduce((n, s) => n + s.items.length, 0)} vs ${primary.length}`);
check('顺序不变', (() => {
    const flat = [];
    for (const s of segs) flat.push(...s.items);
    return flat.every((x, i) => x.id === primary[i].id);
})());
check('段数合理（远小于条目数，也不止一段）',
    segs.length > 1 && segs.length < primary.length / 10, `${segs.length} 段`);
check('每段内 _stage 一致', segs.every(s => s.items.every(i => (i._stage || null) === s.stage)));
check('相邻段 _stage 不同', segs.every((s, i) => i === 0 || s.stage !== segs[i - 1].stage));
check('阶段名不是裸 id（取到了 SOP 的 name）',
    segs.filter(s => s.stage).every(s => s.stageName !== s.stage),
    segs.filter(s => s.stage && s.stageName === s.stage).map(s => s.stage).join(',') || '全部有中文名');
check('归属大组能解析出名字',
    segs.filter(s => s.group).every(s => s.groupName),
    segs.filter(s => s.group && !s.groupName).map(s => s.group).join(',') || 'ok');

// 关键：这张单的实际推进序，按大组折会乱序 —— 验证按阶段折是对的
const order = segs.map(s => s.stage).filter(Boolean);
const iCr = order.indexOf('code_review'), iDp = order.indexOf('deploy_ue');
check('code_review 确实排在 deploy_ue 之后（证明不能按大组折）',
    iCr > iDp && iDp >= 0, `deploy_ue@${iDp} < code_review@${iCr}`);

// 默认展开：最后一段展开，中间已完成的收起
check('最后一段默认展开', _stageDefaultOpen(segs[segs.length - 1], true));
const midClosed = segs.slice(0, -1).filter(s => !_stageDefaultOpen(s, false));
check('中间无错阶段默认收起', midClosed.length > 0, `${midClosed.length}/${segs.length - 1} 段收起`);

// 渲染：不抛异常 + 收起的阶段不铺内容（630 条一次全渲染会卡）
const html = _renderTimelineStageTree(primary);
check('渲染不抛异常且有内容', html.length > 0);
check('阶段节点数与段数一致',
    (html.match(/class="timeline-stage[ "]/g) || []).length === segs.length,
    `${(html.match(/class="timeline-stage[ "]/g) || []).length} vs ${segs.length}`);
const closedCount = (html.match(/style="display:none"/g) || []).length;
check('收起的阶段 body 为空（懒渲染）', closedCount >= midClosed.length,
    `${closedCount} 个 display:none`);

// 折叠组 id 回查：阶段内的循环组必须能找回来（正则改过，最容易在这里坏）
const cycleIds = [...html.matchAll(/id="(tlg-p\d+-\d+)"/g)].map(m => m[1]);
check('阶段内存在折叠组（死循环那 114 轮）', cycleIds.length > 0, `${cycleIds.length} 个`);
check('阶段内折叠组 id 都能回查到',
    cycleIds.every(id => _findTimelineGroupById(id) !== null),
    cycleIds.filter(id => !_findTimelineGroupById(id)).join(',') || '全部命中');
const g0 = _findTimelineGroupById(cycleIds[0]);
if (g0) console.log(`  回查到: period=${g0.period} x${g0.repeats} -> ${_timelineGroupLabel(g0).steps}`);
// 二级日志池（prefix 's'）不能被新正则弄坏
check("二级日志 id 'tlg-s-N' 仍可回查（不回归）", (() => {
    const sec = _lastTimelineItems.filter(i => i._tier === 'secondary' && i._type !== 'comment');
    const gs = _groupTimelineItems(sec);
    const k = gs.findIndex(x => x.type === 'cycle');
    return k < 0 || _findTimelineGroupById(`tlg-s-${k}`) !== null;
})());
check('不存在的 id 回查返回 null', _findTimelineGroupById('tlg-p99-0') === null
    && _findTimelineGroupById('garbage') === null);

// ================= 2. 合成用例 =================
const mk = (stage, extra = {}) => ({
    _type: 'log', _tier: 'primary', level: 'info', agent_type: 'A', action: 'x',
    _message: 'm', _stage: stage, _stage_name: stage ? stage + '名' : undefined,
    _stage_group: stage ? 'gk' : null, ...extra,
});
_lastStageGroups = [{ key: 'gk', name: '大组', icon: '🧪' }];

let s = _timelineStageSegments([mk('a'), mk('a'), mk('b'), mk('a')]);
check('返工二次进入同阶段 -> 分成两段（时序优先）',
    s.length === 3 && s.map(x => x.stage).join(',') === 'a,b,a',
    s.map(x => x.stage).join(','));

s = _timelineStageSegments([mk(null), mk(null)]);
check('无 _stage 的条目归到「未归类」段',
    s.length === 1 && s[0].stage === null && s[0].stageName === '未归类');
check('未归类段 groupName 为空（不乱认大组）', s[0].groupName === '');

check('空数组不崩', _timelineStageSegments([]).length === 0);

// 后端没标阶段（无 traits 项目）→ 必须退回平铺，不能变空白
const unst = [
    { _type: 'log', _tier: 'primary', level: 'info', agent_type: 'A', action: 'x', _message: 'm' },
    { _type: 'log', _tier: 'primary', level: 'info', agent_type: 'A', action: 'y', _message: 'm' },
];
const flatHtml = _renderTimelineStageTree(unst);
check('未标阶段时退回平铺渲染',
    flatHtml.length > 0 && !flatHtml.includes('timeline-stage'),
    flatHtml.includes('timeline-stage') ? '错误地建了树' : '平铺');

// 只有一段时不建树（避免为了树而树）
const oneStage = [mk('a'), mk('a')];
check('只有一个阶段时不建树',
    !_renderTimelineStageTree(oneStage).includes('timeline-stage'));

// 出错的中间阶段要默认展开（错误不该被藏在收起的节点里）
check('含 error 的中间阶段默认展开',
    _stageDefaultOpen({ items: [mk('a', { level: 'error' })] }, false));
check('含 warning 的中间阶段默认展开',
    _stageDefaultOpen({ items: [mk('a', { level: 'warning' })] }, false));
check('全 info 的中间阶段默认收起',
    !_stageDefaultOpen({ items: [mk('a')] }, false));

// 性能
_lastTimelineItems = raw.timeline;
_lastStageGroups = raw.stage_groups;
const t0 = Date.now();
_renderTimelineStageTree(primary);
const ms = Date.now() - t0;
check('性能可接受', ms < 2000, `${primary.length} 条耗时 ${ms}ms`);

console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
process.exit(fail ? 1 : 0);
