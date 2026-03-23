/**
 * AI 自动开发系统 - 前端应用 v0.5
 * 支持 LLM 配置、任务分解展示、项目详情、阶段进度追踪、
 * 一键执行、文件浏览、SSE 实时推送、代码语法高亮
 */

// API 配置
const API_BASE_URL = window.location.protocol === 'file:'
    ? 'http://localhost:8000'
    : window.location.origin;

// 全局状态
let projects = [];
let currentProjectId = null;
let sseConnection = null;  // SSE 连接
let processLogs = [];       // 处理过程日志
let logPanelCollapsed = false;  // Log 面板折叠状态

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
        detailMenu.style.display = (pageName === 'project-detail' || pageName === 'file-browser') ? 'block' : 'none';
    }
    const fbMenu = document.querySelector('[data-page="file-browser"]');
    if (fbMenu) {
        fbMenu.style.display = (pageName === 'file-browser') ? 'block' : 'none';
    }

    // 离开项目详情页时断开 SSE
    if (pageName !== 'project-detail' && pageName !== 'file-browser') {
        disconnectSSE();
    }

    // 页面初始化
    if (pageName === 'home') loadStats();
    else if (pageName === 'projects') loadProjectsFromAPI();
    else if (pageName === 'tools') loadTools();
    else if (pageName === 'llm-config') loadLLMStatus();
    else if (pageName === 'file-browser' && currentProjectId) loadFileBrowser(currentProjectId);
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

            // LLM 状态指示
            const badge = document.getElementById('llm-status-badge');
            const modelInfo = document.getElementById('llm-model-info');
            if (badge) {
                if (h.llm_enabled) {
                    badge.style.background = '#f6ffed';
                    badge.style.borderColor = '#b7eb8f';
                    badge.style.color = '#389e0d';
                    badge.innerHTML = '<span>●</span> LLM 已启用';
                    if (modelInfo) modelInfo.textContent = `模型: ${h.llm_model || 'N/A'}`;
                } else {
                    badge.style.background = '#fff1f0';
                    badge.style.borderColor = '#ffa39e';
                    badge.style.color = '#cf1322';
                    badge.innerHTML = '<span>●</span> LLM 未配置（使用模板引擎）';
                    if (modelInfo) modelInfo.textContent = '点击侧边栏「🧠 LLM 配置」进行设置';
                }
            }
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
    // 如果切换了项目，清空旧日志
    if (currentProjectId !== projectId) {
        processLogs = [];
    }
    currentProjectId = projectId;
    showPage('project-detail');

    // 连接 SSE 实时推送
    connectSSE(projectId);

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
                <div style="margin-top:16px;display:flex;gap:12px;flex-wrap:wrap">
                    <button class="btn btn-success btn-sm" onclick="executeProject('${projectId}')">
                        ▶ 执行下一个任务
                    </button>
                    <button class="btn btn-primary btn-sm" onclick="executeAllTasks('${projectId}')">
                        ⚡ 一键全量执行
                    </button>
                    <button class="btn btn-default btn-sm" onclick="openFileBrowser('${projectId}')">
                        📁 文件浏览器
                    </button>
                    <button class="btn btn-default btn-sm" onclick="downloadProject('${projectId}')">
                        📦 打包下载
                    </button>
                    <button class="btn btn-default btn-sm" onclick="viewProject('${projectId}')">
                        🔄 刷新
                    </button>
                </div>
            </div>

            <!-- 实时处理日志 -->
            <div class="card" style="padding:0;overflow:hidden">
                <div class="process-log-panel">
                    <div class="process-log-header" onclick="toggleLogPanel()">
                        <div class="process-log-title">
                            <span class="dot-pulse" id="log-pulse"></span>
                            <span>📋 处理日志</span>
                        </div>
                        <div class="process-log-actions">
                            <span class="log-badge" id="log-count-badge">${processLogs.length} 条</span>
                            <button class="log-clear-btn" onclick="event.stopPropagation();clearProcessLogs()">清空</button>
                            <span id="log-toggle-icon" style="font-size:12px">${logPanelCollapsed ? '▶' : '▼'}</span>
                        </div>
                    </div>
                    <div class="process-log-body ${logPanelCollapsed ? 'collapsed' : ''}" id="process-log-body">
                        ${processLogs.length > 0 ? processLogs.map(renderLogEntry).join('') : '<div class="log-empty">等待执行任务...</div>'}
                    </div>
                </div>
            </div>

            <!-- 任务列表（Pipeline 看板） -->
            <div class="card">
                <div class="card-header">
                    <h3>🔄 Pipeline</h3>
                    <span style="font-size:12px;color:rgba(0,0,0,0.35)">点击步骤查看日志</span>
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

    let stagesHtml = '';
    let isFirst = true;

    for (const phase of phaseOrder) {
        const tasks = tasksByPhase[phase];
        if (!tasks || tasks.length === 0) continue;

        const config = phaseConfig[phase] || { icon: '📦', label: phase, color: '#999' };

        // 计算 Stage 状态
        const completed = tasks.filter(t => t.status === 'completed').length;
        const failed = tasks.filter(t => t.status === 'failed').length;
        const running = tasks.filter(t => t.status === 'in_progress').length;
        const total = tasks.length;
        const allDone = completed === total;
        const hasRunning = running > 0;
        const hasFailed = failed > 0;

        // Stage 状态 class
        let stageClass = '';
        let iconClass = 'icon-pending';
        let iconContent = '';
        if (allDone) {
            stageClass = 'stage-completed';
            iconClass = 'icon-completed';
            iconContent = '✓';
        } else if (hasFailed) {
            stageClass = 'stage-failed';
            iconClass = 'icon-failed';
            iconContent = '!';
        } else if (hasRunning || completed > 0) {
            stageClass = 'stage-running';
            iconClass = 'icon-running';
            iconContent = '▸';
        }

        // 计算 Stage 总耗时
        let totalDuration = 0;
        tasks.forEach(t => {
            if (t.duration_seconds) totalDuration += t.duration_seconds;
        });
        const durationStr = totalDuration > 0 ? formatDuration(totalDuration) : '';

        // 连接线
        if (!isFirst) {
            const connActive = allDone ? 'active' : '';
            stagesHtml += `<div class="pipeline-connector"><div class="connector-line ${connActive}"></div></div>`;
        }
        isFirst = false;

        // Stage HTML
        stagesHtml += `
            <div class="pipeline-stage">
                <div class="stage-header ${stageClass}">
                    <div class="stage-status-icon ${iconClass}">${iconContent}</div>
                    <span class="stage-name">${config.icon} ${config.label}</span>
                    ${durationStr ? `<span class="stage-duration">${durationStr}</span>` : ''}
                </div>
                <div class="stage-steps ${allDone ? 'steps-completed' : hasRunning ? 'steps-running' : ''}">
                    ${tasks.map(task => renderPipelineStep(task)).join('')}
                </div>
            </div>
        `;
    }

    if (!stagesHtml) {
        return '<p style="color:rgba(0,0,0,0.25);text-align:center;padding:20px">暂无任务数据</p>';
    }

    return `<div class="pipeline-container"><div class="pipeline-stages">${stagesHtml}</div></div>`;
}

