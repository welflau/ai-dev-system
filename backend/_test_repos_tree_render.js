// 把真实仓库树数据灌进 renderFileTree / toggleTreeDir，断言渲染结果对。
// 上面的 _test_repos_tab.js 断的是"代码结构对"；这个断的是"跑起来对" ——
// 光看代码看不出"点开 Engine 只发一次请求"「第二次展开不再发请求」这类行为。
//
//   cd backend && node _test_repos_tree_render.js
// （需要 _fixture_repo_tree.json，由 _dump_repo_tree.py 从真实项目 OG 导出）

const fs = require('fs');
const norm = s => s.replace(/\r\n/g, '\n');
const src = norm(fs.readFileSync('../frontend/app.js', 'utf8'));

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
    return src.slice(m.index, end + close.length);
}

const fx = JSON.parse(fs.readFileSync('_fixture_repo_tree.json', 'utf8'));
const levels = fx.levels;

// ── 沙箱：只搬进树渲染那几个函数，请求层用假的 ──────────────────
const requests = [];
const env = new Function('levels', 'requests', `
    const escapeHtml = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
        .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
    const getFileIcon = () => '📄';
    const formatFileSize = n => n + 'B';
    // 拦住请求：记录被请求的路径，直接吐 fixture
    async function _fetchRepoLevel(rel) {
        requests.push(rel);
        const lv = levels[rel];
        if (!lv) throw new Error('fixture 里没有这一层: ' + rel);
        return lv;
    }
    ${body('renderFileTree')}
    ${body('toggleTreeDir')}
    ${body('_truncHintHtml')}
    return { renderFileTree, toggleTreeDir, requests };
`)(levels, requests);

// ── 极简 DOM：够 toggleTreeDir 用就行 ───────────────────────────
function makeDir(dirPath, depth) {
    const children = { classList: cl(['tree-children', 'collapsed']), innerHTML: '' };
    const el = {
        dataset: { dirPath, depth: String(depth), loaded: '0', hasChildren: '1' },
        classList: cl(['tree-item', 'tree-dir']),
        nextElementSibling: children,
        querySelector: sel => sel === '.tree-arrow' ? arrow : icon,
    };
    const arrow = { textContent: '▸' };
    const icon = { textContent: '📁' };
    el._arrow = arrow; el._icon = icon; el._children = children;
    return el;
}
function cl(init) {
    const set = new Set(init);
    return {
        add: c => set.add(c), remove: c => set.delete(c),
        contains: c => set.has(c),
        toggle(c) { if (set.has(c)) { set.delete(c); return false; } set.add(c); return true; },
    };
}

// ── 1. 根层渲染 ─────────────────────────────────────────────────
const rootHtml = env.renderFileTree(levels[''].entries, 0);
const dirCount = (rootHtml.match(/class="tree-item tree-dir"/g) || []).length;
const fileCount = (rootHtml.match(/class="tree-item tree-file"/g) || []).length;
const srcDirs = levels[''].entries.filter(e => e.type === 'directory').length;
const srcFiles = levels[''].entries.filter(e => e.type === 'file').length;
check('根层目录数对得上', dirCount === srcDirs, `${dirCount} / ${srcDirs}`);
check('根层文件数对得上', fileCount === srcFiles, `${fileCount} / ${srcFiles}`);
check('没有条目被静默丢掉', dirCount + fileCount === levels[''].entries.length,
    `${dirCount + fileCount} / ${levels[''].entries.length}`);

// 懒加载的定义：渲染完根层，子容器全是空的
const emptyChildren = (rootHtml.match(/<div class="tree-children collapsed"><\/div>/g) || []).length;
check('每个目录都有一个空的折叠子容器（证明是懒加载不是全量）',
    emptyChildren === dirCount, `${emptyChildren} / ${dirCount}`);
check('渲染结果里不含深层路径（根层只渲染一层）',
    !rootHtml.includes('Engine/Source'), '');
check('目录排在文件前面',
    rootHtml.indexOf('tree-file') > rootHtml.lastIndexOf('tree-dir'));
check('Engine 目录带 data-dir-path', /data-dir-path="Engine"/.test(rootHtml));

