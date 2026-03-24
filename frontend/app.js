/**
 * AI 自动开发系统 — 前端核心逻辑
 * 工单管理看板 SPA
 */

// ==================== 全局状态 ====================

const API = '/api';
let currentProjectId = null;
let currentProject = null;
let currentPipelineReqId = null;
let eventSource = null;

// ==================== 初始化 ====================

document.addEventListener('DOMContentLoaded', () => {
    checkLLMStatus();
    loadProjects();
    initLogPanel();
});

// ==================== API 工具函数 ====================

async function api(path, options = {}) {
    const url = `${API}${path}`;
    const config = {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    };
    if (config.body && typeof config.body === 'object') {
        config.body = JSON.stringify(config.body);
    }
    try {
        const resp = await fetch(url, config);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(err.detail || err.message || `请求失败 (${resp.status})`);
        }
        return await resp.json();
    } catch (e) {
        console.error(`[API] ${path}:`, e);
        throw e;
    }
}

// ==================== LLM 状态 ====================

async function checkLLMStatus() {
    const el = document.getElementById('llmStatus');
    try {
        const data = await api('/llm/status');
        if (data.configured) {
            el.classList.add('connected');
            el.classList.remove('disconnected');
            el.querySelector('.text').textContent = `LLM: ${data.model || '已配置'}`;
        } else {
            el.classList.add('disconnected');
            el.classList.remove('connected');
            el.querySelector('.text').textContent = 'LLM: 规则引擎模式';
        }
        // 缓存当前配置用于弹窗回填
        window._llmConfig = data;
    } catch {
        el.classList.add('disconnected');
        el.querySelector('.text').textContent = 'LLM: 未连接';
    }
}

// ==================== LLM 配置弹窗 ====================

async function showLLMConfigModal() {
    // 先获取最新状态
    try {
        const data = await api('/llm/status');
        document.getElementById('llmBaseUrl').value = data.base_url || '';
        document.getElementById('llmApiKey').value = '';  // 出于安全不回填 key
        document.getElementById('llmModel').value = data.model || 'gpt-4';
        document.getElementById('llmTimeout').value = data.timeout || 60;
        document.getElementById('llmMaxRetries').value = data.max_retries || 3;
    } catch {
        // 使用空值
        document.getElementById('llmBaseUrl').value = '';
        document.getElementById('llmApiKey').value = '';
        document.getElementById('llmModel').value = 'gpt-4';
        document.getElementById('llmTimeout').value = 60;
        document.getElementById('llmMaxRetries').value = 3;
    }
    // 清除之前的测试结果
    const resultEl = document.getElementById('llmTestResult');
    resultEl.style.display = 'none';
    resultEl.textContent = '';
    openModal('llmConfigModal');
}

async function saveLLMConfig() {
    const base_url = document.getElementById('llmBaseUrl').value.trim();
    const api_key = document.getElementById('llmApiKey').value.trim();
    const model = document.getElementById('llmModel').value.trim() || 'gpt-4';
    const timeout = parseInt(document.getElementById('llmTimeout').value) || 60;
    const max_retries = parseInt(document.getElementById('llmMaxRetries').value) || 3;

    // 构建 payload（只发送非空字段，api_key 为空时不覆盖已有 key）
    const payload = { model, timeout, max_retries };
    if (base_url) payload.base_url = base_url;
    if (api_key) payload.api_key = api_key;

    try {
        const data = await api('/llm/config', {
            method: 'POST',
            body: payload,
        });
        showToast('LLM 配置已保存', 'success');
        closeModal('llmConfigModal');
        // 刷新顶栏状态
        await checkLLMStatus();
    } catch (e) {
        showToast(`保存失败: ${e.message}`, 'error');
    }
}

async function testLLMConnection() {
    const resultEl = document.getElementById('llmTestResult');
    const testBtn = document.getElementById('llmTestBtn');

    // 先保存当前填写的值（临时生效）
    const base_url = document.getElementById('llmBaseUrl').value.trim();
    const api_key = document.getElementById('llmApiKey').value.trim();
    const model = document.getElementById('llmModel').value.trim();

    if (!base_url) {
        resultEl.style.display = 'block';
        resultEl.style.background = 'var(--error-bg, rgba(255,90,90,0.1))';
        resultEl.style.color = 'var(--error)';
        resultEl.textContent = '请先填写 API Base URL';
        return;
    }

    // 先把配置保存到后端（这样测试用的是最新的值）
    const payload = { base_url, model: model || 'gpt-4' };
    if (api_key) payload.api_key = api_key;
    try {
        await api('/llm/config', { method: 'POST', body: payload });
    } catch {}

    testBtn.textContent = '⏳ 测试中...';
    testBtn.disabled = true;
    resultEl.style.display = 'block';
    resultEl.style.background = 'var(--bg-elevated)';
    resultEl.style.color = 'var(--text-secondary)';
    resultEl.textContent = '正在连接 LLM 服务...';

    try {
        const data = await api('/llm/test', { method: 'POST' });
        if (data.status === 'ok') {
            resultEl.style.background = 'rgba(52,211,153,0.1)';
            resultEl.style.color = 'var(--success)';
            resultEl.textContent = `✅ 连接成功！${data.response ? ' 响应: ' + data.response : ''}`;
        } else if (data.status === 'not_configured') {
            resultEl.style.background = 'rgba(251,191,36,0.1)';
            resultEl.style.color = 'var(--warning)';
            resultEl.textContent = '⚠️ LLM 未配置，请填写 API Key';
        } else {
            resultEl.style.background = 'rgba(255,90,90,0.1)';
            resultEl.style.color = 'var(--error)';
            resultEl.textContent = `❌ 连接失败: ${data.message || '未知错误'}`;
        }
    } catch (e) {
        resultEl.style.background = 'rgba(255,90,90,0.1)';
        resultEl.style.color = 'var(--error)';
        resultEl.textContent = `❌ 请求失败: ${e.message}`;
    } finally {
        testBtn.textContent = '🔗 测试连接';
        testBtn.disabled = false;
    }
}

function togglePasswordVisibility(inputId, btn) {
    const input = document.getElementById(inputId);
    if (input.type === 'password') {
        input.type = 'text';
        btn.textContent = '🔒';
    } else {
        input.type = 'password';
        btn.textContent = '👁';
    }
}

// ==================== 页面切换 ====================

function showPage(pageId) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const page = document.getElementById(pageId);
    if (page) page.classList.add('active');
}

function showProjectList() {
    currentProjectId = null;
    currentProject = null;
    disconnectSSE();
    showPage('projectListPage');
    updateBreadcrumb([{ text: '项目列表', onClick: 'showProjectList()' }]);
    loadProjects();
}

function showProjectDetail(projectId) {
    currentProjectId = projectId;
    showPage('projectPage');
    loadProjectDetail();
    connectSSE(projectId);
    // 清空日志面板并加载该项目历史日志
    clearLogPanel();
    loadLogPanelHistory();
}