function renderPipelineStep(task) {
    let stepClass = '';
    let dotClass = 'dot-pending';

    if (task.status === 'completed') {
        stepClass = 'step-completed';
        dotClass = 'dot-completed';
    } else if (task.status === 'in_progress') {
        stepClass = 'step-running';
        dotClass = 'dot-running';
    } else if (task.status === 'failed') {
        stepClass = 'step-failed';
        dotClass = 'dot-failed';
    }

    const durationStr = task.duration_seconds ? formatDuration(task.duration_seconds) : '';

    return `
        <div class="step-item ${stepClass}" onclick="openTaskLog('${task.id}', '${escapeHtml(task.name)}', '${task.status}')" title="点击查看日志">
            <span class="step-dot ${dotClass}"></span>
            <span class="step-name">${escapeHtml(task.name)}</span>
            ${durationStr ? `<span class="step-time">${durationStr}</span>` : ''}
        </div>
    `;
}

function formatDuration(seconds) {
    if (!seconds || seconds <= 0) return '';
    if (seconds < 60) return seconds < 1 ? '<1s' : Math.round(seconds) + 's';
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}

// ============ 执行项目 ============

async function executeProject(projectId) {
    const btn = event ? event.target : null;
    const originalText = btn ? btn.innerHTML : '';

    appendProcessLog('step', '用户触发: 执行下一个任务', '');

    try {
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="loading"></span> 执行中...';
        }

        const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/execute`, {
            method: 'POST',
        });
        const data = await response.json();

        if (response.ok) {
            // 显示执行结果
            const msg = data.message || '执行完成';
            const filesCount = data.files_count || 0;
            const displayMsg = filesCount > 0
                ? `✓ ${data.current_task || '任务完成'} (生成 ${filesCount} 个文件)`
                : `✓ ${msg.substring(0, 60)}`;
            if (btn) {
                btn.innerHTML = displayMsg;
                btn.style.background = '#52c41a';
                setTimeout(() => {
                    btn.innerHTML = originalText;
                    btn.style.background = '';
                    btn.disabled = false;
                }, 2000);
            }
            // 刷新项目详情
            setTimeout(() => viewProject(projectId), 500);
        } else {
            alert('执行失败: ' + (data.detail || '未知错误'));
            if (btn) {
                btn.innerHTML = originalText;
                btn.disabled = false;
            }
        }
    } catch (err) {
        alert('网络错误: ' + err.message);
        if (btn) {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
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

// ============ 一键全量执行 ============

async function executeAllTasks(projectId) {
    const btn = event ? event.target : null;
    const originalText = btn ? btn.innerHTML : '';

    if (!confirm('确认一键执行所有任务？这将依次执行所有 pending 任务。')) return;

    appendProcessLog('step', '用户触发: 一键全量执行', '依次执行所有待处理任务');

    try {
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="loading"></span> 全量执行中...';
        }

        const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/execute-all`, {
            method: 'POST',
        });
        const data = await response.json();

        if (response.ok) {
            const msg = data.message || '全量执行完成';
            if (btn) {
                btn.innerHTML = `✓ ${msg}`;
                btn.style.background = '#52c41a';
                setTimeout(() => {
                    btn.innerHTML = originalText;
                    btn.style.background = '';
                    btn.disabled = false;
                }, 3000);
            }
            // 刷新项目详情
            setTimeout(() => viewProject(projectId), 500);
        } else {
            alert('执行失败: ' + (data.detail || '未知错误'));
            if (btn) { btn.innerHTML = originalText; btn.disabled = false; }
        }
    } catch (err) {
        alert('网络错误: ' + err.message);
        if (btn) { btn.innerHTML = originalText; btn.disabled = false; }
    }
}

// ============ SSE 实时推送 ============

function connectSSE(projectId) {
    // 关闭旧连接
    disconnectSSE();

    const url = `${API_BASE_URL}/api/projects/${projectId}/events`;
    sseConnection = new EventSource(url);

    sseConnection.addEventListener('init', (e) => {
        console.log('[SSE] 已连接，初始状态:', e.data);
        appendProcessLog('info', 'SSE 连接已建立', '实时推送就绪');
    });

    sseConnection.addEventListener('log', (e) => {
        console.log('[SSE] 处理日志:', e.data);
        try {
            const data = JSON.parse(e.data);
            appendProcessLog(data.level || 'info', data.message || '', data.detail || '');
        } catch {}
    });

    sseConnection.addEventListener('task_update', (e) => {
        console.log('[SSE] 任务更新:', e.data);
        // 自动刷新项目详情
        if (currentProjectId === projectId) {
            viewProject(projectId);
        }
    });

    sseConnection.addEventListener('task_progress', (e) => {
        console.log('[SSE] 任务进度:', e.data);
        try {
            const data = JSON.parse(e.data);
            showToast(`✓ ${data.task} 完成 (${data.files_count} 个文件)`, 'success');
            appendProcessLog('success', `第 ${data.step} 步完成: ${data.task}`, `Agent: ${data.agent}，${data.files_count} 个文件`);
        } catch {}
    });

    sseConnection.addEventListener('execute_all_done', (e) => {
        console.log('[SSE] 全量执行完成:', e.data);
        if (currentProjectId === projectId) {
            viewProject(projectId);
        }
        try {
            const data = JSON.parse(e.data);
            showToast(data.message || '全量执行完成', 'success');
            appendProcessLog('success', '全量执行完成', data.message || '');
        } catch {}
    });

    sseConnection.addEventListener('heartbeat', () => {
        // 心跳包，无需处理
    });

    sseConnection.onerror = () => {
        console.log('[SSE] 连接中断，将在 5 秒后重连...');
        disconnectSSE();
        setTimeout(() => {
            if (currentProjectId === projectId) {
                connectSSE(projectId);
            }
        }, 5000);
    };
}

