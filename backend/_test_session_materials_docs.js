/**
 * 会话附件文档要进本会话素材
 *   cd backend && node _test_session_materials_docs.js
 */
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const app = fs.readFileSync(path.join(root, 'frontend/app.js'), 'utf8').replace(/\r\n/g, '\n');
const chat = fs.readFileSync(path.join(root, 'backend/api/chat.py'), 'utf8').replace(/\r\n/g, '\n');
const registry = fs.readFileSync(path.join(root, 'backend/materials/registry.py'), 'utf8').replace(/\r\n/g, '\n');
const smApi = fs.readFileSync(path.join(root, 'backend/api/session_materials.py'), 'utf8').replace(/\r\n/g, '\n');

let pass = 0, fail = 0;
function check(name, cond, detail = '') {
    if (cond) { pass++; console.log(`[OK] ${name}${detail ? ' -- ' + detail : ''}`); }
    else { fail++; console.log(`[FAIL] ${name}${detail ? ' -- ' + detail : ''}`); }
}

check('保存用户消息时登记【附件】', chat.includes('attach_inline_docs(') && chat.includes('登记会话附件失败'));
check('素材列表会补登历史附件', smApi.includes('sync_inline_docs_from_session('));
check('registry 能解析【附件：文件名】', registry.includes('_INLINE_DOC_RE') && registry.includes('attach_inline_docs'));
check('空态提到文档', app.includes('对话中的图片、文档、生成结果会自动出现在这里'));
check('发送文档后刷新素材面板', app.includes('(docs && docs.length)') && app.includes('refreshSessionMaterials()'));
check('素材面板可点开文档', app.includes('async function openSessionMaterial(id)'));
check('中文文件名可进素材名', registry.includes('_display_name') && !/_SAFE_NAME = re\.compile\(r"\[\^\\w\.\-\]\+"\)/.test(registry));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
