// API 基础配置
const API_BASE_URL = 'http://localhost:8000';

// 全局状态
let projects = [];
let currentProjectId = null;

// 页面切换
function showPage(pageName) {
    // 隐藏所有页面
    document.querySelectorAll('.page').forEach(page => {
        page.classList.remove('active');
    });

    // 移除所有菜单项的 active 类
    document.querySelectorAll('.menu-item').forEach(item => {
        item.classList.remove('active');
    });

    // 显示目标页面
    document.getElementById(`page-${pageName}`).classList.add('active');

    // 激活对应菜单项
    document.querySelector(`[data-page="${pageName}"]`).classList.add('active');

    // 页面加载时的特定操作
    if (pageName === 'home') {
        loadStats();
    } else if (pageName === 'projects') {
        loadProjects();
    } else if (pageName === 'tools') {
        loadTools();
    }
}

// 显示提示信息
function showAlert(message, type = 'info') {
    const alertElement = document.getElementById('submit-alert');
    alertElement.textContent = message;
    alertElement.className = `alert alert-${type}`;
    alertElement.classList.remove('hidden');

    // 3秒后自动隐藏
    setTimeout(() => {
        alertElement.classList.add('hidden');
    }, 3000);
}

// 提交需求
async function submitRequirement() {
    const userInput = document.getElementById('user-input').value.trim();
    const techStack = document.getElementById('tech-stack').value.trim();
    const projectName = document.getElementById('project-name').value.trim();
    const submitBtn = document.getElementById('submit-btn');
    const submitBtnText = document.getElementById('submit-btn-text');

    // 验证输入
    if (!userInput) {
        showAlert('请输入项目描述', 'error');
        return;
    }

    // 显示加载状态
    submitBtn.disabled = true;
    submitBtnText.innerHTML = '<span class="loading"></span> 提交中...';

    try {
        const response = await fetch(`${API_BASE_URL}/api/process`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                user_input: userInput,
                tech_stack: techStack ? techStack.split(',').map(s => s.trim()) : [],
                project_name: projectName
            }),
        });

        const data = await response.json();

        if (response.ok) {
            showAlert(`需求提交成功！项目ID: ${data.project_id}`, 'success');
            currentProjectId = data.project_id;

            // 清空表单
            document.getElementById('user-input').value = '';
            document.getElementById('tech-stack').value = '';
            document.getElementById('project-name').value = '';

            // 跳转到项目看板
            setTimeout(() => {
                showPage('projects');
            }, 1000);
        } else {
            showAlert(`提交失败: ${data.detail || '未知错误'}`, 'error');
        }
    } catch (error) {
        showAlert(`网络错误: ${error.message}`, 'error');
    } finally {
        submitBtn.disabled = false;
        submitBtnText.textContent = '提交需求';
    }
}

// 加载统计数据
async function loadStats() {
    try {
        // 加载可用工具数
        const toolsResponse = await fetch(`${API_BASE_URL}/health`);
        const healthData = await toolsResponse.json();
        document.getElementById('stat-tools-available').textContent = healthData.tools_available || 0;

        // 更新项目统计
        const total = projects.length;
        const completed = projects.filter(p => p.status === 'completed').length;
        const inProgress = projects.filter(p => p.status === 'in_progress' || p.status === 'executing').length;

        document.getElementById('stat-total-projects').textContent = total;
        document.getElementById('stat-completed').textContent = completed;
        document.getElementById('stat-in-progress').textContent = inProgress;
    } catch (error) {
        console.error('加载统计数据失败:', error);
    }
}

// 加载项目列表
async function loadProjects() {
    const projectsList = document.getElementById('projects-list');

    if (projects.length === 0) {
        projectsList.innerHTML = `
            <p style="color: rgba(0, 0, 0, 0.45); text-align: center; padding: 40px;">
                暂无项目，请先提交需求
            </p>
        `;
        return;
    }

    projectsList.innerHTML = projects.map(project => `
        <div class="task-item">
            <div class="task-info">
                <h4>${project.name || '未命名项目'}</h4>
                <p>${project.description || '无描述'}</p>
                <p style="margin-top: 8px; font-size: 12px; color: rgba(0, 0, 0, 0.45);">
                    ID: ${project.id} | 创建时间: ${new Date(project.created_at).toLocaleString()}
                </p>
            </div>
            <div style="display: flex; align-items: center; gap: 12px;">
                <span class="tag tag-${project.status}">
                    ${getStatusLabel(project.status)}
                </span>
                <button class="btn btn-primary" onclick="viewProject('${project.id}')">
                    查看详情
                </button>
            </div>
        </div>
    `).join('');
}

// 查看项目详情
async function viewProject(projectId) {
    try {
        const response = await fetch(`${API_BASE_URL}/api/projects/${projectId}/state`);
        const data = await response.json();

        if (response.ok) {
            const projectState = data.project_state;
            const taskSummary = data.task_summary;

            // 显示项目详情（这里简化处理，实际应该用模态框或新页面）
            alert(`项目详情:\n\nID: ${projectState.project_id}\n状态: ${projectState.status}\n总任务: ${taskSummary.total}\n已完成: ${taskSummary.completed}\n进行中: ${taskSummary.in_progress}`);
        } else {
            showAlert('加载项目详情失败', 'error');
        }
    } catch (error) {
        showAlert(`网络错误: ${error.message}`, 'error');
    }
}

// 获取状态标签
function getStatusLabel(status) {
    const statusMap = {
        'pending': '等待中',
        'analyzing': '分析中',
        'executing': '执行中',
        'completed': '已完成',
        'failed': '失败',
        'in_progress': '进行中'
    };
    return statusMap[status] || status;
}

// 加载工具列表
async function loadTools() {
    const toolsList = document.getElementById('tools-list');
    toolsList.innerHTML = '<p>加载中...</p>';

    try {
        const response = await fetch(`${API_BASE_URL}/tools`);
        const data = await response.json();

        if (response.ok && data.tools) {
            const tools = Object.values(data.tools);
            toolsList.innerHTML = tools.map(tool => `
                <div class="tool-card">
                    <h4>${tool.name}</h4>
                    <p>${tool.description || '暂无描述'}</p>
                </div>
            `).join('');
        } else {
            toolsList.innerHTML = '<p>加载工具列表失败</p>';
        }
    } catch (error) {
        console.error('加载工具列表失败:', error);
        toolsList.innerHTML = '<p>网络错误，请稍后重试</p>';
    }
}

// 菜单点击事件
document.querySelectorAll('.menu-item').forEach(item => {
    item.addEventListener('click', () => {
        const pageName = item.getAttribute('data-page');
        showPage(pageName);
    });
});

// 页面加载时初始化
window.addEventListener('DOMContentLoaded', () => {
    showPage('home');
    loadTools();
});

// 定期刷新项目状态（每5秒）
setInterval(async () => {
    if (projects.length > 0 && document.getElementById('page-projects').classList.contains('active')) {
        // 这里可以添加轮询逻辑来更新项目状态
        // loadProjects();
    }
}, 5000);
