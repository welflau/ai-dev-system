// 用真实 ci_builds.raw_output_tail 跑一遍渲染，断言输出里真有换行结构。
// 上面那个测试断的是"代码结构对"；这个断的是"渲染结果对" ——
// 光看代码没法确认 49 行日志最后真的变成 49 个 .cto-line。
//
//   cd backend && node _test_task_output_render.js
// （需要 _fixture_ci_output.json，由 _dump_ci_output.py 从真实库导出）

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

// 把渲染链路搬进沙箱：_renderTaskOutput → _formatCliLines → _colorLine → _escHtmlSafe
const env = new Function(`
    let _taskOutputShown = { taskId: '', text: '', foldJson: true };
    const _CLI_TASKS_MEM = {};
    const _URL_RE = ${/https?:\/\/[^\s"'<>)]+/g.toString()};
    ${body('_renderTaskOutput')}
    ${body('_formatCliLines')}
    ${body('_colorLine')}
    ${body('_escHtmlSafe')}
    return { render: _renderTaskOutput, shown: () => _taskOutputShown };
`)();

/** 假 DOM 元素，只要一个可写的 innerHTML */
const fakeEl = () => ({ innerHTML: '', scrollTop: 0, scrollHeight: 0 });

const fx = JSON.parse(fs.readFileSync('_fixture_ci_output.json', 'utf8'));
check('fixture 里有真实构建输出', fx.length > 0, `${fx.length} 条`);

for (const b of fx) {
    const lines = b.log_tail.split('\n');
    const el = fakeEl();
    env.render(el, {
        taskId: b.id, status: b.status, statusLabel: `CI: ${b.build_type}`,
        text: b.log_tail, maxLines: 25,
    });
    const html = el.innerHTML;
    const rendered = (html.match(/class="cto-line/g) || []).length;

    // 核心断言：多行输入必须产出多个 .cto-line。bug 版本是一整段文本，这里会是 0。
    const expect = Math.min(lines.length, 25);
    check(`${b.id} (${b.build_type}, ${lines.length} 行) 渲染出 ${expect} 个行元素`,
        rendered === expect, `实际 ${rendered}`);

    // 换行不能只靠 \n 留在文本里 —— 那在普通 div 里就是空格
    const bodyPart = html.slice(html.indexOf('cto-body'));
    check(`${b.id} 行与行之间是元素边界，不是裸 \\n`,
        !/>[^<]*\n[^<]*</.test(bodyPart.replace(/\n\s+/g, '')) || rendered > 1);

    if (lines.length > 25) {
        check(`${b.id} 超长输出折起了前 ${lines.length - 25} 行`,
            html.includes(`隐藏了前 ${lines.length - 25} 行`));
        check(`${b.id} 有「显示全部」入口`, html.includes('_cliOutputShowAll'));
    }
    // UE 日志里有 warning CS0618 这类行，要着色。
    // 只能看**可见的那 25 行** —— 被折起来的头部本来就没渲染
    const visible = lines.slice(-Math.min(lines.length, 25));
    if (visible.some(l => /\bwarning\b/i.test(l))) {
        check(`${b.id} warning 行着色`, html.includes('cto-line-warn'));
    }
    check(`${b.id} 原文进了单槽缓存（复制/展开要回查）`,
        env.shown().text === b.log_tail);
}

// 转义：UE 日志里出现过 <> 和 &，不转义会吞掉内容
const el2 = fakeEl();
env.render(el2, { taskId: 't', text: 'a <b> & "c"\nsecond <script>x</script>' });
check('HTML 特殊字符被转义', !/<b>/.test(el2.innerHTML) && el2.innerHTML.includes('&lt;b&gt;'));
check('内联 script 不会被当标签渲染', !/<script>/.test(el2.innerHTML));

// 空输出不该炸
const el3 = fakeEl();
env.render(el3, { taskId: 't', text: '' });
check('空输出不抛异常', el3.innerHTML.includes('cto-header'));

// 单行输出不该出现截断提示
const el4 = fakeEl();
env.render(el4, { taskId: 't', text: 'only one line' });
check('单行输出没有截断提示', !el4.innerHTML.includes('隐藏了前'));

// Windows 路径里的反斜杠不能被当转义吃掉（UE 日志全是 F:\ADS_Projects\…）
const el5 = fakeEl();
env.render(el5, { taskId: 't', text: 'F:\\ADS_Projects\\TestFPS\\TestFPS.uproject' });
check('Windows 路径原样保留', el5.innerHTML.includes('F:\\ADS_Projects\\TestFPS\\TestFPS.uproject'));

console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
process.exit(fail ? 1 : 0);
