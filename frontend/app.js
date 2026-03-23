/**
 * AI 自动开发系统 - 前端应用 v0.2
 * 支持任务分解展示、项目详情、阶段进度追踪
 */

// API 配置
const API_BASE_URL = window.location.protocol === 'file:'
    ? 'http://localhost:8000'
    : window.location.origin;

// 全局状态
let projects = [];
let currentProjectId = null;

// ============ 页面路由 ============

function showPage(pageName) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.menu-item').forEach(m => m.classList.remove('active'));

    const page = document.getElementById(`page-${pageName}`);
    const menu = document.querySelector(`[data-page="${pageName}"]`);
    if (page) page.classList.add('active');
    if (menu) menu.classList.add('active');

    // 显示/隐藏详情菜单项
    const detailMenu = document.querySelector('[data-page="project-detail"]');
    if (detailMenu) {
        detailMenu.style.display = (pageName === 'project-detail') ? 'block' : 'none';
    }

    // 页面初始化
    if (pageName === 'home') loadStats();
    else if (pageName === 'projects') loadProjectsFromAPI();
    else if (pageName === 'tools') loadTools();
}

// ============ 提示信息 ============

function showAlert(message, type = 'info') {
    const el = document.getElementById('submit-alert');
    if (!el) return;
    el.textContent = message;
    el.className = `alert alert-${type}`;
    el.classList.remove('hidden');
    setTimeout(() => el.classList.add('hidden'), 4000);
}

// ============ 提交需求 ============

async function submitRequirement() {
    const userInput = document.getElementById('user-input').value.trim();
    const techStack = document.getElementById('tech-stack').value.trim();
    const projectName = document.getElementById('project-name').value.trim();
    const submitBtn = document.getElementById('submit-btn');
    const submitBtnText = document.getElementById('submit-btn-text');

    if (!userInput) {
        showAlert('请输入项目描述', 'error');
        return;
    }

    submitBtn.disabled = true;
    submitBtnText.innerHTML = '<span class="loading"></span> 分析中...';

    try {
        const response = await fetch(`${API_BASE_URL}/api/process`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                description: userInput,
                tech_stack: techStack ? { preference: techStack } : null,
                preferences: projectName ? { project_name: projectName } : null,
            }),
        });

        const data = await response.json();

        if (response.ok) {
            showAlert(
                `需求提交成功！已分解为 ${data.task_count} 个任务`,
                'success'
            );
            currentProjectId = data.project_id;

            // 清空表单
            document.getElementById('user-input').value = '';
            document.getElementById('tech-stack').value = '';
            document.getElementById('project-name').value = '';

            // 跳转到项目详情
            setTimeout(() => viewProject(data.project_id), 800);
        } else {
            let errorMsg = '未知错误';
            if (data.detail) {
                if (typeof data.detail === 'string') errorMsg = data.detail;
                else if (Array.isArray(data.detail)) {
                    errorMsg = data.detail.map(e => e.msg || JSON.stringify(e)).join('; ');
                } else errorMsg = JSON.stringify(data.detail);
            }
            showAlert(`提交失败: ${errorMsg}`, 'error');
        }
    } catch (err) {
        showAlert(`网络错误: ${err.message}`, 'error');
    } finally {
        submitBtn.disabled = false;
        submitBtnText.textContent = '提交需求';
    }
}

// ============ 首页统计 ============

async function loadStats() {
    try {
        const [healthRes, projectsRes] = await Promise.all([
            fetch(`${API_BASE_URL}/health`).catch(() => null),
            fetch(`${API_BASE_URL}/api/projects`).catch(() => null),
        ]);

        if (healthRes && healthRes.ok) {
            const h = await healthRes.json();
            setText('stat-tools-available', h.tools_available || 0);
            setText('stat-total-projects', h.projects_count || 0);
        }

        if (projectsRes && projectsRes.ok) {
            const data = await projectsRes.json();
            const list = data.projects || [];
            setText('stat-total-projects', list.length);
            setText('stat-completed', list.filter(p => p.phase === 'completed').length);
            setText('stat-in-progress',
                list.filter(p => p.in_progress_count > 0).length
            );
        }
    } catch (err) {
        console.error('加载统计失败:', err);
    }
}

