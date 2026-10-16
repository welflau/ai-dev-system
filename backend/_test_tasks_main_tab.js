// 后台任务面板进主舞台 Tab —— 结构回归
//   cd backend && node _test_tasks_main_tab.js
//
// 这个改动的要害不是"多一个 Tab"，而是**面板只有一份 DOM**：
// _refreshTasksPanel / _setTasksFilter / _tasksSearch / _selectTaskItem 全靠
// getElementById 取 #tasksPanelList / #tasksPanelOutput / .tasks-tab。
// 一旦克隆出第二份同 id 节点，刷新只会命中文档里靠前的那个（多半是隐藏的那个），
// 表现成"点了没反应" —— 和上次圆点那个毛病同一类。
//
// 所以这里断言的是**搬家语义**而不是长相：搬（appendChild）不是复制（cloneNode）、
// 换 Tab 前先搬走（否则被 host.innerHTML 连根删掉）、回页面视图也搬走、
// 两种宿主的 width/border 冲突都让位了。

const fs = require('fs');
// app.js 是 CRLF。所有按 '\n...' 找边界的正则都必须先归一化，
// 否则 '\n    }\n' 这种哨兵永远匹配不上（实际是 '\r\n    }\r\n'），
// 函数体会一路截到文件末尾 —— 断言照样"通过/失败"，但测的根本不是那个函数。
const norm = s => s.replace(/\r\n/g, '\n');
const src = norm(fs.readFileSync('../frontend/app.js', 'utf8'));
const html = norm(fs.readFileSync('../frontend/index.html', 'utf8'));
const css = norm(fs.readFileSync('../frontend/styles.css', 'utf8'));

let pass = 0, fail = 0;
function check(name, cond, detail = '') {
    if (cond) { pass++; console.log(`[OK] ${name}${detail ? ' -- ' + detail : ''}`); }
    else { fail++; console.log(`[FAIL] ${name}${detail ? ' -- ' + detail : ''}`); }
}

/**
 * 取一个函数的源码。
 * 按**声明处的缩进**找收尾的 `}`：adsShell 里的函数缩进 4 格（收尾 `\n    }`），
 * 顶层函数缩进 0（收尾 `\n}`）。找不到就报错，绝不静默退化成"截到文件尾" ——
 * 那样断言会在一整份 app.js 上匹配，永远是绿的，等于没测。
 */
function body(name) {
    const m = new RegExp(`^([ \\t]*)(?:async )?function ${name}\\(`, 'm').exec(src);
    if (!m) throw new Error(`找不到 ${name}`);
    const close = '\n' + m[1] + '}';
    const end = src.indexOf(close, m.index);
    if (end < 0) throw new Error(`找不到 ${name} 的收尾括号`);
    const b = src.slice(m.index, end + close.length);
    // 兜底：真实函数不可能有上千行；有就是边界找歪了
    if (b.split('\n').length > 400) throw new Error(`${name} 截取过长（${b.split('\n').length} 行），边界找歪了`);
    return b;
}

// ── 1. tasks 作为一种 Tab 类型接进 openMain
check("openMain 认识 type:'tasks'", /tab\.type === 'tasks'/.test(body('openMain')));
check('tasks Tab 用固定 id（面板只有一个 DOM，不能按 ticket 分身）',
    /id = 'tasks:panel'/.test(src));
check('Tab 条给 tasks 配了图标', /t\.type === 'tasks' \? '🔄'/.test(src));

// ── 2. 搬家，不是复制 —— 这条是整个改动的地基
const mount = body('_mountTasksPane');
check('_mountTasksPane 用 appendChild 搬真身', /host\.appendChild\(panel\)/.test(mount));
check('_mountTasksPane 不克隆节点（克隆会造出同 id 的第二份）',
    !/cloneNode/.test(mount));
check('搬家前记住原位，关 Tab 能放回侧栏', /dataset\.homeParent/.test(mount));
check('_evictTasksPane 把面板还给原宿主',
    /panel\.parentElement !== home\) home\.appendChild\(panel\)/.test(body('_evictTasksPane')));