function switchTab(tab) {
    // 侧栏导航高亮
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const activeNav = document.querySelector(`.nav-item[data-tab="${tab}"]`);
    if (activeNav) activeNav.classList.add('active');

    // 内容区切换
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    const tabEl = document.getElementById(`tab-${tab}`);
    if (tabEl) tabEl.classList.add('active');

    // 按需加载数据
    if (tab === 'board') refreshBoard();
    if (tab === 'requirements') loadRequirements();
    if (tab === 'pipeline' && currentPipelineReqId) loadPipeline(currentPipelineReqId);
    if (tab === 'stats') loadStats();
    if (tab === 'logs') loadLogs();
}

// ==================== 面包屑 ====================

function updateBreadcrumb(items) {
    const bc = document.getElementById('breadcrumb');
    bc.innerHTML = items.map((item, i) => {
        if (i < items.length - 1) {
            return `<a href="#" onclick="${item.onClick}; return false;">${item.text}</a><span>›</span>`;
        }
        return `<a href="#" class="current">${item.text}</a>`;
    }).join('');
}

// ==================== 项目列表 ====================

async function loadProjects() {
    const grid = document.getElementById('projectGrid');
    try {
        const data = await api('/projects');
        const projects = data.projects || [];
        if (projects.length === 0) {
            grid.innerHTML = `
                <div class="empty-state" style="grid-column: 1 / -1;">
                    <div class="emoji">🚀</div>
                    <p>还没有项目，点击「新建项目」开始吧</p>
                </div>`;
            return;
        }
        grid.innerHTML = projects.map(p => `
            <div class="project-card" onclick="showProjectDetail('${p.id}')">
                <h3>${escHtml(p.name)}</h3>
                <p>${escHtml(p.description || '暂无描述')}</p>
                <div class="card-stats">
                    <span class="stat-item">📅 ${formatDate(p.created_at)}</span>
                    <span class="stat-item">📌 ${p.status === 'active' ? '进行中' : '已归档'}</span>
                </div>
            </div>
        `).join('');
    } catch (e) {
        grid.innerHTML = `<div class="empty-state" style="grid-column: 1 / -1;"><div class="emoji">❌</div><p>加载失败: ${escHtml(e.message)}</p></div>`;
    }
}

// ==================== 创建项目 ====================

function showCreateProjectModal() {
    document.getElementById('projectName').value = '';
    document.getElementById('projectDescription').value = '';
    document.getElementById('projectTechStack').value = '';
    openModal('createProjectModal');
}

async function createProject() {
    const name = document.getElementById('projectName').value.trim();
    const description = document.getElementById('projectDescription').value.trim();
    const tech_stack = document.getElementById('projectTechStack').value.trim();

    if (!name) {
        showToast('请输入项目名称', 'warning');
        return;
    }

    try {
        const data = await api('/projects', {
            method: 'POST',
            body: { name, description, tech_stack },
        });
        closeModal('createProjectModal');
        showToast(`项目「${name}」创建成功`, 'success');
        showProjectDetail(data.id);
    } catch (e) {
        showToast(`创建失败: ${e.message}`, 'error');
    }
}

// ==================== 项目详情 ====================

async function loadProjectDetail() {
    if (!currentProjectId) return;
    try {
        const data = await api(`/projects/${currentProjectId}`);
        currentProject = data;
        document.getElementById('sidebarProjectName').textContent = data.name;
        updateBreadcrumb([
            { text: '项目列表', onClick: 'showProjectList()' },
            { text: data.name, onClick: '' },
        ]);
        // 加载默认 tab
        switchTab('board');
        loadRequirementFilter();
    } catch (e) {
        showToast(`加载项目失败: ${e.message}`, 'error');
    }
}

// ==================== 需求筛选器 ====================

async function loadRequirementFilter() {
    if (!currentProjectId) return;
    try {
        const data = await api(`/projects/${currentProjectId}/requirements`);
        const select = document.getElementById('filterRequirement');
        select.innerHTML = '<option value="">全部需求</option>';
        (data.requirements || []).forEach(r => {
            select.innerHTML += `<option value="${r.id}">${escHtml(r.title)}</option>`;
        });
    } catch {}
}

// ==================== 看板 ====================

async function refreshBoard() {
    if (!currentProjectId) return;
    const reqFilter = document.getElementById('filterRequirement')?.value || '';

    try {
        let url = `/projects/${currentProjectId}/board`;
        if (reqFilter) url += `?requirement_id=${reqFilter}`;
        const data = await api(url);
        const board = data.board || {};

        const columns = ['pending', 'architecture', 'development', 'testing', 'deployed'];
        columns.forEach(col => {
            const tickets = board[col] || [];
            const body = document.getElementById(`col-${col}`);
            const count = document.getElementById(`count-${col}`);
            if (count) count.textContent = tickets.length;

            if (!body) return;
            if (tickets.length === 0) {
                body.innerHTML = '<div class="empty-state"><p style="font-size:12px; padding:16px 0;">暂无工单</p></div>';
                return;
            }
            body.innerHTML = tickets.map(t => renderTicketCard(t)).join('');
        });
    } catch (e) {
        showToast(`看板加载失败: ${e.message}`, 'error');
    }
}

function renderTicketCard(t) {
    // 判断卡片状态样式
    let cardClass = 'ticket-card';
    if (t.status.includes('_in_progress') || t.status === 'deploying') cardClass += ' running';
    else if (t.status === 'deployed') cardClass += ' done';
    else if (t.status.includes('rejected') || t.status.includes('failed')) cardClass += ' rejected';

    const priorityLabel = {1: 'P1', 2: 'P2', 3: 'P3', 4: 'P4', 5: 'P5'};
    const pLabel = priorityLabel[t.priority] || `P${t.priority}`;

    return `
        <div class="${cardClass}" onclick="openTicketDrawer('${t.id}')">
            <div class="ticket-title">${escHtml(t.title)}</div>
            <div class="ticket-meta">
                ${t.module ? `<span class="tag tag-module">${escHtml(t.module)}</span>` : ''}
                <span class="tag tag-type">${escHtml(t.type || 'feature')}</span>
                <span class="tag tag-priority-${t.priority}">${pLabel}</span>
                ${t.assigned_agent ? `<span class="tag tag-agent">${escHtml(t.assigned_agent)}</span>` : ''}
            </div>
            <div class="ticket-footer">
                <span class="ticket-status-label">${escHtml(t.status_label || t.status)}</span>
                ${t.estimated_hours ? `<span>${t.estimated_hours}h</span>` : ''}
            </div>
        </div>`;
}

// ==================== 工单详情抽屉 ====================

