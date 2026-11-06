/**
 * 气泡里的 📎 附件要能点开
 *   cd backend && node _test_chat_bubble_attachment.js
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

check('发送气泡仍写 📎 文件名', app.includes("docs.map(d => `📎 ${d.filename}`)"));
check('formatChatContent 先把【附件】折叠成 📎', app.includes('content = _collapseInlineAttachments(content)'));
check('_renderMarkdownText 把 📎 行收成芯片', app.includes('_chatBubbleDocChipHtml(attachMatch[1].trim())'));
check('芯片点开走 _openChatBubbleAttachment', app.includes('_openChatBubbleAttachment(this.dataset.attachName)'));
check('CSS 用户气泡里的芯片可点', app.includes('.chat-msg.user .chat-bubble-doc-chip') ||
    fs.readFileSync(path.join(__dirname, '../frontend/styles.css'), 'utf8').includes('.chat-msg.user .chat-bubble-doc-chip'));

const sandbox = {
    chatHistory: [],
    escapeHtml(s) {
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },
};

const src = [
    'function _docChipIconText(filename)',
    'function _collapseInlineAttachments(text)',
    'function _chatBubbleDocChipHtml(filename)',
    'function _extractAttachedDocFromHistory(name)',
].map(extract).join('\n\n');
vm.createContext(sandbox);
vm.runInContext(src, sandbox);

const collapsed = sandbox._collapseInlineAttachments(
    '现在有个这样的小说，能否生成AI漫剧\n\n【附件：26021001_古墓丽影：劳拉传奇.md】\n# 正文\n很长很长'
);
check('折叠【附件】只留 📎 文件名，不把小说全文铺进气泡',
    collapsed.includes('📎 26021001_古墓丽影：劳拉传奇.md') && !collapsed.includes('# 正文'),
    collapsed.replace(/\n/g, '\\n'));

const chip = sandbox._chatBubbleDocChipHtml('26021001_古墓丽影：劳拉传奇.md');
check('芯片带 data-attach-name', chip.includes('data-attach-name="26021001_古墓丽影：劳拉传奇.md"'));
check('芯片 onclick 点开附件', chip.includes('_openChatBubbleAttachment(this.dataset.attachName)'));
check('中文文件名原样进芯片', chip.includes('古墓丽影：劳拉传奇.md'));

sandbox.chatHistory = [{
    role: 'user',
    content: '问一句\n\n【附件：26021001_古墓丽影：劳拉传奇.md】\n第一章\n劳拉走进墓穴',
}];
check('能从历史消息抽出附件正文',
    sandbox._extractAttachedDocFromHistory('26021001_古墓丽影：劳拉传奇.md') === '第一章\n劳拉走进墓穴');

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