function disconnectSSE() {
    if (sseConnection) {
        sseConnection.close();
        sseConnection = null;
    }
}

function showToast(message, type = 'info') {
    // 简易 Toast 提示
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.style.cssText = 'position:fixed;top:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:8px';
        document.body.appendChild(container);
    }

    const colors = {
        success: { bg: '#f6ffed', border: '#b7eb8f', text: '#389e0d' },
        error: { bg: '#fff1f0', border: '#ffa39e', text: '#cf1322' },
        info: { bg: '#e6f7ff', border: '#91d5ff', text: '#096dd9' },
    };
    const c = colors[type] || colors.info;

    const toast = document.createElement('div');
    toast.style.cssText = `padding:12px 20px;border-radius:8px;font-size:14px;background:${c.bg};border:1px solid ${c.border};color:${c.text};box-shadow:0 4px 12px rgba(0,0,0,0.1);transition:all 0.3s;opacity:1;max-width:400px`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ============ 代码语法高亮 ============

// ============ 处理日志面板 ============

function appendProcessLog(level, message, detail) {
    const entry = {
        time: new Date(),
        level: level,
        message: message,
        detail: detail || '',
    };
    processLogs.push(entry);

    // 限制最多保留 200 条
    if (processLogs.length > 200) {
        processLogs = processLogs.slice(-200);
    }

    // 实时追加到 DOM（不刷新整个页面）
    const logBody = document.getElementById('process-log-body');
    if (logBody) {
        // 清掉空状态提示
        const empty = logBody.querySelector('.log-empty');
        if (empty) empty.remove();

        const div = document.createElement('div');
        div.innerHTML = renderLogEntry(entry);
        const el = div.firstElementChild;
        logBody.appendChild(el);

        // 自动滚动到底部
        logBody.scrollTop = logBody.scrollHeight;
    }

    // 更新计数器
    const badge = document.getElementById('log-count-badge');
    if (badge) badge.textContent = `${processLogs.length} 条`;

    // 让脉冲点闪一下
    const pulse = document.getElementById('log-pulse');
    if (pulse) {
        pulse.style.background = '#52c41a';
        setTimeout(() => { pulse.style.background = '#52c41a'; }, 500);
    }
}

function renderLogEntry(entry) {
    const levelIcons = {
        step:    '▸',
        info:    '•',
        success: '✓',
        warning: '⚠',
        error:   '✗',
    };
    const icon = levelIcons[entry.level] || '•';
    const timeStr = entry.time instanceof Date
        ? entry.time.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
        : '';
    const detailHtml = entry.detail ? `<span class="log-entry-detail">— ${escapeHtml(entry.detail)}</span>` : '';

    return `<div class="log-entry">
        <span class="log-entry-time">${timeStr}</span>
        <span class="log-entry-level log-level-${entry.level}">${icon}</span>
        <span class="log-entry-msg">${escapeHtml(entry.message)}${detailHtml}</span>
    </div>`;
}

function toggleLogPanel() {
    logPanelCollapsed = !logPanelCollapsed;
    const body = document.getElementById('process-log-body');
    const icon = document.getElementById('log-toggle-icon');
    if (body) {
        body.classList.toggle('collapsed', logPanelCollapsed);
    }
    if (icon) {
        icon.textContent = logPanelCollapsed ? '▶' : '▼';
    }
}

function clearProcessLogs() {
    processLogs = [];
    const logBody = document.getElementById('process-log-body');
    if (logBody) {
        logBody.innerHTML = '<div class="log-empty">日志已清空</div>';
    }
    const badge = document.getElementById('log-count-badge');
    if (badge) badge.textContent = '0 条';
}

// ============ 任务日志抽屉 ============