// ============ 项目列表（从 API 加载） ============

async function loadProjectsFromAPI() {
    const container = document.getElementById('projects-list');
    container.innerHTML = '<p style="text-align:center;padding:20px;color:rgba(0,0,0,0.25)"><span class="loading"></span> 加载中...</p>';

    try {
        const response = await fetch(`${API_BASE_URL}/api/projects`);
        const data = await response.json();

        if (!response.ok) throw new Error(data.detail || '加载失败');

        projects = data.projects || [];

        if (projects.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="icon">📂</div>
                    <p>暂无项目，点击「提交需求」开始你的第一个项目</p>
                </div>`;
            return;
        }

        container.innerHTML = projects.map(p => {
            const progress = p.task_count > 0
                ? Math.round((p.completed_count / p.task_count) * 100)
                : 0;
            return `
                <div class="project-card" onclick="viewProject('${p.project_id}')">
                    <div class="project-card-header">
                        <h4>${escapeHtml(p.name || '未命名项目')}</h4>
                        <span class="tag tag-${p.phase}">${getPhaseLabel(p.phase)}</span>
                    </div>
                    <p>${escapeHtml((p.description || '').substring(0, 100))}</p>
                    <div class="progress-bar-container">
                        <div class="progress-bar-fill" style="width:${progress}%"></div>
                    </div>
                    <div class="project-card-meta">
                        <span>任务: ${p.completed_count}/${p.task_count}</span>
                        <span>进度: ${progress}%</span>
                        ${p.in_progress_count > 0 ? `<span style="color:#1890ff">${p.in_progress_count} 进行中</span>` : ''}
                        ${p.failed_count > 0 ? `<span style="color:#ff4d4f">${p.failed_count} 失败</span>` : ''}
                        <span>${formatTime(p.created_at)}</span>
                    </div>
                </div>`;
        }).join('');
    } catch (err) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="icon">⚠️</div>
                <p>加载失败: ${escapeHtml(err.message)}<br>请确保后端服务运行在 ${API_BASE_URL}</p>
            </div>`;
    }
}

// ============ 项目详情 ============

async function viewProject(projectId) {
    currentProjectId = projectId;
    showPage('project-detail');

    const container = document.getElementById('project-detail-content');
    container.innerHTML = '<p style="text-align:center;padding:40px"><span class="loading"></span> 加载项目详情...</p>';

    try {
        const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/state`);
        const data = await response.json();

        if (!response.ok) throw new Error(data.detail || '加载失败');

        const state = data.project_state;
        const summary = data.task_summary;
        const progress = summary.total > 0
            ? Math.round((summary.completed / summary.total) * 100)
            : 0;

        container.innerHTML = `
            <!-- 项目头部 -->
            <div class="card">
                <div class="card-header">
                    <h3>${escapeHtml(state.name || '未命名项目')}</h3>
                    <span class="tag tag-${state.phase}">${getPhaseLabel(state.phase)}</span>
                </div>
                <p style="color:rgba(0,0,0,0.55);margin:0 0 16px 0;line-height:1.6">${escapeHtml(state.description || '')}</p>
                
                <!-- 统计摘要 -->
                <div class="summary-bar">
                    <div class="summary-item">
                        <div class="num">${summary.total}</div>
                        <div class="lbl">总任务</div>
                    </div>
                    <div class="summary-item">
                        <div class="num" style="color:#52c41a">${summary.completed}</div>
                        <div class="lbl">已完成</div>
                    </div>
                    <div class="summary-item">
                        <div class="num" style="color:#1890ff">${summary.in_progress}</div>
                        <div class="lbl">进行中</div>
                    </div>
                    <div class="summary-item">
                        <div class="num">${summary.pending}</div>
                        <div class="lbl">待处理</div>
                    </div>
                    <div class="summary-item">
                        <div class="num" style="color:#ff4d4f">${summary.failed}</div>
                        <div class="lbl">失败</div>
                    </div>
                </div>

                <!-- 进度条 -->
                <div style="display:flex;align-items:center;gap:12px">
                    <div class="progress-bar-container" style="flex:1">
                        <div class="progress-bar-fill" style="width:${progress}%"></div>
                    </div>
                    <span class="progress-text">${progress}%</span>
                </div>

                <!-- 操作按钮 -->
                <div style="margin-top:16px;display:flex;gap:12px">
                    <button class="btn btn-success btn-sm" onclick="executeProject('${projectId}')">
                        ▶ 执行下一个任务
                    </button>
                    <button class="btn btn-default btn-sm" onclick="viewProject('${projectId}')">
                        🔄 刷新
                    </button>
                </div>
            </div>

            <!-- 任务列表（按阶段分组） -->
            <div class="card">
                <div class="card-header">
                    <h3>任务分解</h3>
                </div>
                ${renderTasksByPhase(state.tasks_by_phase)}
            </div>

            <!-- 项目日志 -->
            ${state.logs && state.logs.length > 0 ? `
            <div class="card">
                <div class="card-header">
                    <h3>项目日志</h3>
                </div>
                <div class="log-list">
                    ${state.logs.slice(-20).reverse().map(log => `
                        <div class="log-item">
                            <span class="log-time">${formatTime(log.timestamp)}</span>
                            <span class="log-event">${escapeHtml(log.event)}</span>
                            <span>${escapeHtml(formatLogData(log.data))}</span>
                        </div>
                    `).join('')}
                </div>
            </div>` : ''}
        `;
    } catch (err) {
        container.innerHTML = `
            <div class="card">
                <div class="empty-state">
                    <div class="icon">⚠️</div>
                    <p>加载项目详情失败: ${escapeHtml(err.message)}</p>
                </div>
            </div>`;
    }
}

// ============ 渲染按阶段分组的任务 ============

function renderTasksByPhase(tasksByPhase) {
    if (!tasksByPhase || Object.keys(tasksByPhase).length === 0) {
        return '<p style="color:rgba(0,0,0,0.25);text-align:center;padding:20px">暂无任务数据</p>';
    }

    const phaseConfig = {
        'requirement': { icon: '📋', label: '需求分析', color: '#722ed1' },
        'design':      { icon: '🎨', label: '架构设计', color: '#1890ff' },
        'development': { icon: '💻', label: '开发实现', color: '#fa8c16' },
        'testing':     { icon: '🧪', label: '测试验证', color: '#13c2c2' },
        'deployment':  { icon: '🚀', label: '部署上线', color: '#52c41a' },
    };

    const phaseOrder = ['requirement', 'design', 'development', 'testing', 'deployment'];

    let html = '';
    for (const phase of phaseOrder) {
        const tasks = tasksByPhase[phase];
        if (!tasks || tasks.length === 0) continue;

        const config = phaseConfig[phase] || { icon: '📦', label: phase, color: '#999' };
        const completed = tasks.filter(t => t.status === 'completed').length;

        html += `
            <div class="phase-section">
                <div class="phase-header">
                    <div class="phase-icon" style="background:${config.color}15;color:${config.color}">
                        ${config.icon}
                    </div>
                    <h4>${config.label}</h4>
                    <span class="phase-count">${completed}/${tasks.length} 完成</span>
                </div>
                ${tasks.map(task => renderTaskRow(task)).join('')}
            </div>
        `;
    }

    return html || '<p style="color:rgba(0,0,0,0.25);text-align:center;padding:20px">暂无任务数据</p>';
}

function renderTaskRow(task) {
    const statusIcon = {
        'pending': '⬜',
        'in_progress': '🔵',
        'completed': '✅',
        'failed': '❌',
        'cancelled': '⛔',
    };

    return `
        <div class="task-row">
            <span>${statusIcon[task.status] || '⬜'}</span>
            <span class="task-name">${escapeHtml(task.name)}</span>
            <div class="task-meta">
                <span class="priority-dot priority-${task.priority || 'medium'}"></span>
                <span class="agent-tag">${getAgentLabel(task.assigned_agent)}</span>
                ${task.estimated_hours ? `<span>${task.estimated_hours}h</span>` : ''}
                <span class="tag tag-${task.status}">${getStatusLabel(task.status)}</span>
            </div>
        </div>
    `;
}

// ============ 执行项目 ============

async function executeProject(projectId) {
    try {
        const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/execute`, {
            method: 'POST',
        });
        const data = await response.json();

        if (response.ok) {
            // 刷新项目详情
            setTimeout(() => viewProject(projectId), 300);
        } else {
            alert('执行失败: ' + (data.detail || '未知错误'));
        }
    } catch (err) {
        alert('网络错误: ' + err.message);
    }
}