async function openTicketDrawer(ticketId) {
    if (!currentProjectId) return;
    try {
        const data = await api(`/projects/${currentProjectId}/tickets/${ticketId}`);
        const drawerTitle = document.getElementById('drawerTitle');
        const drawerBody = document.getElementById('drawerBody');

        drawerTitle.textContent = data.title;

        // 基本信息
        let html = `
        <div class="drawer-section">
            <h4>基本信息</h4>
            <div class="detail-grid">
                <span class="detail-label">状态</span>
                <span class="detail-value"><span class="tag tag-module">${escHtml(data.status_label || data.status)}</span></span>
                <span class="detail-label">模块</span>
                <span class="detail-value">${escHtml(data.module || '-')}</span>
                <span class="detail-label">类型</span>
                <span class="detail-value">${escHtml(data.type || '-')}</span>
                <span class="detail-label">优先级</span>
                <span class="detail-value">P${data.priority}</span>
                <span class="detail-label">负责 Agent</span>
                <span class="detail-value">${escHtml(data.assigned_agent || '待分配')}</span>
                <span class="detail-label">预估工时</span>
                <span class="detail-value">${data.estimated_hours ? data.estimated_hours + ' 小时' : '-'}</span>
                <span class="detail-label">创建时间</span>
                <span class="detail-value">${formatDateTime(data.created_at)}</span>
                ${data.started_at ? `<span class="detail-label">开始时间</span><span class="detail-value">${formatDateTime(data.started_at)}</span>` : ''}
                ${data.completed_at ? `<span class="detail-label">完成时间</span><span class="detail-value">${formatDateTime(data.completed_at)}</span>` : ''}
            </div>
        </div>`;

        // 描述
        if (data.description) {
            html += `
            <div class="drawer-section">
                <h4>描述</h4>
                <p style="font-size:13px; color:var(--text-secondary); line-height:1.7;">${escHtml(data.description)}</p>
            </div>`;
        }

        // 操作按钮
        html += renderTicketActions(data);

        // 子任务
        const subtasks = data.subtasks || [];
        if (subtasks.length > 0) {
            html += `
            <div class="drawer-section">
                <h4>子任务 (${subtasks.length})</h4>
                <div class="subtask-list">
                    ${subtasks.map(st => `
                        <div class="subtask-item ${st.status === 'completed' ? 'completed' : ''}">
                            <span class="subtask-icon">${st.status === 'completed' ? '✅' : st.status === 'in_progress' ? '🔄' : '⬜'}</span>
                            <span class="subtask-title">${escHtml(st.title)}</span>
                        </div>
                    `).join('')}
                </div>
            </div>`;
        }

        // 产物
        const artifacts = data.artifacts || [];
        if (artifacts.length > 0) {
            html += `
            <div class="drawer-section">
                <h4>产物 (${artifacts.length})</h4>
                ${artifacts.map(a => `
                    <div style="background:var(--bg-elevated); padding:10px; border-radius:var(--radius-sm); margin-bottom:8px; cursor:pointer;" onclick="toggleArtifactContent(this)">
                        <div style="display:flex; align-items:center; gap:8px; font-size:13px;">
                            <span>${getArtifactIcon(a.type)}</span>
                            <span style="font-weight:500;">${escHtml(a.name || a.type)}</span>
                            <span style="font-size:11px; color:var(--text-muted); margin-left:auto;">${formatDate(a.created_at)}</span>
                        </div>
                        <div class="artifact-content" style="display:none; margin-top:8px; padding:8px; background:var(--bg); border-radius:4px; font-size:12px; color:var(--text-secondary); max-height:300px; overflow-y:auto; white-space:pre-wrap; word-break:break-all;">${escHtml(tryFormatJson(a.content))}</div>
                    </div>
                `).join('')}
            </div>`;
        }

        // 日志
        const logs = data.logs || [];
        if (logs.length > 0) {
            html += `
            <div class="drawer-section">
                <h4>操作日志 (${logs.length})</h4>
                <div class="log-timeline" style="padding-left:24px;">
                    ${logs.slice(0, 20).map(l => renderLogItem(l)).join('')}
                </div>
            </div>`;
        }

        drawerBody.innerHTML = html;
        // 打开抽屉
        document.getElementById('drawerOverlay').classList.add('active');
        document.getElementById('ticketDrawer').classList.add('active');
    } catch (e) {
        showToast(`加载工单失败: ${e.message}`, 'error');
    }
}

function renderTicketActions(ticket) {
    let buttons = '';
    if (ticket.status === 'pending') {
        buttons += `<button class="btn btn-primary btn-sm" onclick="startTicket('${ticket.id}')">▶ 启动</button>`;
    }
    if (ticket.status !== 'deployed' && ticket.status !== 'cancelled') {
        buttons += `<button class="btn btn-sm" style="color:var(--error);" onclick="cancelTicket('${ticket.id}')">✗ 取消</button>`;
    }
    if (!buttons) return '';
    return `<div class="drawer-section"><h4>操作</h4><div style="display:flex; gap:8px;">${buttons}</div></div>`;
}

async function startTicket(ticketId) {
    try {
        await api(`/projects/${currentProjectId}/tickets/${ticketId}/start`, { method: 'POST' });
        showToast('工单已启动，Agent 开始处理', 'success');
        closeDrawer();
        setTimeout(refreshBoard, 1000);
    } catch (e) {
        showToast(`启动失败: ${e.message}`, 'error');
    }
}

async function cancelTicket(ticketId) {
    if (!confirm('确定取消此工单？')) return;
    try {
        await api(`/projects/${currentProjectId}/tickets/${ticketId}`, { method: 'DELETE' });
        showToast('工单已取消', 'info');
        closeDrawer();
        refreshBoard();
    } catch (e) {
        showToast(`取消失败: ${e.message}`, 'error');
    }
}

function toggleArtifactContent(el) {
    const content = el.querySelector('.artifact-content');
    if (content) {
        content.style.display = content.style.display === 'none' ? 'block' : 'none';
    }
}

function closeDrawer() {
    document.getElementById('drawerOverlay').classList.remove('active');
    document.getElementById('ticketDrawer').classList.remove('active');
}

// ==================== 需求管理 ====================

function showCreateRequirementModal() {
    if (!currentProjectId) {
        showToast('请先进入一个项目', 'warning');
        return;
    }
    document.getElementById('reqTitle').value = '';
    document.getElementById('reqDescription').value = '';
    document.getElementById('reqPriority').value = 'medium';
    document.getElementById('reqModule').value = '';
    openModal('createRequirementModal');
}

async function submitRequirement() {
    const title = document.getElementById('reqTitle').value.trim();
    const description = document.getElementById('reqDescription').value.trim();
    const priority = document.getElementById('reqPriority').value;
    const module = document.getElementById('reqModule').value.trim();

    if (!title || !description) {
        showToast('请填写需求标题和描述', 'warning');
        return;
    }

    try {
        // 1. 创建需求
        const reqData = await api(`/projects/${currentProjectId}/requirements`, {
            method: 'POST',
            body: { title, description, priority, module: module || null },
        });
        showToast(`需求「${title}」已提交`, 'success');
        closeModal('createRequirementModal');

        // 2. 触发拆单
        showToast('正在 AI 拆单，请稍候...', 'info');
        await api(`/projects/${currentProjectId}/requirements/${reqData.id}/decompose`, {
            method: 'POST',
        });
        showToast('拆单已启动，Agent 将自动处理', 'success');

        // 刷新看板和需求列表
        loadRequirementFilter();
        setTimeout(() => {
            refreshBoard();
            loadRequirements();
        }, 2000);
    } catch (e) {
        showToast(`提交失败: ${e.message}`, 'error');
    }
}