async function openTaskLog(taskId, taskName, taskStatus) {
    // 关闭已有的
    closeTaskLog();

    // 创建 overlay
    const overlay = document.createElement('div');
    overlay.className = 'log-drawer-overlay';
    overlay.id = 'log-drawer-overlay';
    overlay.onclick = (e) => {
        if (e.target === overlay) closeTaskLog();
    };

    const statusIcon = {
        'completed': '<span style="color:#52c41a">✓</span>',
        'in_progress': '<span style="color:#1890ff">●</span>',
        'failed': '<span style="color:#ff4d4f">✗</span>',
        'pending': '<span style="color:#999">○</span>',
    }[taskStatus] || '';

    overlay.innerHTML = `
        <div class="log-drawer">
            <div class="log-drawer-header">
                <h4>${statusIcon} ${escapeHtml(taskName)}</h4>
                <button class="close-btn" onclick="closeTaskLog()">✕</button>
            </div>
            <div class="log-drawer-tabs">
                <div class="log-drawer-tab active">日志</div>
                <div class="log-drawer-tab" style="color:#555;cursor:default">配置</div>
            </div>
            <div class="log-search">
                <input type="text" placeholder="Search" id="log-search-input" oninput="filterTaskLogs(this.value)">
                <span class="match-count" id="log-match-count"></span>
            </div>
            <div class="log-drawer-body" id="log-drawer-body">
                <div class="log-empty-msg"><span class="loading"></span> 加载日志...</div>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';

    // 加载日志
    try {
        const response = await fetch(`${API_BASE_URL}/api/projects/${currentProjectId}/tasks/${taskId}/logs`);
        const data = await response.json();

        const body = document.getElementById('log-drawer-body');
        if (!body) return;

        const logs = data.logs || [];
        if (logs.length === 0) {
            body.innerHTML = '<div class="log-empty-msg">暂无日志记录<br><span style="font-size:11px;color:#444">任务执行后会在此显示详细日志</span></div>';
            return;
        }

        // 存储到全局供搜索用
        window._currentTaskLogs = logs;

        body.innerHTML = logs.map((log, i) => renderTaskLogLine(log, i + 1)).join('');

        // 滚动到底部
        body.scrollTop = body.scrollHeight;
    } catch (err) {
        const body = document.getElementById('log-drawer-body');
        if (body) {
            body.innerHTML = `<div class="log-empty-msg" style="color:#f44747">加载失败: ${escapeHtml(err.message)}</div>`;
        }
    }
}

function renderTaskLogLine(log, lineNum) {
    const levelIcons = {
        step: '▸', info: '•', success: '✓', warning: '⚠', error: '✗',
    };
    const icon = levelIcons[log.level] || '•';
    const levelClass = 'll-' + (log.level || 'info');

    let timeStr = '';
    if (log.timestamp) {
        try {
            const d = new Date(log.timestamp);
            timeStr = d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        } catch {}
    }

    const detailHtml = log.detail ? ` <span class="log-line-detail">— ${escapeHtml(log.detail)}</span>` : '';

    return `<div class="log-line" data-msg="${escapeHtml((log.message || '') + ' ' + (log.detail || '')).toLowerCase()}">
        <span class="log-line-num">${lineNum}</span>
        <span class="log-line-time">${timeStr}</span>
        <span class="log-line-level ${levelClass}">${icon}</span>
        <span class="log-line-msg">${escapeHtml(log.message || '')}${detailHtml}</span>
    </div>`;
}

function filterTaskLogs(query) {
    const body = document.getElementById('log-drawer-body');
    const countEl = document.getElementById('log-match-count');
    if (!body) return;

    const lines = body.querySelectorAll('.log-line');
    const q = (query || '').toLowerCase().trim();
    let matchCount = 0;

    lines.forEach(line => {
        if (!q) {
            line.style.display = '';
            matchCount++;
        } else {
            const msg = line.getAttribute('data-msg') || '';
            if (msg.includes(q)) {
                line.style.display = '';
                matchCount++;
            } else {
                line.style.display = 'none';
            }
        }
    });

    if (countEl) {
        countEl.textContent = q ? `${matchCount}/${lines.length}` : '';
    }
}

function closeTaskLog() {
    const overlay = document.getElementById('log-drawer-overlay');
    if (overlay) {
        overlay.remove();
        document.body.style.overflow = '';
    }
    window._currentTaskLogs = null;
}

// ============ 代码语法高亮（实现） ============

function highlightCode(code, filename) {
    if (typeof hljs === 'undefined') return escapeHtml(code);

    // 根据文件名推断语言
    const ext = (filename || '').split('.').pop().toLowerCase();
    const langMap = {
        'py': 'python', 'js': 'javascript', 'ts': 'typescript',
        'html': 'html', 'css': 'css', 'json': 'json',
        'md': 'markdown', 'yml': 'yaml', 'yaml': 'yaml',
        'sh': 'bash', 'bash': 'bash', 'sql': 'sql',
        'toml': 'ini', 'ini': 'ini', 'cfg': 'ini',
        'xml': 'xml', 'jsx': 'javascript', 'tsx': 'typescript',
    };

    const lang = langMap[ext];
    if (lang) {
        try {
            return hljs.highlight(code, { language: lang }).value;
        } catch { /* fall through */ }
    }
    // 自动检测
    try {
        return hljs.highlightAuto(code).value;
    } catch {
        return escapeHtml(code);
    }
}

// ============ 文件浏览器（GitHub 风格） ============

let fbFiles = [];           // 当前项目的所有文件
let fbCurrentFile = null;   // 当前选中的文件路径
let fbRawMode = false;      // 是否原始文本模式
let fbFileContent = '';     // 当前文件内容缓存

function openFileBrowser(projectId) {
    currentProjectId = projectId;
    showPage('file-browser');
    loadFileBrowser(projectId);
}

async function loadFileBrowser(projectId) {
    if (!projectId) projectId = currentProjectId;
    if (!projectId) return;

    const treeContainer = document.getElementById('fb-tree-container');
    if (treeContainer) {
        treeContainer.innerHTML = '<div class="fb-loading"><span class="loading"></span>&nbsp;加载中...</div>';
    }

    // 获取项目名称
    try {
        const stateRes = await fetch(`${API_BASE_URL}/api/projects/${projectId}/state`);
        if (stateRes.ok) {
            const stateData = await stateRes.json();
            const name = stateData.project_state?.name || '未命名项目';
            const titleEl = document.getElementById('fb-project-title');
            const repoNameEl = document.getElementById('fb-repo-name');
            if (titleEl) titleEl.textContent = `📂 ${name}`;
            if (repoNameEl) repoNameEl.textContent = name;
        }
    } catch (e) { /* ignore */ }

    // 加载文件列表
    try {
        const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/files`);
        const data = await response.json();

        if (!response.ok) throw new Error(data.detail || '加载失败');

        fbFiles = data.files || [];
        const countEl = document.getElementById('fb-file-count');
        if (countEl) countEl.textContent = `${fbFiles.length} 个文件`;

        renderFileTree(fbFiles);

        // 重置右侧
        fbCurrentFile = null;
        const header = document.getElementById('fb-main-header');
        const tabs = document.getElementById('fb-tabs');
        if (header) header.style.display = 'none';
        if (tabs) tabs.style.display = 'none';
        const codeContainer = document.getElementById('fb-code-container');
        if (codeContainer) {
            codeContainer.innerHTML = `
                <div class="fb-empty-state">
                    <div class="fb-empty-icon">📂</div>
                    <p>选择左侧文件查看内容</p>
                    <p style="font-size:12px;color:#8b949e">共 ${fbFiles.length} 个文件，支持语法高亮和行号显示</p>
                </div>`;
        }
    } catch (err) {
        if (treeContainer) {
            treeContainer.innerHTML = `<div class="fb-empty-state" style="min-height:200px"><p style="color:#cf1322">加载失败: ${escapeHtml(err.message)}</p></div>`;
        }
    }
}

