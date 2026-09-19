// 时间轴圆点热区结构回归
//   cd backend && node _test_timeline_dots.js
//
// 背景：圆点原本是 CSS 伪元素（`.log-item::before` / `.timeline-stage::before`），
// **伪元素不在 DOM 里、接不到事件**，所以点上去永远没反应。修法是在圆点位置盖一个
// 真实的透明 <span> 热区。这类改动没法用纯函数测（要 DOM + 布局），所以这里退一步
// 做**结构断言**：热区在每个该有的渲染点都存在、不该有的地方确实没有、
// CSS 侧的三个易错前提（尺寸、层级、不动 padding）都还成立。
//
// 断言的是「不变量」而不是「当前长相」：改样式不会红，
// 但把热区漏掉、把 stopPropagation 删掉、给单行条目加回假圆点，会红。

const fs = require('fs');

const src = fs.readFileSync('../frontend/app.js', 'utf8');
const css = fs.readFileSync('../frontend/styles.css', 'utf8');

let pass = 0, fail = 0;
function check(name, cond, detail = '') {
    if (cond) { pass++; console.log(`[OK] ${name}${detail ? ' — ' + detail : ''}`); }
    else { fail++; console.log(`[FAIL] ${name}${detail ? ' — ' + detail : ''}`); }
}

/** 取一个函数的源码（到下一个顶层 function 为止，够用且不依赖括号配平） */
function body(name) {
    const i = src.indexOf(`function ${name}(`);
    if (i < 0) throw new Error(`找不到 ${name}`);
    const j = src.indexOf('\nfunction ', i + 10);
    return src.slice(i, j < 0 ? src.length : j);
}

// ── 1. 会画圆点的多行条目：必须挂热区
for (const name of ['renderLogItem', '_renderLayerLogItem']) {
    check(`${name} 挂了 li-dot 热区`, body(name).includes('_logDotHotspot()'));
}

// ── 2. 单行条目：不挂热区，且圆点也收掉（不画不能点的点）
for (const name of ['_renderReactToolItem', '_renderSkillStepItem']) {
    check(`${name} 不挂热区（单行摘要，折起来长度不变）`,
        !body(name).includes('_logDotHotspot()'));
}
check('单行条目的圆点已在 CSS 里收掉',
    /\.log-item\.log-react-tool::before[\s\S]{0,140}display:\s*none/.test(css)
    && /\.log-item\.log-skill-step::before[\s\S]{0,140}display:\s*none/.test(css));

// ── 3. 阶段节点热区
check('_renderTimelineStage 挂了 ts-dot 并绑 toggleTimelineStage',
    /class="ts-dot"[\s\S]{0,180}toggleTimelineStage/.test(src));

// ── 4. 每个热区都要拦事件冒泡
// 带 hasExpand 的条目整行挂着 onclick="toggleBlock(...)"，
// 不 stopPropagation 就会「折叠」和「展开详情」同时触发。
const dots = (src.match(/class="(ts|li)-dot"/g) || []).length;
const guarded = (src.match(/(ts|li)-dot"[\s\S]{0,220}?event\.stopPropagation\(\)/g) || []).length;
check('每个热区都带 event.stopPropagation()', dots > 0 && dots === guarded,
    `${guarded}/${dots}`);

check('toggleLogItemCollapse 用 closest 找宿主条目（不依赖 DOM 层级写死）',
    /function toggleLogItemCollapse[\s\S]{0,240}closest\('\.log-item'\)/.test(src));

// ── 5. CSS 前提
const dotRule = /\.ts-dot,\s*\n\.li-dot\s*\{([^}]*)\}/.exec(css);
check('.ts-dot/.li-dot 有实际尺寸（0 尺寸接不到点击）',
    !!dotRule && /width:\s*20px/.test(dotRule[1]) && /height:\s*20px/.test(dotRule[1]));
check('热区 z-index 抬到内容之上', !!dotRule && /z-index:\s*[1-9]/.test(dotRule[1]));
check('热区自身透明（只接事件，不改视觉）',
    !!dotRule && /background:\s*transparent/.test(dotRule[1]));
check('折叠态保留 header 行', /li-collapsed > div:not\(\.log-header\)/.test(css));
// 圆点是 top:16px 绝对定位，不随 padding 走；缩 padding 行变矮，圆点就掉到行外
check('折叠态不动 padding（否则圆点掉出行外）',
    !/\.log-item\.li-collapsed\s*\{[^}]*padding/.test(css));
check('嵌在折叠组里的条目不留隐形热区（那儿的圆点本就 display:none）',
    /\.timeline-group-body \.log-item > \.li-dot\s*\{\s*display:\s*none/.test(css));

console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
process.exit(fail ? 1 : 0);