async function loadRequirements() {
    if (!currentProjectId) return;
    const list = document.getElementById('requirementList');

    try {
        const data = await api(`/projects/${currentProjectId}/requirements`);
        const reqs = data.requirements || [];

        if (reqs.length === 0) {
            list.innerHTML = `
                <div class="empty-state">
                    <div class="emoji">📋</div>
                    <p>暂无需求，点击「提交需求」开始吧</p>
                </div>`;
            return;
        }

        list.innerHTML = reqs.map(r => `
            <div class="requirement-card" onclick="openPipeline('${r.id}')">
                <div class="req-header">
                    <span class="req-title">${escHtml(r.title)}</span>
                    <span class="req-status ${r.status}">${getStatusLabel(r.status)}</span>
                </div>
                <div class="req-description">${escHtml(r.description)}</div>
                <div class="req-meta">
                    <span>优先级: ${escHtml(r.priority)}</span>
                    <span>工单: ${r.ticket_count || 0} 个</span>
                    <span>提交: ${formatDate(r.created_at)}</span>
                </div>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = `<div class="empty-state"><p>加载失败: ${escHtml(e.message)}</p></div>`;
    }
}

// ==================== Pipeline 视图（蓝盾风格） ====================

let currentPipelineData = null;
let activeJobId = null;

function openPipeline(reqId) {
    currentPipelineReqId = reqId;
    switchTab('pipeline');
    loadPipeline(reqId);
}

async function loadPipeline(reqId) {
    if (!currentProjectId || !reqId) return;
    const stagesRow = document.getElementById('pipelineStagesRow');
    stagesRow.innerHTML = '<div class="empty-state"><div class="emoji">⏳</div><p>加载中...</p></div>';

    try {
        const data = await api(`/projects/${currentProjectId}/requirements/${reqId}/pipeline`);
        currentPipelineData = data;
        const req = data.requirement;

        // 更新标题栏
        document.getElementById('pipelineReqTitle').textContent = req.title;
        const statusEl = document.getElementById('pipelineReqStatus');
        statusEl.textContent = getStatusLabel(req.status);
        statusEl.className = `req-status ${req.status}`;

        // 更新执行信息栏
        renderPipelineInfoBar(data);

        // 渲染 Stage
        renderPipelineStages(stagesRow, data.stages);

        // 隐藏日志面板
        closeJobLogPanel();
    } catch (e) {
        stagesRow.innerHTML = `<div class="empty-state"><div class="emoji">❌</div><p>加载失败: ${escHtml(e.message)}</p></div>`;
    }
}

function formatDuration(seconds) {
    if (seconds == null || seconds < 0) return '-';
    if (seconds < 60) return `00:${String(seconds).padStart(2,'0')}`;
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    if (m < 60) return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    const h = Math.floor(m / 60);
    const rm = m % 60;
    return `${String(h).padStart(2,'0')}:${String(rm).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

function renderPipelineInfoBar(data) {
    // 执行状态 badge
    const statusMap = {
        success: { text: '执行成功', cls: 'success' },
        running: { text: '执行中', cls: 'running' },
        pending: { text: '等待执行', cls: 'pending' },
        cancelled: { text: '已取消', cls: 'cancelled' },
        failed: { text: '执行失败', cls: 'failed' },
    };
    const st = statusMap[data.exec_status] || statusMap.pending;
    document.getElementById('pipelineExecStatus').innerHTML = `<span class="exec-badge ${st.cls}">${st.text}</span>`;

    // 时间线
    document.getElementById('plTriggerTime').textContent = data.trigger_time ? formatDateTime(data.trigger_time) : '-';
    document.getElementById('plStartTime').textContent = data.start_time ? formatDateTime(data.start_time) : '-';
    document.getElementById('plEndTime').textContent = data.end_time ? formatDateTime(data.end_time) : '-';

    // 总耗时
    document.getElementById('pipelineDuration').innerHTML = `总耗时: <strong>${formatDuration(data.total_duration)}</strong>`;
}

function renderPipelineStages(container, stages) {
    const expandJobs = document.getElementById('plExpandJobs')?.checked ?? true;
    let html = '';

    stages.forEach((stage, idx) => {
        const cls = stage.status || 'pending';
        let statusText = '';
        if (cls === 'done') statusText = '✓ 已完成';
        else if (cls === 'running') statusText = '● 进行中';
        else if (cls === 'failed') statusText = '✗ 失败';
        else statusText = '○ 等待中';

        // Stage 圆点图标
        let dotContent = stage.icon;
        if (cls === 'done') dotContent = '✓';
        if (cls === 'failed') dotContent = '✗';

        html += `<div class="pl-stage ${cls}">
            <div class="pl-stage-header">
                <div class="pl-stage-dot">${dotContent}</div>
                <div class="pl-stage-label">
                    <div class="pl-stage-name">${escHtml(stage.name)}</div>
                    <div class="pl-stage-status-text">${statusText}</div>
                </div>
            </div>
            <div class="pl-stage-jobs">`;

        // 渲染 Jobs
        const jobs = stage.jobs || [];
        if (jobs.length === 0 && cls !== 'pending') {
            html += `<div style="font-size:12px; color:var(--text-muted); padding:8px 0;">暂无任务</div>`;
        }

        jobs.forEach((job) => {
            const jobCls = job.status || 'pending';
            const jobIcon = jobCls === 'done' ? '✓' : (jobCls === 'running' ? '●' : (jobCls === 'failed' ? '✗' : '○'));
            const isActive = activeJobId === job.id;
            const dur = formatDuration(job.duration);

            html += `<div class="pl-job-card ${isActive ? 'active' : ''}" data-job-id="${job.id}" onclick="selectJob('${job.id}', '${stage.key}')">
                <div class="pl-job-header">
                    <span class="pl-job-status-icon ${jobCls}">${jobIcon}</span>
                    <span class="pl-job-name">${escHtml(job.title)}</span>
                    <span class="pl-job-duration">${dur}</span>
                    <span class="pl-job-expand ${expandJobs ? 'open' : ''}" onclick="event.stopPropagation(); toggleJobExpand(this)">▾</span>
                </div>
                <div class="pl-job-subtasks ${expandJobs ? 'expanded' : ''}">`;

            // 子任务
            const subtasks = job.subtasks || [];
            subtasks.forEach(st => {
                const stIcon = st.status === 'completed' ? '✓' : (st.status === 'in_progress' ? '●' : '○');
                const stDur = formatDuration(st.duration);
                html += `<div class="pl-subtask-item">
                    <span class="pl-subtask-icon ${st.status}">${stIcon}</span>
                    <span class="pl-subtask-name">${escHtml(st.title)}</span>
                    <span class="pl-subtask-duration">${stDur}</span>
                </div>`;
            });

            html += `</div></div>`; // close pl-job-subtasks, pl-job-card
        });

        html += `</div></div>`; // close pl-stage-jobs, pl-stage
    });

    container.innerHTML = html;
}

function toggleExpandJobs() {
    const expanded = document.getElementById('plExpandJobs')?.checked ?? true;
    document.querySelectorAll('.pl-job-subtasks').forEach(el => {
        el.classList.toggle('expanded', expanded);
    });
    document.querySelectorAll('.pl-job-expand').forEach(el => {
        el.classList.toggle('open', expanded);
    });
}

function toggleJobExpand(arrow) {
    const card = arrow.closest('.pl-job-card');
    const subtasks = card?.querySelector('.pl-job-subtasks');
    if (subtasks) {
        subtasks.classList.toggle('expanded');
        arrow.classList.toggle('open');
    }
}

async function selectJob(jobId, stageKey) {
    activeJobId = jobId;
    // 高亮当前 Job 卡片
    document.querySelectorAll('.pl-job-card').forEach(el => el.classList.remove('active'));
    const card = document.querySelector(`.pl-job-card[data-job-id="${jobId}"]`);
    if (card) card.classList.add('active');

    // 打开日志面板
    const panel = document.getElementById('pipelineJobLogPanel');
    panel.style.display = 'flex';

    // 查找 Job 数据
    let job = null;
    if (currentPipelineData) {
        for (const stage of currentPipelineData.stages) {
            for (const j of (stage.jobs || [])) {
                if (j.id === jobId) { job = j; break; }
            }
            if (job) break;
        }
    }

    const titleEl = document.getElementById('jobLogTitle');
    const iconEl = document.getElementById('jobLogIcon');
    titleEl.textContent = job ? job.title : 'Job';

    if (job) {
        const cls = job.status || 'pending';
        iconEl.textContent = cls === 'done' ? '✓' : (cls === 'running' ? '●' : (cls === 'failed' ? '✗' : '○'));
        iconEl.style.background = cls === 'done' ? 'var(--success)' : (cls === 'running' ? 'var(--info)' : (cls === 'failed' ? 'var(--error)' : 'var(--text-muted)'));
    }

    // 加载日志
    await loadJobLogs(jobId, stageKey);
}

async function loadJobLogs(jobId, stageKey) {
    const entries = document.getElementById('jobLogEntries');
    entries.innerHTML = '<div class="log-panel-empty">加载日志...</div>';

    try {
        // 如果是需求分析阶段的 Job，从需求日志获取
        let logs = [];
        if (stageKey === 'requirement_analysis' && currentPipelineData) {
            // 从 pipeline data 中的 logs 字段过滤
            logs = (currentPipelineData.logs || []).filter(l => l.agent_type === 'ProductAgent' || l.agent_type === 'System');
            logs = logs.reverse(); // 按时间正序
        } else {
            // 从工单日志 API 获取
            const data = await api(`/tickets/${jobId}/logs`);
            logs = (data.logs || []).reverse();
        }

        if (logs.length === 0) {
            entries.innerHTML = '<div class="log-panel-empty">暂无日志</div>';
            return;
        }

        let html = '';
        logs.forEach((log, i) => {
            let message = '';
            try {
                const parsed = JSON.parse(log.detail || '{}');
                message = parsed.message || '';
            } catch { message = log.detail || ''; }

            const level = log.level || 'info';
            const agent = log.agent_type || 'System';
            const action = log.action || '';
            const time = formatTime(log.created_at) || '';

            // 格式化日志行（类似蓝盾输出格式）
            let prefix = '';
            if (log.from_status && log.to_status) {
                prefix = `[${getStatusLabel(log.from_status)} → ${getStatusLabel(log.to_status)}] `;
            }

            const text = `${time} [${agent}] ${action ? action + ': ' : ''}${prefix}${message}`;
            const textCls = level === 'error' ? 'error' : (level === 'warn' ? 'warn' : 'info');

            html += `<div class="job-log-line">
                <span class="job-log-line-num">${i + 1}</span>
                <span class="job-log-line-text ${textCls}">${escHtml(text)}</span>
            </div>`;
        });

        entries.innerHTML = html;
        // 滚动到底部
        const body = document.getElementById('jobLogBody');
        if (body) body.scrollTop = body.scrollHeight;
    } catch (e) {
        entries.innerHTML = `<div class="log-panel-empty">加载失败: ${escHtml(e.message)}</div>`;
    }
}

function closeJobLogPanel() {
    activeJobId = null;
    const panel = document.getElementById('pipelineJobLogPanel');
    if (panel) panel.style.display = 'none';
    document.querySelectorAll('.pl-job-card').forEach(el => el.classList.remove('active'));
}

function switchJobLogTab(tab) {
    document.querySelectorAll('.job-log-tab').forEach(el => el.classList.remove('active'));
    event.target.classList.add('active');
    // 只有 log tab 有实现，config tab 显示占位
    const entries = document.getElementById('jobLogEntries');
    if (tab === 'config') {
        entries.innerHTML = '<div class="log-panel-empty">配置信息暂未实现</div>';
    } else if (activeJobId) {
        // 重新加载日志
        let stageKey = '';
        if (currentPipelineData) {
            for (const stage of currentPipelineData.stages) {
                if ((stage.jobs || []).some(j => j.id === activeJobId)) {
                    stageKey = stage.key;
                    break;
                }
            }
        }
        loadJobLogs(activeJobId, stageKey);
    }
}

function scrollToPipelineLogs() {
    const panel = document.getElementById('pipelineJobLogPanel');
    if (panel) {
        panel.style.display = 'flex';
        panel.scrollIntoView({ behavior: 'smooth' });
    }
}

async function showRequirementDetail(reqId) {
    try {
        const data = await api(`/projects/${currentProjectId}/requirements/${reqId}`);
        // 打开抽屉显示需求详情
        const drawerTitle = document.getElementById('drawerTitle');
        const drawerBody = document.getElementById('drawerBody');

        drawerTitle.textContent = `📋 ${data.title}`;

        let html = `
        <div class="drawer-section">
            <h4>需求信息</h4>
            <div class="detail-grid">
                <span class="detail-label">状态</span>
                <span class="detail-value"><span class="req-status ${data.status}">${getStatusLabel(data.status)}</span></span>
                <span class="detail-label">优先级</span>
                <span class="detail-value">${escHtml(data.priority)}</span>
                <span class="detail-label">提交时间</span>
                <span class="detail-value">${formatDateTime(data.created_at)}</span>
            </div>
        </div>
        <div class="drawer-section">
            <h4>描述</h4>
            <p style="font-size:13px; color:var(--text-secondary); line-height:1.7;">${escHtml(data.description)}</p>
        </div>`;

        // PRD
        if (data.prd_content) {
            html += `
            <div class="drawer-section">
                <h4>PRD 摘要</h4>
                <p style="font-size:13px; color:var(--text-secondary); line-height:1.7; background:var(--bg-elevated); padding:12px; border-radius:var(--radius-sm);">${escHtml(data.prd_content)}</p>
            </div>`;
        }

        // 操作按钮
        if (data.status === 'submitted') {
            html += `
            <div class="drawer-section">
                <h4>操作</h4>
                <button class="btn btn-primary btn-sm" onclick="decomposeReq('${data.id}')">🤖 AI 拆单</button>
                <button class="btn btn-sm" style="color:var(--error); margin-left:8px;" onclick="cancelReq('${data.id}')">✗ 取消</button>
            </div>`;
        }

        // 关联工单
        const tickets = data.tickets || [];
        if (tickets.length > 0) {
            html += `
            <div class="drawer-section">
                <h4>关联工单 (${tickets.length})</h4>
                ${tickets.map(t => `
                    <div style="background:var(--bg-elevated); padding:10px; border-radius:var(--radius-sm); margin-bottom:6px; cursor:pointer; display:flex; justify-content:space-between; align-items:center;" onclick="closeDrawer(); setTimeout(() => openTicketDrawer('${t.id}'), 300);">
                        <span style="font-size:13px;">${escHtml(t.title)}</span>
                        <span class="tag tag-module" style="font-size:11px;">${getStatusLabel(t.status)}</span>
                    </div>
                `).join('')}
            </div>`;
        }

        drawerBody.innerHTML = html;
        document.getElementById('drawerOverlay').classList.add('active');
        document.getElementById('ticketDrawer').classList.add('active');
    } catch (e) {
        showToast(`加载需求详情失败: ${e.message}`, 'error');
    }
}

async function decomposeReq(reqId) {
    try {
        showToast('正在 AI 拆单...', 'info');
        await api(`/projects/${currentProjectId}/requirements/${reqId}/decompose`, { method: 'POST' });
        showToast('拆单已启动', 'success');
        closeDrawer();
        setTimeout(() => {
            refreshBoard();
            loadRequirements();
            loadRequirementFilter();
        }, 2000);
    } catch (e) {
        showToast(`拆单失败: ${e.message}`, 'error');
    }
}

async function cancelReq(reqId) {
    if (!confirm('确定取消此需求？')) return;
    try {
        await api(`/projects/${currentProjectId}/requirements/${reqId}`, { method: 'DELETE' });
        showToast('需求已取消', 'info');
        closeDrawer();
        loadRequirements();
    } catch (e) {
        showToast(`取消失败: ${e.message}`, 'error');
    }
}

// ==================== 统计面板 ====================

async function loadStats() {
    if (!currentProjectId) return;
    const grid = document.getElementById('statsGrid');

    try {
        const data = await api(`/projects/${currentProjectId}/stats`);

        // 顶部卡片
        let html = `
            <div class="stat-card">
                <div class="stat-value">${data.total_tickets || 0}</div>
                <div class="stat-label">总工单数</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="color:var(--success);">${data.completed_tickets || 0}</div>
                <div class="stat-label">已完成</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="color:var(--accent);">${data.completion_rate || 0}%</div>
                <div class="stat-label">完成率</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="color:var(--warning);">${Object.keys(data.requirement_stats || {}).reduce((s, k) => s + (data.requirement_stats[k] || 0), 0)}</div>
                <div class="stat-label">总需求数</div>
            </div>`;

        // 工单状态分布
        const ticketStats = data.ticket_stats || {};
        const total = data.total_tickets || 1;
        if (Object.keys(ticketStats).length > 0) {
            html += `<div class="stat-section" style="grid-column: 1 / -1;"><h3>工单状态分布</h3><div class="stat-bar-list">`;
            for (const [status, count] of Object.entries(ticketStats)) {
                const pct = Math.round(count / total * 100);
                html += `
                    <div class="stat-bar-item">
                        <span class="stat-bar-label">${getStatusLabel(status)}</span>
                        <div class="stat-bar"><div class="stat-bar-fill" style="width:${pct}%; background:${getStatusColor(status)};"></div></div>
                        <span class="stat-bar-value">${count}</span>
                    </div>`;
            }
            html += `</div></div>`;
        }

        // 模块分布
        const moduleStats = data.module_stats || {};
        if (Object.keys(moduleStats).length > 0) {
            html += `<div class="stat-section" style="grid-column: 1 / -1;"><h3>模块分布</h3><div class="stat-bar-list">`;
            for (const [mod, count] of Object.entries(moduleStats)) {
                const pct = Math.round(count / total * 100);
                html += `
                    <div class="stat-bar-item">
                        <span class="stat-bar-label">${escHtml(mod)}</span>
                        <div class="stat-bar"><div class="stat-bar-fill" style="width:${pct}%; background:var(--accent);"></div></div>
                        <span class="stat-bar-value">${count}</span>
                    </div>`;
            }
            html += `</div></div>`;
        }

        // Agent 工作量
        const agentStats = data.agent_stats || {};
        if (Object.keys(agentStats).length > 0) {
            const maxAgent = Math.max(...Object.values(agentStats), 1);
            html += `<div class="stat-section" style="grid-column: 1 / -1;"><h3>Agent 工作量</h3><div class="stat-bar-list">`;
            for (const [agent, count] of Object.entries(agentStats)) {
                const pct = Math.round(count / maxAgent * 100);
                html += `
                    <div class="stat-bar-item">
                        <span class="stat-bar-label">${escHtml(agent)}</span>
                        <div class="stat-bar"><div class="stat-bar-fill" style="width:${pct}%; background:var(--primary);"></div></div>
                        <span class="stat-bar-value">${count}</span>
                    </div>`;
            }
            html += `</div></div>`;
        }

        grid.innerHTML = html;
    } catch (e) {
        grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1;"><p>加载失败: ${escHtml(e.message)}</p></div>`;
    }
}

// ==================== 操作日志 ====================

async function loadLogs() {
    if (!currentProjectId) return;
    const timeline = document.getElementById('logTimeline');

    try {
        const data = await api(`/projects/${currentProjectId}/logs?limit=100`);
        const logs = data.logs || [];

        if (logs.length === 0) {
            timeline.innerHTML = '<div class="empty-state"><div class="emoji">📝</div><p>暂无操作日志</p></div>';
            return;
        }

        timeline.innerHTML = logs.map(l => renderLogItem(l)).join('');
    } catch (e) {
        timeline.innerHTML = `<div class="empty-state"><p>加载失败: ${escHtml(e.message)}</p></div>`;
    }
}

function renderLogItem(log) {
    let detail = '';
    try {
        const parsed = JSON.parse(log.detail || '{}');
        detail = parsed.message || '';
    } catch {
        detail = log.detail || '';
    }

    return `
        <div class="log-item ${log.level || 'info'}">
            <div class="log-header">
                <span class="log-agent">${escHtml(log.agent_type || 'System')}</span>
                <span class="log-action">${escHtml(log.action || '')}</span>
                ${log.from_status && log.to_status ? `
                    <span class="log-status-change">
                        ${getStatusLabel(log.from_status)} <span class="arrow">→</span> ${getStatusLabel(log.to_status)}
                    </span>` : ''}
                <span class="log-time">${formatTime(log.created_at)}</span>
            </div>
            <div class="log-message">${escHtml(detail)}</div>
        </div>`;
}

// ==================== SSE 实时推送 ====================

function connectSSE(projectId) {
    disconnectSSE();
    try {
        eventSource = new EventSource(`${API}/projects/${projectId}/events`);

        eventSource.addEventListener('ticket_status_changed', (e) => {
            const data = JSON.parse(e.data);
            console.log('[SSE] ticket_status_changed:', data);
            refreshBoard();
            // 同步刷新 Pipeline
            if (currentPipelineReqId) loadPipeline(currentPipelineReqId);
        });

        eventSource.addEventListener('requirement_decomposed', (e) => {
            const data = JSON.parse(e.data);
            console.log('[SSE] requirement_decomposed:', data);
            showToast(`需求已拆分为 ${data.ticket_count} 个工单`, 'success');
            refreshBoard();
            loadRequirements();
            loadRequirementFilter();
            // 同步刷新 Pipeline
            if (currentPipelineReqId) loadPipeline(currentPipelineReqId);
        });

        eventSource.addEventListener('requirement_completed', (e) => {
            const data = JSON.parse(e.data);
            console.log('[SSE] requirement_completed:', data);
            showToast('需求已全部完成! 🎉', 'success');
            loadRequirements();
        });

        eventSource.addEventListener('agent_working', (e) => {
            const data = JSON.parse(e.data);
            console.log('[SSE] agent_working:', data);
            // agent_working 事件也追加到日志面板（作为实时动态）
            appendLogEntry({
                agent_type: data.agent,
                action: data.action,
                detail: JSON.stringify({message: `${data.agent} 正在执行 ${data.action}${data.ticket_id ? ' (工单 ' + data.ticket_id.slice(-6) + ')' : ''}${data.requirement_id ? ' (需求 ' + data.requirement_id.slice(-6) + ')' : ''}`}),
                level: 'info',
                created_at: new Date().toISOString(),
            });
        });

        eventSource.addEventListener('ticket_rejected', (e) => {
            const data = JSON.parse(e.data);
            showToast(`工单被打回: ${data.reason || ''}`, 'warning');
            refreshBoard();
        });

        eventSource.addEventListener('requirement_analyzing', (e) => {
            const data = JSON.parse(e.data);
            showToast('ProductAgent 正在分析需求...', 'info');
            appendLogEntry({
                agent_type: 'ProductAgent',
                action: 'analyze',
                detail: JSON.stringify({message: `开始分析需求「${data.title || data.id}」`}),
                level: 'info',
                created_at: new Date().toISOString(),
            });
        });

        eventSource.addEventListener('requirement_created', (e) => {
            const data = JSON.parse(e.data);
            loadRequirements();
            loadRequirementFilter();
            appendLogEntry({
                agent_type: 'System',
                action: 'create',
                detail: JSON.stringify({message: `新需求「${data.title}」已创建`}),
                level: 'info',
                created_at: new Date().toISOString(),
            });
        });

        // SSE: 后端日志实时推送
        eventSource.addEventListener('log_added', (e) => {
            const data = JSON.parse(e.data);
            console.log('[SSE] log_added:', data);
            appendLogEntry(data);
        });

        eventSource.onerror = () => {
            console.warn('[SSE] 连接断开，30 秒后重连');
            disconnectSSE();
            setTimeout(() => {
                if (currentProjectId === projectId) {
                    connectSSE(projectId);
                }
            }, 30000);
        };
    } catch (e) {
        console.warn('[SSE] 不支持或连接失败，使用轮询降级');
        startPolling(projectId);
    }
}

function disconnectSSE() {
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
    stopPolling();
}

// 轮询降级
let pollingTimer = null;

function startPolling(projectId) {
    stopPolling();
    pollingTimer = setInterval(() => {
        if (currentProjectId === projectId) {
            refreshBoard();
        } else {
            stopPolling();
        }
    }, 30000);
}

function stopPolling() {
    if (pollingTimer) {
        clearInterval(pollingTimer);
        pollingTimer = null;
    }
}

// ==================== 模态框 ====================

function openModal(id) {
    document.getElementById(id).classList.add('active');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('active');
}

// 点击 overlay 关闭
document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) {
            overlay.classList.remove('active');
        }
    });
});