function renderFileTree(files) {
    const container = document.getElementById('fb-tree-container');
    if (!container) return;

    if (files.length === 0) {
        container.innerHTML = `<div class="fb-empty-state" style="min-height:200px;padding:20px"><div class="fb-empty-icon">📂</div><p>暂无文件</p><p style="font-size:12px">请先执行任务生成文件</p></div>`;
        return;
    }

    // 构建树结构
    const tree = {};
    files.forEach(f => {
        const parts = f.path.split('/');
        let current = tree;
        for (let i = 0; i < parts.length - 1; i++) {
            if (!current[parts[i]]) {
                current[parts[i]] = { _isDir: true, _children: {} };
            }
            current = current[parts[i]]._children;
        }
        current[parts[parts.length - 1]] = { _isDir: false, _file: f };
    });

    container.innerHTML = renderTreeNode(tree, 0);
}

function renderTreeNode(node, depth) {
    let html = '';
    const indent = depth * 16;

    // 先渲染目录，再渲染文件
    const dirs = [];
    const fileItems = [];

    for (const [name, val] of Object.entries(node)) {
        if (val._isDir) {
            dirs.push([name, val]);
        } else if (val._file) {
            fileItems.push([name, val._file]);
        }
    }

    // 排序
    dirs.sort((a, b) => a[0].localeCompare(b[0]));
    fileItems.sort((a, b) => a[0].localeCompare(b[0]));

    // 目录
    dirs.forEach(([name, dir]) => {
        const childrenHtml = renderTreeNode(dir._children, depth + 1);
        const dirId = 'fbdir-' + Math.random().toString(36).substr(2, 8);
        html += `
            <div class="fb-tree-item fb-tree-dir" style="padding-left:${16 + indent}px" onclick="toggleFbDir('${dirId}', this)">
                <span class="fb-toggle">▼</span>
                <span class="fb-icon fb-icon-folder">📁</span>
                <span class="fb-name">${escapeHtml(name)}</span>
            </div>
            <div class="fb-tree-children" id="${dirId}">
                ${childrenHtml}
            </div>`;
    });

    // 文件
    fileItems.forEach(([name, file]) => {
        const ext = name.split('.').pop().toLowerCase();
        const icon = getFileIcon(ext);
        html += `
            <div class="fb-tree-item" style="padding-left:${16 + indent + 22}px" onclick="selectFileInBrowser('${escapeHtml(file.path)}')" data-filepath="${escapeHtml(file.path)}" data-filename="${escapeHtml(name.toLowerCase())}">
                <span class="fb-icon fb-icon-file">${icon}</span>
                <span class="fb-name">${escapeHtml(name)}</span>
                <span class="fb-size">${file.size_display}</span>
            </div>`;
    });

    return html;
}

function toggleFbDir(dirId, el) {
    const children = document.getElementById(dirId);
    if (!children) return;
    const isCollapsed = children.classList.contains('hidden');
    if (isCollapsed) {
        children.classList.remove('hidden');
        el.classList.remove('collapsed');
    } else {
        children.classList.add('hidden');
        el.classList.add('collapsed');
    }
}

function filterFileTree(query) {
    const q = (query || '').toLowerCase().trim();
    const items = document.querySelectorAll('#fb-tree-container .fb-tree-item:not(.fb-tree-dir)');
    const dirs = document.querySelectorAll('#fb-tree-container .fb-tree-dir');
    const childrenDivs = document.querySelectorAll('#fb-tree-container .fb-tree-children');

    if (!q) {
        // 显示所有
        items.forEach(item => item.style.display = '');
        dirs.forEach(dir => dir.style.display = '');
        childrenDivs.forEach(div => div.classList.remove('hidden'));
        return;
    }

    // 隐藏所有目录先
    dirs.forEach(dir => dir.style.display = 'none');
    childrenDivs.forEach(div => div.style.display = 'none');

    // 过滤文件，匹配的显示（扁平化）
    items.forEach(item => {
        const filepath = (item.getAttribute('data-filepath') || '').toLowerCase();
        const filename = (item.getAttribute('data-filename') || '').toLowerCase();
        if (filepath.includes(q) || filename.includes(q)) {
            item.style.display = '';
            item.style.paddingLeft = '16px';  // 搜索模式下去掉缩进
        } else {
            item.style.display = 'none';
        }
    });
}

