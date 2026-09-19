// 拿真实接口返回跑一遍扩展面板搜索（不是合成数据）
//   1) 先抓数据：见 _test_ext_search_live 里的 curl 说明
//   2) node _test_ext_search_live.js
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
function extractConst(name) {
    const m = new RegExp(`const ${name}\\s*=\\s*\\[[\\s\\S]*?\\];`).exec(src);
    if (!m) throw new Error(`找不到 const ${name}`);
    return m[0];
}
const _extSearchQuery = {};
eval([
    extractConst('_EXT_SOURCE_KEYS'), extractConst('_EXT_SEARCH_KEYS'),
    extract('_extHaystack'), extract('_extTokens'), extract('_extItemMatches'),
    extract('_filterExtData'), extract('_extSumSources'),
].join('\n'));

let pass = 0, fail = 0;
function check(name, cond, detail = '') {
    if (cond) { pass++; console.log(`[OK] ${name}${detail ? ' — ' + detail : ''}`); }
    else { fail++; console.log(`[FAIL] ${name}${detail ? ' — ' + detail : ''}`); }
}

const EPS = ['skills', 'commands', 'rules'];
for (const ep of EPS) {
    const f = `_ep_${ep}.json`;
    if (!fs.existsSync(f)) { console.log(`[SKIP] ${ep}: 缺 ${f}`); continue; }
    const data = JSON.parse(fs.readFileSync(f, 'utf8'));
    const total = _extSumSources(data);
    const cid = `live_${ep}`;

    console.log(`\n=== ${ep}: ${total} 条`);

    // 每条都至少能被自己的 name 搜到 —— 搜不到就是有条目「不可达」
    let unreachable = [];
    for (const k of ['builtin', 'project', 'user', 'pack', 'openspec']) {
        for (const it of (data[k] || [])) {
            const nm = it.name || it.id || '';
            if (!nm) continue;
            if (!_extItemMatches(it, _extTokens(nm))) unreachable.push(`${k}/${nm}`);
        }
    }
    check(`${ep}: 每条都能用自己的名字搜到`, unreachable.length === 0,
        unreachable.length ? `${unreachable.length} 条不可达: ${unreachable.slice(0,3).join(', ')}` : `${total} 条全可达`);

    // 关键词过滤：真实数据上必须收窄
    _extSearchQuery[cid] = 'ue5';
    const hit = _filterExtData(cid, data);
    check(`${ep}: 搜 "ue5" 有结果且收窄`, hit.counts.total > 0 && hit.counts.total < total,
        `${total} -> ${hit.counts.total}`);
    check(`${ep}: counts.total 与实际条数一致`, hit.counts.total === _extSumSources(hit));

    // 每条结果都真的含关键词（不是漏筛）
    const bad = [];
    for (const k of ['builtin', 'project', 'user', 'pack', 'openspec']) {
        for (const it of (hit[k] || [])) {
            if (!_extHaystack(it).includes('ue5')) bad.push(it.name);
        }
    }
    check(`${ep}: 结果无误报`, bad.length === 0, bad.length ? bad.slice(0,3).join(', ') : '');

    // 不存在的词 -> 归零
    _extSearchQuery[cid] = 'zzz_nonexistent_qq';
    check(`${ep}: 不存在的词 -> 0`, _extSumSources(_filterExtData(cid, data)) === 0);

    // 原数据不被改
    check(`${ep}: 原数据未被改动`, _extSumSources(data) === total);

    // 性能
    _extSearchQuery[cid] = 'ue';
    const t0 = Date.now();
    for (let i = 0; i < 50; i++) _filterExtData(cid, data);
    const ms = Date.now() - t0;
    check(`${ep}: 50 次过滤 < 500ms`, ms < 500, `${ms}ms`);

    // 多词 AND 在真实数据上真的更窄
    _extSearchQuery[cid] = 'ue5';
    const one = _extSumSources(_filterExtData(cid, data));
    _extSearchQuery[cid] = 'ue5 zzz_nonexistent_qq';
    const two = _extSumSources(_filterExtData(cid, data));
    check(`${ep}: 多词 AND 更窄`, two < one, `${one} -> ${two}`);
}

console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
process.exit(fail ? 1 : 0);