// ESC 关闭
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay.active').forEach(m => m.classList.remove('active'));
        closeDrawer();
    }
});

// ==================== Toast 通知 ====================

function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span>${icons[type] || ''}</span><span>${escHtml(message)}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        toast.style.transition = 'all 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ==================== 底部日志面板 ====================

let logPanelAutoScroll = true;
let logPanelCollapsed = false;
let logPanelNewCount = 0;
const LOG_PANEL_MAX_ENTRIES = 500;

/**
 * 初始化日志面板：拖拽调高 + 双击切换
 */
function initLogPanel() {
    const panel = document.getElementById('logPanel');
    const resize = document.getElementById('logPanelResize');
    const header = document.getElementById('logPanelHeader');
    if (!panel || !resize) return;

    // 从 localStorage 恢复状态
    const savedHeight = localStorage.getItem('logPanelHeight');
    const savedCollapsed = localStorage.getItem('logPanelCollapsed');
    if (savedHeight) {
        panel.style.setProperty('--log-panel-height', savedHeight + 'px');
        panel.style.height = savedHeight + 'px';
    }
    if (savedCollapsed === 'true') {
        panel.classList.add('collapsed');
        logPanelCollapsed = true;
        document.getElementById('logPanelToggle').textContent = '▲';
    }

    // 拖拽调整高度
    let startY = 0;
    let startH = 0;
    let dragging = false;

    resize.addEventListener('mousedown', (e) => {
        e.preventDefault();
        dragging = true;
        startY = e.clientY;
        startH = panel.offsetHeight;
        resize.classList.add('dragging');
        document.body.style.cursor = 'ns-resize';
        document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        const diff = startY - e.clientY;
        const newH = Math.min(Math.max(startH + diff, 100), window.innerHeight * 0.6);
        panel.style.height = newH + 'px';
        panel.style.setProperty('--log-panel-height', newH + 'px');
    });

    document.addEventListener('mouseup', () => {
        if (!dragging) return;
        dragging = false;
        resize.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        localStorage.setItem('logPanelHeight', panel.offsetHeight);
    });

    // 双击标题切换展开/收起
    header.addEventListener('dblclick', (e) => {
        if (e.target.tagName === 'SELECT' || e.target.tagName === 'BUTTON') return;
        toggleLogPanel();
    });
}