// ── 2. 点开一个目录：只发一次请求 ───────────────────────────────
(async () => {
    requests.length = 0;
    const el = makeDir('Engine', 0);
    await env.toggleTreeDir(el);

    check('展开 Engine 发了一次请求', requests.length === 1, JSON.stringify(requests));
    check('请求的是 Engine 这一层', requests[0] === 'Engine');
    check('展开后标记 loaded=1', el.dataset.loaded === '1');
    check('展开后子容器不再折叠', !el._children.classList.contains('collapsed'));
    check('箭头翻成展开态', el._arrow.textContent === '▾', el._arrow.textContent);
    check('图标翻成打开态', el._icon.textContent === '📂');
    const n = (el._children.innerHTML.match(/class="tree-item/g) || []).length;
    check('Engine 下的条目都渲染出来了', n === levels['Engine'].entries.length,
        `${n} / ${levels['Engine'].entries.length}`);
    check('子层能看到 Source', /data-dir-path="Engine\/Source"/.test(el._children.innerHTML));
    // 子层缩进要比父层深一级，否则树看起来是平的
    check('子层缩进 +1', /--depth:1/.test(el._children.innerHTML));

    // 收起再展开：不能再发请求（这是懒加载缓存的意义）
    requests.length = 0;
    await env.toggleTreeDir(el);
    check('收起不发请求', requests.length === 0);
    check('收起后子容器折叠', el._children.classList.contains('collapsed'));
    await env.toggleTreeDir(el);
    check('二次展开不再发请求（内容已缓存在 DOM 里）', requests.length === 0,
        JSON.stringify(requests));

    // ── 3. 空目录不发请求 ───────────────────────────────────────
    requests.length = 0;
    const emptyEl = makeDir('不存在的目录', 0);
    emptyEl.dataset.hasChildren = '0';
    await env.toggleTreeDir(emptyEl);
    check('空目录点了不发请求', requests.length === 0);
    check('空目录不会被误标成已加载', emptyEl.dataset.loaded === '0');

    // ── 4. 请求失败：给出错误提示且能重试 ───────────────────────
    const badEl = makeDir('fixture里没有的路径', 0);
    await env.toggleTreeDir(badEl);
    check('加载失败时渲染错误提示', /tree-load-error/.test(badEl._children.innerHTML),
        badEl._children.innerHTML.slice(0, 60));
    check('失败后不卡在 loading 态', !badEl.classList.contains('loading'));

    // ── 5. 截断提示 ─────────────────────────────────────────────
    // Engine/Content/Editor/Slate/Icons 真实有 1098 项，后端只给前 500
    const big = levels['Engine/Content/Editor/Slate/Icons'];
    if (big) {
        check('fixture 里确实有一层被截断', big.truncated === true,
            `${big.entries.length} / ${big.total}`);
        requests.length = 0;
        const bigEl = makeDir('Engine/Content/Editor/Slate/Icons', 2);
        await env.toggleTreeDir(bigEl);
        const h = bigEl._children.innerHTML;
        check('截断层渲染出提示条', /class="tree-truncated"/.test(h));
        check('提示里写了真实总数', h.includes(String(big.total)), `total=${big.total}`);
        const shown = (h.match(/class="tree-item/g) || []).length;
        check('截断层只渲染返回的那 500 条', shown === big.entries.length,
            `${shown} / ${big.entries.length}`);
    }

    // ── 6. 老接口数据（/git/tree 带 children）仍能渲染 ───────────
    // _fetchRepoLevel 在没识别到仓库时会退回 /git/tree，那份数据是带 children 的
    const legacy = [
        { name: 'src', type: 'directory', path: 'src', children: [
            { name: 'a.js', type: 'file', path: 'src/a.js', size: 10 },
        ] },
        { name: 'README.md', type: 'file', path: 'README.md', size: 20 },
    ];
    const lh = env.renderFileTree(legacy, 0);
    check('老接口的 children 直接渲染出来', /src\/a\.js/.test(lh));
    check('老接口的节点标记成已加载（别再去拉一次）', /data-loaded="1"/.test(lh));

    console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
    process.exit(fail ? 1 : 0);
})();