// ── 3. 生命周期：三条出口都要先搬走
const loader = body('_loadMainTabContent');
check('切到非 tasks Tab 前先搬走（否则被 host.innerHTML 删掉）',
    /if \(tab\.type !== 'tasks'\) _evictTasksPane\(\)/.test(loader));
// 注意锚点要用**赋值语句**而不是裸字符串 'host.innerHTML'：
// 上一行的注释里就写着 "下面那句 host.innerHTML = ... 会把它连根删掉"，
// 按裸字符串找会先命中注释，量出来的顺序是假的。
check('tasks 分支在 host.innerHTML 覆盖之前就 return',
    loader.indexOf('_mountTasksPane(tab, host)') < loader.indexOf('host.innerHTML = `'),
    `mount@${loader.indexOf('_mountTasksPane(tab, host)')} < wipe@${loader.indexOf('host.innerHTML = `')}`);
check('回到页面视图时也搬走（host 整块隐藏，面板不能陪葬）',
    /_evictTasksPane\(\);/.test(body('_renderMainWorkspace')));
// closeMainTab / closeAllMainTabs 都走 _renderMainWorkspace，由上一条覆盖
check('closeMainTab 经由 _renderMainWorkspace 触发搬回',
    /_renderMainWorkspace\(\);/.test(body('closeMainTab')));

// ── 4. 两种宿主的样式冲突都让位了
const rule = /#tasksSidePanel\.tasks-in-main-ws\s*\{([^}]*)\}/.exec(css);
check('主舞台形态覆盖了侧栏写死的 width:400px',
    !!rule && /width:\s*auto\s*!important/.test(rule[1]));
check('主舞台形态放开 flex-shrink（否则窄窗口顶出横向滚动条）',
    !!rule && /flex-shrink:\s*1/.test(rule[1]));
check('主舞台形态去掉 border-left（左边已无聊天区）',
    !!rule && /border-left:\s*none/.test(rule[1]));
check('index.html 里重复的 display:none 已清掉',
    !/id="tasksSidePanel"[^>]*display:none;[^>]*display:none;/.test(html));

// ── 5. 入口分发：默认主舞台，壳层不可用时退回侧栏
const hostMode = body('_tasksHostMode');
check('壳层没起来时退回侧栏（项目列表页/聊天全屏没有主舞台）',
    /isProjectShell\(\)/.test(hostMode) && /chat-fullscreen/.test(hostMode));
check('_openTasksPanel 按宿主分发', /_tasksHostMode\(\) === 'main'/.test(body('_openTasksPanel')));
check('工单版入口同样分发（不再硬写侧栏）',
    /_tasksHostMode\(\) === 'main'/.test(body('_openTicketTasksPanel')));
check('✕ 两种形态都能关', /tasks-in-main-ws/.test(body('_closeTasksSplitPane')));
check('提供了宿主切换入口', /function _toggleTasksHost/.test(src)
    && /onclick="_toggleTasksHost\(\)"/.test(html));
// ⇄ 是双向箭头，看不出"按下去会去哪"；两个宿主各自挂载后都要刷一次文案
check('切换钮文案随宿主更新', /function _syncTasksHostBtn/.test(src)
    && /_syncTasksHostBtn\(\)/.test(body('_mountTasksPane'))
    && /_syncTasksHostBtn\(\)/.test(body('_openTasksInSidePanel')));
check('切到侧栏时先关主舞台 Tab（不能两个宿主同时认领）',
    /closeMainTab\('tasks:panel'\)/.test(body('_toggleTasksHost')));

// ── 6. 面板内部的 id 引用没被动过（搬家的前提是这些还成立）
for (const id of ['tasksPanelList', 'tasksPanelOutput', 'tasksFilterTabs']) {
    const n = (html.match(new RegExp(`id="${id}"`, 'g')) || []).length;
    check(`#${id} 在 index.html 里仍然唯一`, n === 1, `${n} 处`);
}

console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
process.exit(fail ? 1 : 0);