/**
 * 切换日志面板展开/收起
 */
function toggleLogPanel() {
    const panel = document.getElementById('logPanel');
    logPanelCollapsed = !logPanelCollapsed;
    panel.classList.toggle('collapsed', logPanelCollapsed);
    document.getElementById('logPanelToggle').textContent = logPanelCollapsed ? '▲' : '▼';
    localStorage.setItem('logPanelCollapsed', logPanelCollapsed);

    // 展开时清除新消息计数
    if (!logPanelCollapsed) {
        logPanelNewCount = 0;
        const badge = document.getElementById('logPanelBadge');
        badge.style.display = 'none';
        badge.textContent = '0';
    }
}

/**
 * 切换自动滚动
 */
function toggleAutoScroll() {
    logPanelAutoScroll = !logPanelAutoScroll;
    const btn = document.getElementById('autoScrollBtn');
    btn.style.opacity = logPanelAutoScroll ? '1' : '0.4';
    btn.title = logPanelAutoScroll ? '自动滚动: 开' : '自动滚动: 关';
}

/**
 * 清空日志面板
 */
function clearLogPanel() {
    const entries = document.getElementById('logPanelEntries');
    entries.innerHTML = '<div class="log-panel-empty">日志已清空</div>';
    logPanelNewCount = 0;
    const badge = document.getElementById('logPanelBadge');
    badge.style.display = 'none';
}

