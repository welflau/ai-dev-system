// 后台任务输出区排版 —— 回归
//   cd backend && node _test_task_output_format.js
//
// 症状：后台任务面板选中 `CI: package_client`，4415 字符 / 49 行的 UE 打包日志
// 糊成一整段没有任何换行（截图见 dev-notes/2026-09-19_02）。
//
// 根因：#tasksPanelOutput 是个普通 <div>，**没有 white-space:pre-wrap**。
// _selectTaskItem 四个分支里只有 cli_task 走 _renderCliTaskOutput（内部把每行包成
// .cto-line，那个 class 自带 pre-wrap）；ticket / ci_build / 兜底 JSON 三个分支
// 直接 `outputEl.textContent = '…\n…'` —— \n 在普通 div 里就是空格。
//
// 修法是让四个分支共用 _renderTaskOutput。本测试钉死的就是"不许再有人绕过它"。

const fs = require('fs');
// app.js 是 CRLF，按 '\n...' 找边界的哨兵都得先归一化
const norm = s => s.replace(/\r\n/g, '\n');
const src = norm(fs.readFileSync('../frontend/app.js', 'utf8'));
const css = norm(fs.readFileSync('../frontend/styles.css', 'utf8'));
const html = norm(fs.readFileSync('../frontend/index.html', 'utf8'));

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
    if (b.split('\n').length > 200) throw new Error(`${name} 截取过长（${b.split('\n').length} 行），边界找歪了`);
    return b;
}

// ── 1. 核心：四个分支一个都不能绕过统一渲染 ────────────────────────
const sel = body('_selectTaskItem');
// 这是 bug 本体：任何 `outputEl.textContent = ` 带 \n 的赋值都会糊成一段
const textAssigns = sel.match(/outputEl\.textContent\s*=\s*[^;]+/g) || [];
const multiline = textAssigns.filter(a => a.includes('\\n'));
check('没有任何分支用 textContent 输出多行文本（\\n 在普通 div 里就是空格）',
    multiline.length === 0, multiline.length ? multiline[0].slice(0, 80) : '');
// textContent 只允许用在单行提示上（'加载中…' / '（暂无日志）' / 报错）
check('剩下的 textContent 都是单行提示', textAssigns.length <= 4,
    `${textAssigns.length} 处`);