async function selectFileInBrowser(filePath) {
    if (!currentProjectId) return;

    fbCurrentFile = filePath;
    fbRawMode = false;

    // 高亮当前文件
    document.querySelectorAll('#fb-tree-container .fb-tree-item').forEach(item => {
        item.classList.toggle('active', item.getAttribute('data-filepath') === filePath);
    });

    // 显示头部
    const header = document.getElementById('fb-main-header');
    const tabs = document.getElementById('fb-tabs');
    if (header) header.style.display = '';
    if (tabs) tabs.style.display = '';

    // 面包屑
    renderBreadcrumb(filePath);

    // 加载中状态
    const codeContainer = document.getElementById('fb-code-container');
    if (codeContainer) {
        codeContainer.innerHTML = '<div class="fb-loading"><span class="loading"></span>&nbsp;加载文件...</div>';
    }

    try {
        const response = await fetch(`${API_BASE_URL}/api/projects/${currentProjectId}/files/${filePath}`);
        const data = await response.json();

        if (!response.ok) throw new Error(data.detail || '加载失败');

        fbFileContent = data.content || '';
        const fileSize = data.size || 0;
        const lines = fbFileContent.split('\n');

        // 文件信息
        const fileInfo = document.getElementById('fb-file-info');
        if (fileInfo) {
            const ext = filePath.split('.').pop().toLowerCase();
            const langLabel = getLangLabel(ext);
            fileInfo.innerHTML = `
                <span class="fb-info-item">${lines.length} 行</span>
                <span class="fb-info-item">${fileSize < 1024 ? fileSize + ' B' : (fileSize / 1024).toFixed(1) + ' KB'}</span>
                <span class="fb-info-item" style="background:#f1f8ff;padding:2px 8px;border-radius:12px;color:#0969da;font-weight:500">${langLabel}</span>`;
        }

        // 渲染代码
        renderCodeView(fbFileContent, filePath);

        // 更新 Tab（Preview 仅对 md/html 有效）
        const ext = filePath.split('.').pop().toLowerCase();
        const previewTab = document.querySelector('.fb-tab[data-tab="preview"]');
        if (previewTab) {
            previewTab.style.display = ['md', 'html', 'json'].includes(ext) ? '' : 'none';
        }
        // 重置到 Code tab
        document.querySelectorAll('.fb-tab').forEach(t => t.classList.toggle('active', t.getAttribute('data-tab') === 'code'));

    } catch (err) {
        if (codeContainer) {
            codeContainer.innerHTML = `<div class="fb-empty-state"><p style="color:#cf1322">加载失败: ${escapeHtml(err.message)}</p></div>`;
        }
    }
}

function renderBreadcrumb(filePath) {
    const el = document.getElementById('fb-breadcrumb');
    if (!el) return;

    const parts = filePath.split('/');
    let html = '<span class="fb-bc-link" onclick="loadFileBrowser()">📂 root</span>';

    for (let i = 0; i < parts.length; i++) {
        html += '<span>/</span>';
        if (i === parts.length - 1) {
            html += `<span class="fb-bc-current">${escapeHtml(parts[i])}</span>`;
        } else {
            html += `<span class="fb-bc-link">${escapeHtml(parts[i])}</span>`;
        }
    }

    el.innerHTML = html;
}

function renderCodeView(content, filePath) {
    const container = document.getElementById('fb-code-container');
    if (!container) return;

    if (!content && content !== '') {
        container.innerHTML = '<div class="fb-empty-state"><p>空文件</p></div>';
        return;
    }

    const lines = content.split('\n');

    // 语法高亮
    let highlightedCode;
    if (fbRawMode) {
        highlightedCode = escapeHtml(content);
    } else {
        highlightedCode = highlightCode(content, filePath);
    }

    // 将高亮后的代码按行分割
    const highlightedLines = highlightedCode.split('\n');

    let tableHtml = '<table class="fb-code-table">';
    for (let i = 0; i < lines.length; i++) {
        const lineNum = i + 1;
        const lineCode = highlightedLines[i] !== undefined ? highlightedLines[i] : '';
        tableHtml += `<tr id="L${lineNum}" onclick="highlightLine(${lineNum})">
            <td class="fb-line-num">${lineNum}</td>
            <td class="fb-line-code">${lineCode || ' '}</td>
        </tr>`;
    }
    tableHtml += '</table>';

    container.innerHTML = tableHtml;
}

function highlightLine(lineNum) {
    // 移除旧的高亮
    document.querySelectorAll('.fb-code-table tr.highlighted').forEach(tr => tr.classList.remove('highlighted'));
    const row = document.getElementById(`L${lineNum}`);
    if (row) {
        row.classList.add('highlighted');
        // 更新 URL hash（不跳转）
        history.replaceState(null, '', `#L${lineNum}`);
    }
}

function toggleRawView() {
    fbRawMode = !fbRawMode;
    const btn = document.getElementById('fb-raw-btn');
    if (btn) {
        btn.style.background = fbRawMode ? '#0969da' : '';
        btn.style.color = fbRawMode ? '#fff' : '';
    }
    if (fbCurrentFile && fbFileContent !== undefined) {
        renderCodeView(fbFileContent, fbCurrentFile);
    }
}

function copyFileContent() {
    if (!fbFileContent && fbFileContent !== '') return;
    navigator.clipboard.writeText(fbFileContent).then(() => {
        showToast('已复制到剪贴板', 'success');
    }).catch(() => {
        showToast('复制失败', 'error');
    });
}

function switchFileTab(tab) {
    document.querySelectorAll('.fb-tab').forEach(t => t.classList.toggle('active', t.getAttribute('data-tab') === tab));

    const container = document.getElementById('fb-code-container');
    if (!container || !fbFileContent) return;

    if (tab === 'code') {
        renderCodeView(fbFileContent, fbCurrentFile);
    } else if (tab === 'preview') {
        const ext = (fbCurrentFile || '').split('.').pop().toLowerCase();
        if (ext === 'json') {
            try {
                const formatted = JSON.stringify(JSON.parse(fbFileContent), null, 2);
                container.innerHTML = `<pre style="padding:16px;font-size:13px;line-height:1.6;font-family:Consolas,monospace;overflow:auto;height:100%">${highlightCode(formatted, 'data.json')}</pre>`;
            } catch {
                container.innerHTML = `<pre style="padding:16px;font-size:13px">${escapeHtml(fbFileContent)}</pre>`;
            }
        } else if (ext === 'md') {
            // 简单的 Markdown 渲染
            container.innerHTML = `<div style="padding:24px;line-height:1.8;font-size:14px;max-width:860px">${simpleMarkdown(fbFileContent)}</div>`;
        } else if (ext === 'html') {
            container.innerHTML = `<iframe srcdoc="${escapeHtml(fbFileContent)}" style="width:100%;height:100%;border:none"></iframe>`;
        }
    }
}