/**
 * 追加一条日志到面板
 */
function appendLogEntry(log) {
    const entries = document.getElementById('logPanelEntries');
    if (!entries) return;

    // 去重：同一条日志不重复显示
    if (log.id && entries.querySelector(`[data-log-id="${log.id}"]`)) return;

    // 移除空状态提示
    const empty = entries.querySelector('.log-panel-empty');
    if (empty) empty.remove();

    // 解析 detail 消息
    let message = '';
    try {
        const parsed = JSON.parse(log.detail || '{}');
        message = parsed.message || '';
    } catch {
        message = log.detail || '';
    }

    const level = log.level || 'info';
    const agent = log.agent_type || 'System';
    const action = log.action || '';
    const time = formatTime(log.created_at) || new Date().toLocaleTimeString('zh-CN', {hour12: false});

    // 构建状态变化
    let statusHtml = '';
    if (log.from_status && log.to_status) {
        statusHtml = `<span class="log-entry-status">${getStatusLabel(log.from_status)} <span class="arrow">→</span> ${getStatusLabel(log.to_status)}</span>`;
    }

    const div = document.createElement('div');
    div.className = `log-entry new ${level}`;
    if (log.id) div.dataset.logId = log.id;
    div.innerHTML = `
        <span class="log-entry-time">${escHtml(time)}</span>
        <span class="log-entry-level ${level}">${level.toUpperCase()}</span>
        <span class="log-entry-agent">${escHtml(agent)}</span>
        <span class="log-entry-action">${escHtml(action)}</span>
        ${statusHtml}
        <span class="log-entry-msg">${escHtml(message)}</span>
    `;

    // 检查筛选条件
    const levelFilter = document.getElementById('logLevelFilter')?.value || '';
    const agentFilter = document.getElementById('logAgentFilter')?.value || '';
    if (levelFilter && level !== levelFilter) div.style.display = 'none';
    if (agentFilter && agent !== agentFilter) div.style.display = 'none';

    entries.appendChild(div);

    // 移除超出上限的旧日志
    while (entries.children.length > LOG_PANEL_MAX_ENTRIES) {
        entries.removeChild(entries.firstChild);
    }

    // 自动滚动
    if (logPanelAutoScroll) {
        const body = document.getElementById('logPanelBody');
        if (body) body.scrollTop = body.scrollHeight;
    }

    // 收起状态时显示新消息计数
    if (logPanelCollapsed) {
        logPanelNewCount++;
        const badge = document.getElementById('logPanelBadge');
        badge.textContent = logPanelNewCount > 99 ? '99+' : logPanelNewCount;
        badge.style.display = 'inline-block';
    }

    // 1 秒后移除高亮动画 class
    setTimeout(() => div.classList.remove('new'), 1000);
}

