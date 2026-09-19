// 验证扩展面板搜索：8 个 Tab 各一个搜索框的过滤逻辑
//   node _test_ext_search.js
// 只测纯函数（匹配 / 过滤 / 分词），不碰 DOM。
// 从 app.js 源码里抽函数，避免复制一份走样。

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
// 常量也从源码取，防止测试和实现里的字段列表各写一份
function extractConst(name) {
    const m = new RegExp(`const ${name}\\s*=\\s*\\[[\\s\\S]*?\\];`).exec(src);
    if (!m) throw new Error(`找不到 const ${name}`);
    return m[0];
}

const _extSearchQuery = {};
// 必须一次 eval：分开 eval 的 const 不会互相可见（各自是独立的 eval 作用域）
eval([
    extractConst('_EXT_SOURCE_KEYS'),
    extractConst('_EXT_SEARCH_KEYS'),
    extract('_extHaystack'),
    extract('_extTokens'),
    extract('_extItemMatches'),
    extract('_filterExtData'),
    extract('_extSumSources'),
].join('\n'));

let pass = 0, fail = 0;
function check(name, cond, detail = '') {
    if (cond) { pass++; console.log(`[OK] ${name}${detail ? ' — ' + detail : ''}`); }
    else { fail++; console.log(`[FAIL] ${name}${detail ? ' — ' + detail : ''}`); }
}
const T = (q) => _extTokens(q);

// ================= 1. 分词 =================
check('空关键词 -> 无 token', T('').length === 0 && T('   ').length === 0 && T(null).length === 0);
check('多空格切分', T('  ue5   skill ').join(',') === 'ue5,skill');
check('大小写归一', T('UE5')[0] === 'ue5');

// ================= 2. 字段匹配 =================
const skill = { name: 'ue5-blueprint', description: '蓝图开发规范', source: 'pack', pack_name: 'ue5-dev' };
check('命中 name', _extItemMatches(skill, T('blueprint')));
check('命中中文 description', _extItemMatches(skill, T('蓝图')));
check('命中 pack_name', _extItemMatches(skill, T('ue5-dev')));
check('不命中无关词', !_extItemMatches(skill, T('godot')));
check('多词 AND：都命中', _extItemMatches(skill, T('ue5 蓝图')));
check('多词 AND：只中一个 -> 不算命中', !_extItemMatches(skill, T('ue5 godot')));

// 数组字段：contains / tools / actions / matched_traits
check('命中 contains 数组', _extItemMatches({ name: 'p', contains: ['agents', 'skills'] }, T('skills')));
check('命中 tools 数组（MCP）', _extItemMatches({ name: 'm', tools: ['read_file', 'write_file'] }, T('write_file')));
check('命中 actions 对象数组（Agent）',
    _extItemMatches({ name: 'a', actions: [{ name: 'plan_code_change' }, 'write_file'] }, T('plan_code')));
check('命中 matched_traits', _extItemMatches({ name: 'p', matched_traits: ['UE5', '游戏'] }, T('游戏')));

// Hook 字段
const hook = { name: 'h', event: 'PreToolUse', matcher: 'Bash', command: 'npm run lint' };
check('命中 Hook event', _extItemMatches(hook, T('pretooluse')));
check('命中 Hook matcher', _extItemMatches(hook, T('bash')));
check('命中 Hook command', _extItemMatches(hook, T('lint')));

// Rule globs
check('命中 Rule globs', _extItemMatches({ name: 'r', globs: '**/*.ts' }, T('*.ts')));

// 不搜正文：content / preview 命中不算 —— 否则「这条为什么在结果里」没法解释
check('不搜 content 正文',
    !_extItemMatches({ name: 'x', content: '这里面有 secretword', preview: 'secretword' }, T('secretword')));

// 健壮性
check('null item 不崩', !_extItemMatches(null, T('a')));
check('空 item 不崩', !_extItemMatches({}, T('a')));
check('非字符串字段不崩', _extItemMatches({ name: 'ok', description: 123, tools: [null, 5] }, T('ok')));
check('无 token 时全部通过', _extItemMatches({ name: 'x' }, T('')));