// ============ 工具列表 ============

async function loadTools() {
    const container = document.getElementById('tools-list');
    container.innerHTML = '<p>加载中...</p>';

    try {
        const response = await fetch(`${API_BASE_URL}/tools`);
        const data = await response.json();

        if (response.ok && data.tools) {
            const tools = Object.values(data.tools);
            container.innerHTML = tools.map(tool => `
                <div class="tool-card">
                    <h4>${escapeHtml(tool.name)}</h4>
                    <p>${escapeHtml(tool.description || '暂无描述')}</p>
                </div>
            `).join('');
        } else {
            container.innerHTML = '<p>加载工具列表失败</p>';
        }
    } catch (err) {
        container.innerHTML = `<p>网络错误: ${escapeHtml(err.message)}</p>`;
    }
}

// ============ 工具函数 ============

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function getStatusLabel(status) {
    const map = {
        'pending': '待处理',
        'in_progress': '进行中',
        'completed': '已完成',
        'failed': '失败',
        'cancelled': '已取消',
        'analyzing': '分析中',
        'executing': '执行中',
    };
    return map[status] || status;
}

function getPhaseLabel(phase) {
    const map = {
        'requirement_analysis': '需求分析',
        'design': '架构设计',
        'development': '开发中',
        'testing': '测试中',
        'deployment': '部署中',
        'completed': '已完成',
    };
    return map[phase] || phase;
}