/**
 * 日志面板筛选
 */
function filterLogPanel() {
    const levelFilter = document.getElementById('logLevelFilter')?.value || '';
    const agentFilter = document.getElementById('logAgentFilter')?.value || '';
    const entries = document.getElementById('logPanelEntries');
    if (!entries) return;

    entries.querySelectorAll('.log-entry').forEach(el => {
        const level = el.querySelector('.log-entry-level')?.textContent?.toLowerCase() || '';
        const agent = el.querySelector('.log-entry-agent')?.textContent || '';
        let show = true;
        if (levelFilter && level !== levelFilter) show = false;
        if (agentFilter && agent !== agentFilter) show = false;
        el.style.display = show ? '' : 'none';
    });
}

/**
 * 进入项目后加载历史日志到面板
 */
async function loadLogPanelHistory() {
    if (!currentProjectId) return;
    try {
        const data = await api(`/projects/${currentProjectId}/logs?limit=50`);
        const logs = data.logs || [];
        // 历史日志按时间正序显示（API 返回 DESC，翻转一下）
        logs.reverse().forEach(log => appendLogEntry(log));
    } catch (e) {
        console.warn('[LogPanel] 加载历史日志失败:', e);
    }
}

// ==================== 工具函数 ====================

function escHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

function formatDate(iso) {
    if (!iso) return '-';
    try {
        const d = new Date(iso);
        return `${d.getMonth() + 1}/${d.getDate()}`;
    } catch { return '-'; }
}

function formatDateTime(iso) {
    if (!iso) return '-';
    try {
        const d = new Date(iso);
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    } catch { return '-'; }
}

function formatTime(iso) {
    if (!iso) return '';
    try {
        const d = new Date(iso);
        return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    } catch { return ''; }
}

function pad(n) { return n.toString().padStart(2, '0'); }

const STATUS_LABELS = {
    pending: '待启动', architecture_in_progress: '架构中', architecture_done: '架构完成',
    development_in_progress: '开发中', development_done: '开发完成',
    acceptance_passed: '验收通过', acceptance_rejected: '验收不通过',
    testing_in_progress: '测试中', testing_done: '测试通过', testing_failed: '测试不通过',
    deploying: '部署中', deployed: '已部署', cancelled: '已取消',
    submitted: '已提交', analyzing: '分析中', decomposed: '已拆单',
    in_progress: '进行中', completed: '已完成',
};

function getStatusLabel(status) {
    return STATUS_LABELS[status] || status || '-';
}

function getStatusColor(status) {
    if (status.includes('deployed') || status === 'completed' || status === 'testing_done' || status === 'acceptance_passed') return 'var(--success)';
    if (status.includes('_in_progress') || status === 'deploying' || status === 'analyzing' || status === 'in_progress') return 'var(--info)';
    if (status.includes('rejected') || status.includes('failed') || status === 'cancelled') return 'var(--error)';
    if (status === 'pending' || status === 'submitted') return 'var(--text-muted)';
    return 'var(--primary)';
}

function getArtifactIcon(type) {
    const icons = {
        prd: '📄', architecture: '🏗️', code: '💻', test: '🧪', deploy_config: '🚀',
    };
    return icons[type] || '📦';
}

function tryFormatJson(str) {
    if (!str) return '';
    try {
        return JSON.stringify(JSON.parse(str), null, 2);
    } catch {
        return str;
    }
}