// ================= 3. 整份数据过滤 =================
const data = {
    builtin:  [{ name: 'code-review' }, { name: 'ue5-basics' }],
    project:  [{ name: 'proj-rule', description: 'ue5 项目规范' }],
    user:     [],
    pack:     [{ name: 'p1', pack_name: 'ue5-dev' }, { name: 'p2', pack_name: 'godot-dev' }],
    openspec: [{ name: 'openspec-proposal' }],
    counts:   { total: 6, builtin: 2, project: 1, user: 0, pack: 2, openspec: 1 },
};

_extSearchQuery['t'] = '';
let out = _filterExtData('t', data);
check('无关键词 -> 原对象直接返回（不复制）', out === data);

_extSearchQuery['t'] = 'ue5';
out = _filterExtData('t', data);
check('过滤后 builtin 命中 1', out.builtin.length === 1 && out.builtin[0].name === 'ue5-basics');
check('过滤后 project 命中 1（靠 description）', out.project.length === 1);
check('过滤后 pack 命中 1（靠 pack_name）', out.pack.length === 1 && out.pack[0].name === 'p1');
check('过滤后 openspec 归零', out.openspec.length === 0);
check('counts 同步重算', out.counts.total === 3 && out.counts.pack === 1 && out.counts.openspec === 0,
    JSON.stringify(out.counts));
check('_extSumSources 与 counts.total 一致', _extSumSources(out) === out.counts.total);
check('原数据未被改动', data.builtin.length === 2 && data.counts.total === 6);

_extSearchQuery['t'] = 'zzz-不存在';
out = _filterExtData('t', data);
check('无匹配 -> 各组全空且 total=0',
    _extSumSources(out) === 0 && out.counts.total === 0);

// 面板之间互不干扰：同一份数据，两个面板各自的关键词
_extSearchQuery['a'] = 'ue5';
_extSearchQuery['b'] = 'godot';
check('面板关键词互相隔离',
    _filterExtData('a', data).counts.total === 3 && _filterExtData('b', data).counts.total === 1);

// 缺少某些来源键的数据（Hooks 只有 builtin/project/pack）
_extSearchQuery['h'] = 'bash';
const hookData = { builtin: [hook], project: [], pack: [], counts: { total: 1, builtin: 1 } };
out = _filterExtData('h', hookData);
check('缺 user/openspec 键不崩', out.builtin.length === 1 && out.counts.total === 1);
check('缺失的键不会被凭空造出来', !('openspec' in out) || out.openspec === undefined);

// null data
check('null data 不崩', _filterExtData('t', null) === null);

// ================= 4. 源码层面的接线检查 =================
// 8 个 Tab 都要真的接上搜索框，漏一个就等于用户在那页搜不了
const wired = [
    ['Agent',      "_injectSearchBox(wrapper, 'agentListSettings'"],
    ['MCP',        "_injectSearchBox(wrapper, 'mcpServerList'"],
    ['Skills',     "_injectSearchBox(wrapper, 'skillsListSettings'"],
    ['Commands',   "_injectSearchBox(wrapper, 'commandListSettings'"],
    ['Rules',      "_injectSearchBox(wrapper, 'rulesListSettings'"],
    ['Hooks',      "_injectSearchBox(wrapper, 'hooksListSettings'"],
    ['ConfigPack', '_injectPackSearchBox()'],
    ['OpenSpec',   '_injectOpenSpecSearchBox()'],
];
for (const [tab, needle] of wired) {
    check(`${tab} Tab 已接搜索框`, src.includes(needle));
}

// inline handler 引用的函数必须是全局可达的顶层 function（不能藏在闭包里）
for (const fn of ['_onExtSearch', '_onPackSearch', '_onOpenSpecSearch']) {
    check(`${fn} 是顶层函数（inline onclick 可达）`,
        new RegExp(`^function ${fn}\\(`, 'm').test(src));
}

console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
process.exit(fail ? 1 : 0);
