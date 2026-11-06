/**
 * PRD 分析要有进度日志，看板轮询不能刷屏
 *   cd backend && node _test_prd_analysis_logs.js
 */
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const app = fs.readFileSync(path.join(root, 'frontend/app.js'), 'utf8').replace(/\r\n/g, '\n');
const orch = fs.readFileSync(path.join(root, 'backend/orchestrator.py'), 'utf8').replace(/\r\n/g, '\n');
const product = fs.readFileSync(path.join(root, 'backend/agents/product.py'), 'utf8').replace(/\r\n/g, '\n');

let pass = 0, fail = 0;
function check(name, cond, detail = '') {
    if (cond) { pass++; console.log(`[OK] ${name}${detail ? ' -- ' + detail : ''}`); }
    else { fail++; console.log(`[FAIL] ${name}${detail ? ' -- ' + detail : ''}`); }
}

check('分析过程写 progress/heartbeat', orch.includes('action": "heartbeat"') || orch.includes('"heartbeat"') || orch.includes('heartbeat", "analyzing"'));
check('中断的 analyzing 会续跑', orch.includes('_resume_stuck_analyses') && orch.includes("status = 'analyzing'"));
check('ProductAgent 拆单前有 on_step', product.includes('on_step') && product.includes('正在调用 LLM 拆单'));
check('看板 GET 不进实时日志', app.includes('function _isNoisyApiLog') && app.includes('/(board|health|metrics|hooks\\/status)'));
check('刷新 pipeline 不关掉正在看的 Job 日志', app.includes('keepJobLog') && app.includes('_ensurePipelineProgressPoll'));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