function getAgentLabel(agent) {
    const map = {
        'product': '产品',
        'architect': '架构师',
        'dev': '开发',
        'test': '测试',
        'review': '审查',
        'deploy': '运维',
    };
    return map[agent] || agent || '未分配';
}

function formatTime(isoString) {
    if (!isoString) return '';
    try {
        const d = new Date(isoString);
        return d.toLocaleString('zh-CN', {
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
        });
    } catch {
        return isoString;
    }
}

function formatLogData(data) {
    if (!data) return '';
    if (typeof data === 'string') return data;
    const parts = [];
    if (data.task_name) parts.push(data.task_name);
    if (data.old_status && data.new_status) {
        parts.push(`${data.old_status} → ${data.new_status}`);
    }
    if (data.task_count) parts.push(`${data.task_count} 个任务`);
    if (data.requirement) parts.push(data.requirement.substring(0, 60));
    return parts.join(' | ') || JSON.stringify(data).substring(0, 80);
}

// ============ 事件绑定 ============

document.querySelectorAll('.menu-item').forEach(item => {
    item.addEventListener('click', () => {
        const page = item.getAttribute('data-page');
        if (page) showPage(page);
    });
});

// 初始化
window.addEventListener('DOMContentLoaded', () => {
    showPage('home');
});

// 自动刷新项目状态（项目详情页，每 8 秒）
setInterval(() => {
    if (currentProjectId &&
        document.getElementById('page-project-detail') &&
        document.getElementById('page-project-detail').classList.contains('active')) {
        viewProject(currentProjectId);
    }
}, 8000);
