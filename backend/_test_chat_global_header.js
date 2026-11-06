/**
 * 全局 AI 助手标题栏：不要把磁盘路径显示成当前工作区
 *   cd backend && node _test_chat_global_header.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const app = fs.readFileSync(path.join(__dirname, '../frontend/app.js'), 'utf8').replace(/\r\n/g, '\n');

let pass = 0, fail = 0;
function check(name, cond, detail = '') {
    if (cond) { pass++; console.log(`[OK] ${name}${detail ? ' -- ' + detail : ''}`); }
    else { fail++; console.log(`[FAIL] ${name}${detail ? ' -- ' + detail : ''}`); }
}

function extract(sig) {
    const start = app.indexOf(sig);
    if (start < 0) throw new Error(`找不到 ${sig}`);
    let i = app.indexOf('{', start), depth = 0;
    for (let j = i; j < app.length; j++) {
        if (app[j] === '{') depth++;
        else if (app[j] === '}') { depth--; if (depth === 0) return app.slice(start, j + 1); }
    }
    throw new Error(`${sig} 花括号不配平`);
}

const sandbox = {
    currentProjectId: null,
    currentProject: null,
    chatMode: 'global',
    document: {
        getElementById(id) {
            return sandbox._els[id] || null;
        },
    },
    _els: {
        chatPanelTitle: { textContent: '' },
        chatPanelSessionTitle: { textContent: 'F:\\A_Works\\GASP-LMM', title: '', style: { display: '' } },
    },
};

const src = [
    'function _looksLikeFsPath(t)',
    'function _clearChatPanelSessionTitle()',
    'function _applyChatPanelTitle()',
    'function _sessionDisplayTitle(s)',
].map(extract).join('\n\n');

vm.createContext(sandbox);
vm.runInContext(src, sandbox);

check('Windows 盘符路径算工作区路径', sandbox._looksLikeFsPath('F:\\A_Works\\GASP-LMM'));
check('UNC 路径也算', sandbox._looksLikeFsPath('\\\\nas\\share\\proj'));
check('Unix 绝对路径也算', sandbox._looksLikeFsPath('/home/user/proj'));
check('普通会话标题不算路径', !sandbox._looksLikeFsPath('能新建视频项目？'));
check('空字符串不算路径', !sandbox._looksLikeFsPath(''));

const pathTitle = sandbox._sessionDisplayTitle({
    title: 'F:\\A_Works\\GASP-LMM',
    updated_at: '2026-10-23T12:41:00',
    message_count: 4,
});
check('路径标题回退到日期，不把盘符挂在 AI 助手旁边',
    pathTitle === '对话（2026-10-23，4条）', pathTitle);

const okTitle = sandbox._sessionDisplayTitle({
    title: '能新建视频项目？',
    updated_at: '2026-10-23T12:41:00',
    message_count: 2,
});
check('正常中文标题原样保留', okTitle === '能新建视频项目？', okTitle);

sandbox.currentProjectId = null;
sandbox.currentProject = null;
sandbox._applyChatPanelTitle();
check('无项目时标题是「AI 助手 · 全局」',
    sandbox._els.chatPanelTitle.textContent === 'AI 助手 · 全局',
    sandbox._els.chatPanelTitle.textContent);

sandbox.currentProjectId = 'PRJ-1';
sandbox.currentProject = { name: 'jizhang' };
sandbox._applyChatPanelTitle();
check('项目内标题带项目名',
    sandbox._els.chatPanelTitle.textContent === 'AI 助手 · jizhang');

sandbox._clearChatPanelSessionTitle();
check('清会话小字会隐藏元素', sandbox._els.chatPanelSessionTitle.style.display === 'none');
check('清会话小字会掏空文本', sandbox._els.chatPanelSessionTitle.textContent === '');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