function simpleMarkdown(text) {
    // 极简 Markdown 渲染（不依赖第三方库）
    return escapeHtml(text)
        .replace(/^### (.+)$/gm, '<h3 style="margin:16px 0 8px;font-size:16px">$1</h3>')
        .replace(/^## (.+)$/gm, '<h2 style="margin:20px 0 10px;font-size:18px;border-bottom:1px solid #d0d7de;padding-bottom:6px">$1</h2>')
        .replace(/^# (.+)$/gm, '<h1 style="margin:24px 0 12px;font-size:22px;border-bottom:2px solid #d0d7de;padding-bottom:8px">$1</h1>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/`([^`]+)`/g, '<code style="background:#f6f8fa;padding:2px 6px;border-radius:4px;font-size:13px">$1</code>')
        .replace(/^- (.+)$/gm, '<li style="margin:4px 0;margin-left:20px">$1</li>')
        .replace(/\n\n/g, '<br><br>')
        .replace(/\n/g, '<br>');
}

function getLangLabel(ext) {
    const map = {
        py: 'Python', js: 'JavaScript', ts: 'TypeScript', html: 'HTML', css: 'CSS',
        json: 'JSON', md: 'Markdown', yml: 'YAML', yaml: 'YAML', sql: 'SQL',
        sh: 'Shell', bash: 'Bash', toml: 'TOML', ini: 'INI', cfg: 'Config',
        xml: 'XML', txt: 'Text', env: 'Env', jsx: 'JSX', tsx: 'TSX',
        dockerfile: 'Dockerfile', makefile: 'Makefile',
    };
    return map[ext] || ext.toUpperCase();
}

// ============ 项目 ZIP 下载 ============

async function downloadProject(projectId) {
    const btn = event ? event.target : null;
    const originalText = btn ? btn.innerHTML : '';

    appendProcessLog('step', '开始打包下载项目...');

    try {
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="loading"></span> 打包中...';
        }

        const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/download`);

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || '下载失败');
        }

        // 从响应头获取文件名
        const disposition = response.headers.get('Content-Disposition');
        let filename = 'project.zip';
        if (disposition) {
            const match = disposition.match(/filename="?([^"]+)"?/);
            if (match) filename = match[1];
        }

        // 创建 Blob 并触发下载
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);

        appendProcessLog('success', `✓ 项目已打包下载`, filename);
        showToast(`📦 ${filename} 下载成功`, 'success');
    } catch (err) {
        appendProcessLog('error', '✗ 打包下载失败', err.message);
        showToast(`下载失败: ${err.message}`, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }
}

async function showProjectFiles(projectId) {
    const panel = document.getElementById(`files-panel-${projectId}`);
    const content = document.getElementById(`files-content-${projectId}`);
    if (!panel || !content) return;

    panel.style.display = 'block';
    content.innerHTML = '<p style="text-align:center;padding:20px"><span class="loading"></span> 加载文件列表...</p>';

    try {
        const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/files`);
        const data = await response.json();

        if (!response.ok) throw new Error(data.detail || '加载失败');

        const files = data.files || [];
        if (files.length === 0) {
            content.innerHTML = `
                <div class="empty-state" style="padding:24px">
                    <div class="icon">📂</div>
                    <p>暂无生成文件，请先执行任务</p>
                </div>`;
            return;
        }

        // 按目录分组
        const tree = {};
        files.forEach(f => {
            const parts = f.path.split('/');
            const dir = parts.length > 1 ? parts.slice(0, -1).join('/') : '.';
            if (!tree[dir]) tree[dir] = [];
            tree[dir].push(f);
        });

        let html = `<div class="files-summary" style="padding:12px 16px;background:#f6f8fa;border-bottom:1px solid #f0f0f0;font-size:13px;color:rgba(0,0,0,0.55)">
            共 ${files.length} 个文件
        </div>`;

        for (const [dir, dirFiles] of Object.entries(tree)) {
            html += `<div class="file-dir" style="padding:8px 16px;font-weight:600;font-size:13px;color:rgba(0,0,0,0.45);border-bottom:1px solid #f0f0f0">📂 ${escapeHtml(dir)}/</div>`;
            dirFiles.forEach(f => {
                const ext = f.name.split('.').pop().toLowerCase();
                const icon = getFileIcon(ext);
                html += `
                    <div class="file-row" onclick="previewFile('${projectId}', '${escapeHtml(f.path)}')" style="padding:10px 16px 10px 32px;display:flex;align-items:center;gap:10px;cursor:pointer;border-bottom:1px solid #fafafa;transition:background 0.15s" onmouseover="this.style.background='#f6f8fa'" onmouseout="this.style.background=''">
                        <span style="font-size:16px">${icon}</span>
                        <span style="flex:1;font-size:14px">${escapeHtml(f.name)}</span>
                        <span style="font-size:12px;color:rgba(0,0,0,0.35)">${f.size_display}</span>
                    </div>`;
            });
        }

        content.innerHTML = html;
    } catch (err) {
        content.innerHTML = `<p style="padding:20px;color:#ff4d4f">加载失败: ${escapeHtml(err.message)}</p>`;
    }
}

async function previewFile(projectId, filePath) {
    const titleEl = document.getElementById(`code-preview-title-${projectId}`);
    const contentEl = document.getElementById(`code-preview-content-${projectId}`);
    const panel = document.getElementById(`code-preview-${projectId}`);
    if (!panel || !contentEl) return;

    panel.style.display = 'block';
    if (titleEl) {
        const ext = filePath.split('.').pop().toLowerCase();
        const langLabel = { py: 'Python', js: 'JavaScript', html: 'HTML', css: 'CSS', json: 'JSON', md: 'Markdown', yml: 'YAML', sql: 'SQL' }[ext] || ext.toUpperCase();
        titleEl.innerHTML = `📄 ${escapeHtml(filePath)} <span class="code-lang-tag">${langLabel}</span>`;
    }
    contentEl.textContent = '加载中...';

    try {
        const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/files/${filePath}`);
        const data = await response.json();

        if (!response.ok) throw new Error(data.detail || '加载失败');

        const code = data.content || '(空文件)';
        // 使用 highlight.js 语法高亮
        contentEl.innerHTML = highlightCode(code, filePath);
    } catch (err) {
        contentEl.textContent = `加载失败: ${err.message}`;
    }
}

function getFileIcon(ext) {
    const icons = {
        'py': '🐍', 'js': '📜', 'html': '🌐', 'css': '🎨',
        'json': '📋', 'md': '📝', 'txt': '📄', 'yml': '⚙️',
        'yaml': '⚙️', 'sql': '🗃️', 'sh': '🖥️', 'bat': '🖥️',
        'toml': '⚙️', 'cfg': '⚙️', 'ini': '⚙️', 'env': '🔐',
    };
    return icons[ext] || '📄';
}

// ============ LLM 配置管理 ============

async function loadLLMStatus() {
    const statusEl = document.getElementById('llm-config-status');
    if (!statusEl) return;

    try {
        const response = await fetch(`${API_BASE_URL}/api/llm/status`);
        const data = await response.json();

        if (response.ok) {
            const enabled = data.enabled;
            statusEl.innerHTML = `
                <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
                    <div style="width:12px;height:12px;border-radius:50%;background:${enabled ? '#52c41a' : '#ff4d4f'}"></div>
                    <strong style="font-size:15px">${enabled ? 'LLM 已启用' : 'LLM 未配置'}</strong>
                </div>
                <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;font-size:13px;color:rgba(0,0,0,0.65)">
                    <div><strong>API 地址:</strong> ${escapeHtml(data.base_url || '未设置')}</div>
                    <div><strong>模型:</strong> ${escapeHtml(data.model || '未设置')}</div>
                    <div><strong>API Key:</strong> ${data.has_api_key ? '✅ 已配置' : '❌ 未配置'}</div>
                    <div><strong>超时:</strong> ${data.timeout || 120}s / 重试: ${data.max_retries || 2}次</div>
                </div>
            `;

            // 填充表单默认值
            const baseUrlInput = document.getElementById('llm-base-url');
            const modelInput = document.getElementById('llm-model');
            if (baseUrlInput && !baseUrlInput.value) baseUrlInput.value = data.base_url || '';
            if (modelInput && !modelInput.value) modelInput.value = data.model || '';
        } else {
            statusEl.innerHTML = '<p style="color:#ff4d4f">无法获取 LLM 状态</p>';
        }
    } catch (err) {
        statusEl.innerHTML = `<p style="color:#ff4d4f">连接失败: ${escapeHtml(err.message)}</p>`;
    }
}

async function saveLLMConfig() {
    const baseUrl = document.getElementById('llm-base-url').value.trim();
    const apiKey = document.getElementById('llm-api-key').value.trim();
    const model = document.getElementById('llm-model').value.trim();
    const alertEl = document.getElementById('llm-config-alert');

    if (!apiKey && !baseUrl && !model) {
        showLLMAlert('请至少填写 API Key', 'error');
        return;
    }

    try {
        const params = new URLSearchParams();
        if (baseUrl) params.append('base_url', baseUrl);
        if (apiKey) params.append('api_key', apiKey);
        if (model) params.append('model', model);

        const response = await fetch(`${API_BASE_URL}/api/llm/config?${params.toString()}`, {
            method: 'POST',
        });
        const data = await response.json();

        if (response.ok) {
            showLLMAlert('LLM 配置已保存！', 'success');
            // 清空密码框
            document.getElementById('llm-api-key').value = '';
            // 刷新状态
            loadLLMStatus();
        } else {
            showLLMAlert(`保存失败: ${data.detail || '未知错误'}`, 'error');
        }
    } catch (err) {
        showLLMAlert(`网络错误: ${err.message}`, 'error');
    }
}

async function testLLMConnection() {
    const btn = document.getElementById('llm-test-text');
    const resultEl = document.getElementById('llm-test-result');
    if (!resultEl) return;

    if (btn) btn.innerHTML = '<span class="loading"></span> 测试中...';

    try {
        const response = await fetch(`${API_BASE_URL}/api/llm/test`, {
            method: 'POST',
        });
        const data = await response.json();

        resultEl.classList.remove('hidden');
        if (data.success) {
            resultEl.style.background = '#f6ffed';
            resultEl.style.borderColor = '#b7eb8f';
            resultEl.innerHTML = `
                <div style="color:#389e0d;font-weight:600;margin-bottom:8px">✅ 连接成功！</div>
                <div style="font-size:13px;color:rgba(0,0,0,0.65)">
                    <div>模型: ${escapeHtml(data.model || 'N/A')}</div>
                    <div>响应: ${escapeHtml(data.response || 'N/A')}</div>
                </div>
            `;
        } else {
            resultEl.style.background = '#fff1f0';
            resultEl.style.borderColor = '#ffa39e';
            resultEl.innerHTML = `
                <div style="color:#cf1322;font-weight:600;margin-bottom:8px">❌ 连接失败</div>
                <div style="font-size:13px;color:rgba(0,0,0,0.65)">${escapeHtml(data.error || '未知错误')}</div>
            `;
        }
    } catch (err) {
        resultEl.classList.remove('hidden');
        resultEl.style.background = '#fff1f0';
        resultEl.style.borderColor = '#ffa39e';
        resultEl.innerHTML = `<div style="color:#cf1322">网络错误: ${escapeHtml(err.message)}</div>`;
    } finally {
        if (btn) btn.textContent = '测试连接';
    }
}

function showLLMAlert(message, type) {
    const el = document.getElementById('llm-config-alert');
    if (!el) return;
    el.textContent = message;
    el.className = `alert alert-${type}`;
    el.classList.remove('hidden');
    setTimeout(() => el.classList.add('hidden'), 4000);
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

// SSE 降级：仅在 EventSource 不可用时回退到 30 秒轮询
if (typeof EventSource === 'undefined') {
    setInterval(() => {
        if (currentProjectId &&
            document.getElementById('page-project-detail') &&
            document.getElementById('page-project-detail').classList.contains('active')) {
            viewProject(currentProjectId);
        }
    }, 30000);
}