for (const t of ['ticket', 'ci_build']) {
    const i = sel.indexOf(`'${t}'`);
    const next = sel.indexOf('} else', i);
    const branch = sel.slice(i, next > 0 ? next : undefined);
    check(`${t} 分支走 _renderTaskOutput`, /_renderTaskOutput\(outputEl, \{/.test(branch));
}
// 兜底分支（认不出的 type）在最后一个 else 里
const tail = sel.slice(sel.lastIndexOf('} else {'));
check('兜底分支（未知 type）也走 _renderTaskOutput',
    /_renderTaskOutput\(outputEl, \{/.test(tail));
check('cli_task 分支仍走 _renderCliTaskOutput（内部转调统一入口）',
    /_renderCliTaskOutput\(task\.id, outputEl\)/.test(sel));
check('_renderCliTaskOutput 复用统一入口，没有自己拼一套 HTML',
    /_renderTaskOutput\(outputEl, \{/.test(body('_renderCliTaskOutput')));

// ── 2. 换行归 .cto-line 负责，不是父容器 ───────────────────────────
const lineRule = /\.cto-line\s*\{([^}]*)\}/.exec(css);
check('.cto-line 有 white-space:pre-wrap（换行真正生效的地方）',
    !!lineRule && /white-space:\s*pre-wrap/.test(lineRule[1]));
// 长路径要能断，但别用 break-all 把普通单词从中间劈开
check('.cto-line 用 overflow-wrap:anywhere 而不是 word-break:break-all',
    !!lineRule && /overflow-wrap:\s*anywhere/.test(lineRule[1])
    && !/word-break:\s*break-all/.test(lineRule[1]));
// 关键：父容器**不能**加 pre-wrap —— innerHTML 模板里 div 间的缩进会变成可见空行
const panelDiv = /id="tasksPanelOutput"[^>]*style="([^"]*)"/.exec(html);
check('#tasksPanelOutput 没有 white-space:pre-wrap（否则模板缩进变成空行）',
    !!panelDiv && !/white-space:\s*pre/.test(panelDiv[1]));

// ── 3. 统一入口本身 ───────────────────────────────────────────────
const r = body('_renderTaskOutput');
check('每行包成 .cto-line（经 _formatCliLines）', /_formatCliLines\(/.test(r));
check('保留 \\n 切行', /text\.split\('\\n'\)/.test(r));
check('输出转义（UE 日志里有 <>&，不转义会吞内容甚至注入）',
    /_escHtmlSafe\(/.test(body('_colorLine')));
check('长输出默认截断，可展开', /hiddenCount/.test(r) && /_cliOutputShowAll/.test(r));
check('无 taskId 时不渲染复制按钮（点了也回查不到原文）',
    /const copyBtn = taskId/.test(r));
// 状态样式三态齐全，否则 running 的构建显示成"完成"
check('状态三态（running / error / done）都映射到已有 .cto-status 样式',
    /'running'/.test(r) && /'error'/.test(r) && /'done'/.test(r));
check('blocked 也算失败态（工单状态里有它）', /blocked/.test(r));
check('elapsed 为 "?" 时不显示（后端算不出耗时就返回 "?"）',
    (sel.match(/task\.elapsed !== '\?'/g) || []).length >= 2);

// ── 4. 复制 / 展开要能拿到非 cli_task 的原文 ───────────────────────
// ticket 与 ci_build 类任务不在 _CLI_TASKS_MEM 里，只查内存表会拿到空字符串
const txt = body('_taskOutputText');
check('_taskOutputText 先查内存表', /_CLI_TASKS_MEM\[taskId\]/.test(txt));
check('_taskOutputText 回退单槽缓存（ticket / ci_build 不在内存表里）',
    /_taskOutputShown\.taskId === taskId/.test(txt));
check('复制走 _taskOutputText', /_taskOutputText\(taskId\)/.test(body('_cliOutputCopyAll')));
check('展开全部走 _taskOutputText', /_taskOutputText\(taskId\)/.test(body('_cliOutputShowAll')));
check('统一入口会写入单槽缓存', /_taskOutputShown = \{ taskId, text, foldJson \}/.test(r));
check('_taskOutputShown 只声明一次（重复 let 会让整个文件报错）',
    (src.match(/^let _taskOutputShown/gm) || []).length === 1);

// ── 5. JSON 折叠可关闭 ────────────────────────────────────────────
// 兜底分支传的本来就是一整块 JSON，折起来屏幕上只剩一行 summary = 等于没显示
const fmt = body('_formatCliLines');
check('_formatCliLines 支持 foldJson=false', /foldJson = true/.test(fmt));
check('foldJson=false 时整段按普通行渲染',
    /if \(!foldJson\) return lines\.map/.test(fmt));
check('兜底分支关掉 JSON 折叠', /foldJson: false/.test(tail));
// 工单日志每行是 [时间] 前缀，不是 JSON，折它只会误判
const ticketBranch = sel.slice(sel.indexOf("'ticket'"), sel.indexOf('} else'));
check('工单日志分支关掉 JSON 折叠', /foldJson: false/.test(ticketBranch));
check('工单日志不截到 25 行（接口已 limit=200）', /maxLines: 200/.test(ticketBranch));

// ── 6. flushJson 的 catch 必须拿到原始行（曾经静默丢行）────────────
// 原实现把 `jsonBuf = []` 写在 try 之前，catch 里 `jsonBuf.map(...)` 在**空数组**
// 上跑 —— "像 JSON 但解析不过"的行被静默丢掉。UE 打包日志每行都以 `[package]`
// 开头，全部命中 `[` 探测，18 行只渲染出 12 行、70 行只剩 15 行。
// 排版修好了、行数却对不上，比糊成一段更难发现。
check('flushJson 先取出待处理行再清空 buffer', /const pending = jsonBuf;/.test(fmt));
check('catch 分支用 pending 而不是已清空的 jsonBuf',
    /catch \{[\s\S]{0,120}pending\.map/.test(fmt) && !/catch \{[\s\S]{0,120}jsonBuf\.map/.test(fmt));
check('try 里也用 pending 拼原文', /JSON\.parse\(pending\.join/.test(fmt));

console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
process.exit(fail ? 1 : 0);
