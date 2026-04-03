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

// ==================== 工具函数 ====================

/**
 * 中文转拼音（简化版）
 * 将中文字符转换为拼音，用于生成英文路径
 */
function chineseToPinyin(text) {
    // 常用汉字拼音映射（简化版）
    const pinyinMap = {
        // 常见词组
        '我的游戏': 'my-game', '我的项目': 'my-project', '我的应用': 'my-app',
        '我的工具': 'my-tool', '我的助手': 'my-assistant',
        '在线游戏': 'online-game', '网络游戏': 'online-game', '手机游戏': 'mobile-game',
        '电商平台': 'eshop-mall', '网上商城': 'online-shop', '在线商城': 'online-store',
        '智能助手': 'smart-assistant', 'AI助手': 'ai-assistant', '人工智能': 'ai',
        '管理系统': 'management-system', '办公系统': 'office-system',
        '社交平台': 'social-platform', '社区论坛': 'community-forum',
        '教育平台': 'education-platform', '学习系统': 'learning-system',
        '医疗系统': 'medical-system', '健康平台': 'health-platform',
        '金融系统': 'finance-system', '支付平台': 'payment-platform',
        '视频平台': 'video-platform', '音乐平台': 'music-platform',
        '娱乐系统': 'entertainment-system', '游戏平台': 'game-platform',
        '数据分析': 'data-analysis', '数据平台': 'data-platform',
        '云服务': 'cloud-service', '云平台': 'cloud-platform',
        '移动应用': 'mobile-app', '网页应用': 'web-app',
        
        // 单字映射
        '我': 'wo', '的': 'de', '游戏': 'game', '项目': 'project',
        '系统': 'system', '平台': 'platform', '应用': 'app', '应用程序': 'application',
        '管理': 'manage', '管理': 'management', '商城': 'mall', '商城': 'shop',
        '博客': 'blog', '论坛': 'forum', '社区': 'community',
        '办公': 'office', '企业': 'enterprise', '学校': 'school',
        '医疗': 'medical', '医院': 'hospital', '健康': 'health',
        '金融': 'finance', '银行': 'bank', '支付': 'payment',
        '教育': 'education', '学习': 'learning', '培训': 'training',
        '娱乐': 'entertainment', '视频': 'video', '音乐': 'music',
        '社交': 'social', '聊天': 'chat', '通讯': 'communication',
        '工具': 'tool', '助手': 'assistant', '服务': 'service',
        '数据': 'data', '分析': 'analysis', '报表': 'report',
        '智能': 'smart', '智慧': 'wisdom', 'AI': 'ai', '人工智能': 'ai',
        '开发': 'dev', '测试': 'test', '运维': 'ops',
        '前端': 'frontend', '后端': 'backend', '全栈': 'fullstack',
        '移动': 'mobile', '网页': 'web', '桌面': 'desktop',
        '云': 'cloud', '服务器': 'server', '数据库': 'database',
        '用户': 'user', '客户': 'customer', '会员': 'member',
        '订单': 'order', '商品': 'product', '库存': 'inventory',
        '购物车': 'cart', '支付': 'pay', '结算': 'checkout',
        '登录': 'login', '注册': 'register', '认证': 'auth',
        '权限': 'permission', '角色': 'role', '菜单': 'menu',
        '设置': 'settings', '配置': 'config', '个人': 'profile',
        '消息': 'message', '通知': 'notification', '推送': 'push',
        '搜索': 'search', '筛选': 'filter', '排序': 'sort',
        '上传': 'upload', '下载': 'download', '导出': 'export',
        '导入': 'import', '打印': 'print', '预览': 'preview',
        '编辑': 'edit', '删除': 'delete', '添加': 'add',
        '创建': 'create', '更新': 'update', '保存': 'save',
        '取消': 'cancel', '确定': 'confirm', '提交': 'submit',
        '返回': 'back', '首页': 'home', '关于': 'about',
        '帮助': 'help', '文档': 'docs', '常见问题': 'faq',
        '联系': 'contact', '反馈': 'feedback', '建议': 'suggestion',
        '版本': 'version', '更新日志': 'changelog', '说明': 'readme',
        '协议': 'license', '隐私': 'privacy', '条款': 'terms',
        '团队': 'team', '公司': 'company', '品牌': 'brand',
        '产品': 'product', '解决方案': 'solution', '案例': 'case',
        '新闻': 'news', '活动': 'event', '公告': 'announcement',
        '首页': 'index', '列表': 'list', '详情': 'detail',
        '分类': 'category', '标签': 'tag', '评论': 'comment',
        '点赞': 'like', '收藏': 'favorite', '分享': 'share',
        '关注': 'follow', '粉丝': 'follower', '好友': 'friend',
        '群组': 'group', '频道': 'channel', '话题': 'topic',
        '帖子': 'post', '文章': 'article', '问答': 'qa',
        '任务': 'task', '日程': 'schedule', '提醒': 'reminder',
        '日历': 'calendar', '时钟': 'clock', '天气': 'weather',
        '地图': 'map', '定位': 'location', '导航': 'navigation',
        '相机': 'camera', '相册': 'gallery', '图片': 'image',
        '文件': 'file', '文件夹': 'folder', '压缩包': 'archive',
        '文档': 'document', '表格': 'spreadsheet', '演示': 'presentation',
        '音频': 'audio', '视频': 'video', '直播': 'live',
        '游戏': 'game', '竞技': 'esports', '休闲': 'casual',
        '角色': 'rpg', '动作': 'action', '策略': 'strategy',
        '射击': 'shooter', '赛车': 'racing', '体育': 'sports',
        '冒险': 'adventure', '解谜': 'puzzle', '模拟': 'simulation',
        '在线': 'online', '离线': 'offline', '多人': 'multiplayer',
        '单人': 'singleplayer', '合作': 'coop', '对战': 'pvp',
        '排行榜': 'rank', '成就': 'achievement', '奖励': 'reward',
        '道具': 'item', '装备': 'equipment', '技能': 'skill',
        '等级': 'level', '经验': 'exp', '金币': 'gold',
        '钻石': 'diamond', '点券': 'coupon', '商城': 'store',
        '充值': 'recharge', '签到': 'checkin', '活动': 'event',
        '任务': 'quest', '副本': 'dungeon', '世界': 'world',
        '地图': 'map', '场景': 'scene', '角色': 'character',
        '职业': 'class', '天赋': 'talent', '符文': 'rune',
        '装备': 'gear', '武器': 'weapon', '防具': 'armor',
        '饰品': 'accessory', '消耗品': 'consumable', '材料': 'material',
        '打造': 'craft', '合成': 'combine', '升级': 'upgrade',
        '强化': 'enhance', '觉醒': 'awaken', '转职': 'advance',
        '公会': 'guild', '联盟': 'alliance', '战队': 'team',
        '战场': 'battlefield', '竞技场': 'arena', '排位': 'ranked',
        '赛季': 'season', '段位': 'tier', '积分': 'points',
        '匹配': 'match', '排队': 'queue', '房间': 'room',
        '聊天': 'chat', '语音': 'voice', '表情': 'emoji',
        '动作': 'gesture', '动画': 'animation', '特效': 'effect',
        '音效': 'sound', '背景音乐': 'bgm', '界面': 'ui',
        '操作': 'control', '按键': 'keybind', '设置': 'settings',
        '选项': 'options', '帮助': 'help', '教程': 'tutorial',
        '新手': 'newbie', '引导': 'guide', '提示': 'hint',
        '提示框': 'tooltip', '对话框': 'dialog', '弹窗': 'modal',
        '按钮': 'button', '输入框': 'input', '下拉框': 'select',
        '复选框': 'checkbox', '单选框': 'radio', '开关': 'toggle',
        '滑块': 'slider', '进度条': 'progress', '加载': 'loading',
        '刷新': 'refresh', '返回': 'back', '退出': 'exit',
        '登录': 'login', '注册': 'signup', '找回密码': 'forgot',
        '账号': 'account', '密码': 'password', '邮箱': 'email',
        '手机': 'phone', '验证码': 'code', '短信': 'sms',
        '微信': 'wechat', '支付宝': 'alipay', 'QQ': 'qq'
    };

    let result = text.toLowerCase();
    // 先尝试匹配多字词
    for (const [chinese, pinyin] of Object.entries(pinyinMap)) {
        result = result.split(chinese).join(pinyin);
    }
    // 替换空格和特殊字符为连字符
    result = result.replace(/[\s\u4e00-\u9fa5，。！？、；：""''（）【】]+/g, '-');
    // 移除多余连字符
    result = result.replace(/-+/g, '-').replace(/^-|-$/g, '');
    // 如果没有结果，使用 base64 编码
    if (!result) {
        result = btoa(encodeURIComponent(text)).replace(/=/g, '');
    }
    return result;
}

/**
 * 根据项目名称生成本地仓库路径
 */
function generateLocalPath(projectName) {
    const englishName = chineseToPinyin(projectName);
    return `D:/Projects/${englishName}`;
}

// ==================== 初始化 ====================

document.addEventListener('DOMContentLoaded', () => {
    checkLLMStatus();
    loadProjects();
    initLogPanel();
    initProjectNameListener();
    // 默认打开 AI 助手面板
    toggleChatPanel();
});

/**
 * 初始化项目名称输入监听
 */
function initProjectNameListener() {
    const projectNameInput = document.getElementById('projectName');
    const localPathInput = document.getElementById('projectLocalPath');

    projectNameInput.addEventListener('input', () => {
        const name = projectNameInput.value.trim();
        if (name) {
            // 自动生成本地路径
            localPathInput.value = generateLocalPath(name);
        } else {
            // 清空时恢复默认提示
            localPathInput.value = '';
        }
    });
}

/**
 * 选择本地路径（显示常用路径建议）
 * 由于浏览器安全限制，Web 应用无法调用系统文件夹对话框
 * 这里显示常用路径供用户选择和编辑
 */
async function selectLocalPath() {
    try {
        const response = await api('/filesystem/available-paths');
        if (response.paths && response.paths.length > 0) {
            // 显示路径选择对话框
            showPathSelector(response.paths);
        } else {
            showToast('无法获取可用路径列表', 'warning');
        }
    } catch (e) {
        console.error('获取路径列表失败:', e);
        showToast('请手动输入路径（如：D:/Projects/my-game）', 'info');
    }
}

/**
 * 显示路径选择对话框
 */
function showPathSelector(paths) {
    // 创建模态框
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.id = 'pathSelectorModal';

    let pathOptions = paths.map(item =>
        `<div class="path-option" onclick="selectPath('${item.path}')">
            <span class="path-icon">${item.exists ? '📁' : '📝'}</span>
            <span class="path-text">${item.path}</span>
            ${!item.exists ? '<span class="path-hint">（建议）</span>' : ''}
        </div>`
    ).join('');

    modal.innerHTML = `
        <div class="modal">
            <div class="modal-header">
                <h3>选择本地仓库路径</h3>
                <button class="btn-icon" onclick="closePathSelector()">&times;</button>
            </div>
            <div class="modal-body">
                <div class="path-list">
                    ${pathOptions}
                </div>
                <p class="path-tip">💡 提示：选择路径后，请在输入框中手动添加项目文件夹名称（如：/my-game）</p>
            </div>
            <div class="modal-footer">
                <button class="btn" onclick="closePathSelector()">取消</button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);
    openModal('pathSelectorModal');
}

/**
 * 选择的路径
 */
function selectPath(path) {
    const localPathInput = document.getElementById('projectLocalPath');
    
    // 如果路径末尾没有斜杠，添加斜杠
    if (!path.endsWith('/')) {
        path += '/';
    }
    
    // 获取项目名称
    const projectName = document.getElementById('projectName').value.trim();
    if (projectName) {
        // 自动添加项目名称（英文）
        const englishName = chineseToPinyin(projectName);
        localPathInput.value = path + englishName;
    } else {
        // 只选择路径，不添加项目名
        localPathInput.value = path;
    }
    
    closeModal('pathSelectorModal');
}

/**
 * 关闭路径选择器
 */
function closePathSelector() {
    closeModal('pathSelectorModal');
    const modal = document.getElementById('pathSelectorModal');
    if (modal) {
        modal.remove();
    }
}

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
            const detail = err.detail;
            let msg;
            if (typeof detail === 'string') msg = detail;
            else if (Array.isArray(detail)) msg = detail.map(d => d.msg || JSON.stringify(d)).join('; ');
            else if (detail) msg = JSON.stringify(detail);
            else msg = err.message || `请求失败 (${resp.status})`;
            throw new Error(msg);
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
    // 聊天面板切换到全局模式
    _updateChatPanelForContext();
}

function showProjectDetail(projectId) {
    currentProjectId = projectId;
    showPage('projectPage');
    loadProjectDetail();
    connectSSE(projectId);
    // 清空日志面板并加载该项目历史日志
    clearLogPanel();
    loadLogPanelHistory();
    // 聊天面板切换到项目模式
    _updateChatPanelForContext();
    // 切换项目时重置仓库文件预览区，避免显示上一个项目的文件
    const repoPreview = document.getElementById('repoFilePreview');
    if (repoPreview) repoPreview.innerHTML = '<div class="file-preview-empty"><div class="emoji">📄</div><p>选择文件查看内容</p></div>';
    _activeTreeItem = null;
}

/**
 * 根据当前是否在项目内，更新聊天面板的模式栏和欢迎消息
 */
function _updateChatPanelForContext() {
    const modeBar = document.getElementById('chatModeBar');
    const modeBtn = document.getElementById('chatModeBtn');
    if (currentProjectId) {
        if (modeBar) modeBar.style.display = '';
        if (modeBtn) modeBtn.style.display = '';
    } else {
        if (modeBar) modeBar.style.display = 'none';
        if (modeBtn) modeBtn.style.display = 'none';
        if (chatMode !== 'global') setChatMode('global');
    }
    // 重置聊天历史和界面
    chatHistory = [];
    if (chatPanelOpen) {
        showChatWelcome();
        if (currentProjectId && chatMode === 'global') {
            loadChatHistory();
        }
    }
}

function switchTab(tab) {
    // 侧栏导航高亮（主导航项）
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const activeNav = document.querySelector(`.nav-item[data-tab="${tab}"]`);
    if (activeNav) activeNav.classList.add('active');

    // 如果是设置子 tab，高亮设置主按钮并展开抽屉
    if (tab.startsWith('settings-')) {
        document.querySelector('.nav-item-settings')?.classList.add('active');
        const drawer = document.getElementById('settingsDrawer');
        const arrow = document.getElementById('settingsArrow');
        if (drawer) drawer.classList.add('open');
        if (arrow) arrow.classList.add('expanded');
    }

    // 如果是工单子 tab（board, ticket-list, ticket-graph），高亮工单主按钮并展开抽屉
    const ticketTabs = ['board', 'ticket-list', 'ticket-graph'];
    if (ticketTabs.includes(tab)) {
        document.querySelector('.nav-item-tickets')?.classList.add('active');
        const drawer = document.getElementById('ticketsDrawer');
        const arrow = document.getElementById('ticketsArrow');
        if (drawer) drawer.classList.add('open');
        if (arrow) { arrow.classList.add('expanded'); arrow.textContent = '▾'; }
    }

    // 内容区切换
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    const tabEl = document.getElementById(`tab-${tab}`);
    if (tabEl) tabEl.classList.add('active');

    // 按需加载数据（切走时停止不需要的轮询）
    if (tab !== 'agents') stopAgentMonitor();
    if (tab === 'board') refreshBoard();
    if (tab === 'requirements') loadRequirements();
    if (tab === 'ticket-list') loadTicketList();
    if (tab === 'ticket-graph') loadTicketGraph();
    if (tab === 'pipeline' && currentPipelineReqId) loadPipeline(currentPipelineReqId);
    if (tab === 'repo') loadRepoTree();
    if (tab === 'roadmap') loadRoadmap();
    if (tab === 'stats') loadStats();
    if (tab === 'agents') startAgentMonitor();
    if (tab === 'cicd') loadCICD();
    if (tab === 'logs') loadLogs();
    if (tab === 'bugs') loadBugs();
    if (tab === 'settings-general') loadSettingsGeneral();
    if (tab === 'settings-repo') loadSettingsRepo();
    if (tab === 'settings-envs') loadEnvironments();
    if (tab === 'settings-agents') { loadAgentList(); loadAgentToolsStatus(); }
    if (tab === 'settings-knowledge') loadKnowledgeDocs();
}

// ==================== 工单子菜单 ====================

/** 切换工单抽屉展开/收起 */
function toggleTicketsPanel() {
    const drawer = document.getElementById('ticketsDrawer');
    const arrow = document.getElementById('ticketsArrow');
    if (!drawer || !arrow) return;

    const isOpen = drawer.classList.toggle('open');
    arrow.classList.toggle('expanded', isOpen);
    arrow.textContent = isOpen ? '▾' : '▸';

    // 如果展开，默认打开看板
    if (isOpen) {
        const activeSubItem = drawer.querySelector('.nav-sub-item.active');
        if (!activeSubItem) {
            switchTab('board');
        }
    }
}

// ==================== 设置面板 ====================

/** 切换设置抽屉展开/收起 */
function toggleSettingsPanel() {
    const drawer = document.getElementById('settingsDrawer');
    const arrow = document.getElementById('settingsArrow');
    if (!drawer || !arrow) return;

    const isOpen = drawer.classList.toggle('open');
    arrow.classList.toggle('expanded', isOpen);

    // 如果展开，默认打开第一个设置子页
    if (isOpen) {
        const activeSubItem = drawer.querySelector('.nav-sub-item.active');
        if (!activeSubItem) {
            switchTab('settings-general');
        }
    }
}

/** 加载基本信息设置 */
function loadSettingsGeneral() {
    if (!currentProject) return;
    const p = currentProject;
    document.getElementById('settingsProjectName').value = p.name || '';
    document.getElementById('settingsProjectDesc').value = p.description || '';
    document.getElementById('settingsTechStack').value = p.tech_stack || '';
    document.getElementById('settingsProjectStatus').value = p.status || 'active';
    document.getElementById('settingsProjectId').value = p.id || '';
    document.getElementById('settingsCreatedAt').value = formatDateTime(p.created_at) || '';
}

/** 加载仓库设置 */
async function loadSettingsRepo() {
    if (!currentProject) return;
    const p = currentProject;
    document.getElementById('settingsGitRemote').value = p.git_remote_url || '';
    document.getElementById('settingsRepoPath').value = p.git_repo_path || '默认路径';

    // 加载仓库状态
    await refreshRepoStatus();

    // 加载分支信息
    await loadBranchInfo();
}

/** 加载分支列表和合并操作 */
async function loadBranchInfo() {
    if (!currentProjectId) return;
    const container = document.getElementById('branchInfoContainer');
    if (!container) return;
    try {
        const data = await api(`/projects/${currentProjectId}/git/branches`);
        const branches = data.branches || [];
        const current = data.current || '?';

        let html = `<div style="margin-bottom:12px;">
            <span style="font-size:12px; color:var(--text-muted);">当前分支:</span>
            <span class="req-branch-tag">🌿 ${escHtml(current)}</span>
        </div>`;

        if (branches.length > 0) {
            html += `<div style="font-size:12px; color:var(--text-muted); margin-bottom:8px;">所有分支 (${branches.length}):</div>`;
            html += branches.map(b => `<span class="tag tag-module" style="margin:2px 4px 2px 0; font-size:11px;">${escHtml(b)}</span>`).join('');
        }

        // 合并操作按钮
        const hasDevelop = branches.includes('develop');
        const mainBranch = branches.includes('main') ? 'main' : (branches.includes('master') ? 'master' : null);
        if (hasDevelop && mainBranch) {
            html += `<div style="margin-top:16px; display:flex; gap:8px;">
                <button class="btn btn-primary btn-sm" onclick="mergeBranch('develop', '${mainBranch}')">
                    🔀 develop → ${mainBranch}（发布上线）
                </button>
            </div>`;
        }

        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = `<span style="color:var(--text-muted); font-size:12px;">分支信息加载失败</span>`;
    }
}

/** 触发分支合并 */
async function mergeBranch(source, target) {
    if (!confirm(`确认合并 ${source} → ${target}？`)) return;
    try {
        const res = await api(`/projects/${currentProjectId}/git/merge`, {
            method: 'POST',
            body: { source, target },
        });
        if (res.success) {
            showToast(`合并成功: ${source} → ${target} (${res.commit})`, 'success');
            loadBranchInfo();
        } else {
            showToast(`合并失败: ${res.error}`, 'error');
        }
    } catch (e) {
        showToast(`合并失败: ${e.message}`, 'error');
    }
}

// ==================== 环境管理 ====================

async function loadEnvironments() {
    if (!currentProjectId) return;
    const container = document.getElementById('envCards');
    if (!container) return;

    try {
        const data = await api(`/projects/${currentProjectId}/environments`);
        const envs = data.environments || [];

        const envMeta = {
            dev:  { icon: '🔧', label: '开发环境', color: 'var(--info)', desc: 'feat/* 分支，Agent 开发后自动部署' },
            test: { icon: '🧪', label: '测试环境', color: 'var(--warning, #f59e0b)', desc: 'develop 分支，构建通过后自动部署' },
            prod: { icon: '🚀', label: '生产环境', color: 'var(--success)', desc: 'main 分支，Master 构建通过后部署' },
        };

        container.innerHTML = envs.map(env => {
            const meta = envMeta[env.env_type] || {};
            const running = env.status === 'running';
            return `
            <div class="env-card ${running ? 'env-running' : ''}">
                <div class="env-card-header">
                    <span class="env-icon">${meta.icon || '🌍'}</span>
                    <span class="env-label">${meta.label || env.env_type}</span>
                    <span class="env-status-dot" style="background:${running ? meta.color : 'var(--text-muted)'}"></span>
                    <span class="env-status-text">${running ? '运行中' : '未启动'}</span>
                </div>
                <div class="env-card-body">
                    <div class="env-info-row"><span class="env-info-label">分支</span><span class="env-info-value">${env.branch ? '🌿 ' + escapeHtml(env.branch) : '-'}</span></div>
                    <div class="env-info-row"><span class="env-info-label">端口</span><span class="env-info-value">${env.port || '-'}</span></div>
                    <div class="env-info-row"><span class="env-info-label">Commit</span><span class="env-info-value" style="font-family:monospace;">${env.last_commit || '-'}</span></div>
                    <div class="env-info-row"><span class="env-info-label">部署时间</span><span class="env-info-value">${env.last_deployed_at ? formatTime(env.last_deployed_at) : '-'}</span></div>
                    ${running && env.url ? `<div class="env-info-row"><span class="env-info-label">预览</span><a class="env-preview-link" href="${env.url}" target="_blank">${env.url}</a></div>` : ''}
                </div>
                <div class="env-card-actions">
                    ${running
                        ? `<button class="btn btn-sm btn-danger" onclick="stopEnv('${env.env_type}')">停止</button>
                           <a class="btn btn-sm btn-primary" href="${env.url}" target="_blank">打开预览</a>`
                        : `<button class="btn btn-sm btn-primary" onclick="deployEnv('${env.env_type}')">部署</button>`
                    }
                </div>
                <div class="env-desc">${meta.desc || ''}</div>
            </div>`;
        }).join('');
    } catch (e) {
        container.innerHTML = `<div class="env-card">加载失败: ${escapeHtml(e.message)}</div>`;
    }
}

async function deployEnv(envType) {
    if (!currentProjectId) return;
    showToast(`正在部署 ${envType} 环境...`, 'info');
    try {
        const res = await api(`/projects/${currentProjectId}/environments/${envType}/deploy`, { method: 'POST' });
        showToast(`${envType} 环境已部署: ${res.url}`, 'success');
        loadEnvironments();
    } catch (e) {
        showToast(`${envType} 部署失败: ${e.message}`, 'error');
    }
}

async function stopEnv(envType) {
    if (!currentProjectId) return;
    try {
        await api(`/projects/${currentProjectId}/environments/${envType}/stop`, { method: 'POST' });
        showToast(`${envType} 环境已停止`, 'info');
        loadEnvironments();
    } catch (e) {
        showToast(`停止失败: ${e.message}`, 'error');
    }
}

/** 刷新仓库状态 */
async function refreshRepoStatus() {
    if (!currentProjectId) return;
    try {
        // 尝试获取 git log 和 tree
        const [logData, treeData] = await Promise.allSettled([
            api(`/projects/${currentProjectId}/git/log?limit=1`),
            api(`/projects/${currentProjectId}/git/tree`),
        ]);

        // 仓库状态
        const statusEl = document.getElementById('repoStatusValue');
        if (logData.status === 'fulfilled') {
            statusEl.textContent = '✅ 已初始化';
            statusEl.style.color = 'var(--success)';
        } else {
            statusEl.textContent = '❌ 未初始化';
            statusEl.style.color = 'var(--danger, #ef4444)';
        }

        // 最近提交
        const commitEl = document.getElementById('repoLastCommit');
        if (logData.status === 'fulfilled' && logData.value?.commits?.length) {
            const c = logData.value.commits[0];
            commitEl.textContent = `${c.message || '-'} (${formatDateTime(c.date)})`;
        } else {
            commitEl.textContent = '无提交记录';
        }

        // 文件数量
        const fileCountEl = document.getElementById('repoFileCount');
        if (treeData.status === 'fulfilled' && treeData.value?.tree) {
            const countFiles = (tree) => {
                let count = 0;
                for (const item of tree) {
                    if (item.type === 'file') count++;
                    else if (item.children) count += countFiles(item.children);
                }
                return count;
            };
            fileCountEl.textContent = countFiles(treeData.value.tree) + ' 个文件';
        } else {
            fileCountEl.textContent = '-';
        }
    } catch (e) {
        console.warn('刷新仓库状态失败:', e);
    }
}

/** 保存项目基本设置 */
async function saveProjectSettings() {
    if (!currentProjectId) return;
    const name = document.getElementById('settingsProjectName').value.trim();
    const description = document.getElementById('settingsProjectDesc').value.trim();
    const tech_stack = document.getElementById('settingsTechStack').value.trim();
    const status = document.getElementById('settingsProjectStatus').value;

    if (!name) {
        showToast('项目名称不能为空', 'error');
        return;
    }

    try {
        await api(`/projects/${currentProjectId}`, { method: 'PUT', body: { name, description, tech_stack, status } });
        showToast('项目设置已保存', 'success');
        // 刷新当前项目数据
        const data = await api(`/projects/${currentProjectId}`);
        currentProject = data;
        document.getElementById('sidebarProjectName').textContent = data.name;
    } catch (e) {
        showToast(`保存失败: ${e.message}`, 'error');
    }
}

/** 保存仓库设置 */
async function saveRepoSettings() {
    if (!currentProjectId) return;
    const git_remote_url = document.getElementById('settingsGitRemote').value.trim();

    try {
        await api(`/projects/${currentProjectId}`, { method: 'PUT', body: { git_remote_url } });
        showToast('仓库配置已保存', 'success');
        const data = await api(`/projects/${currentProjectId}`);
        currentProject = data;
    } catch (e) {
        showToast(`保存失败: ${e.message}`, 'error');
    }
}

/** 在浏览器中打开 Git 远程仓库 */
function openGitRemoteUrl() {
    const url = document.getElementById('settingsGitRemote')?.value;
    if (url) {
        window.open(url.replace(/\.git$/, ''), '_blank');
    } else {
        showToast('未配置远程仓库 URL', 'warning');
    }
}

/** 复制文本到剪贴板 */
async function copyToClipboard(text) {
    if (!text) return;
    try {
        await navigator.clipboard.writeText(text);
        showToast('已复制到剪贴板', 'success');
    } catch {
        // fallback
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        showToast('已复制到剪贴板', 'success');
    }
}

/** 归档项目 */
async function archiveProject() {
    if (!currentProjectId) return;
    if (!confirm('确定要归档此项目吗？归档后将不再接受新需求。')) return;
    try {
        await api(`/projects/${currentProjectId}`, { method: 'PUT', body: { status: 'archived' } });
        showToast('项目已归档', 'success');
        showProjectList();
    } catch (e) {
        showToast(`归档失败: ${e.message}`, 'error');
    }
}

/** 删除项目 */
async function deleteProject() {
    if (!currentProjectId) return;
    const name = currentProject?.name || currentProjectId;
    const input = prompt(`此操作不可恢复！\n请输入项目名称 "${name}" 确认删除：`);
    if (input !== name) {
        if (input !== null) showToast('项目名称不匹配，已取消', 'warning');
        return;
    }
    try {
        await api(`/projects/${currentProjectId}`, { method: 'DELETE' });
        showToast('项目已删除', 'success');
        showProjectList();
    } catch (e) {
        showToast(`删除失败: ${e.message}`, 'error');
    }
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
    document.getElementById('projectGitRemote').value = '';
    document.getElementById('projectLocalPath').value = '';
    clearProjectDocs();
    openModal('createProjectModal');
}

// ==================== 新建项目 - 文档导入 ====================

/** 当前待分析的文件列表 */
let _projectDocFiles = [];

function handleDocDragOver(e) {
    e.preventDefault();
    document.getElementById('docDropZone').classList.add('drag-over');
}

function handleDocDragLeave(e) {
    document.getElementById('docDropZone').classList.remove('drag-over');
}

function handleDocDrop(e) {
    e.preventDefault();
    document.getElementById('docDropZone').classList.remove('drag-over');
    const files = Array.from(e.dataTransfer.files);
    addProjectDocFiles(files);
}

function handleDocFileSelect(e) {
    const files = Array.from(e.target.files);
    addProjectDocFiles(files);
    // 重置 input，允许重复选同一文件
    e.target.value = '';
}

function addProjectDocFiles(files) {
    const TEXT_EXTS = new Set(['.txt','.md','.markdown','.rst','.json','.yaml','.yml',
                                '.toml','.xml','.html','.htm','.csv','.log','.conf','.ini']);
    for (const f of files) {
        const ext = f.name.includes('.') ? '.' + f.name.split('.').pop().toLowerCase() : '';
        if (!TEXT_EXTS.has(ext) && ext !== '') {
            showToast(`${f.name} 格式不支持，请上传文本文档`, 'warning');
            continue;
        }
        if (_projectDocFiles.find(x => x.name === f.name && x.size === f.size)) continue; // 去重
        _projectDocFiles.push(f);
    }
    renderProjectDocList();
}

function renderProjectDocList() {
    const listEl = document.getElementById('docFileList');
    const barEl  = document.getElementById('docAnalyzeBar');
    const btnEl  = document.getElementById('docAnalyzeBtnText');

    if (_projectDocFiles.length === 0) {
        listEl.style.display = 'none';
        barEl.style.display  = 'none';
        return;
    }

    listEl.style.display = 'flex';
    barEl.style.display  = 'flex';
    btnEl.textContent    = `✨ AI 分析 ${_projectDocFiles.length} 个文档并填写信息`;

    listEl.innerHTML = _projectDocFiles.map((f, i) => `
        <div class="doc-file-tag" title="${escHtml(f.name)}">
            <span>📄 ${escHtml(f.name)}</span>
            <span class="doc-file-tag-remove" onclick="removeProjectDoc(${i})">×</span>
        </div>
    `).join('');
}

function removeProjectDoc(idx) {
    _projectDocFiles.splice(idx, 1);
    renderProjectDocList();
}

function clearProjectDocs() {
    _projectDocFiles = [];
    renderProjectDocList();
    // 移除已填充徽章
    const badge = document.getElementById('docFilledBadge');
    if (badge) badge.remove();
}

async function analyzeProjectDocs() {
    if (_projectDocFiles.length === 0) return;

    const btn     = document.getElementById('docAnalyzeBtn');
    const btnText = document.getElementById('docAnalyzeBtnText');
    btn.disabled  = true;
    btnText.innerHTML = '<span class="doc-analyzing"><span class="loading-spinner"></span> AI 正在分析文档…</span>';

    try {
        const formData = new FormData();
        for (const f of _projectDocFiles) {
            formData.append('files', f);
        }

        const resp = await fetch('/api/projects/analyze-docs', {
            method: 'POST',
            body: formData,
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(err.detail || resp.statusText);
        }

        const data = await resp.json();

        // 填充到表单（仅覆盖空字段，避免覆盖用户已填写的内容）
        const nameEl  = document.getElementById('projectName');
        const descEl  = document.getElementById('projectDescription');
        const techEl  = document.getElementById('projectTechStack');

        if (!nameEl.value.trim()  && data.name)        nameEl.value  = data.name;
        if (!descEl.value.trim()  && data.description) descEl.value  = data.description;
        if (!techEl.value.trim()  && data.tech_stack)  techEl.value  = data.tech_stack;

        // 显示已填充徽章
        let badge = document.getElementById('docFilledBadge');
        if (!badge) {
            badge = document.createElement('span');
            badge.id = 'docFilledBadge';
            badge.className = 'doc-filled-badge';
            document.getElementById('docAnalyzeBar').appendChild(badge);
        }
        badge.innerHTML = `✅ 已填充项目信息`;

        showToast(`AI 已从 ${data.doc_count} 个文档提取项目信息`, 'success');
    } catch (e) {
        showToast(`分析失败: ${e.message}`, 'error');
    } finally {
        btn.disabled  = false;
        btnText.textContent = `✨ AI 重新分析文档`;
    }
}

async function createProject() {
    const name = document.getElementById('projectName').value.trim();
    const description = document.getElementById('projectDescription').value.trim();
    const tech_stack = document.getElementById('projectTechStack').value.trim();
    const git_remote_url = document.getElementById('projectGitRemote').value.trim();
    const local_repo_path = document.getElementById('projectLocalPath').value.trim();

    if (!name) {
        showToast('请输入项目名称', 'warning');
        return;
    }

    if (!git_remote_url) {
        showToast('请输入 Git 远程仓库 URL', 'warning');
        return;
    }

    try {
        const body = { name, description, tech_stack, git_remote_url };
        if (local_repo_path) {
            body.local_repo_path = local_repo_path;
        }

        const data = await api('/projects', {
            method: 'POST',
            body,
        });

        closeModal('createProjectModal');

        // 项目创建成功后，若有导入文档则上传到 docs/Design/
        const docsToUpload = [..._projectDocFiles];
        clearProjectDocs();

        if (docsToUpload.length > 0) {
            showToast(`项目「${name}」创建成功，正在保存文档到仓库…`, 'info');
            try {
                const formData = new FormData();
                for (const f of docsToUpload) {
                    formData.append('files', f);
                }
                const uploadResp = await fetch(`/api/projects/${data.id}/upload-docs`, {
                    method: 'POST',
                    body: formData,
                });
                if (uploadResp.ok) {
                    const uploadData = await uploadResp.json();
                    const pushNote = uploadData.push_success ? '，已推送到远程仓库' : '';
                    showToast(`${uploadData.count} 个文档已保存到 docs/Design/${pushNote}`, 'success');
                } else {
                    showToast('文档保存失败，项目已创建成功', 'warning');
                }
            } catch (e) {
                showToast('文档保存失败，项目已创建成功', 'warning');
            }
        } else {
            let message = `项目「${name}」创建成功`;
            if (data.push_success) {
                message += '，并已推送到远程仓库';
            } else {
                message += '（首次推送失败，请检查远程仓库权限）';
            }
            showToast(message, data.push_success ? 'success' : 'warning');
        }

        showProjectDetail(data.id);
    } catch (e) {
        showToast(`创建失败: ${e.message}`, 'error');
    }
}

// ==================== 导入现有工程 ====================

function showImportProjectModal() {
    // 重置表单
    document.getElementById('importProjectName').value = '';
    document.getElementById('importProjectDesc').value = '';
    document.getElementById('importTechStack').value = '';
    document.getElementById('importGitRemote').value = '';
    document.getElementById('importLocalPath').value = '';
    document.getElementById('importRepoPath').value = '';

    // 默认选中远程仓库方式
    document.querySelector('input[name="importType"][value="remote"]').checked = true;
    handleImportTypeChange();

    // 隐藏检测信息
    document.getElementById('detectInfo').style.display = 'none';

    openModal('importProjectModal');
}

function handleImportTypeChange() {
    const importType = document.querySelector('input[name="importType"]:checked').value;
    const remoteForm = document.getElementById('importRemoteForm');
    const localForm = document.getElementById('importLocalForm');
    const repoPathGroup = document.getElementById('repoPathGroup');
    const repoPathInput = document.getElementById('importRepoPath');
    const repoPathHint = document.getElementById('repoPathHint');
    const selectRepoBtn = document.getElementById('selectRepoPathBtn');

    if (importType === 'remote') {
        remoteForm.style.display = 'block';
        localForm.style.display = 'none';
        // 远程仓库模式：本地仓库路径可选，可编辑
        repoPathGroup.style.display = 'block';
        repoPathInput.removeAttribute('readonly');
        repoPathInput.placeholder = '留空则自动克隆到 backend/projects/{project_id}/';
        repoPathHint.textContent = '可选：指定本地 Git 仓库的绝对路径';
        selectRepoBtn.style.display = 'flex';
        if (document.getElementById('importLocalPath').value) {
            repoPathInput.value = '';
        }
    } else {
        remoteForm.style.display = 'none';
        localForm.style.display = 'block';
        // 本地文件夹模式：本地仓库路径自动填充到选择框
        repoPathGroup.style.display = 'block';
        repoPathInput.removeAttribute('readonly');
        repoPathInput.placeholder = '留空则使用选中的本地文件夹路径';
        repoPathHint.textContent = '留空则自动使用本地文件夹路径作为仓库路径';
        selectRepoBtn.style.display = 'flex';
        // 清空之前的远程仓库配置的路径
        if (repoPathInput.value && !document.getElementById('importLocalPath').value) {
            repoPathInput.value = '';
        }
    }
}

async function detectLocalProjectInfo() {
    const localPath = document.getElementById('importLocalPath').value.trim();
    if (!localPath) {
        showToast('请先选择本地文件夹', 'warning');
        return;
    }

    try {
        const data = await api('/projects/detect-local', {
            method: 'POST',
            body: { local_path: localPath },
        });

        // 填充检测到的信息
        if (data.project_name) {
            document.getElementById('importProjectName').value = data.project_name;
        }
        if (data.git_remote_url) {
            document.getElementById('importGitRemote').value = data.git_remote_url;
        }
        if (data.description) {
            document.getElementById('importProjectDesc').value = data.description;
        }
        if (data.tech_stack) {
            document.getElementById('importTechStack').value = data.tech_stack;
        }

        // 自动填充本地仓库路径（使用选中的路径）
        document.getElementById('importRepoPath').value = localPath;

        // 显示检测信息
        const detectInfoContent = document.getElementById('detectInfoContent');
        detectInfoContent.textContent = JSON.stringify(data, null, 2);
        document.getElementById('detectInfo').style.display = 'block';

        showToast('项目信息检测成功', 'success');
    } catch (e) {
        showToast(`检测失败: ${e.message}`, 'error');
    }
}

async function importProject() {
    const importType = document.querySelector('input[name="importType"]:checked').value;
    const name = document.getElementById('importProjectName').value.trim();
    const description = document.getElementById('importProjectDesc').value.trim();
    const tech_stack = document.getElementById('importTechStack').value.trim();
    const local_repo_path = document.getElementById('importRepoPath').value.trim();

    if (!name) {
        showToast('请输入项目名称', 'warning');
        return;
    }

    let git_remote_url = '';
    if (importType === 'remote') {
        git_remote_url = document.getElementById('importGitRemote').value.trim();
        if (!git_remote_url) {
            showToast('请输入 Git 远程仓库 URL', 'warning');
            return;
        }
    } else {
        // 本地导入，检测或手动填写 Git URL
        git_remote_url = document.getElementById('importGitRemote').value.trim();
        const localPath = document.getElementById('importLocalPath').value.trim();
        if (!localPath) {
            showToast('请选择本地文件夹', 'warning');
            return;
        }
        if (!git_remote_url) {
            showToast('请填写 Git 远程仓库 URL（或选择包含 .git 的文件夹自动检测）', 'warning');
            return;
        }
        // 如果没有指定 repo_path，使用选中的本地路径
        if (!local_repo_path) {
            document.getElementById('importRepoPath').value = localPath;
        }
    }

    try {
        const body = { name, description, tech_stack, git_remote_url };
        if (local_repo_path) {
            body.local_repo_path = local_repo_path;
        }

        const data = await api('/projects', {
            method: 'POST',
            body,
        });

        closeModal('importProjectModal');

        let message = `项目「${name}」导入成功`;
        if (data.push_success) {
            message += '，并已推送到远程仓库';
        } else {
            message += '（首次推送失败，请检查远程仓库权限）';
        }
        showToast(message, data.push_success ? 'success' : 'warning');

        showProjectDetail(data.id);
    } catch (e) {
        showToast(`导入失败: ${e.message}`, 'error');
    }
}

function selectImportLocalPath() {
    // 使用 prompt 让用户输入完整路径（浏览器安全限制无法直接获取文件夹绝对路径）
    const path = prompt('请输入本地文件夹的完整路径（如 D:/MyProject）:');
    if (path) {
        document.getElementById('importLocalPath').value = path;
        // 自动检测项目信息
        detectLocalProjectInfo();
    }
}

function selectImportRepoPath() {
    // 使用 prompt 让用户输入完整路径（浏览器安全限制无法直接获取文件夹绝对路径）
    const path = prompt('请输入本地仓库的完整路径（如 D:/MyProject）:');
    if (path) {
        document.getElementById('importRepoPath').value = path;
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

        const columns = ['pending', 'architecture', 'development', 'testing', 'done', 'deployed'];
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

    // 所有工单状态选项
    const allStatuses = [
        { value: 'pending', label: '待启动' },
        { value: 'architecture_in_progress', label: '架构中' },
        { value: 'architecture_done', label: '架构完成' },
        { value: 'development_in_progress', label: '开发中' },
        { value: 'development_done', label: '开发完成' },
        { value: 'acceptance_passed', label: '验收通过' },
        { value: 'acceptance_rejected', label: '验收不通过' },
        { value: 'testing_in_progress', label: '测试中' },
        { value: 'testing_done', label: '测试通过' },
        { value: 'testing_failed', label: '测试不通过' },
        { value: 'deploying', label: '部署中' },
        { value: 'deployed', label: '已部署' },
        { value: 'cancelled', label: '已取消' },
    ];
    const statusOptions = allStatuses.map(s =>
        `<option value="${s.value}" ${t.status === s.value ? 'selected' : ''}>${s.label}</option>`
    ).join('');

    return `
        <div class="${cardClass}${t.type === 'bug' ? ' bug-ticket' : ''}">
            <div class="ticket-title" style="cursor:pointer;" onclick="openTicketDrawer('${t.id}')">${t.type === 'bug' ? '<span class="bug-label">BUG</span>' : ''}${escHtml(t.title)}${t.has_error ? ' <span class="ticket-status-badge error" title="测试失败或被拒绝">✗</span>' : t.has_warning ? ' <span class="ticket-status-badge warning" title="测试有警告">⚠</span>' : ''}</div>
            <div class="ticket-meta">
                ${t.module ? `<span class="tag tag-module">${escHtml(t.module)}</span>` : ''}
                <span class="tag tag-type${t.type === 'bug' ? ' tag-bug' : ''}">${escHtml(t.type || 'feature')}</span>
                <span class="tag tag-priority-${t.priority}">${pLabel}</span>
                ${t.assigned_agent ? `<span class="tag tag-agent">${escHtml(t.assigned_agent)}</span>` : ''}
            </div>
            <div class="ticket-footer">
                <select class="status-select" onchange="updateTicketStatus('${t.id}', this.value, this)" onclick="event.stopPropagation()">
                    ${statusOptions}
                </select>
                ${t.estimated_hours ? `<span>${t.estimated_hours}h</span>` : ''}
            </div>
        </div>`;
}

// ==================== 工单状态编辑 ====================

async function updateTicketStatus(ticketId, newStatus, selectEl) {
    if (!currentProjectId) return;
    try {
        const res = await api(`/projects/${currentProjectId}/tickets/${ticketId}/status`, {
            method: 'PATCH',
            body: { status: newStatus },
        });
        showToast(`状态已更新: ${res.status_label}`, 'success');
        setTimeout(() => { refreshBoard(); loadTicketList(); }, 500);
    } catch (e) {
        showToast(`状态更新失败: ${e.message}`, 'error');
        refreshBoard();
        loadTicketList();
    }
}

// ==================== 工单详情抽屉 ====================

async function openTicketDrawer(ticketId) {
    if (!currentProjectId) return;

    // 联动聊天面板 — 设置当前工单上下文
    chatCurrentTicketId = ticketId;

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

        // 描述（支持 Markdown 图片语法渲染）
        if (data.description) {
            let descHtml;
            if (window.marked) {
                try {
                    // 只渲染图片和基础格式，其余文字仍转义
                    descHtml = marked.parse(data.description);
                } catch (e) {
                    descHtml = `<p>${escHtml(data.description)}</p>`;
                }
            } else {
                descHtml = `<p>${escHtml(data.description)}</p>`;
            }
            html += `
            <div class="drawer-section">
                <h4>描述</h4>
                <div class="ticket-description" style="font-size:13px; color:var(--text-secondary); line-height:1.7;">${descHtml}</div>
            </div>`;
        }

        // 操作按钮
        html += renderTicketActions(data);

        // 依赖关系
        let depsArr = [];
        try {
            depsArr = data.dependencies ? JSON.parse(data.dependencies) : [];
        } catch (e) { depsArr = []; }

        if (depsArr.length > 0) {
            html += `
            <div class="drawer-section">
                <h4>🔗 前置依赖 (${depsArr.length})</h4>
                <div class="subtask-list" id="drawerDepsList"></div>
            </div>`;
            // 异步加载依赖工单详情
            setTimeout(() => _loadDependencyDetails(depsArr), 100);
        }

        // 查找依赖此工单的后续工单（反向依赖）
        html += `<div id="drawerDependentsSection"></div>`;
        if (data.id) {
            setTimeout(() => _loadDependents(data.id, data.project_id), 150);
        }

        // 子工单（child_tickets — 真正的工单，有完整状态机）
        const childTickets = data.child_tickets || [];
        if (childTickets.length > 0) {
            html += `
            <div class="drawer-section">
                <h4>子工单 (${childTickets.length})</h4>
                <div class="subtask-list">
                    ${childTickets.map(ct => {
                        const ctShortId = (ct.id || '').slice(-6);
                        const ctStatusColor = getStatusColor(ct.status);
                        const ctStatusLabel = ct.status_label || getStatusLabel(ct.status);
                        return `
                        <div class="subtask-item child-ticket-link ${ct.status === 'deployed' ? 'completed' : ''}"
                             onclick="event.stopPropagation(); openTicketDrawer('${ct.id}');"
                             title="点击查看子工单详情">
                            <span class="subtask-icon" style="font-size:11px;">🎫</span>
                            <span class="tl-id-badge" style="font-size:11px; margin-right:4px;">#${ctShortId}</span>
                            <span class="subtask-title" style="flex:1;">${escHtml(ct.title)}</span>
                            <span class="tl-status-badge" style="font-size:11px; border-left:2px solid ${ctStatusColor}; padding:1px 6px;">${escHtml(ctStatusLabel)}</span>
                        </div>`;
                    }).join('')}
                </div>
            </div>`;
        }

        // 子任务（subtasks — 轻量任务项，关联到子工单）
        const subtasks = data.subtasks || [];
        if (subtasks.length > 0) {
            // 建立子任务标题到子工单的映射（模糊匹配）
            const childTicketByTitle = {};
            childTickets.forEach(ct => {
                childTicketByTitle[ct.title.toLowerCase().trim()] = ct;
            });

            html += `
            <div class="drawer-section">
                <h4>子任务 (${subtasks.length})</h4>
                <div class="subtask-list">
                    ${subtasks.map(st => {
                        // 尝试匹配子工单
                        const matchedTicket = childTicketByTitle[st.title.toLowerCase().trim()];
                        const clickAttr = matchedTicket
                            ? `onclick="event.stopPropagation(); openTicketDrawer('${matchedTicket.id}');" class="subtask-item child-ticket-link ${st.status === 'completed' ? 'completed' : ''}" title="点击查看关联工单 #${(matchedTicket.id || '').slice(-6)}"`
                            : `class="subtask-item ${st.status === 'completed' ? 'completed' : ''}"`;
                        const linkIcon = matchedTicket ? ' 🔗' : '';
                        return `
                        <div ${clickAttr}>
                            <span class="subtask-icon">${st.status === 'completed' ? '✅' : st.status === 'in_progress' ? '🔄' : '⬜'}</span>
                            <span class="subtask-title">${escHtml(st.title)}${linkIcon}</span>
                        </div>`;
                    }).join('')}
                </div>
            </div>`;
        }

        // 产物
        const artifacts = data.artifacts || [];
        const ticketBranch = data.branch_name || '';
        if (artifacts.length > 0) {
            html += `
            <div class="drawer-section">
                <h4>产出文件 (${artifacts.length})${ticketBranch ? ` <span class="req-branch-tag" style="font-size:11px;font-weight:normal;">🌿 ${escHtml(ticketBranch)}</span>` : ''}</h4>
                ${artifacts.map(a => {
                    // 从 metadata.git.files 或 content.files 提取文件列表
                    let fileList = [];
                    try {
                        const meta = a.metadata ? (typeof a.metadata === 'string' ? JSON.parse(a.metadata) : a.metadata) : {};
                        if (meta.git && meta.git.files) {
                            fileList = meta.git.files;
                        }
                    } catch {}
                    if (fileList.length === 0) {
                        try {
                            const parsed = JSON.parse(a.content || '{}');
                            if (parsed.files) {
                                fileList = Array.isArray(parsed.files) ? parsed.files : Object.keys(parsed.files);
                            } else if (parsed.dev_result && parsed.dev_result.files) {
                                fileList = Object.keys(parsed.dev_result.files);
                            }
                        } catch {}
                    }
                    const commitHash = (() => { try { const m = a.metadata ? (typeof a.metadata === 'string' ? JSON.parse(a.metadata) : a.metadata) : {}; return m.git?.commit_hash || ''; } catch { return ''; } })();

                    let filesHtml = '';
                    if (fileList.length > 0) {
                        filesHtml = '<div class="artifact-file-list">';
                        fileList.forEach(f => {
                            const filePath = typeof f === 'string' ? f : (f.path || f.name || '');
                            const fileName = filePath.split('/').pop();
                            const dirPath = filePath.includes('/') ? filePath.substring(0, filePath.lastIndexOf('/') + 1) : '';
                            filesHtml += `<a class="artifact-file-link" onclick="event.stopPropagation(); openArtifactFile('${escHtml(filePath)}', '${escHtml(ticketBranch)}')" title="${escHtml(filePath)}${ticketBranch ? ' (' + escHtml(ticketBranch) + ')' : ''}">
                                <span class="file-icon">📄</span>
                                <span class="file-dir">${escHtml(dirPath)}</span><span class="file-name">${escHtml(fileName)}</span>
                            </a>`;
                        });
                        filesHtml += '</div>';
                    }

                    const isScreenshot = a.type === 'screenshot';
                    const imgHtml = isScreenshot && a.path
                        ? `<div class="artifact-screenshot"><img src="${escHtml(a.path)}" alt="${escHtml(a.name)}" style="max-width:100%;border-radius:4px;margin-top:8px;cursor:pointer;" onclick="event.stopPropagation();window.open(this.src,'_blank')"></div>`
                        : '';

                    // 文件路径徽章（报告或有明确路径的产物）
                    const pathBadge = (!isScreenshot && a.path)
                        ? `<div style="margin-top:6px;" onclick="event.stopPropagation();">
                               <span class="artifact-path-badge" title="${escHtml(a.path)}" onclick="event.stopPropagation();">
                                   <span class="path-icon">📁</span>${escHtml(a.path)}
                               </span>
                           </div>`
                        : '';

                    // 可折叠内容块
                    const rawContent = tryFormatJson(a.content);
                    const contentBlockId = 'acb-' + a.id;
                    const contentBlock = (!isScreenshot && rawContent)
                        ? `<div class="collapsible-block" onclick="event.stopPropagation();" id="${contentBlockId}">
                               <div class="collapsible-preview" onclick="toggleCollapsible('${contentBlockId}')">${escHtml(rawContent)}</div>
                               <div class="collapsible-toggle" onclick="toggleCollapsible('${contentBlockId}')">
                                   <span>展开查看</span><span class="toggle-arrow">▼</span>
                               </div>
                           </div>`
                        : '';

                    return `
                    <div class="artifact-card" onclick="">
                        <div style="display:flex; align-items:center; gap:8px; font-size:13px;">
                            <span>${getArtifactIcon(a.type)}</span>
                            <span style="font-weight:500;">${escHtml(a.name || a.type)}</span>
                            <span class="tag tag-module" style="font-size:11px;">${escHtml(a.type)}</span>
                            ${commitHash ? `<span style="font-size:10px;color:var(--text-muted);font-family:monospace;">${escHtml(commitHash)}</span>` : ''}
                            <span style="font-size:11px; color:var(--text-muted); margin-left:auto;">${formatDate(a.created_at)}</span>
                        </div>
                        ${pathBadge}
                        ${filesHtml}
                        ${imgHtml}
                        ${contentBlock}
                    </div>`;
                }).join('')}
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
        // 描述区图片点击放大
        drawerBody.querySelectorAll('.ticket-description img').forEach(img => {
            img.onclick = () => window.open(img.src, '_blank');
            img.title = '点击查看大图';
        });
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
    // 查看 AI 对话按钮
    buttons += `<button class="btn btn-sm" onclick="selectTicketForChat('${ticket.id}', '${escHtml(ticket.title).replace(/'/g, "\\'")}'); closeDrawer();">💬 AI 对话</button>`;
    if (ticket.status !== 'deployed' && ticket.status !== 'cancelled') {
        buttons += `<button class="btn btn-sm" style="color:var(--error);" onclick="cancelTicket('${ticket.id}')">✗ 取消</button>`;
    }
    if (!buttons) return '';
    return `<div class="drawer-section"><h4>操作</h4><div style="display:flex; gap:8px; flex-wrap:wrap;">${buttons}</div></div>`;
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

function toggleCollapsible(blockId) {
    const block = document.getElementById(blockId);
    if (!block) return;
    const preview = block.querySelector('.collapsible-preview');
    const toggle = block.querySelector('.collapsible-toggle');
    if (!preview || !toggle) return;
    const isExpanded = preview.classList.contains('expanded');
    if (isExpanded) {
        preview.classList.remove('expanded');
        toggle.classList.remove('expanded');
        toggle.innerHTML = '<span>展开查看</span><span class="toggle-arrow">▼</span>';
    } else {
        preview.classList.add('expanded');
        toggle.classList.add('expanded');
        toggle.innerHTML = '<span>收起</span><span class="toggle-arrow">▼</span>';
    }
}

function closeDrawer() {
    document.getElementById('drawerOverlay').classList.remove('active');
    document.getElementById('ticketDrawer').classList.remove('active');
}

/** 加载前置依赖工单详情 */
async function _loadDependencyDetails(depIds) {
    const container = document.getElementById('drawerDepsList');
    if (!container || !currentProjectId) return;

    let html = '';
    for (const depId of depIds) {
        try {
            const dep = await api(`/projects/${currentProjectId}/tickets/${depId}`);
            const shortId = (dep.id || '').slice(-6);
            const statusColor = getStatusColor(dep.status);
            const statusLabel = dep.status_label || getStatusLabel(dep.status);
            const isComplete = dep.status === 'deployed';
            html += `
            <div class="subtask-item child-ticket-link ${isComplete ? 'completed' : ''}"
                 onclick="event.stopPropagation(); openTicketDrawer('${dep.id}');"
                 title="点击查看依赖工单详情">
                <span class="subtask-icon">${isComplete ? '✅' : '⏳'}</span>
                <span class="tl-id-badge" style="font-size:11px; margin-right:4px;">#${shortId}</span>
                <span class="subtask-title" style="flex:1;">${escHtml(dep.title)}</span>
                <span class="tl-status-badge" style="font-size:11px; border-left:2px solid ${statusColor}; padding:1px 6px;">${escHtml(statusLabel)}</span>
            </div>`;
        } catch (e) {
            html += `<div class="subtask-item"><span class="subtask-icon">❓</span><span class="subtask-title">${depId} (加载失败)</span></div>`;
        }
    }
    container.innerHTML = html;
}

/** 加载后续依赖工单（依赖此工单的工单） */
async function _loadDependents(ticketId, projectId) {
    const section = document.getElementById('drawerDependentsSection');
    if (!section || !projectId) return;

    try {
        const data = await api(`/projects/${projectId}/ticket-graph`);
        const dependents = (data.edges || [])
            .filter(e => e.type === 'dependency' && e.source === ticketId)
            .map(e => e.target);

        if (dependents.length === 0) return;

        let html = `<div class="drawer-section"><h4>🔗 后续工单 (${dependents.length})</h4><div class="subtask-list">`;
        for (const depId of dependents) {
            const node = (data.nodes || []).find(n => n.id === depId);
            if (!node) continue;
            const shortId = (node.id || '').slice(-6);
            const statusColor = getStatusColor(node.status);
            html += `
            <div class="subtask-item child-ticket-link"
                 onclick="event.stopPropagation(); openTicketDrawer('${node.id}');">
                <span class="subtask-icon">➡️</span>
                <span class="tl-id-badge" style="font-size:11px; margin-right:4px;">#${shortId}</span>
                <span class="subtask-title" style="flex:1;">${escHtml(node.title)}</span>
                <span class="tl-status-badge" style="font-size:11px; border-left:2px solid ${statusColor}; padding:1px 6px;">${escHtml(node.status_label || '')}</span>
            </div>`;
        }
        html += '</div></div>';
        section.innerHTML = html;
    } catch (e) { /* ignore */ }
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

// 缓存需求关联工单数据（用于折叠展开）
let reqTicketsCache = {};

async function loadRequirements() {
    if (!currentProjectId) return;
    const list = document.getElementById('requirementList');
    reqTicketsCache = {};

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

        // TAPD 风格表格视图 + 可折叠关联工单
        let html = `
        <div class="req-table-header">
            <span class="req-table-summary">${escHtml(currentProject?.name || '项目')} <span class="req-table-count">(${reqs.length})</span></span>
        </div>
        <table class="req-table">
            <thead>
                <tr>
                    <th class="col-expand" style="width:32px;"></th>
                    <th class="col-title">标题</th>
                    <th class="col-status">状态</th>
                    <th class="col-priority">优先级</th>
                    <th class="col-tickets">工单</th>
                    <th class="col-module">模块</th>
                    <th class="col-time">创建时间</th>
                    <th class="col-actions">操作</th>
                </tr>
            </thead>
            <tbody>`;

        reqs.forEach(r => {
            const priorityMap = {
                critical: { label: '紧急', cls: 'critical' },
                high: { label: 'High', cls: 'high' },
                medium: { label: 'Middle', cls: 'medium' },
                low: { label: 'Low', cls: 'low' },
            };
            const pInfo = priorityMap[r.priority] || { label: r.priority, cls: 'medium' };
            const ticketCount = r.ticket_count || 0;

            html += `
                <tr class="req-table-row" data-req-id="${r.id}">
                    <td class="col-expand" onclick="event.stopPropagation(); toggleReqTickets('${r.id}', this);">
                        ${ticketCount > 0 ? `<span class="req-expand-arrow" id="arrow-${r.id}">▶</span>` : '<span style="width:14px;display:inline-block;"></span>'}
                    </td>
                    <td class="col-title" onclick="openPipeline('${r.id}')">
                        <span class="req-table-title">${escHtml(r.title)}</span>
                        ${r.branch_name ? `<span class="req-branch-tag" title="${escHtml(r.branch_name)}">🌿 ${escHtml(r.branch_name)}</span>` : ''}
                        ${r.description ? `<span class="req-table-desc">${escHtml(r.description)}</span>` : ''}
                    </td>
                    <td class="col-status"><span class="req-status-tag ${r.status}">${getStatusLabel(r.status)}</span></td>
                    <td class="col-priority"><span class="req-priority-tag ${pInfo.cls}">${escHtml(pInfo.label)}</span></td>
                    <td class="col-tickets">${ticketCount}</td>
                    <td class="col-module">${escHtml(r.module || '-')}</td>
                    <td class="col-time">${formatDateTime(r.created_at)}</td>
                    <td class="col-actions" onclick="event.stopPropagation()">
                        <button class="btn-icon req-action-btn" onclick="showRequirementDetail('${r.id}')" title="详情">📋</button>
                        <button class="btn-icon req-action-btn req-delete-btn" onclick="deleteReq('${r.id}', '${escHtml(r.title).replace(/'/g, "\\'")}')" title="删除">🗑️</button>
                    </td>
                </tr>
                <tr class="req-tickets-row" id="req-tickets-${r.id}" style="display:none;">
                    <td colspan="8" class="req-tickets-cell">
                        <div class="req-tickets-container" id="req-tickets-container-${r.id}">
                            <div style="padding:12px; color:var(--text-muted); font-size:12px;">加载中...</div>
                        </div>
                    </td>
                </tr>`;
        });

        html += '</tbody></table>';
        list.innerHTML = html;
    } catch (e) {
        list.innerHTML = `<div class="empty-state"><p>加载失败: ${escHtml(e.message)}</p></div>`;
    }
}

/** 切换需求下关联工单的折叠/展开 */
async function toggleReqTickets(reqId, tdEl) {
    const row = document.getElementById(`req-tickets-${reqId}`);
    const arrow = document.getElementById(`arrow-${reqId}`);
    if (!row) return;

    const isVisible = row.style.display !== 'none';
    if (isVisible) {
        row.style.display = 'none';
        if (arrow) arrow.classList.remove('expanded');
        return;
    }

    row.style.display = 'table-row';
    if (arrow) arrow.classList.add('expanded');

    // 如果已加载过，直接显示
    if (reqTicketsCache[reqId]) {
        renderReqTicketsSubTable(reqId, reqTicketsCache[reqId]);
        return;
    }

    // 从 API 获取需求详情（含工单列表）
    try {
        const data = await api(`/projects/${currentProjectId}/requirements/${reqId}`);
        const tickets = data.tickets || [];
        reqTicketsCache[reqId] = tickets;
        renderReqTicketsSubTable(reqId, tickets);
    } catch (e) {
        const container = document.getElementById(`req-tickets-container-${reqId}`);
        if (container) container.innerHTML = `<div style="padding:12px; color:var(--error); font-size:12px;">加载失败: ${escHtml(e.message)}</div>`;
    }
}

/** 渲染需求下折叠的工单子表格 */
function renderReqTicketsSubTable(reqId, tickets) {
    const container = document.getElementById(`req-tickets-container-${reqId}`);
    if (!container) return;

    if (tickets.length === 0) {
        container.innerHTML = `<div style="padding:12px; color:var(--text-muted); font-size:12px;">暂无关联工单</div>`;
        return;
    }

    let html = `<table class="req-sub-ticket-table">
        <thead><tr>
            <th>工单标题</th>
            <th style="width:90px;">状态</th>
            <th style="width:70px;">类型</th>
            <th style="width:80px;">模块</th>
            <th style="width:100px;">Agent</th>
            <th style="width:60px;">优先级</th>
        </tr></thead><tbody>`;

    tickets.forEach(t => {
        const statusColor = getStatusColor(t.status);
        const priorityLabel = {1:'P1',2:'P2',3:'P3',4:'P4',5:'P5'};
        const pLabel = priorityLabel[t.priority] || `P${t.priority}`;

        html += `<tr class="req-sub-ticket-row" onclick="openTicketDrawer('${t.id}')">
            <td>
                <span class="req-sub-ticket-title">${escHtml(t.title)}</span>
            </td>
            <td><span class="ticket-status-dot" style="background:${statusColor};"></span> ${escHtml(t.status_label || getStatusLabel(t.status))}</td>
            <td><span class="tag tag-type" style="font-size:11px;">${escHtml(t.type || 'feature')}</span></td>
            <td>${escHtml(t.module || '-')}</td>
            <td>${t.assigned_agent ? `<span class="tag tag-agent" style="font-size:11px;">${escHtml(t.assigned_agent)}</span>` : '<span style="color:var(--text-muted);">-</span>'}</td>
            <td><span class="tag tag-priority-${t.priority}" style="font-size:11px;">${pLabel}</span></td>
        </tr>`;
    });

    html += '</tbody></table>';
    container.innerHTML = html;
}

// ==================== 工单关系图（SVG 拓扑 + 连线） ====================

/** 加载工单关系图 */
async function loadTicketGraph() {
    if (!currentProjectId) return;
    const container = document.getElementById('ticketGraphContainer');
    if (!container) return;

    // 填充需求筛选
    await _populateGraphReqFilter();

    const reqFilter = document.getElementById('graphReqFilter')?.value || '';
    let url = `/projects/${currentProjectId}/ticket-graph`;
    if (reqFilter) url += `?requirement_id=${reqFilter}`;

    try {
        const data = await api(url);
        renderTicketGraph(container, data.nodes || [], data.edges || []);
    } catch (e) {
        container.innerHTML = `<div class="empty-state"><div class="emoji">❌</div><p>加载失败: ${escHtml(e.message)}</p></div>`;
    }
}

async function _populateGraphReqFilter() {
    const sel = document.getElementById('graphReqFilter');
    if (!sel || !currentProjectId) return;
    try {
        const data = await api(`/projects/${currentProjectId}/requirements`);
        const reqs = data.requirements || [];
        const current = sel.value;
        sel.innerHTML = '<option value="">全部需求</option>';
        reqs.forEach(r => {
            sel.innerHTML += `<option value="${r.id}" ${r.id === current ? 'selected' : ''}>${escHtml(r.title)}</option>`;
        });
    } catch (e) { /* ignore */ }
}

/** 使用 SVG 渲染工单关系图 */
function renderTicketGraph(container, nodes, edges) {
    if (nodes.length === 0) {
        container.innerHTML = `<div class="empty-state"><div class="emoji">🔗</div><p>暂无工单数据</p></div>`;
        return;
    }

    // === 布局算法：按层级分层排列 ===
    // 1. 分离父节点（无 parent_ticket_id）和子节点
    const nodeMap = {};
    nodes.forEach(n => { nodeMap[n.id] = n; });

    // 2. 计算入度（依赖关系），做拓扑排序分层
    const depEdges = edges.filter(e => e.type === 'dependency');
    const parentEdges = edges.filter(e => e.type === 'parent_child');

    // 父节点：顶层工单（无 parent_ticket_id）
    const topNodes = nodes.filter(n => !n.parent_ticket_id);
    const childNodes = nodes.filter(n => n.parent_ticket_id);

    // 拓扑排序确定层级
    const inDegree = {};
    const adjList = {};  // source → [targets]
    topNodes.forEach(n => { inDegree[n.id] = 0; adjList[n.id] = []; });

    depEdges.forEach(e => {
        if (inDegree[e.target] !== undefined) {
            inDegree[e.target] = (inDegree[e.target] || 0) + 1;
        }
        if (adjList[e.source]) adjList[e.source].push(e.target);
    });

    // BFS 分层
    const layers = [];
    const assigned = new Set();
    let queue = topNodes.filter(n => (inDegree[n.id] || 0) === 0).map(n => n.id);
    if (queue.length === 0) queue = topNodes.map(n => n.id); // fallback

    while (queue.length > 0) {
        const layer = [];
        const nextQueue = [];
        queue.forEach(id => {
            if (!assigned.has(id)) {
                assigned.add(id);
                layer.push(id);
            }
        });
        layers.push(layer);

        layer.forEach(id => {
            (adjList[id] || []).forEach(targetId => {
                if (!assigned.has(targetId)) {
                    inDegree[targetId] = (inDegree[targetId] || 1) - 1;
                    if (inDegree[targetId] <= 0) {
                        nextQueue.push(targetId);
                    }
                }
            });
        });
        queue = nextQueue;
        if (layers.length > 20) break; // 安全阀
    }

    // 未分配的节点放最后一层
    topNodes.forEach(n => {
        if (!assigned.has(n.id)) {
            if (layers.length === 0) layers.push([]);
            layers[layers.length - 1].push(n.id);
        }
    });

    // === 计算坐标 ===
    const NODE_W = 220, NODE_H = 72, CHILD_H = 50;
    const GAP_X = 80, GAP_Y = 40, CHILD_GAP = 6;
    const PADDING = 40;

    const positions = {};  // id → {x, y, w, h}

    // 计算每层节点的总高度（含子节点）
    function getNodeTotalHeight(nodeId) {
        const children = childNodes.filter(c => c.parent_ticket_id === nodeId);
        return NODE_H + children.length * (CHILD_H + CHILD_GAP);
    }

    let maxX = 0, maxY = 0;

    layers.forEach((layer, layerIdx) => {
        const x = PADDING + layerIdx * (NODE_W + GAP_X);
        let y = PADDING;

        layer.forEach(nodeId => {
            const totalH = getNodeTotalHeight(nodeId);
            positions[nodeId] = { x, y, w: NODE_W, h: NODE_H };

            // 子节点在父节点下方
            const children = childNodes.filter(c => c.parent_ticket_id === nodeId);
            children.forEach((child, ci) => {
                const cy = y + NODE_H + ci * (CHILD_H + CHILD_GAP);
                positions[child.id] = { x: x + 24, y: cy, w: NODE_W - 24, h: CHILD_H };
            });

            y += totalH + GAP_Y;
        });

        if (y > maxY) maxY = y;
        if (x + NODE_W > maxX) maxX = x + NODE_W;
    });

    const svgW = maxX + PADDING;
    const svgH = maxY + PADDING;

    // === 绘制 SVG ===
    let svg = `<svg class="ticket-graph-svg" width="${svgW}" height="${svgH}" viewBox="0 0 ${svgW} ${svgH}">`;

    // 箭头标记
    svg += `
    <defs>
        <marker id="arrow-dep" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto" markerUnits="userSpaceOnUse">
            <path d="M0,0 L8,3 L0,6" fill="#e8a735" />
        </marker>
        <marker id="arrow-parent" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto" markerUnits="userSpaceOnUse">
            <path d="M0,0 L8,3 L0,6" fill="#58a6ff" />
        </marker>
    </defs>`;

    // 画边（依赖关系 — 黄色虚线箭头）
    depEdges.forEach(e => {
        const src = positions[e.source];
        const tgt = positions[e.target];
        if (!src || !tgt) return;

        const x1 = src.x + src.w;
        const y1 = src.y + src.h / 2;
        const x2 = tgt.x;
        const y2 = tgt.y + tgt.h / 2;

        // 贝塞尔曲线
        const cx = (x1 + x2) / 2;
        svg += `<path d="M${x1},${y1} C${cx},${y1} ${cx},${y2} ${x2},${y2}"
                  fill="none" stroke="#e8a735" stroke-width="2" stroke-dasharray="6,3"
                  marker-end="url(#arrow-dep)" class="graph-edge graph-edge-dep" />`;

        // 依赖标签
        const mx = (x1 + x2) / 2;
        const my = (y1 + y2) / 2 - 8;
        svg += `<text x="${mx}" y="${my}" class="graph-edge-label" fill="#e8a735">依赖</text>`;
    });

    // 画边（父子关系 — 蓝色实线）
    parentEdges.forEach(e => {
        const src = positions[e.source];
        const tgt = positions[e.target];
        if (!src || !tgt) return;

        const x1 = src.x + 12;
        const y1 = src.y + src.h;
        const x2 = tgt.x;
        const y2 = tgt.y + tgt.h / 2;

        svg += `<path d="M${x1},${y1} L${x1},${y2} L${x2},${y2}"
                  fill="none" stroke="#58a6ff" stroke-width="1.5"
                  marker-end="url(#arrow-parent)" class="graph-edge graph-edge-parent" />`;
    });

    // 画节点
    nodes.forEach(n => {
        const pos = positions[n.id];
        if (!pos) return;
        const isChild = !!n.parent_ticket_id;
        const statusColor = getStatusColor(n.status);
        const shortId = (n.id || '').slice(-6);

        if (isChild) {
            // 子工单：小卡片
            svg += `
            <g class="graph-node graph-node-child" onclick="openTicketDrawer('${n.id}')" style="cursor:pointer;">
                <rect x="${pos.x}" y="${pos.y}" width="${pos.w}" height="${pos.h}"
                      rx="4" fill="var(--bg-card)" stroke="${statusColor}" stroke-width="1" />
                <text x="${pos.x + 8}" y="${pos.y + 18}" class="graph-node-id" fill="var(--text-muted)">#${shortId}</text>
                <text x="${pos.x + 52}" y="${pos.y + 18}" class="graph-node-title-sm">${escHtml(n.title.slice(0, 22))}</text>
                <rect x="${pos.x + pos.w - 48}" y="${pos.y + 6}" width="40" height="16" rx="3"
                      fill="${statusColor}20" stroke="${statusColor}" stroke-width="0.5" />
                <text x="${pos.x + pos.w - 28}" y="${pos.y + 18}" class="graph-node-status-sm" fill="${statusColor}">${escHtml(n.status_label || '')}</text>
            </g>`;
        } else {
            // 父工单：完整卡片
            const priorityLabel = {1:'P1',2:'P2',3:'P3',4:'P4',5:'P5'};
            const pLabel = priorityLabel[n.priority] || 'P3';

            svg += `
            <g class="graph-node" onclick="openTicketDrawer('${n.id}')" style="cursor:pointer;">
                <rect x="${pos.x}" y="${pos.y}" width="${pos.w}" height="${pos.h}"
                      rx="6" fill="var(--bg-card)" stroke="${statusColor}" stroke-width="2" />
                <rect x="${pos.x}" y="${pos.y}" width="4" height="${pos.h}" rx="2" fill="${statusColor}" />
                <text x="${pos.x + 12}" y="${pos.y + 20}" class="graph-node-id" fill="var(--text-muted)">#${shortId}</text>
                <text x="${pos.x + 58}" y="${pos.y + 20}" class="graph-node-priority" fill="var(--text-muted)">${pLabel}</text>
                <text x="${pos.x + 12}" y="${pos.y + 42}" class="graph-node-title">${escHtml(n.title.slice(0, 24))}</text>
                <text x="${pos.x + 12}" y="${pos.y + 60}" class="graph-node-meta" fill="var(--text-muted)">${escHtml(n.module || '')} · ${escHtml(n.assigned_agent || '未分配')}</text>
                <rect x="${pos.x + pos.w - 62}" y="${pos.y + 8}" width="52" height="18" rx="4"
                      fill="${statusColor}20" stroke="${statusColor}" stroke-width="0.5" />
                <text x="${pos.x + pos.w - 36}" y="${pos.y + 21}" class="graph-node-status" fill="${statusColor}">${escHtml(n.status_label || '')}</text>
            </g>`;
        }
    });

    svg += '</svg>';
    container.innerHTML = svg;
}


// ==================== 工单列表（全量工单表格 + 看板视图） ====================

let ticketListViewMode = 'table'; // 'table' | 'board'

function switchTicketListView(mode) {
    ticketListViewMode = mode;
    document.getElementById('viewBtnTable')?.classList.toggle('active', mode === 'table');
    document.getElementById('viewBtnBoard')?.classList.toggle('active', mode === 'board');
    loadTicketList();
}

async function loadTicketList() {
    if (!currentProjectId) return;
    const content = document.getElementById('ticketListContent');
    if (!content) return;

    const statusFilter = document.getElementById('ticketListStatusFilter')?.value || '';
    const moduleFilter = document.getElementById('ticketListModuleFilter')?.value || '';

    try {
        // 获取所有需求
        const reqData = await api(`/projects/${currentProjectId}/requirements`);
        const reqs = reqData.requirements || [];

        // 并行获取每个需求的工单
        let allTickets = [];
        const reqMap = {};
        reqs.forEach(r => { reqMap[r.id] = r; });

        const ticketPromises = reqs.map(async r => {
            try {
                const detail = await api(`/projects/${currentProjectId}/requirements/${r.id}`);
                return (detail.tickets || []).map(t => ({ ...t, req_title: r.title, req_id: r.id }));
            } catch { return []; }
        });

        const results = await Promise.all(ticketPromises);
        results.forEach(tickets => allTickets.push(...tickets));

        // 过滤
        if (statusFilter) {
            allTickets = allTickets.filter(t => t.status === statusFilter || t.status.includes(statusFilter));
        }
        if (moduleFilter) {
            allTickets = allTickets.filter(t => t.module === moduleFilter);
        }

        if (ticketListViewMode === 'board') {
            renderTicketListBoard(content, allTickets);
        } else {
            renderTicketListTable(content, allTickets);
        }
    } catch (e) {
        content.innerHTML = `<div class="empty-state"><p>加载失败: ${escHtml(e.message)}</p></div>`;
    }
}

/** 渲染单个工单表格行 */
function _renderTicketRow(t, isChild) {
    const statusColor = getStatusColor(t.status);
    const priorityLabel = {1:'P1',2:'P2',3:'P3',4:'P4',5:'P5'};
    const pLabel = priorityLabel[t.priority] || `P${t.priority}`;
    const shortId = (t.id || '').slice(-6);
    const childCount = t.child_ticket_count || 0;
    const hasChildren = childCount > 0;
    const childClass = isChild ? ' tl-child-row' : '';
    const parentAttr = isChild ? '' : (hasChildren ? ` data-parent-id="${t.id}"` : '');

    // 标题列：父工单有子工单时显示展开箭头
    const bugLabel = t.type === 'bug' ? '<span class="bug-label">BUG</span>' : '';
    const warnIcon = t.has_error ? '<span class="ticket-status-badge error" title="测试失败或被拒绝">✗</span>'
                   : t.has_warning ? '<span class="ticket-status-badge warning" title="测试有警告">⚠</span>'
                   : '';
    let titleHtml = '';
    if (!isChild && hasChildren) {
        titleHtml = `
            <span class="tl-expand-arrow" onclick="event.stopPropagation(); toggleTicketChildren('${t.id}', this)">▶</span>
            ${bugLabel}<span class="tl-title-text">${escHtml(t.title)}</span>${warnIcon}
            <span class="tl-child-count-badge">${childCount}</span>`;
    } else if (isChild) {
        titleHtml = `
            <span class="tl-child-indent">└</span>
            ${bugLabel}<span class="tl-title-text">${escHtml(t.title)}</span>${warnIcon}`;
    } else {
        titleHtml = `${bugLabel}<span class="tl-title-text">${escHtml(t.title)}</span>${warnIcon}`;
    }
    if (t.description && !isChild) {
        titleHtml += `<span class="tl-title-desc">${escHtml(t.description)}</span>`;
    }

    // 状态下拉选项
    const allStatuses = [
        { value: 'pending', label: '待启动' },
        { value: 'architecture_in_progress', label: '架构中' },
        { value: 'architecture_done', label: '架构完成' },
        { value: 'development_in_progress', label: '开发中' },
        { value: 'development_done', label: '开发完成' },
        { value: 'acceptance_passed', label: '验收通过' },
        { value: 'acceptance_rejected', label: '验收不通过' },
        { value: 'testing_in_progress', label: '测试中' },
        { value: 'testing_done', label: '测试通过' },
        { value: 'testing_failed', label: '测试不通过' },
        { value: 'deploying', label: '部署中' },
        { value: 'deployed', label: '已部署' },
        { value: 'cancelled', label: '已取消' },
    ];
    const statusOptions = allStatuses.map(s =>
        `<option value="${s.value}" ${t.status === s.value ? 'selected' : ''}>${s.label}</option>`
    ).join('');

    return `
        <tr class="tl-table-row${childClass}" ${parentAttr}
            ${isChild ? `data-child-of="${t.parent_ticket_id}" style="display:none;"` : ''}>
            <td class="tl-col-id"><span class="tl-id-badge">#${shortId}</span></td>
            <td class="tl-col-title" style="cursor:pointer;" onclick="openTicketDrawer('${t.id}')">${titleHtml}</td>
            <td class="tl-col-status" onclick="event.stopPropagation()">
                <select class="status-select" onchange="updateTicketStatus('${t.id}', this.value, this)">
                    ${statusOptions}
                </select>
            </td>
            <td class="tl-col-type"><span class="tag tag-type${t.type === 'bug' ? ' tag-bug' : ''}" style="font-size:11px;">${escHtml(t.type || 'feature')}</span></td>
            <td class="tl-col-module">${escHtml(t.module || '-')}</td>
            <td class="tl-col-agent">${t.assigned_agent ? `<span class="tag tag-agent" style="font-size:11px;">${escHtml(t.assigned_agent)}</span>` : '<span style="color:var(--text-muted);">未分配</span>'}</td>
            <td class="tl-col-priority"><span class="tag tag-priority-${t.priority}" style="font-size:11px;">${pLabel}</span></td>
            <td class="tl-col-req"><span class="tl-req-link" onclick="event.stopPropagation(); openPipeline('${t.req_id}');">${escHtml(t.req_title || '-')}</span></td>
            <td class="tl-col-time">${formatDateTime(t.created_at)}</td>
        </tr>`;
}

/** 展开/收起子工单 */
function toggleTicketChildren(parentId, arrowEl) {
    const rows = document.querySelectorAll(`tr[data-child-of="${parentId}"]`);
    const isExpanded = arrowEl.classList.contains('expanded');
    rows.forEach(r => r.style.display = isExpanded ? 'none' : '');
    arrowEl.classList.toggle('expanded', !isExpanded);
    arrowEl.textContent = isExpanded ? '▶' : '▼';
}

/** 渲染 TAPD 风格工单列表表格（支持父子工单折叠） */
function renderTicketListTable(container, tickets) {
    if (tickets.length === 0) {
        container.innerHTML = `<div class="empty-state"><div class="emoji">🎫</div><p>暂无工单</p></div>`;
        return;
    }

    // 分离父工单和子工单
    const parentTickets = tickets.filter(t => !t.parent_ticket_id);
    const childMap = {}; // parentId -> [children]
    tickets.forEach(t => {
        if (t.parent_ticket_id) {
            if (!childMap[t.parent_ticket_id]) childMap[t.parent_ticket_id] = [];
            childMap[t.parent_ticket_id].push(t);
        }
    });

    const parentCount = parentTickets.length;
    const childCount = tickets.length - parentCount;

    let html = `
    <div class="tl-table-header">
        <span class="tl-table-summary">全部工单 <span class="tl-table-count">(${parentCount}${childCount > 0 ? ` + ${childCount} 子工单` : ''})</span></span>
    </div>
    <table class="tl-table">
        <thead>
            <tr>
                <th class="tl-col-id" style="width:80px;">ID</th>
                <th class="tl-col-title">标题</th>
                <th class="tl-col-status" style="width:110px;">状态</th>
                <th class="tl-col-type" style="width:70px;">类型</th>
                <th class="tl-col-module" style="width:80px;">模块</th>
                <th class="tl-col-agent" style="width:120px;">负责 Agent</th>
                <th class="tl-col-priority" style="width:60px;">优先级</th>
                <th class="tl-col-req" style="width:160px;">所属需求</th>
                <th class="tl-col-time" style="width:140px;">创建时间</th>
            </tr>
        </thead>
        <tbody>`;

    // 渲染父工单 + 紧跟其子工单
    parentTickets.forEach(t => {
        html += _renderTicketRow(t, false);
        const children = childMap[t.id] || [];
        children.forEach(child => {
            html += _renderTicketRow(child, true);
        });
    });

    html += '</tbody></table>';
    container.innerHTML = html;
}

/** 渲染工单列表的看板视图（简化版，按状态分列） */
function renderTicketListBoard(container, tickets) {
    if (tickets.length === 0) {
        container.innerHTML = `<div class="empty-state"><div class="emoji">📌</div><p>暂无工单</p></div>`;
        return;
    }

    // 按状态分组
    const statusGroups = {
        pending: { label: '待启动', color: 'var(--text-muted)', tickets: [] },
        in_progress: { label: '进行中', color: 'var(--info)', tickets: [] },
        review: { label: '待审查', color: 'var(--warning)', tickets: [] },
        testing: { label: '测试中', color: 'var(--accent)', tickets: [] },
        done: { label: '已完成', color: 'var(--success)', tickets: [] },
    };

    // 看板只展示父工单（子工单在父工单详情中查看）
    const parentOnly = tickets.filter(t => !t.parent_ticket_id);
    parentOnly.forEach(t => {
        const s = t.status;
        if (s === 'pending') statusGroups.pending.tickets.push(t);
        else if (s.includes('_in_progress') || s === 'deploying' || s === 'analyzing') statusGroups.in_progress.tickets.push(t);
        else if (s.includes('review') || s.includes('rejected')) statusGroups.review.tickets.push(t);
        else if (s.includes('testing')) statusGroups.testing.tickets.push(t);
        else if (s === 'deployed' || s === 'completed' || s === 'acceptance_passed' || s === 'testing_done') statusGroups.done.tickets.push(t);
        else statusGroups.pending.tickets.push(t);
    });

    let html = '<div class="tl-board">';
    for (const [key, group] of Object.entries(statusGroups)) {
        html += `
        <div class="tl-board-column">
            <div class="tl-board-col-header">
                <span class="tl-board-col-dot" style="background:${group.color};"></span>
                <span class="tl-board-col-title">${group.label}</span>
                <span class="tl-board-col-count">${group.tickets.length}</span>
            </div>
            <div class="tl-board-col-body">`;

        if (group.tickets.length === 0) {
            html += '<div style="padding:16px; text-align:center; color:var(--text-muted); font-size:12px;">暂无</div>';
        } else {
            group.tickets.forEach(t => {
                const pLabel = {1:'P1',2:'P2',3:'P3',4:'P4',5:'P5'}[t.priority] || `P${t.priority}`;
                html += `
                <div class="tl-board-card${t.type === 'bug' ? ' bug-ticket' : ''}" onclick="openTicketDrawer('${t.id}')">
                    <div class="tl-board-card-title">${t.type === 'bug' ? '<span class="bug-label">BUG</span>' : ''}${escHtml(t.title)}${t.has_error ? ' <span class="ticket-status-badge error" title="测试失败或被拒绝">✗</span>' : t.has_warning ? ' <span class="ticket-status-badge warning" title="测试有警告">⚠</span>' : ''}</div>
                    <div class="tl-board-card-meta">
                        <span class="tag tag-priority-${t.priority}" style="font-size:10px;">${pLabel}</span>
                        ${t.module ? `<span class="tag tag-module" style="font-size:10px;">${escHtml(t.module)}</span>` : ''}
                        ${t.assigned_agent ? `<span class="tag tag-agent" style="font-size:10px;">${escHtml(t.assigned_agent)}</span>` : ''}
                    </div>
                    <div class="tl-board-card-req">${escHtml(t.req_title || '')}</div>
                </div>`;
            });
        }

        html += '</div></div>';
    }
    html += '</div>';
    container.innerHTML = html;
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
        paused: { text: '已暂停', cls: 'paused' },
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

        // 警告/错误徽章（叠加在圆点右上角）
        const stageBadge = stage.has_error ? '<span class="pl-stage-badge error" title="存在失败/被拒绝的工单">✗</span>'
                         : stage.has_warning ? '<span class="pl-stage-badge warning" title="存在测试警告">⚠</span>'
                         : '';

        html += `<div class="pl-stage ${cls}">
            <div class="pl-stage-header">
                <div class="pl-stage-dot-wrap">
                    <div class="pl-stage-dot">${dotContent}</div>${stageBadge}
                </div>
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
            // 警告/错误徽章
            const jobBadge = job.has_error ? '<span class="pl-job-badge error" title="存在失败/被拒绝的工单">✗</span>'
                           : job.has_warning ? '<span class="pl-job-badge warning" title="存在测试警告">⚠</span>'
                           : '';

            html += `<div class="pl-job-card ${isActive ? 'active' : ''} ${jobCls === 'pending' ? 'job-pending' : ''}" data-job-id="${job.id}" onclick="selectJob('${job.id}', '${stage.key}')">
                <div class="pl-job-header">
                    <span class="pl-job-status-wrap"><span class="pl-job-status-icon ${jobCls}">${jobIcon}</span>${jobBadge}</span>
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
                const stBadge = st.has_error ? ' <span class="pl-st-badge error" title="失败/被拒绝">✗</span>'
                              : st.has_warning ? ' <span class="pl-st-badge warning" title="测试有警告">⚠</span>'
                              : '';
                html += `<div class="pl-subtask-item">
                    <span class="pl-subtask-icon ${st.status}">${stIcon}</span>
                    <span class="pl-subtask-name">${escHtml(st.title)}${stBadge}</span>
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

    // 打开日志抽屉
    const panel = document.getElementById('pipelineJobLogPanel');
    const overlay = document.getElementById('jobDrawerOverlay');
    panel.classList.add('active');
    overlay.classList.add('active');

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

    // 从 Job 数据中查找真正的 ticket_id
    let ticketId = null;
    let job = null;
    if (currentPipelineData) {
        for (const stage of currentPipelineData.stages) {
            for (const j of (stage.jobs || [])) {
                if (j.id === jobId) { job = j; ticketId = j.ticket_id; break; }
            }
            if (job) break;
        }
    }

    try {
        // 如果是需求分析阶段的 Job，从需求日志获取
        let logs = [];
        if (stageKey === 'requirement_analysis' && currentPipelineData) {
            // 从 pipeline data 中的 logs 字段过滤
            logs = (currentPipelineData.logs || []).filter(l => l.agent_type === 'ProductAgent' || l.agent_type === 'System');
            logs = logs.reverse(); // 按时间正序
        } else if (ticketId) {
            // 用真正的 ticket_id 获取日志
            const data = await api(`/tickets/${ticketId}/logs`);
            logs = (data.logs || []).reverse();
        } else if (currentPipelineData) {
            // 多工单阶段（ticket_id 为 null），从 pipeline 全量日志按 Agent 类型过滤
            const stageAgentMap = {
                architecture: 'ArchitectAgent',
                development: 'DevAgent',
                testing: 'TestAgent',
                deployment: 'DeployAgent',
            };
            const targetAgent = stageAgentMap[stageKey];
            logs = (currentPipelineData.logs || []).filter(l =>
                !targetAgent || l.agent_type === targetAgent || l.agent_type === 'Orchestrator'
            );
            logs = logs.reverse();
        } else {
            // 预期 Job（还没执行），无日志
            entries.innerHTML = '<div class="log-panel-empty">该任务尚未执行，暂无日志</div>';
            return;
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
    const overlay = document.getElementById('jobDrawerOverlay');
    if (panel) panel.classList.remove('active');
    if (overlay) overlay.classList.remove('active');
    document.querySelectorAll('.pl-job-card').forEach(el => el.classList.remove('active'));
}

function switchJobLogTab(tab) {
    document.querySelectorAll('.job-log-tab').forEach(el => el.classList.remove('active'));
    event.target.classList.add('active');
    const entries = document.getElementById('jobLogEntries');

    if (tab === 'ai') {
        loadJobLLMLogs();
    } else if (tab === 'artifacts') {
        loadJobArtifacts();
    } else if (tab === 'commands') {
        loadJobCommands();
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

async function loadJobLLMLogs() {
    const entries = document.getElementById('jobLogEntries');
    entries.innerHTML = '<div class="log-panel-empty">加载 AI 对话记录...</div>';

    // 查找当前 Job 的 ticket_id 和所属阶段
    let ticketId = null;
    let reqId = null;
    let stageKey = null;
    if (currentPipelineData) {
        reqId = currentPipelineData.requirement?.id;
        for (const stage of currentPipelineData.stages) {
            for (const j of (stage.jobs || [])) {
                if (j.id === activeJobId) {
                    ticketId = j.ticket_id;
                    stageKey = stage.key;
                    break;
                }
            }
            if (stageKey) break;
        }
    }

    try {
        let conversations = [];
        if (stageKey === 'requirement_analysis' && reqId) {
            const data = await api(`/requirements/${reqId}/llm-logs`);
            conversations = data.conversations || [];
        } else if (ticketId) {
            const data = await api(`/tickets/${ticketId}/llm-logs`);
            conversations = data.conversations || [];
        } else if (reqId) {
            // 多工单阶段（ticket_id 为 null），按需求 ID 查询所有 LLM 日志
            const data = await api(`/requirements/${reqId}/llm-logs`);
            // 按阶段对应的 Agent 类型过滤
            const stageAgentMap = {
                architecture: 'ArchitectAgent',
                development: 'DevAgent',
                testing: 'TestAgent',
                deployment: 'DeployAgent',
            };
            const targetAgent = stageAgentMap[stageKey];
            conversations = (data.conversations || []).filter(c =>
                !targetAgent || c.agent_type === targetAgent
            );
        }

        if (conversations.length === 0) {
            entries.innerHTML = '<div class="log-panel-empty">暂无 AI 对话记录</div>';
            return;
        }

        let html = '';
        conversations.forEach((conv, i) => {
            const time = formatTime(conv.created_at) || '';
            const agent = conv.agent_type || 'System';
            const action = conv.action || '';
            const model = conv.model || '-';
            const inputTokens = conv.input_tokens || '-';
            const outputTokens = conv.output_tokens || '-';
            const duration = conv.duration_ms ? (conv.duration_ms / 1000).toFixed(1) + 's' : '-';
            const status = conv.status || 'success';
            const statusIcon = status === 'success' ? '✅' : (status === 'fallback' ? '⚠️' : '❌');

            // 解析 messages
            let messagesHtml = '';
            try {
                const msgs = JSON.parse(conv.messages || '[]');
                msgs.forEach(msg => {
                    const role = msg.role || 'user';
                    const roleLabel = role === 'system' ? '🔧 System' : (role === 'user' ? '👤 User' : '🤖 Assistant');
                    const roleClass = role === 'system' ? 'system' : (role === 'user' ? 'user' : 'assistant');
                    // 截断太长的 content
                    let content = msg.content || '';
                    const truncated = content.length > 2000;
                    if (truncated) content = content.slice(0, 2000);
                    messagesHtml += `<div class="llm-msg ${roleClass}">
                        <div class="llm-msg-role">${roleLabel}</div>
                        <pre class="llm-msg-content">${escHtml(content)}${truncated ? '\n... (已截断)' : ''}</pre>
                    </div>`;
                });
            } catch { messagesHtml = '<div class="llm-msg">无法解析消息</div>'; }

            // Response
            let responseText = conv.response || '';
            const resTruncated = responseText.length > 3000;
            if (resTruncated) responseText = responseText.slice(0, 3000);

            html += `<div class="llm-conv-card" onclick="toggleLLMConvDetail(this)">
                <div class="llm-conv-header">
                    <span class="llm-conv-num">#${conversations.length - i}</span>
                    <span class="llm-conv-agent">${escHtml(agent)}</span>
                    <span class="llm-conv-action">${escHtml(action)}</span>
                    <span class="llm-conv-meta">${statusIcon} ${escHtml(model)} | 输入 ${inputTokens} tokens | 输出 ${outputTokens} tokens | ${duration}</span>
                    <span class="llm-conv-time">${time}</span>
                </div>
                <div class="llm-conv-detail" style="display:none;">
                    <div class="llm-conv-section">
                        <h5>📤 Prompt Messages</h5>
                        ${messagesHtml}
                    </div>
                    <div class="llm-conv-section">
                        <h5>📥 LLM Response</h5>
                        <pre class="llm-response-content">${escHtml(responseText)}${resTruncated ? '\n... (已截断)' : ''}</pre>
                    </div>
                </div>
            </div>`;
        });

        entries.innerHTML = html;
    } catch (e) {
        entries.innerHTML = `<div class="log-panel-empty">加载失败: ${escHtml(e.message)}</div>`;
    }
}

function toggleLLMConvDetail(el) {
    const detail = el.querySelector('.llm-conv-detail');
    if (detail) {
        detail.style.display = detail.style.display === 'none' ? 'block' : 'none';
    }
}

async function loadJobArtifacts() {
    const entries = document.getElementById('jobLogEntries');
    entries.innerHTML = '<div class="log-panel-empty">加载产出文件...</div>';

    // 查找当前 Job 的 ticket_id
    let ticketId = null;
    let reqId = null;
    let stageKey = null;
    if (currentPipelineData) {
        reqId = currentPipelineData.requirement?.id;
        for (const stage of currentPipelineData.stages) {
            for (const j of (stage.jobs || [])) {
                if (j.id === activeJobId) {
                    ticketId = j.ticket_id;
                    stageKey = stage.key;
                    break;
                }
            }
            if (stageKey) break;
        }
    }

    try {
        let artifacts = [];
        if (stageKey === 'requirement_analysis' && reqId) {
            // 需求分析阶段：获取需求级产物
            const data = await api(`/requirements/${reqId}/artifacts`);
            artifacts = (data.artifacts || []).filter(a => !a.ticket_id);
        } else if (ticketId) {
            const data = await api(`/tickets/${ticketId}/artifacts`);
            artifacts = data.artifacts || [];
        } else if (reqId) {
            // 多工单阶段（ticket_id 为 null），按需求 ID 查询所有产出文件
            const data = await api(`/requirements/${reqId}/artifacts`);
            // 按阶段对应的产物类型过滤
            const stageArtifactTypes = {
                architecture: ['architecture'],
                development: ['code'],
                testing: ['test'],
                deployment: ['deploy_config'],
            };
            const targetTypes = stageArtifactTypes[stageKey] || [];
            artifacts = (data.artifacts || []).filter(a =>
                targetTypes.length === 0 || targetTypes.includes(a.type)
            );
        }

        if (artifacts.length === 0) {
            entries.innerHTML = '<div class="log-panel-empty">暂无产出文件</div>';
            return;
        }

        let html = '';
        artifacts.forEach(a => {
            const icon = getArtifactIcon(a.type);
            const time = formatDateTime(a.created_at);

            // 解析文件列表（从 content 中提取）
            let filesHtml = '';
            let contentPreview = '';
            try {
                const parsed = JSON.parse(a.content || '{}');
                // 提取代码文件列表
                if (parsed.files && Array.isArray(parsed.files)) {
                    filesHtml = '<div class="artifact-files"><h6>📁 文件列表</h6>';
                    parsed.files.forEach(f => {
                        const fileName = typeof f === 'string' ? f : (f.path || f.name || f.filename || JSON.stringify(f));
                        const lang = typeof f === 'object' ? (f.language || '') : '';
                        filesHtml += `<div class="artifact-file-item">
                            <span class="file-icon">📄</span>
                            <span class="file-name">${escHtml(fileName)}</span>
                            ${lang ? `<span class="file-lang">${escHtml(lang)}</span>` : ''}
                        </div>`;
                    });
                    filesHtml += '</div>';
                }
                contentPreview = JSON.stringify(parsed, null, 2);
            } catch {
                contentPreview = a.content || '';
            }

            // 截断过长内容
            const truncated = contentPreview.length > 5000;
            if (truncated) contentPreview = contentPreview.slice(0, 5000);

            html += `<div class="artifact-card" onclick="toggleArtifactExpand(this)">
                <div class="artifact-header">
                    <span class="artifact-icon">${icon}</span>
                    <span class="artifact-name">${escHtml(a.name || a.type)}</span>
                    <span class="artifact-type tag tag-module">${escHtml(a.type)}</span>
                    <span class="artifact-time">${time}</span>
                </div>
                ${filesHtml}
                <div class="artifact-content-expand" style="display:none;">
                    <pre class="artifact-raw-content">${escHtml(contentPreview)}${truncated ? '\n... (已截断)' : ''}</pre>
                </div>
            </div>`;
        });

        entries.innerHTML = html;
    } catch (e) {
        entries.innerHTML = `<div class="log-panel-empty">加载失败: ${escHtml(e.message)}</div>`;
    }
}

function toggleArtifactExpand(el) {
    const content = el.querySelector('.artifact-content-expand');
    if (content) {
        content.style.display = content.style.display === 'none' ? 'block' : 'none';
    }
}

function scrollToPipelineLogs() {
    const panel = document.getElementById('pipelineJobLogPanel');
    const overlay = document.getElementById('jobDrawerOverlay');
    if (panel) {
        panel.classList.add('active');
        overlay.classList.add('active');
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
                <span class="detail-label">开发分支</span>
                <span class="detail-value">${data.branch_name ? `<span class="req-branch-tag">🌿 ${escHtml(data.branch_name)}</span>` : '<span style="color:var(--text-muted);">未创建</span>'}</span>
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

        // 完成报告
        if (data.status === 'completed') {
            html += `
            <div class="drawer-section">
                <h4>📊 完成报告</h4>
                <div id="reqReportContent-${data.id}" style="font-size:12px; color:var(--text-muted); padding:8px;">加载中...</div>
            </div>`;
            // 异步加载报告
            setTimeout(() => loadRequirementReport(data.id), 100);
        }

        // 操作按钮
        let reqActions = '';
        if (data.status === 'submitted') {
            reqActions += `<button class="btn btn-primary btn-sm" onclick="decomposeReq('${data.id}')">🤖 AI 拆单</button>`;
            reqActions += `<button class="btn btn-sm" style="color:var(--error); margin-left:8px;" onclick="cancelReq('${data.id}')">✗ 取消</button>`;
        }
        if (data.status === 'completed' || data.status === 'decomposed' || data.status === 'in_progress') {
            reqActions += `<button class="btn btn-sm btn-primary" onclick="rerunReq('${data.id}')">🔄 重新执行</button>`;
        }
        reqActions += `<button class="btn btn-sm" style="color:var(--error); margin-left:8px;" onclick="deleteReq('${data.id}', '${escHtml(data.title).replace(/'/g, "\\'")}')">🗑️ 删除</button>`;
        html += `
            <div class="drawer-section">
                <h4>操作</h4>
                <div style="display:flex; gap:8px; flex-wrap:wrap;">${reqActions}</div>
            </div>`;

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

async function loadRequirementReport(reqId) {
    const container = document.getElementById(`reqReportContent-${reqId}`);
    if (!container) return;
    try {
        const data = await api(`/projects/${currentProjectId}/requirements/${reqId}/artifacts`);
        const report = (data.artifacts || []).find(a => a.type === 'report');
        if (report && report.content) {
            // 简单的 Markdown 渲染（表格、标题、列表）
            let html = report.content
                .replace(/^### (.*$)/gm, '<h5 style="margin:8px 0 4px;">$1</h5>')
                .replace(/^## (.*$)/gm, '<h4 style="margin:12px 0 6px; color:var(--text-primary);">$1</h4>')
                .replace(/^# (.*$)/gm, '<h3 style="margin:16px 0 8px; color:var(--text-primary);">$1</h3>')
                .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                .replace(/`(.*?)`/g, '<code style="background:var(--bg-hover); padding:1px 4px; border-radius:3px; font-size:11px;">$1</code>')
                .replace(/^- (.*$)/gm, '<div style="padding-left:12px;">• $1</div>')
                .replace(/\n/g, '<br>');
            container.innerHTML = `<div style="max-height:400px; overflow-y:auto; font-size:12px; line-height:1.7; color:var(--text-secondary);">${html}</div>`;
        } else {
            container.innerHTML = '<span style="color:var(--text-muted);">暂无报告（需求完成后自动生成）</span>';
        }
    } catch (e) {
        container.innerHTML = `<span style="color:var(--error);">加载失败: ${escHtml(e.message)}</span>`;
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

async function rerunReq(reqId) {
    if (!confirm('确定重新执行此需求？\n\n所有关联工单将重置为待启动状态，重新走开发流程。')) return;
    try {
        await api(`/projects/${currentProjectId}/requirements/${reqId}/rerun`, { method: 'POST' });
        showToast('需求已重置，工单将重新执行', 'success');
        closeDrawer();
        loadRequirements();
        refreshBoard();
    } catch (e) {
        showToast(`重新执行失败: ${e.message}`, 'error');
    }
}

async function deleteReq(reqId, title) {
    if (!confirm(`确定永久删除需求「${title}」？\n\n此操作将同时删除所有关联工单、日志和产出文件，且不可恢复！`)) return;
    try {
        await api(`/projects/${currentProjectId}/requirements/${reqId}/permanent`, { method: 'DELETE' });
        showToast(`需求「${title}」已永久删除`, 'success');
        closeDrawer();
        loadRequirements();
        loadRequirementFilter();
        refreshBoard();
    } catch (e) {
        showToast(`删除失败: ${e.message}`, 'error');
    }
}

// ==================== Agent 监控面板 ====================

let agentMonitorTimer = null;

function startAgentMonitor() {
    loadAgentMonitor();
    if (agentMonitorTimer) clearInterval(agentMonitorTimer);
    agentMonitorTimer = setInterval(loadAgentMonitor, 5000);
}

function stopAgentMonitor() {
    if (agentMonitorTimer) { clearInterval(agentMonitorTimer); agentMonitorTimer = null; }
}

async function loadAgentMonitor() {
    const grid = document.getElementById('agentMonitorGrid');
    if (!grid) return;

    try {
        const data = await fetch(`${API}/agents/status`).then(r => r.json());
        const agents = data.agents || {};
        const processingCount = data.processing_count || 0;

        const agentIcons = {
            'ProductAgent': '📋',
            'ArchitectAgent': '🏗️',
            'DevAgent': '💻',
            'TestAgent': '🧪',
            'ReviewAgent': '🔍',
            'DeployAgent': '🚀',
        };

        const agentRoles = {
            'ProductAgent': '产品验收',
            'ArchitectAgent': '架构设计',
            'DevAgent': '代码开发',
            'TestAgent': '测试执行',
            'ReviewAgent': '代码审查',
            'DeployAgent': '部署发布',
        };

        let html = `<div style="display:flex; gap:8px; margin-bottom:16px; flex-wrap:wrap;">
            <div class="agent-summary-card">
                <span style="font-size:20px;">⚡</span>
                <span>处理中: <strong>${processingCount}</strong></span>
            </div>
        </div>`;

        html += '<div class="agent-monitor-grid">';
        for (const [name, info] of Object.entries(agents)) {
            const icon = agentIcons[name] || '🤖';
            const role = agentRoles[name] || name;
            const isWorking = info.status === 'working';
            const statusClass = isWorking ? 'agent-working' : 'agent-idle';
            const statusText = isWorking ? '工作中' : '空闲';
            const completed = info.completed_count || 0;
            const errors = info.error_count || 0;

            let taskInfo = '';
            if (isWorking && info.ticket_title) {
                const elapsed = info.started_at ? Math.round((Date.now() - new Date(info.started_at).getTime()) / 1000) : 0;
                taskInfo = `
                    <div class="agent-task-info">
                        <div class="agent-task-title">${escHtml(info.ticket_title)}</div>
                        <div class="agent-task-action">${escHtml(info.action || '')} · ${elapsed}s</div>
                    </div>`;
            }

            html += `
                <div class="agent-card ${statusClass}">
                    <div class="agent-card-header">
                        <span class="agent-icon">${icon}</span>
                        <div>
                            <div class="agent-name">${name}</div>
                            <div class="agent-role">${role}</div>
                        </div>
                        <span class="agent-status-dot ${statusClass}"></span>
                    </div>
                    <div class="agent-status-text">${statusText}</div>
                    ${taskInfo}
                    <div class="agent-stats-row">
                        <span>✅ 完成 ${completed}</span>
                        <span>❌ 异常 ${errors}</span>
                    </div>
                </div>`;
        }
        html += '</div>';

        grid.innerHTML = html;
    } catch (e) {
        grid.innerHTML = `<div class="empty-state"><p>加载失败: ${escHtml(e.message)}</p></div>`;
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

    const PREVIEW_LIMIT = 160;
    const isLong = detail.length > PREVIEW_LIMIT;
    const logId = 'log-' + (log.id || Math.random().toString(36).slice(2));

    let messageHtml;
    if (isLong) {
        messageHtml = `<div class="log-message log-message-collapsible" id="${logId}">
            <div class="log-message-preview">${escHtml(detail)}</div>
            <span class="log-expand-link" onclick="toggleLogMessage('${logId}')">展开 ▼</span>
        </div>`;
    } else {
        messageHtml = `<div class="log-message">${escHtml(detail)}</div>`;
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
            ${messageHtml}
        </div>`;
}

function toggleLogMessage(logId) {
    const el = document.getElementById(logId);
    if (!el) return;
    const preview = el.querySelector('.log-message-preview');
    const link = el.querySelector('.log-expand-link');
    if (!preview || !link) return;
    const isExpanded = preview.classList.contains('expanded');
    if (isExpanded) {
        preview.classList.remove('expanded');
        link.textContent = '展开 ▼';
    } else {
        preview.classList.add('expanded');
        link.textContent = '收起 ▲';
    }
}

// ==================== SSE 实时推送 ====================

let _sseRefreshTimer = null;
function _debouncedSSERefresh() {
    if (_sseRefreshTimer) clearTimeout(_sseRefreshTimer);
    _sseRefreshTimer = setTimeout(() => {
        refreshBoard();
        loadTicketList();
        loadTicketGraph();
        if (currentPipelineReqId) loadPipeline(currentPipelineReqId);
    }, 800);
}

function connectSSE(projectId) {
    disconnectSSE();
    try {
        eventSource = new EventSource(`${API}/projects/${projectId}/events`);

        eventSource.addEventListener('ticket_status_changed', (e) => {
            const data = JSON.parse(e.data);
            console.log('[SSE] ticket_status_changed:', data);
            _debouncedSSERefresh();
            appendLogEntry({id: 'ts-' + Date.now(), agent_type: data.agent || 'Orchestrator', action: 'status_change', from_status: data.from, to_status: data.to, detail: JSON.stringify({message: `工单状态: ${data.from} → ${data.to}`}), level: 'info', created_at: new Date().toISOString(), ticket_id: data.ticket_id});
        });

        eventSource.addEventListener('requirement_decomposed', (e) => {
            const data = JSON.parse(e.data);
            console.log('[SSE] requirement_decomposed:', data);
            showToast(`需求已拆分为 ${data.ticket_count} 个工单`, 'success');
            appendLogEntry({id: 'rd-' + Date.now(), agent_type: 'ProductAgent', action: 'decompose', detail: JSON.stringify({message: `需求已拆分为 ${data.ticket_count} 个工单`}), level: 'info', created_at: new Date().toISOString()});
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

        // SSE: 需求状态变更（暂停/恢复/关闭）
        eventSource.addEventListener('requirement_status_changed', (e) => {
            const data = JSON.parse(e.data);
            console.log('[SSE] requirement_status_changed:', data);
            loadRequirements();
            refreshBoard();
            const statusLabels = {paused: '已暂停', in_progress: '已恢复', cancelled: '已关闭'};
            const label = statusLabels[data.to] || data.to;
            appendLogEntry({
                agent_type: 'ChatAssistant',
                action: 'update_status',
                detail: JSON.stringify({message: `需求「${data.title}」${label}`}),
                level: data.to === 'cancelled' ? 'warn' : 'info',
                created_at: new Date().toISOString(),
            });
        });

        // SSE: 后端日志实时推送
        eventSource.addEventListener('log_added', (e) => {
            const data = JSON.parse(e.data);
            console.log('[SSE] log_added:', data);
            appendLogEntry(data);
            // 实时追加到工单对话 Feed
            if (chatMode === 'job' && data.ticket_id) {
                appendToTicketFeed(data);
            }
        });

        // SSE: CI/CD 构建事件
        eventSource.addEventListener('ci_build_started', (e) => {
            const data = JSON.parse(e.data);
            console.log('[SSE] ci_build_started:', data);
            const labels = {develop_build: 'Develop 构建', master_build: 'Master 构建', deploy: '部署'};
            const msg = `${labels[data.build_type] || data.build_type} 已开始`;
            showToast(msg, 'info');
            appendLogEntry({id: 'ci-' + Date.now(), agent_type: 'CI/CD', action: data.build_type, detail: JSON.stringify({message: msg}), level: 'info', created_at: new Date().toISOString()});
            if (document.getElementById('tab-cicd')?.classList.contains('active')) loadCICD();
        });

        eventSource.addEventListener('ci_build_completed', (e) => {
            const data = JSON.parse(e.data);
            console.log('[SSE] ci_build_completed:', data);
            const labels = {develop_build: 'Develop 构建', master_build: 'Master 构建', deploy: '部署'};
            const ok = data.status === 'success';
            const msg = `${ok ? '✅' : '❌'} ${labels[data.build_type] || data.build_type} ${ok ? '成功' : '失败'}`;
            showToast(msg, ok ? 'success' : 'error');
            appendLogEntry({id: 'ci-' + Date.now(), agent_type: 'CI/CD', action: data.build_type, detail: JSON.stringify({message: msg}), level: ok ? 'info' : 'error', created_at: new Date().toISOString()});
            if (document.getElementById('tab-cicd')?.classList.contains('active')) loadCICD();
        });

        eventSource.addEventListener('ci_build_failed', (e) => {
            const data = JSON.parse(e.data);
            console.log('[SSE] ci_build_failed:', data);
            const labels = {develop_build: 'Develop 构建', master_build: 'Master 构建', deploy: '部署'};
            const msg = `❌ ${labels[data.build_type] || data.build_type} 失败: ${data.error_message || ''}`;
            showToast(msg, 'error');
            appendLogEntry({id: 'ci-' + Date.now(), agent_type: 'CI/CD', action: data.build_type, detail: JSON.stringify({message: msg}), level: 'error', created_at: new Date().toISOString()});
            if (document.getElementById('tab-cicd')?.classList.contains('active')) loadCICD();
        });

        eventSource.addEventListener('ci_branch_merged', (e) => {
            const data = JSON.parse(e.data);
            console.log('[SSE] ci_branch_merged:', data);
            showToast(`🔀 ${data.source} → ${data.target} 合并成功`, 'success');
        });

        // BUG 相关 SSE 事件
        eventSource.addEventListener('bug_created', (e) => {
            const data = JSON.parse(e.data);
            if (document.getElementById('tab-bugs')?.classList.contains('active')) loadBugs();
        });

        eventSource.addEventListener('bug_status_changed', (e) => {
            const data = JSON.parse(e.data);
            const statusLabels = { open:'待处理', in_dev:'修复中', in_test:'测试中', fixed:'已修复' };
            const label = statusLabels[data.status] || data.status;
            // 更新卡片状态（不重新渲染整个列表，避免闪烁）
            const card = document.querySelector(`.bug-card[data-bug-id="${data.bug_id}"]`);
            if (card) {
                const badge = card.querySelector('.bug-status-badge');
                const statusColors = { open:'var(--danger,#ea4a5a)', in_dev:'var(--warning,#f0a500)', in_test:'var(--primary)', fixed:'var(--success,#34d058)' };
                const color = statusColors[data.status] || 'var(--text-muted)';
                if (badge) {
                    badge.textContent = label;
                    badge.style.cssText = `background:${color}20;color:${color};border:1px solid ${color}40;`;
                }
            } else if (document.getElementById('tab-bugs')?.classList.contains('active')) {
                loadBugs();
            }
            appendLogEntry({
                agent_type: 'System',
                action: 'bug_status',
                detail: JSON.stringify({ message: `BUG 状态变更 → ${label}${data.reason ? '：' + data.reason : ''}` }),
                level: 'info',
                created_at: new Date().toISOString(),
            });
        });

        eventSource.addEventListener('bug_fixed', (e) => {
            const data = JSON.parse(e.data);
            showToast(`✅ BUG「${data.title || data.bug_id}」修复完成${data.version_id ? '，已并入版本' : ''}`, 'success');
            if (document.getElementById('tab-bugs')?.classList.contains('active')) loadBugs();
        });

        // agent_working 时若是 BUG 修复，在 BUG 卡片上显示进度
        eventSource.addEventListener('agent_working', (e) => {
            const data = JSON.parse(e.data);
            if (data.bug_id) {
                const agentLabels = { DevAgent:'🔧 DevAgent 修复中', TestAgent:'🧪 TestAgent 测试中' };
                const card = document.querySelector(`.bug-card[data-bug-id="${data.bug_id}"]`);
                if (card) {
                    let progressEl = card.querySelector('.bug-progress');
                    if (!progressEl) {
                        progressEl = document.createElement('div');
                        progressEl.className = 'bug-progress';
                        card.querySelector('.bug-card-actions')?.before(progressEl);
                    }
                    progressEl.innerHTML = `<span class="bug-progress-text">⏳ ${agentLabels[data.agent] || data.agent + ' 处理中'}</span>`;
                }
            }
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

// ==================== Agent 配置 ====================

let agentRegistryCache = null;

/** 加载 Agent 列表到设置页 */
async function loadAgentList() {
    const container = document.getElementById('agentListSettings');
    if (!container) return;

    try {
        if (!agentRegistryCache) {
            const data = await api('/agents');
            agentRegistryCache = data.agents || [];
        }

        if (agentRegistryCache.length === 0) {
            container.innerHTML = '<div style="text-align:center; padding:20px; color:var(--text-muted); font-size:13px;">暂无 Agent 配置</div>';
            return;
        }

        container.innerHTML = agentRegistryCache.map(agent => `
            <div class="agent-item" onclick="showAgentDetail('${escHtml(agent.name)}')">
                <div class="agent-icon">${agent.icon || '🤖'}</div>
                <div class="agent-info">
                    <div class="agent-name">${escHtml(agent.name)}</div>
                    <div class="agent-desc">${escHtml(agent.description)}</div>
                </div>
                <span class="tag tag-success">${agent.enabled ? '启用' : '停用'}</span>
            </div>
        `).join('');
    } catch (e) {
        container.innerHTML = '<div style="text-align:center; padding:20px; color:var(--error); font-size:13px;">加载 Agent 列表失败</div>';
    }
}

/** 高亮提示词中的变量占位符 {xxx} */
function highlightPromptVars(text) {
    return escHtml(text).replace(/\{(\w+)\}/g, '<span class="prompt-var">{$1}</span>');
}

/** 显示 Agent 详情弹窗 */
function showAgentDetail(agentName) {
    if (!agentRegistryCache) return;
    const agent = agentRegistryCache.find(a => a.name === agentName);
    if (!agent) return;

    const titleEl = document.getElementById('agentDetailTitle');
    const bodyEl = document.getElementById('agentDetailBody');

    titleEl.textContent = `${agent.icon || '🤖'} ${agent.name}`;

    let html = '';

    // 头部信息
    html += `
    <div class="agent-detail-header">
        <div class="agent-detail-icon">${agent.icon || '🤖'}</div>
        <div class="agent-detail-meta">
            <h3>${escHtml(agent.name)}</h3>
            <p>角色: ${escHtml(agent.role || '')} · ${escHtml(agent.description)}</p>
        </div>
    </div>`;

    // 参数标签
    html += `
    <div class="agent-params">
        <div class="agent-param-chip">
            <span class="param-label">Temperature</span>
            <span class="param-value">${agent.temperature ?? '-'}</span>
        </div>
        <div class="agent-param-chip">
            <span class="param-label">Max Tokens</span>
            <span class="param-value">${agent.max_tokens ?? '-'}</span>
        </div>
        <div class="agent-param-chip">
            <span class="param-label">状态</span>
            <span class="param-value">${agent.enabled ? '✅ 启用' : '⏸ 停用'}</span>
        </div>
    </div>`;

    // 提示词列表
    if (agent.prompts && agent.prompts.length > 0) {
        agent.prompts.forEach((prompt, idx) => {
            const expanded = idx === 0 ? 'expanded' : '';
            const displayStyle = idx === 0 ? '' : 'style="display:none;"';
            html += `
            <div class="agent-prompt-section">
                <div class="agent-prompt-label" onclick="togglePromptSection(this)">
                    <span class="prompt-arrow ${expanded}">▶</span>
                    <span class="prompt-action-tag">${escHtml(prompt.action || '')}</span>
                    ${escHtml(prompt.label || '提示词')}
                </div>
                <div class="agent-prompt-code" ${displayStyle}>${highlightPromptVars(prompt.template || '（无模板）')}</div>
            </div>`;
        });
    }

    // 静态规则（ReviewAgent 专属）
    if (agent.static_rules && agent.static_rules.length > 0) {
        html += `
        <div class="agent-static-rules">
            <h4>📏 静态审查规则</h4>
            <div class="agent-rules-grid">
                ${agent.static_rules.map(rule => `<div class="agent-rule-chip">${escHtml(rule)}</div>`).join('')}
            </div>
        </div>`;
    }

    bodyEl.innerHTML = html;
    openModal('agentDetailModal');
}

/** 切换提示词展开/折叠 */
function togglePromptSection(labelEl) {
    const arrow = labelEl.querySelector('.prompt-arrow');
    const codeBlock = labelEl.nextElementSibling;
    if (!codeBlock) return;

    const isExpanded = arrow.classList.toggle('expanded');
    codeBlock.style.display = isExpanded ? '' : 'none';
}

// ==================== 模态框 ====================

function openModal(id) {
    document.getElementById(id).classList.add('active');
}

function closeModal(id) {
    document.getElementById(id).classList.remove('active');
}

// 点击 overlay 不关闭（只通过 ESC 或关闭按钮关闭）
// document.querySelectorAll('.modal-overlay').forEach(overlay => {
//     overlay.addEventListener('click', (e) => {
//         if (e.target === overlay) {
//             overlay.classList.remove('active');
//         }
//     });
// });

// ESC 关闭
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay.active').forEach(m => m.classList.remove('active'));
        closeDrawer();
        closeJobLogPanel();
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

    // 拖拽调整高度（Docking 模式）
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
        const wrapper = panel.closest('.content-dock-wrapper');
        const wrapperH = wrapper ? wrapper.offsetHeight : window.innerHeight * 0.8;
        const maxH = wrapperH - 100; // 内容区至少保留 100px
        const diff = startY - e.clientY;
        const newH = Math.min(Math.max(startH + diff, 60), maxH);
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

    // 初始化服务健康检查
    initServerHealthCheck();
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
    let detailParsed = {};
    try {
        detailParsed = JSON.parse(log.detail || '{}');
        message = detailParsed.message || '';
    } catch {
        message = log.detail || '';
    }

    const level = log.level || 'info';
    const agent = log.agent_type || 'System';
    const action = log.action || '';
    const time = formatTime(log.created_at) || new Date().toLocaleTimeString('zh-CN', {hour12: false});
    const isLlmCall = action === 'llm_call';

    // 构建状态变化
    let statusHtml = '';
    if (log.from_status && log.to_status) {
        statusHtml = `<span class="log-entry-status">${getStatusLabel(log.from_status)} <span class="arrow">→</span> ${getStatusLabel(log.to_status)}</span>`;
    }

    // LLM 调用的额外标签（tokens + 耗时）
    let llmBadgesHtml = '';
    if (isLlmCall && detailParsed.duration_ms) {
        const dur = detailParsed.duration_ms;
        const inT = detailParsed.input_tokens || 0;
        const outT = detailParsed.output_tokens || 0;
        llmBadgesHtml = `
            <span class="log-entry-badge llm-dur">${dur >= 1000 ? (dur / 1000).toFixed(1) + 's' : dur + 'ms'}</span>
            <span class="log-entry-badge llm-tokens">${inT}→${outT}</span>
        `;
    }

    const div = document.createElement('div');
    div.className = `log-entry new ${level}${isLlmCall ? ' llm-call' : ''}`;
    if (log.id) div.dataset.logId = log.id;
    div.innerHTML = `
        <span class="log-entry-time">${escHtml(time)}</span>
        <span class="log-entry-level ${level}">${isLlmCall ? '🤖' : level.toUpperCase()}</span>
        <span class="log-entry-agent">${escHtml(agent)}</span>
        <span class="log-entry-action">${escHtml(isLlmCall ? 'AI调用' : action)}</span>
        ${statusHtml}
        ${llmBadgesHtml}
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
    in_progress: '进行中', paused: '已暂停', completed: '已完成', cancelled: '已取消',
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
        prd: '📄', architecture: '🏗️', code: '💻', test: '🧪', deploy_config: '🚀', screenshot: '🖼️',
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


// ==================== 配置 Tab: 执行命令 ====================

async function loadJobCommands() {
    const entries = document.getElementById('jobLogEntries');
    entries.innerHTML = '<div class="log-panel-empty">加载执行命令...</div>';

    let ticketId = null;
    let reqId = null;
    let stageKey = null;
    if (currentPipelineData) {
        reqId = currentPipelineData.requirement?.id;
        for (const stage of currentPipelineData.stages) {
            for (const j of (stage.jobs || [])) {
                if (j.id === activeJobId) {
                    ticketId = j.ticket_id;
                    stageKey = stage.key;
                    break;
                }
            }
            if (stageKey) break;
        }
    }

    try {
        let commands = [];
        if (ticketId) {
            const data = await api(`/tickets/${ticketId}/commands`);
            commands = data.commands || [];
        } else if (reqId) {
            const data = await api(`/requirements/${reqId}/commands`);
            commands = (data.commands || []).filter(c => {
                if (!stageKey) return true;
                const agentMap = {
                    'requirement_analysis': 'ProductAgent',
                    'architecture': 'ArchitectAgent',
                    'development': 'DevAgent',
                    'testing': 'TestAgent',
                    'deployment': 'DeployAgent',
                };
                return c.agent_type === agentMap[stageKey];
            });
        }

        if (commands.length === 0) {
            entries.innerHTML = '<div class="log-panel-empty">暂无执行命令记录</div>';
            return;
        }

        const cmdTypeIcons = {
            write_file: '📝',
            git_commit: '💾',
            git_push: '🚀',
            agent_invoke: '🤖',
            llm_call: '🧠',
        };

        const cmdTypeLabels = {
            write_file: '写入文件',
            git_commit: 'Git 提交',
            git_push: 'Git 推送',
            agent_invoke: 'Agent 调用',
            llm_call: 'LLM 调用',
        };

        let html = '<div class="cmd-list">';
        let currentAction = '';
        for (const cmd of commands) {
            // 按 action 分组
            const actionLabel = `${cmd.agent_type} → ${cmd.action}`;
            if (actionLabel !== currentAction) {
                if (currentAction) html += '</div>';
                currentAction = actionLabel;
                html += `<div class="cmd-group">
                    <div class="cmd-group-header">
                        <span class="cmd-group-icon">🤖</span>
                        <span class="cmd-group-title">${actionLabel}</span>
                    </div>`;
            }

            const icon = cmdTypeIcons[cmd.command_type] || '⚡';
            const typeLabel = cmdTypeLabels[cmd.command_type] || cmd.command_type;
            const statusClass = cmd.status === 'success' ? 'cmd-success' : 'cmd-fail';
            const duration = cmd.duration_ms ? `(${cmd.duration_ms}ms)` : '';

            html += `<div class="cmd-item ${statusClass}">
                <span class="cmd-step">#${cmd.step_order + 1}</span>
                <span class="cmd-icon">${icon}</span>
                <span class="cmd-type">${typeLabel}</span>
                <span class="cmd-text">${escapeHtml(cmd.command)}</span>
                <span class="cmd-duration">${duration}</span>
                <span class="cmd-status-dot ${statusClass}"></span>
            </div>`;
        }
        if (currentAction) html += '</div>';
        html += '</div>';

        entries.innerHTML = html;
    } catch (err) {
        entries.innerHTML = `<div class="log-panel-empty">加载失败: ${err.message}</div>`;
    }
}


// ==================== 仓库文件浏览 ====================

// 记录当前激活的文件树节点
let _activeTreeItem = null;

async function loadRepoTree() {
    const container = document.getElementById('repoTree');
    if (!currentProjectId) {
        container.innerHTML = '<div class="empty-state"><div class="emoji">📂</div><p>请先选择项目</p></div>';
        return;
    }

    container.innerHTML = '<div class="empty-state"><div class="emoji">⏳</div><p>加载中...</p></div>';
    _activeTreeItem = null;

    try {
        const tree = await api(`/projects/${currentProjectId}/git/tree`);

        // 显示当前分支
        const branchTag = document.getElementById('repoBranchTag');
        if (branchTag && tree.current_branch) {
            branchTag.textContent = '🌿 ' + tree.current_branch;
        }

        // 更新分支选择器
        loadRepoBranchSelector(tree.current_branch);

        if (!tree.children || tree.children.length === 0) {
            container.innerHTML = '<div class="empty-state"><div class="emoji">📂</div><p>仓库为空或尚未初始化</p></div>';
            return;
        }
        container.innerHTML = renderFileTree(tree.children, 0);
    } catch (err) {
        container.innerHTML = `<div class="empty-state"><div class="emoji">❌</div><p>加载失败: ${err.message}</p></div>`;
    }
}

async function loadRepoBranchSelector(currentBranch) {
    const select = document.getElementById('repoBranchSelect');
    if (!select || !currentProjectId) return;
    try {
        const data = await api(`/projects/${currentProjectId}/git/branches`);
        const branches = data.branches || [];
        select.innerHTML = branches.map(b =>
            `<option value="${escapeHtml(b)}" ${b === currentBranch ? 'selected' : ''}>🌿 ${escapeHtml(b)}</option>`
        ).join('');
    } catch {}
}

async function switchRepoBranch(branch) {
    if (!branch || !currentProjectId) return;
    try {
        await api(`/projects/${currentProjectId}/git/switch-branch`, {
            method: 'POST', body: { branch }
        });
        showToast(`已切换到分支: ${branch}`, 'success');
        loadRepoTree();
    } catch (e) {
        showToast(`切换分支失败: ${e.message}`, 'error');
    }
}

function renderFileTree(nodes, depth) {
    let html = '';
    // 目录在前，文件在后
    const dirs = nodes.filter(n => n.type === 'directory');
    const files = nodes.filter(n => n.type !== 'directory');
    const sorted = [...dirs, ...files];

    for (const node of sorted) {
        const indentStyle = depth > 0 ? `style="--depth:${depth}"` : '';
        if (node.type === 'directory') {
            const hasChildren = node.children && node.children.length > 0;
            const childCount = hasChildren ? node.children.length : 0;
            html += `<div class="tree-item tree-dir" ${indentStyle} onclick="toggleTreeDir(this)" data-depth="${depth}">
                <span class="tree-arrow">${hasChildren ? '▾' : '▸'}</span>
                <span class="tree-icon">📁</span>
                <span class="tree-name">${escapeHtml(node.name)}</span>
                ${childCount > 0 ? `<span class="tree-count">${childCount}</span>` : ''}
            </div>`;
            if (hasChildren) {
                html += `<div class="tree-children">${renderFileTree(node.children, depth + 1)}</div>`;
            }
        } else {
            const ext = node.name.split('.').pop().toLowerCase();
            const icon = getFileIcon(ext);
            const size = node.size ? formatFileSize(node.size) : '';
            html += `<div class="tree-item tree-file" ${indentStyle} data-path="${escapeHtml(node.path)}" data-depth="${depth}" onclick="viewRepoFile('${escapeHtml(node.path)}', this)">
                <span class="tree-arrow"> </span>
                <span class="tree-icon">${icon}</span>
                <span class="tree-name">${escapeHtml(node.name)}</span>
                <span class="tree-size">${size}</span>
            </div>`;
        }
    }
    return html;
}

function toggleTreeDir(el) {
    const children = el.nextElementSibling;
    if (children && children.classList.contains('tree-children')) {
        const collapsed = children.classList.toggle('collapsed');
        const arrow = el.querySelector('.tree-arrow');
        const icon = el.querySelector('.tree-icon');
        if (arrow) arrow.textContent = collapsed ? '▸' : '▾';
        if (icon) icon.textContent = collapsed ? '📁' : '📂';
    }
}

async function viewRepoFile(path, itemEl) {
    // 激活选中态
    if (_activeTreeItem) _activeTreeItem.classList.remove('active');
    if (itemEl) { itemEl.classList.add('active'); _activeTreeItem = itemEl; }

    const previewPanel = document.getElementById('repoFilePreview');
    const fileName = path.split('/').pop();
    const ext = fileName.includes('.') ? fileName.split('.').pop().toLowerCase() : '';

    previewPanel.innerHTML = `
        <div class="file-preview-header">
            <div class="file-preview-path">
                <span class="file-preview-icon">${getFileIcon(ext)}</span>
                <span title="${escapeHtml(path)}">${escapeHtml(path)}</span>
            </div>
            <div class="file-preview-actions">
                <button class="icon-btn" onclick="copyFileContent()" title="复制内容">⎘ 复制</button>
            </div>
        </div>
        <div class="file-info-bar" id="fileInfoBar">
            <span class="file-info-loading">⏳ 加载中...</span>
        </div>
        <div class="file-code-wrap" id="fileCodeWrap">
            <div class="file-loading">加载中...</div>
        </div>
    `;

    const codeWrap = document.getElementById('fileCodeWrap');
    const infoBar = document.getElementById('fileInfoBar');

    try {
        const data = await api(`/projects/${currentProjectId}/git/file?path=${encodeURIComponent(path)}`);
        const content = data.content || '';
        const size = data.size ? formatFileSize(data.size) : '';
        const lines = content.split('\n');
        const lineCount = lines.length;

        // 更新信息栏
        infoBar.innerHTML = `
            <span class="file-info-badge">${escapeHtml(ext || 'txt')}</span>
            ${size ? `<span class="file-info-item"><span class="file-info-label">大小</span>${size}</span>` : ''}
            <span class="file-info-item"><span class="file-info-label">行数</span>${lineCount}</span>
            <span class="file-info-item"><span class="file-info-label">编码</span>UTF-8</span>
        `;

        // 判断是否为图片
        const imgExts = ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico', 'bmp'];
        if (imgExts.includes(ext)) {
            codeWrap.innerHTML = `<div class="file-preview-img"><img src="/projects/${currentProjectId}/git/file-raw?path=${encodeURIComponent(path)}" alt="${escapeHtml(fileName)}" style="max-width:100%;max-height:500px;border-radius:6px;"></div>`;
            return;
        }

        // Markdown 渲染预览
        if (ext === 'md' || ext === 'markdown') {
            renderMarkdown(codeWrap, content, infoBar);
            // 预览/源码切换按钮
            const actions = document.querySelector('.file-preview-actions');
            if (actions && !actions.querySelector('.md-toggle')) {
                const toggleBtn = document.createElement('button');
                toggleBtn.className = 'icon-btn md-toggle';
                toggleBtn.title = '切换源码/预览';
                toggleBtn.textContent = '< > 源码';
                toggleBtn.onclick = () => toggleMarkdownView(codeWrap, content, ext, toggleBtn);
                actions.prepend(toggleBtn);
            }
            return;
        }

        // 超大文件提示
        if (lineCount > 2000) {
            codeWrap.innerHTML = `<div class="file-too-large">⚠️ 文件过大（${lineCount} 行），仅显示前 500 行</div>`;
            renderCodeWithLineNumbers(codeWrap, lines.slice(0, 500).join('\n'), ext, path);
            return;
        }

        renderCodeWithLineNumbers(codeWrap, content, ext, path);
    } catch (err) {
        codeWrap.innerHTML = `<div class="file-error">❌ 加载失败: ${escapeHtml(err.message)}</div>`;
        infoBar.innerHTML = `<span class="file-info-error">错误: ${escapeHtml(err.message)}</span>`;
    }
}

function renderMarkdown(container, content, infoBar) {
    if (!window.marked) {
        // fallback: 当 CDN 未加载时退化为代码展示
        renderCodeWithLineNumbers(container, content, 'md');
        return;
    }

    // 配置 marked：代码块自动用 hljs 高亮
    marked.setOptions({
        highlight: function(code, lang) {
            if (lang && window.hljs) {
                try {
                    return hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
                } catch {}
            }
            return window.hljs ? hljs.highlightAuto(code).value : code;
        },
        breaks: true,
        gfm: true,
    });

    let html = '';
    try {
        html = marked.parse(content);
    } catch (e) {
        html = `<p style="color:#f87171">Markdown 渲染失败: ${escapeHtml(e.message)}</p>`;
    }

    container.innerHTML = `<div class="md-preview">${html}</div>`;
    container.dataset.mode = 'preview';

    // 给渲染后的代码块补上 hljs 样式类
    container.querySelectorAll('pre code').forEach(block => {
        if (window.hljs) hljs.highlightElement(block);
    });
}

function toggleMarkdownView(container, content, ext, btn) {
    const mode = container.dataset.mode || 'preview';
    if (mode === 'preview') {
        // 切换到源码模式
        renderCodeWithLineNumbers(container, content, ext);
        container.dataset.mode = 'source';
        btn.textContent = '👁 预览';
        btn.classList.add('active');
    } else {
        // 切换回预览模式
        renderMarkdown(container, content);
        container.dataset.mode = 'preview';
        btn.textContent = '< > 源码';
        btn.classList.remove('active');
    }
}

function renderCodeWithLineNumbers(container, content, ext, path) {
    // 尝试语法高亮
    let highlighted = '';
    const langMap = {
        py: 'python', js: 'javascript', ts: 'typescript', html: 'html', css: 'css',
        md: 'markdown', json: 'json', yml: 'yaml', yaml: 'yaml', toml: 'ini',
        sh: 'bash', bash: 'bash', sql: 'sql', dockerfile: 'dockerfile',
        go: 'go', rs: 'rust', java: 'java', cpp: 'cpp', c: 'c', rb: 'ruby',
        php: 'php', swift: 'swift', kt: 'kotlin', xml: 'xml', ini: 'ini',
    };
    const lang = langMap[ext] || '';

    try {
        if (lang && window.hljs) {
            highlighted = hljs.highlight(content, { language: lang, ignoreIllegals: true }).value;
        } else if (window.hljs) {
            highlighted = hljs.highlightAuto(content, Object.values(langMap)).value;
        }
    } catch (e) {
        highlighted = '';
    }

    const lines = content.split('\n');
    const highlightedLines = highlighted ? highlighted.split('\n') : null;

    // 生成行号 + 代码
    const gutterHtml = lines.map((_, i) =>
        `<span class="line-num">${i + 1}</span>`
    ).join('\n');

    const codeHtml = highlightedLines
        ? highlightedLines.map(l => `<span class="code-line">${l}</span>`).join('\n')
        : lines.map(l => `<span class="code-line">${escapeHtml(l)}</span>`).join('\n');

    container.innerHTML = `
        <div class="code-block" data-raw="${escapeHtml(content)}">
            <div class="code-gutter">${gutterHtml}</div>
            <pre class="code-content hljs"><code>${codeHtml}</code></pre>
        </div>
    `;
}

function copyFileContent() {
    const block = document.querySelector('.code-block');
    if (!block) return;
    const raw = block.getAttribute('data-raw') || '';
    navigator.clipboard.writeText(raw).then(() => {
        showToast('已复制到剪贴板', 'success');
    }).catch(() => {
        showToast('复制失败，请手动选择', 'warning');
    });
}

/**
 * 从产出文件点击文件链接 → 切换分支 → 跳转到仓库文件页并打开预览
 */
async function openArtifactFile(filePath, branch) {
    // 关闭工单详情抽屉
    document.getElementById('ticketDrawer')?.classList.remove('open');

    // 如果有分支名，先切换分支
    if (branch && currentProjectId) {
        try {
            await api(`/projects/${currentProjectId}/git/switch-branch`, {
                method: 'POST', body: { branch }
            });
        } catch (e) {
            console.warn('切换分支失败:', e.message);
        }
    }

    // 切换到仓库文件 tab（会重新加载文件树和分支选择器）
    switchTab('repo');
    // 等待 tab 渲染后打开文件预览
    setTimeout(() => viewRepoFile(filePath, null), 400);
}

async function toggleGitLogPanel() {
    const panel = document.getElementById('gitLogPanel');
    const btn = document.getElementById('gitLogToggleBtn');
    const workspace = panel.closest('.repo-workspace');
    const isHidden = panel.style.display === 'none';
    panel.style.display = isHidden ? 'flex' : 'none';
    if (workspace) workspace.classList.toggle('with-log', isHidden);
    if (btn) btn.classList.toggle('active', isHidden);
    if (isHidden) loadGitLog();
}

async function loadGitLog() {
    const list = document.getElementById('gitLogList');
    list.innerHTML = '<div class="log-panel-empty">⏳ 加载中...</div>';

    try {
        const data = await api(`/projects/${currentProjectId}/git/log?limit=50`);
        const commits = data.commits || [];
        if (commits.length === 0) {
            list.innerHTML = '<div class="log-panel-empty">暂无提交记录</div>';
            return;
        }

        list.innerHTML = commits.map(c => `
            <div class="git-commit-item">
                <div class="git-commit-top">
                    <span class="git-commit-hash">${escapeHtml(c.short_hash)}</span>
                    <span class="git-commit-time">${formatTime(c.date)}</span>
                </div>
                <div class="git-commit-msg">${escapeHtml(c.message)}</div>
                <div class="git-commit-author">👤 ${escapeHtml(c.author)}</div>
            </div>
        `).join('');
    } catch (err) {
        list.innerHTML = `<div class="log-panel-empty">加载失败: ${err.message}</div>`;
    }
}

function getFileIcon(ext) {
    const icons = {
        py: '🐍', js: '📜', ts: '📘', jsx: '⚛️', tsx: '⚛️',
        html: '🌐', css: '🎨', scss: '🎨', sass: '🎨',
        md: '📝', json: '📋', yml: '⚙️', yaml: '⚙️', toml: '⚙️', ini: '⚙️',
        txt: '📄', sh: '💻', bash: '💻', zsh: '💻',
        go: '🐹', rs: '🦀', java: '☕', cpp: '⚡', c: '⚡', rb: '💎',
        php: '🐘', swift: '🍎', kt: '🎯',
        dockerfile: '🐳', sql: '🗃️', xml: '📰',
        png: '🖼️', jpg: '🖼️', jpeg: '🖼️', svg: '🖼️', gif: '🖼️', webp: '🖼️',
        zip: '📦', tar: '📦', gz: '📦',
        pdf: '📕', doc: '📘', docx: '📘',
        env: '🔑', gitignore: '🚫', lock: '🔒',
    };
    return icons[ext] || '📄';
}

function formatFileSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTime(dateStr) {
    if (!dateStr) return '-';
    try {
        const d = new Date(dateStr);
        if (isNaN(d.getTime())) return dateStr;
        return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
    } catch { return dateStr; }
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}


// ==================== 服务健康检查 ====================

let serverLogsExpanded = false;

function initServerHealthCheck() {
    addLog('info', '前端已加载，开始连接后端服务...');
    checkServerHealth();
    // 定期检查后端健康状态
    setInterval(checkServerHealth, 30000); // 每30秒检查一次
}

// toggleLogs 已废弃（旧服务日志面板已移除，使用 Docking 面板）

async function checkServerHealth() {
    try {
        const start = Date.now();
        const resp = await fetch('/api/health', { method: 'GET', cache: 'no-store' });
        const duration = Date.now() - start;

        if (resp.ok) {
            const data = await resp.json();
            addLog('success', `后端服务正常 (${duration}ms) - 版本: ${data.version || 'unknown'}`);
            updateLLMStatusIndicator('available');
        } else {
            addLog('error', `后端服务异常 (${resp.status})`);
            updateLLMStatusIndicator('error');
        }
    } catch (e) {
        addLog('error', `无法连接后端服务: ${e.message}`);
        updateLLMStatusIndicator('error');
    }
}

function addLog(level, message) {
    const content = document.getElementById('logPanelEntries');
    if (!content) return;

    // 移除空状态提示
    const empty = content.querySelector('.log-panel-empty');
    if (empty) empty.remove();

    const now = new Date();
    const time = formatDateTime(now);
    const levelEmoji = {
        info: 'ℹ️',
        success: '✅',
        warning: '⚠️',
        error: '❌'
    }[level] || '•';

    const levelMap = { info: 'INFO', success: 'INFO', warning: 'WARN', error: 'ERROR' };

    const entry = document.createElement('div');
    entry.className = `log-entry ${level}`;
    entry.innerHTML = `
        <span class="log-entry-time">${escapeHtml(time)}</span>
        <span class="log-entry-level ${levelMap[level] || 'info'}">${levelEmoji}</span>
        <span class="log-entry-agent">System</span>
        <span class="log-entry-msg">${escapeHtml(message)}</span>
    `;

    // 限制日志条数
    while (content.children.length >= LOG_PANEL_MAX_ENTRIES) {
        content.removeChild(content.firstChild);
    }

    content.appendChild(entry);

    // 自动滚动
    if (logPanelAutoScroll) {
        const body = document.getElementById('logPanelBody');
        if (body) body.scrollTop = body.scrollHeight;
    }

    // 如果面板收起，更新 badge
    if (logPanelCollapsed) {
        logPanelNewCount++;
        const badge = document.getElementById('logPanelBadge');
        if (badge) {
            badge.textContent = logPanelNewCount > 99 ? '99+' : logPanelNewCount;
            badge.style.display = '';
        }
    }
}

function formatDateTime(input) {
    if (!input) return '-';
    const date = (input instanceof Date) ? input : new Date(input);
    if (isNaN(date.getTime())) return String(input);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');
    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
}

// 修改 checkLLMStatus 函数，添加日志记录
const originalCheckLLMStatus = checkLLMStatus;
checkLLMStatus = async function() {
    addLog('info', '检查 LLM 配置状态...');
    try {
        await originalCheckLLMStatus();
        const el = document.getElementById('llmStatus');
        const text = el.querySelector('.text').textContent;
        if (text === '可用') {
            addLog('success', 'LLM 配置正常');
        } else if (text === '未配置') {
            addLog('warning', 'LLM 未配置，请点击右上角配置');
        } else if (text === '不可用') {
            addLog('error', 'LLM 连接失败，请检查配置');
        }
    } catch (e) {
        addLog('error', `检查 LLM 状态失败: ${e.message}`);
    }
};

// 拦截 API 请求，添加日志记录
const originalApi = api;
api = async function(path, options = {}) {
    const startTime = Date.now();
    addLog('info', `API 请求: ${options.method || 'GET'} ${path}`);

    try {
        const result = await originalApi(path, options);
        const duration = Date.now() - startTime;
        addLog('success', `API 响应: ${path} (${duration}ms)`);
        return result;
    } catch (e) {
        const duration = Date.now() - startTime;
        addLog('error', `API 失败: ${path} (${duration}ms) - ${e.message}`);
        throw e;
    }
};

function updateLLMStatusIndicator(status) {
    const el = document.getElementById('llmStatus');
    const dot = el.querySelector('.dot');
    const text = el.querySelector('.text');

    el.classList.remove('available', 'error', 'unconfigured');
    el.classList.add(status);

    if (status === 'available') {
        text.textContent = '可用';
        dot.style.background = 'var(--success)';
    } else if (status === 'error') {
        text.textContent = '不可用';
        dot.style.background = 'var(--error)';
    } else if (status === 'unconfigured') {
        text.textContent = '未配置';
        dot.style.background = 'var(--warning)';
    } else {
        text.textContent = '检测中';
        dot.style.background = 'var(--text-muted)';
    }
}


// ==================== 聊天面板 ====================

let chatMode = 'global';           // 'global' | 'job'
let chatPanelOpen = false;
let chatHistory = [];               // 全局聊天历史 [{role, content}]
let chatCurrentTicketId = null;     // Job 模式选中的工单 ID
let chatCurrentTicketTitle = '';    // Job 模式选中的工单标题
let chatSending = false;
let chatPendingImages = [];         // 待发送的图片 base64 data URL 列表
let chatPendingDocs = [];           // 待发送的文档 [{filename, text, chars}]

// ---- 图片粘贴支持（用事件委托，避免 SPA 动态渲染导致绑定失败）----
document.addEventListener('paste', (e) => {
    // 只在焦点在聊天输入框时处理
    const active = document.activeElement;
    const chatInput = document.getElementById('chatInput');
    if (!chatInput || active !== chatInput) return;
    handleChatImagePaste(e);
});

function handleChatImagePaste(e) {
    const items = e.clipboardData?.items;
    if (!items) return;
    let hasImage = false;
    for (const item of items) {
        if (item.type.startsWith('image/')) {
            hasImage = true;
            e.preventDefault(); // 尽早阻止，防止文件名出现在文本框
            const file = item.getAsFile();
            if (!file) continue;
            const reader = new FileReader();
            reader.onload = (ev) => {
                chatPendingImages.push(ev.target.result);
                renderChatImagePreviews();
            };
            reader.readAsDataURL(file);
        }
    }
}

function renderChatImagePreviews() {
    const container = document.getElementById('chatImagePreviews');
    if (!container) return;
    if (chatPendingImages.length === 0) {
        container.innerHTML = '';
        container.style.display = 'none';
        return;
    }
    container.style.display = 'flex';
    container.innerHTML = chatPendingImages.map((src, i) => `
        <div class="chat-img-thumb" title="点击移除">
            <img src="${src}" alt="图片${i+1}">
            <button class="chat-img-remove" onclick="removeChatImage(${i})">✕</button>
        </div>
    `).join('');
}

function removeChatImage(index) {
    chatPendingImages.splice(index, 1);
    renderChatImagePreviews();
}

// ---- 附件上传 ----

function openFileAttachment() {
    const input = document.getElementById('chatFileInput');
    if (input) input.click();
}

function handleFileInputChange(e) {
    const files = e.target.files;
    if (files && files.length > 0) {
        handleFileAttachment(files);
    }
    // 清空 value，允许重复选同一文件
    e.target.value = '';
}

async function handleFileAttachment(files) {
    for (const file of files) {
        const ext = file.name.split('.').pop().toLowerCase();
        const isImage = /^(png|jpg|jpeg|gif|webp|bmp)$/.test(ext);

        // 图片：直接本地读取 base64，无需上传（和粘贴图片逻辑相同）
        if (isImage) {
            const reader = new FileReader();
            reader.onload = (ev) => {
                chatPendingImages.push(ev.target.result);
                renderChatImagePreviews();
            };
            reader.readAsDataURL(file);
            continue;
        }

        // 文档/代码：需要上传到后端提取文本
        if (!currentProjectId) {
            showToast('上传文档附件需要先选择一个项目', 'warning');
            continue;
        }
        const formData = new FormData();
        formData.append('file', file);
        try {
            const resp = await fetch(`${API}/projects/${currentProjectId}/chat/upload-attachment`, {
                method: 'POST',
                body: formData,
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({ detail: resp.statusText }));
                showToast(`上传失败: ${err.detail || resp.statusText}`, 'error');
                continue;
            }
            const result = await resp.json();
            if (result.type === 'image') {
                chatPendingImages.push(result.data_url);
                renderChatImagePreviews();
            } else if (result.type === 'document') {
                chatPendingDocs.push({
                    filename: result.filename,
                    text: result.text,
                    chars: result.text.length,
                });
                renderChatDocPreviews();
            }
        } catch (err) {
            showToast(`上传出错: ${err.message}`, 'error');
        }
    }
}

function renderChatDocPreviews() {
    const container = document.getElementById('chatDocPreviews');
    if (!container) return;
    if (chatPendingDocs.length === 0) {
        container.innerHTML = '';
        container.style.display = 'none';
        return;
    }
    container.style.display = 'flex';
    container.innerHTML = chatPendingDocs.map((doc, i) => {
        const ext = doc.filename.split('.').pop().toLowerCase();
        const icon = ext === 'pdf' ? '📄' : ext === 'docx' ? '📝' : '📃';
        const charsText = doc.chars >= 1000
            ? `${(doc.chars / 1000).toFixed(1)}k 字符`
            : `${doc.chars} 字符`;
        return `
        <div class="chat-doc-card">
            <span class="chat-doc-icon">${icon}</span>
            <div class="chat-doc-info">
                <div class="chat-doc-name" title="${escapeHtml(doc.filename)}">${escapeHtml(doc.filename)}</div>
                <div class="chat-doc-meta">${charsText}</div>
            </div>
            <button class="chat-doc-remove" onclick="removeChatDoc(${i})" title="移除">✕</button>
        </div>`;
    }).join('');
}

function removeChatDoc(index) {
    chatPendingDocs.splice(index, 1);
    renderChatDocPreviews();
}

/**
 * 切换聊天面板显示/隐藏
 */
function toggleChatPanel() {
    chatPanelOpen = !chatPanelOpen;
    const panel = document.getElementById('chatPanel');
    const toggleBtn = document.getElementById('chatToggleBtn');

    if (chatPanelOpen) {
        document.body.classList.add('chat-open');
        toggleBtn?.classList.add('active');

        // 根据是否在项目内，决定显示/隐藏模式切换栏
        const modeBar = document.getElementById('chatModeBar');
        const modeBtn = document.getElementById('chatModeBtn');
        if (currentProjectId) {
            modeBar.style.display = '';
            modeBtn.style.display = '';
        } else {
            modeBar.style.display = 'none';
            modeBtn.style.display = 'none';
            // 无项目时强制全局模式
            if (chatMode !== 'global') setChatMode('global');
        }

        // 加载聊天历史
        if (chatMode === 'global') {
            loadChatHistory();
        }
    } else {
        document.body.classList.remove('chat-open');
        toggleBtn?.classList.remove('active');
    }
}

/**
 * 聊天面板宽度拖拽调整
 */
(function initChatPanelResize() {
    let isDragging = false;
    let startX = 0;
    let startWidth = 0;

    document.addEventListener('mousedown', (e) => {
        const handle = e.target.closest('#chatPanelResize');
        if (!handle) return;
        e.preventDefault();
        isDragging = true;
        handle.classList.add('dragging');
        startX = e.clientX;
        const panel = document.getElementById('chatPanel');
        startWidth = panel ? panel.offsetWidth : 380;
        document.body.style.cursor = 'ew-resize';
        document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        e.preventDefault();
        const delta = startX - e.clientX; // 向左拖 = 变宽
        let newWidth = startWidth + delta;
        newWidth = Math.max(300, Math.min(700, newWidth));

        // 更新 CSS 变量驱动 grid 布局
        document.documentElement.style.setProperty('--chat-panel-width', newWidth + 'px');
    });

    document.addEventListener('mouseup', () => {
        if (!isDragging) return;
        isDragging = false;
        document.getElementById('chatPanelResize')?.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
    });
})();

/**
 * 设置聊天模式
 */
function setChatMode(mode) {
    chatMode = mode;

    // 更新 Tab 样式
    document.getElementById('chatModeGlobal')?.classList.toggle('active', mode === 'global');
    document.getElementById('chatModeJob')?.classList.toggle('active', mode === 'job');

    // 更新标题
    const titleEl = document.getElementById('chatPanelTitle');
    const iconEl = document.getElementById('chatPanelIcon');
    const inputArea = document.getElementById('chatPanelInput');

    if (mode === 'global') {
        titleEl.textContent = 'AI 助手';
        iconEl.textContent = '💬';
        inputArea.style.display = '';
        loadChatHistory();
    } else {
        titleEl.textContent = '工单对话';
        iconEl.textContent = '🔧';
        inputArea.style.display = 'none';
        loadAllTicketConversations();
    }
}

/**
 * 切换聊天模式
 */
function toggleChatMode() {
    setChatMode(chatMode === 'global' ? 'job' : 'global');
}

/**
 * 加载全局聊天历史
 */
async function loadChatHistory() {
    if (!currentProjectId) {
        showChatWelcome();
        return;
    }

    const container = document.getElementById('chatMessages');

    try {
        const resp = await originalApi(`/projects/${currentProjectId}/chat/history?limit=50`);
        const messages = resp.messages || [];
        chatHistory = messages.map(m => ({ role: m.role, content: m.content }));

        if (messages.length === 0) {
            showChatWelcome();
            return;
        }

        container.innerHTML = '';
        for (const msg of messages) {
            appendChatBubble(
                msg.role,
                msg.content,
                msg.created_at,
                msg.action_data ? JSON.parse(msg.action_data) : null,
                msg.images || []
            );
        }
        scrollChatToBottom();
    } catch (e) {
        // 可能是首次使用，表还没创建
        showChatWelcome();
    }
}

/**
 * 加载工单 AI 对话记录
 */
async function loadTicketConversations(ticketId) {
    if (!currentProjectId || !ticketId) return;

    const container = document.getElementById('chatMessages');
    container.innerHTML = '<div class="chat-typing"><div class="chat-typing-dot"></div><div class="chat-typing-dot"></div><div class="chat-typing-dot"></div></div>';

    try {
        const resp = await originalApi(`/projects/${currentProjectId}/chat/ticket/${ticketId}/conversations`);
        const messages = resp.messages || [];
        const ticket = resp.ticket || {};

        container.innerHTML = '';

        // 添加工单信息头
        if (ticket.title) {
            chatCurrentTicketTitle = ticket.title;
            const header = document.createElement('div');
            header.className = 'chat-job-header';
            header.innerHTML = `
                <div class="job-status-dot" style="background: ${getStatusColor(ticket.status)}"></div>
                <div class="job-title">${escapeHtml(ticket.title)}</div>
                <span class="job-close-btn" onclick="clearJobSelection()" title="取消选择">✕</span>
            `;
            container.parentElement.insertBefore(header, container);
        }

        if (messages.length === 0) {
            container.innerHTML = `
                <div class="chat-job-hint">
                    <div class="hint-icon">📭</div>
                    <div class="hint-text">该工单暂无 AI 对话记录</div>
                </div>
            `;
            return;
        }

        for (const msg of messages) {
            if (msg.is_agent) {
                // Agent 消息带标签
                const agentBadge = msg.agent_type ? `<div class="chat-agent-badge">${msg.agent_type} / ${msg.action || ''}</div>` : '';
                const metaInfo = msg.model ? `<span style="font-size:10px;color:var(--text-muted)">${msg.model} · ${msg.duration_ms || 0}ms · ${(msg.input_tokens || 0)}→${(msg.output_tokens || 0)} tokens</span>` : '';

                const msgEl = document.createElement('div');
                msgEl.className = `chat-msg ${msg.role}`;
                msgEl.innerHTML = `
                    <div class="chat-msg-avatar">${msg.role === 'user' ? '📝' : '🤖'}</div>
                    <div class="chat-msg-content">
                        ${agentBadge}
                        <div class="chat-msg-bubble">${formatChatContent(msg.content)}</div>
                        <div class="chat-msg-time">${formatTime(msg.created_at)} ${metaInfo}</div>
                    </div>
                `;
                container.appendChild(msgEl);
            } else {
                appendChatBubble(msg.role, msg.content, msg.created_at);
            }
        }
        scrollChatToBottom();
    } catch (e) {
        container.innerHTML = `
            <div class="chat-job-hint">
                <div class="hint-icon">❌</div>
                <div class="hint-text">加载失败: ${escapeHtml(e.message)}</div>
            </div>
        `;
    }
}

/**
 * 加载项目下所有工单对话（统一 Feed）
 */
async function loadAllTicketConversations() {
    if (!currentProjectId) return;

    const container = document.getElementById('chatMessages');
    // 移除旧的 job header
    document.querySelectorAll('.chat-job-header').forEach(el => el.remove());
    container.innerHTML = '<div class="chat-typing"><div class="chat-typing-dot"></div><div class="chat-typing-dot"></div><div class="chat-typing-dot"></div></div>';

    try {
        const resp = await originalApi(`/projects/${currentProjectId}/chat/tickets/conversations`);
        const tickets = resp.tickets || [];
        container.innerHTML = '';

        if (tickets.length === 0) {
            container.innerHTML = `
                <div class="chat-job-hint">
                    <div class="hint-icon">📭</div>
                    <div class="hint-text">暂无工单对话记录</div>
                </div>`;
            return;
        }

        for (const t of tickets) {
            // 工单 section 容器
            const section = document.createElement('div');
            section.className = 'ticket-conversation-section';
            section.id = `ticket-section-${t.id}`;

            // section header
            const header = document.createElement('div');
            header.className = 'ticket-section-header';
            header.innerHTML = `
                <span class="job-status-dot" style="background:${getStatusColor(t.status)}"></span>
                <span class="ticket-section-title">${escapeHtml(t.title)}</span>
                <span class="ticket-section-status">${getStatusLabel(t.status)}</span>
            `;
            header.onclick = () => selectTicketForChat(t.id, t.title);
            section.appendChild(header);

            // messages
            const msgArea = document.createElement('div');
            msgArea.className = 'ticket-section-messages';

            if (t.messages.length === 0) {
                msgArea.innerHTML = '<div style="color:var(--text-muted);font-size:11px;padding:4px 12px;">暂无记录</div>';
            } else {
                for (const msg of t.messages) {
                    if (msg.type === 'log') {
                        // 状态变更日志条目
                        const logEl = document.createElement('div');
                        logEl.className = 'ticket-feed-log-entry';
                        const actionLabel = {assign:'接单', complete:'完成', accept:'验收通过', reject:'验收不通过', error:'异常', start:'开始'}[msg.action] || msg.action;
                        logEl.innerHTML = `<span class="log-agent">${escapeHtml(msg.agent_type)}</span> <span class="log-action">${escapeHtml(actionLabel)}</span> ${msg.message ? '<span class="log-msg">'+escapeHtml(msg.message.substring(0,80))+'</span>' : ''} <span class="log-time">${formatTime(msg.created_at)}</span>`;
                        msgArea.appendChild(logEl);
                    } else {
                        // Agent 对话消息
                        const agentBadge = msg.agent_type ? `<div class="chat-agent-badge">${msg.agent_type} / ${msg.action || ''}</div>` : '';
                        const metaInfo = msg.model ? `<span style="font-size:10px;color:var(--text-muted)">${msg.model} · ${msg.duration_ms || 0}ms · ${(msg.input_tokens || 0)}→${(msg.output_tokens || 0)} tokens</span>` : '';
                        const msgEl = document.createElement('div');
                        msgEl.className = `chat-msg ${msg.role}`;
                        msgEl.innerHTML = `
                            <div class="chat-msg-avatar">${msg.role === 'user' ? '📝' : '🤖'}</div>
                            <div class="chat-msg-content">
                                ${agentBadge}
                                <div class="chat-msg-bubble">${formatChatContent(msg.content)}</div>
                                <div class="chat-msg-time">${formatTime(msg.created_at)} ${metaInfo}</div>
                            </div>`;
                        msgArea.appendChild(msgEl);
                    }
                }
            }
            section.appendChild(msgArea);
            container.appendChild(section);
        }

        // 如果有选中的工单，滚动定位
        if (chatCurrentTicketId) {
            setTimeout(() => scrollToTicketSection(chatCurrentTicketId), 100);
        } else {
            scrollChatToBottom();
        }
    } catch (e) {
        container.innerHTML = `
            <div class="chat-job-hint">
                <div class="hint-icon">❌</div>
                <div class="hint-text">加载失败: ${escapeHtml(e.message)}</div>
            </div>`;
    }
}

/**
 * 滚动到指定工单 section 并高亮
 */
function scrollToTicketSection(ticketId) {
    const section = document.getElementById(`ticket-section-${ticketId}`);
    if (section) {
        section.scrollIntoView({ behavior: 'smooth', block: 'start' });
        section.classList.add('ticket-section-highlight');
        setTimeout(() => section.classList.remove('ticket-section-highlight'), 2000);
    }
}

/**
 * SSE 实时追加到工单 Feed
 */
function appendToTicketFeed(logData) {
    if (!logData.ticket_id) return;
    const section = document.getElementById(`ticket-section-${logData.ticket_id}`);
    if (!section) return;

    let msgArea = section.querySelector('.ticket-section-messages');
    if (!msgArea) return;

    const actionLabel = {assign:'接单', complete:'完成', accept:'验收通过', reject:'验收不通过', error:'异常', start:'开始'}[logData.action] || logData.action;
    let detail = '';
    if (logData.detail) {
        try {
            const d = typeof logData.detail === 'string' ? JSON.parse(logData.detail) : logData.detail;
            detail = d.message || '';
        } catch { detail = ''; }
    }

    const logEl = document.createElement('div');
    logEl.className = 'ticket-feed-log-entry';
    logEl.innerHTML = `<span class="log-agent">${escapeHtml(logData.agent_type || 'System')}</span> <span class="log-action">${escapeHtml(actionLabel)}</span> ${detail ? '<span class="log-msg">'+escapeHtml(detail.substring(0,80))+'</span>' : ''} <span class="log-time">${formatTime(logData.created_at)}</span>`;
    msgArea.appendChild(logEl);

    // 更新 section header 的状态
    if (logData.to_status) {
        const statusEl = section.querySelector('.ticket-section-status');
        if (statusEl) statusEl.textContent = getStatusLabel(logData.to_status);
        const dotEl = section.querySelector('.job-status-dot');
        if (dotEl) dotEl.style.background = getStatusColor(logData.to_status);
    }
}

/**
 * 发送聊天消息
 */
async function sendChatMessage() {
    if (chatSending || chatMode !== 'global') return;

    const input = document.getElementById('chatInput');
    const message = input.value.trim();
    const images = [...chatPendingImages]; // 拷贝一份，防止发送中被修改
    const docs = [...chatPendingDocs];     // 拷贝文档列表

    // 将文档内容追加到消息末尾
    let fullMessage = message;
    for (const doc of docs) {
        fullMessage += `\n\n【附件：${doc.filename}】\n${doc.text}`;
    }

    if (!fullMessage.trim() && images.length === 0) return;

    chatSending = true;
    const sendBtn = document.getElementById('chatSendBtn');
    sendBtn.disabled = true;
    input.value = '';
    autoResizeChatInput();

    // 清空图片和文档预览区
    chatPendingImages = [];
    chatPendingDocs = [];
    renderChatImagePreviews();
    renderChatDocPreviews();

    // 移除欢迎消息
    const welcome = document.querySelector('.chat-welcome');
    if (welcome) welcome.remove();

    // 添加用户消息气泡（含图片）— 气泡显示原始消息（不含文档全文），文档名用标签代替
    const bubbleMessage = message + (docs.length > 0 ? '\n' + docs.map(d => `📎 ${d.filename}`).join(' ') : '');
    appendChatBubble('user', bubbleMessage, null, null, images);
    scrollChatToBottom();

    // 添加加载动画
    const typingEl = document.createElement('div');
    typingEl.className = 'chat-msg assistant';
    typingEl.id = 'chatTyping';
    typingEl.innerHTML = `
        <div class="chat-msg-avatar">🤖</div>
        <div class="chat-msg-content">
            <div class="chat-msg-bubble">
                <div class="chat-typing">
                    <div class="chat-typing-dot"></div>
                    <div class="chat-typing-dot"></div>
                    <div class="chat-typing-dot"></div>
                </div>
            </div>
        </div>
    `;
    document.getElementById('chatMessages').appendChild(typingEl);
    scrollChatToBottom();

    try {
        // 构建历史（只取最近 10 条）
        const historyToSend = chatHistory.slice(-10);

        let resp;
        if (currentProjectId) {
            // 项目内聊天 — 走原有 API
            resp = await originalApi(`/projects/${currentProjectId}/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: fullMessage,
                    history: historyToSend,
                    images: images.length > 0 ? images : undefined,
                }),
            });
        } else {
            // 全局聊天（无项目）— 走全局 API
            resp = await originalApi(`/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: fullMessage,
                    history: historyToSend,
                    images: images.length > 0 ? images : undefined,
                }),
            });
        }

        // 移除加载动画
        document.getElementById('chatTyping')?.remove();

        const reply = resp.reply || '(无回复)';
        const action = resp.action || null;

        // 更新历史
        chatHistory.push({ role: 'user', content: fullMessage });
        chatHistory.push({ role: 'assistant', content: reply });

        // 添加回复气泡
        appendChatBubble('assistant', reply, null, action);
        scrollChatToBottom();

        // 项目创建成功（全局模式）
        if (action && action.type === 'project_created') {
            showToast(`项目「${action.name}」已创建`, 'success');
            // 延迟刷新项目列表并跳转
            setTimeout(() => {
                if (action.project_id) {
                    showProjectDetail(action.project_id);
                } else {
                    loadProjects();
                }
            }, 1000);
        }

        // 如果创建了需求，刷新需求列表
        if (action && action.type === 'requirement_created') {
            showToast(`需求「${action.title}」已创建`, 'success');
            // 延迟刷新，避免 UI 卡顿
            setTimeout(() => {
                if (typeof loadRequirements === 'function') loadRequirements();
                if (typeof refreshBoard === 'function') refreshBoard();
            }, 500);
        }

        // 需求状态管理操作
        if (action && action.type === 'requirement_paused') {
            showToast(`需求「${action.title}」已暂停`, 'warning');
            setTimeout(() => {
                if (typeof loadRequirements === 'function') loadRequirements();
                if (typeof refreshBoard === 'function') refreshBoard();
            }, 500);
        }
        if (action && action.type === 'requirement_resumed') {
            showToast(`需求「${action.title}」已恢复执行`, 'success');
            setTimeout(() => {
                if (typeof loadRequirements === 'function') loadRequirements();
                if (typeof refreshBoard === 'function') refreshBoard();
            }, 500);
        }
        if (action && action.type === 'requirement_closed') {
            showToast(`需求「${action.title}」已关闭`, 'info');
            setTimeout(() => {
                if (typeof loadRequirements === 'function') loadRequirements();
                if (typeof refreshBoard === 'function') refreshBoard();
            }, 500);
        }
        if (action && action.type === 'document_generated') {
            showToast(`文档「${action.title || action.path}」已生成`, 'success');
        }

    } catch (e) {
        document.getElementById('chatTyping')?.remove();
        // e 可能是 Error 对象或普通对象，统一转成字符串
        let errMsg = '';
        if (e instanceof Error) {
            errMsg = e.message;
        } else if (typeof e === 'string') {
            errMsg = e;
        } else {
            errMsg = JSON.stringify(e);
        }
        appendChatBubble('assistant', `⚠️ 请求失败: ${errMsg}\n\n请检查 LLM 是否已配置。`);
        scrollChatToBottom();
    } finally {
        chatSending = false;
        sendBtn.disabled = false;
        input.focus();
    }
}

/**
 * 追加聊天气泡
 */
function appendChatBubble(role, content, timestamp = null, action = null, images = []) {
    const container = document.getElementById('chatMessages');
    const msgEl = document.createElement('div');
    msgEl.className = `chat-msg ${role}`;

    const avatar = role === 'user' ? '👤' : '🤖';
    const timeStr = timestamp ? formatTime(timestamp) : formatTime(new Date().toISOString());

    let actionHtml = '';
    if (action && action.type === 'requirement_created') {
        actionHtml = `
            <div class="chat-action-card">
                <div class="action-title">✅ 需求已创建</div>
                <div class="action-detail">
                    <strong>${escapeHtml(action.title)}</strong><br>
                    优先级: ${action.priority || 'medium'}
                </div>
                <span class="action-link" onclick="switchTab('requirements')">查看需求列表 →</span>
            </div>
        `;
    } else if (action && action.type === 'project_created') {
        actionHtml = `
            <div class="chat-action-card" style="border-left-color: var(--success, #34d058);">
                <div class="action-title">🎉 项目已创建</div>
                <div class="action-detail">
                    <strong>${escapeHtml(action.name || '')}</strong><br>
                    ${action.tech_stack ? '技术栈: ' + escapeHtml(action.tech_stack) + '<br>' : ''}
                    ${action.git_remote_url ? 'Git: ' + escapeHtml(action.git_remote_url) : ''}
                </div>
                ${action.project_id ? `<span class="action-link" onclick="showProjectDetail('${action.project_id}')">进入项目 →</span>` : ''}
            </div>
        `;
    } else if (action && action.type === 'requirement_paused') {
        actionHtml = `
            <div class="chat-action-card" style="border-left-color: var(--warning, #f0a020);">
                <div class="action-title">⏸️ 需求已暂停</div>
                <div class="action-detail">
                    <strong>${escapeHtml(action.title)}</strong><br>
                    ${action.reason ? '原因: ' + escapeHtml(action.reason) : ''}
                </div>
                <span class="action-link" onclick="switchTab('requirements')">查看需求列表 →</span>
            </div>
        `;
    } else if (action && action.type === 'requirement_resumed') {
        actionHtml = `
            <div class="chat-action-card" style="border-left-color: var(--success, #34d058);">
                <div class="action-title">▶️ 需求已恢复</div>
                <div class="action-detail">
                    <strong>${escapeHtml(action.title)}</strong><br>
                    需求已恢复执行
                </div>
                <span class="action-link" onclick="switchTab('requirements')">查看需求列表 →</span>
            </div>
        `;
    } else if (action && action.type === 'requirement_closed') {
        actionHtml = `
            <div class="chat-action-card" style="border-left-color: var(--danger, #ea4a5a);">
                <div class="action-title">🚫 需求已关闭</div>
                <div class="action-detail">
                    <strong>${escapeHtml(action.title)}</strong><br>
                    ${action.reason ? '原因: ' + escapeHtml(action.reason) : ''}
                    ${action.cancelled_tickets > 0 ? '<br>同时取消了 ' + action.cancelled_tickets + ' 个关联工单' : ''}
                </div>
                <span class="action-link" onclick="switchTab('requirements')">查看需求列表 →</span>
            </div>
        `;
    } else if (action && action.type === 'document_generated') {
        actionHtml = `
            <div class="chat-action-card" style="border-left-color: var(--info, #58a6ff);">
                <div class="action-title">📄 文档已生成</div>
                <div class="action-detail">
                    <strong>${escapeHtml(action.title || action.path || '')}</strong><br>
                    路径: <code>${escapeHtml(action.path || '')}</code>
                    ${action.commit ? '<br>Commit: ' + escapeHtml(action.commit) : ''}
                </div>
                ${action.path ? `<span class="action-link" onclick="openRepoFileFromChat('${escapeHtml(action.path)}')">查看仓库文件 →</span>` : `<span class="action-link" onclick="switchTab('repo')">查看仓库文件 →</span>`}
            </div>
        `;
    } else if (action && action.type === 'git_result') {
        const gitIcons = {switch_branch: '🌿', list_branches: '🌿', log: '📜', read_file: '📄', merge: '🔀'};
        // read_file 时尝试从 action.path 或 action.message 中提取路径
        const gitFilePath = action.path || (action.action === 'read_file' ? extractPathFromGitMsg(action.message || '') : '');
        const gitLinkHtml = action.action === 'switch_branch'
            ? `<span class="action-link" onclick="switchTab('repo'); loadRepoTree();">查看仓库文件 →</span>`
            : action.action === 'read_file' && gitFilePath
                ? `<span class="action-link" onclick="openRepoFileFromChat('${escapeHtml(gitFilePath)}')">查看文件 →</span>`
                : '';
        actionHtml = `
            <div class="chat-action-card" style="border-left-color: var(--info, #58a6ff);">
                <div class="action-title">${gitIcons[action.action] || '🔧'} Git: ${escapeHtml(action.action || '')}</div>
                <div class="action-detail">${formatChatContent(action.message || '')}</div>
                ${gitLinkHtml}
            </div>
        `;
    } else if (action && action.type === 'error') {
        actionHtml = `
            <div class="chat-action-card" style="border-left-color: var(--danger, #ea4a5a);">
                <div class="action-title">⚠️ 操作失败</div>
                <div class="action-detail">${escapeHtml(action.message || '未知错误')}</div>
            </div>
        `;
    } else if (action && action.type === 'confirm_requirement') {
        const priorityLabel = {'critical':'🔴 紧急','high':'🟠 高','medium':'🟡 中','low':'🟢 低'}[action.priority] || action.priority;
        const safeId = 'req_confirm_' + Date.now();
        const imagesJson = action.images && action.images.length ? escapeHtml(JSON.stringify(action.images)) : '';
        const imagesPreview = action.images && action.images.length
            ? `<div class="confirm-card-images">${action.images.map(u => `<img src="${escapeHtml(u)}" class="confirm-card-img" onclick="event.stopPropagation();window.open(this.src,'_blank')" title="点击查看大图">`).join('')}</div>`
            : '';
        actionHtml = `
            <div class="chat-action-card chat-confirm-card" id="${safeId}"
                 data-title="${escapeHtml(action.title)}"
                 data-description="${escapeHtml(action.description)}"
                 data-priority="${escapeHtml(action.priority)}"
                 data-images="${imagesJson}"
                 style="border-left-color: var(--primary);">
                <div class="action-title">📋 识别到新需求，是否创建？</div>
                <div class="action-detail">
                    <div class="confirm-req-title">${escapeHtml(action.title)}</div>
                    <div class="confirm-req-desc">${escapeHtml(action.description)}</div>
                    <div class="confirm-req-meta">优先级：${priorityLabel}</div>
                    ${imagesPreview}
                </div>
                <div class="confirm-req-btns">
                    <button class="btn btn-sm btn-primary" onclick="doConfirmRequirement('${safeId}')">✅ 确认创建</button>
                    <button class="btn btn-sm" onclick="doCancelRequirement('${safeId}')">✗ 取消</button>
                </div>
            </div>
        `;
    } else if (action && action.type === 'confirm_bug') {
        const priorityLabel = {'critical':'🔴 紧急','high':'🟠 高','medium':'🟡 中','low':'🟢 低'}[action.priority] || action.priority;
        const safeId = 'bug_confirm_' + Date.now();
        const imagesJson = action.images && action.images.length ? escapeHtml(JSON.stringify(action.images)) : '';
        const imagesPreview = action.images && action.images.length
            ? `<div class="confirm-card-images">${action.images.map(u => `<img src="${escapeHtml(u)}" class="confirm-card-img" onclick="event.stopPropagation();window.open(this.src,'_blank')" title="点击查看大图">`).join('')}</div>`
            : '';
        actionHtml = `
            <div class="chat-action-card chat-confirm-card chat-confirm-bug-card" id="${safeId}"
                 data-title="${escapeHtml(action.title)}"
                 data-description="${escapeHtml(action.description)}"
                 data-priority="${escapeHtml(action.priority)}"
                 data-requirement-id="${escapeHtml(action.requirement_id || '')}"
                 data-images="${imagesJson}"
                 style="border-left-color: var(--danger, #ea4a5a);">
                <div class="action-title">🐛 识别到 BUG，是否上报？</div>
                <div class="action-detail">
                    <div class="confirm-req-title">${escapeHtml(action.title)}</div>
                    <div class="confirm-req-desc">${escapeHtml(action.description)}</div>
                    <div class="confirm-req-meta">优先级：${priorityLabel}</div>
                    ${imagesPreview}
                </div>
                <div class="confirm-req-btns">
                    <button class="btn btn-sm btn-danger" onclick="doConfirmBug('${safeId}')">🐛 确认上报</button>
                    <button class="btn btn-sm" onclick="doCancelRequirement('${safeId}')">✗ 取消</button>
                </div>
            </div>
        `;
    }

    // 图片展示（用户发送的图片）
    const imagesHtml = (images && images.length > 0)
        ? `<div class="chat-bubble-images">${images.map(src =>
            `<img class="chat-bubble-img" src="${src}" alt="图片" onclick="openChatImageViewer(this.src)">`
          ).join('')}</div>`
        : '';

    // assistant 消息底部工具栏（复制 + 保存到文件）
    const toolbarHtml = (role === 'assistant' && content && content.trim())
        ? `<div class="chat-bubble-toolbar">
            <button class="chat-bubble-tool-btn" onclick="copyChatBubble(this)" title="复制内容">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                复制
            </button>
            ${currentProjectId ? `<button class="chat-bubble-tool-btn" onclick="saveChatBubbleToRepo(this)" title="保存为 Markdown 文件到仓库">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
                保存到仓库
            </button>` : ''}
           </div>`
        : '';

    msgEl.innerHTML = `
        <div class="chat-msg-avatar">${avatar}</div>
        <div class="chat-msg-content">
            ${imagesHtml}
            <div class="chat-msg-bubble">${formatChatContent(content)}</div>
            ${actionHtml}
            ${toolbarHtml}
            <div class="chat-msg-time">${timeStr}</div>
        </div>
    `;
    container.appendChild(msgEl);
}

/** 用户确认创建需求 */
async function doConfirmRequirement(cardId) {
    const card = document.getElementById(cardId);
    if (!card || !currentProjectId) return;
    const title = card.dataset.title || '';
    const description = card.dataset.description || '';
    const priority = card.dataset.priority || 'medium';
    const images = card.dataset.images ? JSON.parse(card.dataset.images) : [];
    const btns = card.querySelector('.confirm-req-btns');
    if (btns) btns.innerHTML = '<span style="color:var(--text-muted);font-size:12px">⏳ 创建中...</span>';
    try {
        const result = await api(`/projects/${currentProjectId}/chat/confirm-create-requirement`, {
            method: 'POST',
            body: { title, description, priority, images },
        });
        card.style.borderLeftColor = 'var(--success, #34d058)';
        card.querySelector('.action-title').textContent = '✅ 需求已创建';
        if (btns) btns.innerHTML = `<span class="action-link" onclick="switchTab('requirements')">查看需求列表 →</span>`;
        showToast(`需求「${title}」已创建`, 'success');
        setTimeout(() => {
            if (typeof loadRequirements === 'function') loadRequirements();
            if (typeof refreshBoard === 'function') refreshBoard();
        }, 500);
    } catch (e) {
        card.style.borderLeftColor = 'var(--danger, #ea4a5a)';
        card.querySelector('.action-title').textContent = '⚠️ 创建失败';
        if (btns) btns.innerHTML = `<span style="color:var(--danger);font-size:12px">${escapeHtml(e.message)}</span>`;
    }
}

/** 用户取消创建需求 */
function doCancelRequirement(cardId) {
    const card = document.getElementById(cardId);
    if (!card) return;
    card.style.opacity = '0.5';
    card.querySelector('.action-title').textContent = '✗ 已取消';
    const btns = card.querySelector('.confirm-req-btns');
    if (btns) btns.remove();
}

/** 复制气泡内容到剪贴板 */
function copyChatBubble(btn) {
    const bubble = btn.closest('.chat-msg-content').querySelector('.chat-msg-bubble');
    const text = bubble ? (bubble.innerText || bubble.textContent) : '';
    navigator.clipboard.writeText(text.trim()).then(() => {
        const orig = btn.innerHTML;
        btn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> 已复制';
        btn.style.color = 'var(--success, #34d058)';
        setTimeout(() => { btn.innerHTML = orig; btn.style.color = ''; }, 2000);
    }).catch(() => showToast('复制失败', 'error'));
}

/** 保存气泡内容为 Markdown 文件到项目仓库 */
async function saveChatBubbleToRepo(btn) {
    if (!currentProjectId) return;
    const bubble = btn.closest('.chat-msg-content').querySelector('.chat-msg-bubble');
    const text = bubble ? (bubble.innerText || bubble.textContent) : '';
    if (!text.trim()) return;

    // 用时间戳生成文件名
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const filename = `chat-export-${ts}.md`;
    const content = `# AI 对话导出\n\n> 导出时间：${new Date().toLocaleString()}\n\n---\n\n${text.trim()}`;

    btn.disabled = true;
    const orig = btn.innerHTML;
    btn.innerHTML = '⏳ 保存中...';

    try {
        const resp = await fetch(`${API}/projects/${currentProjectId}/chat/save-to-repo`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename: `docs/${filename}`, content }),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || resp.statusText);
        }
        const result = await resp.json();
        btn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> 已保存';
        btn.style.color = 'var(--success, #34d058)';
        showToast(`已保存到 ${result.path || filename}`, 'success');
        setTimeout(() => { btn.innerHTML = orig; btn.style.color = ''; btn.disabled = false; }, 3000);
    } catch (e) {
        showToast(`保存失败: ${e.message}`, 'error');
        btn.innerHTML = orig;
        btn.disabled = false;
    }
}

/** 简易图片查看器（点图片全屏预览） */
function openChatImageViewer(src) {
    let overlay = document.getElementById('chatImgViewerOverlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'chatImgViewerOverlay';
        overlay.style.cssText = `position:fixed;inset:0;background:rgba(0,0,0,0.85);z-index:9999;display:flex;align-items:center;justify-content:center;cursor:zoom-out;`;
        overlay.onclick = () => overlay.remove();
        document.body.appendChild(overlay);
    }
    overlay.innerHTML = `<img src="${src}" style="max-width:90vw;max-height:90vh;border-radius:8px;box-shadow:0 8px 40px rgba(0,0,0,0.6);">`;
    overlay.style.display = 'flex';
}

/**
 * 格式化聊天内容（简单 Markdown 支持）
 */
function formatChatContent(content) {
    if (!content) return '';

    // 过滤掉残留的 [ACTION:...] ... [/ACTION] 块（后端已 clean，此为兜底）
    // 同时处理 token 截断导致未闭合的 [ACTION:...] 块
    content = content.replace(/\[ACTION:\w+\][\s\S]*?\[\/ACTION\]/g, '');
    content = content.replace(/\[ACTION:\w+\][\s\S]*$/g, '').trim();
    if (!content) return '';

    let result = '';
    // 按代码块分割，逐段处理
    const parts = content.split(/(```[\w]*\n[\s\S]*?```)/g);

    for (const part of parts) {
        const codeBlockMatch = part.match(/^```([\w]*)\n([\s\S]*?)```$/);
        if (codeBlockMatch) {
            const lang = codeBlockMatch[1] || '';
            const code = codeBlockMatch[2];
            result += buildCodeFileCard(lang, code);
        } else {
            // 普通文本：转义后做简单 Markdown 处理
            let text = escapeHtml(part);
            // 行内代码
            text = text.replace(/`([^`\n]+)`/g, '<code class="chat-inline-code">$1</code>');
            // 加粗
            text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
            // 换行
            text = text.replace(/\n/g, '<br>');
            result += text;
        }
    }
    return result;
}

/** 生成可折叠的代码文件卡片 */
function buildCodeFileCard(lang, code) {
    const lines = code.split('\n');
    const lineCount = lines.length;
    const cardId = 'cfc_' + Math.random().toString(36).slice(2, 9);

    // 尝试从代码第一行注释或内容推断文件名
    const guessedFile = guessFileName(code, lang);

    // 语言标签
    const langLabel = lang ? lang.toUpperCase() : 'CODE';
    const langIcon = getFileIcon(lang);

    // 预览：前 3 行
    const previewLines = lines.slice(0, 3).join('\n');
    const previewEscaped = escapeHtml(previewLines);

    // 完整代码（转义）
    const fullEscaped = escapeHtml(code);

    // 是否有对应的仓库文件链接
    const repoLinkHtml = guessedFile
        ? `<button class="code-card-repo-btn" onclick="openRepoFileFromChat('${escapeHtml(guessedFile)}')" title="在仓库中打开">📂 仓库</button>`
        : '';

    return `
<div class="code-file-card" id="${cardId}">
    <div class="code-card-header" onclick="toggleCodeCard('${cardId}')">
        <div class="code-card-left">
            <span class="code-card-arrow" id="${cardId}_arrow">▶</span>
            <span class="code-card-icon">${langIcon}</span>
            <span class="code-card-filename">${escapeHtml(guessedFile || '代码片段')}</span>
            <span class="code-card-badge">${langLabel}</span>
            <span class="code-card-lines">${lineCount} 行</span>
        </div>
        <div class="code-card-right" onclick="event.stopPropagation()">
            ${repoLinkHtml}
            <button class="code-card-copy-btn" onclick="copyCodeCard('${cardId}')" title="复制代码">⎘</button>
        </div>
    </div>
    <div class="code-card-preview" id="${cardId}_preview">
        <pre class="code-card-pre">${previewEscaped}</pre>
        ${lineCount > 3 ? `<div class="code-card-more">…还有 ${lineCount - 3} 行，点击展开</div>` : ''}
    </div>
    <div class="code-card-full" id="${cardId}_full" style="display:none;">
        <pre class="code-card-pre" data-raw="${fullEscaped}">${fullEscaped}</pre>
    </div>
</div>`;
}

/** 根据代码内容猜测文件名 */
function guessFileName(code, lang) {
    // 匹配常见注释模式：# filename.py  /  // filename.js  / /* filename */
    const patterns = [
        /^#\s*([\w\-./]+\.\w+)/m,
        /^\/\/\s*([\w\-./]+\.\w+)/m,
        /^\/\*\s*([\w\-./]+\.\w+)/m,
        /filename[:\s]+([\w\-./]+\.\w+)/i,
        /文件[名：:]\s*([\w\-./]+\.\w+)/,
    ];
    for (const pat of patterns) {
        const m = code.match(pat);
        if (m) return m[1];
    }
    // 从语言推断默认扩展名
    const extMap = {
        python: 'py', py: 'py', javascript: 'js', js: 'js',
        typescript: 'ts', ts: 'ts', html: 'html', css: 'css',
        bash: 'sh', sh: 'sh', sql: 'sql', json: 'json',
        yaml: 'yml', yml: 'yml', go: 'go', rust: 'rs',
        java: 'java', cpp: 'cpp', c: 'c',
    };
    return extMap[lang] ? `snippet.${extMap[lang]}` : null;
}

/** 展开/收起代码卡片 */
function toggleCodeCard(cardId) {
    const preview = document.getElementById(cardId + '_preview');
    const full = document.getElementById(cardId + '_full');
    const arrow = document.getElementById(cardId + '_arrow');
    const card = document.getElementById(cardId);
    if (!preview || !full) return;

    const isExpanded = full.style.display !== 'none';
    if (isExpanded) {
        full.style.display = 'none';
        preview.style.display = 'block';
        arrow.textContent = '▶';
        card.classList.remove('expanded');
    } else {
        preview.style.display = 'none';
        full.style.display = 'block';
        arrow.textContent = '▼';
        card.classList.add('expanded');
        // 展开时对代码块做语法高亮
        const codeEl = full.querySelector('pre');
        if (codeEl && window.hljs && !codeEl.dataset.highlighted) {
            codeEl.dataset.highlighted = '1';
            hljs.highlightElement(codeEl);
        }
    }
}

/** 复制代码卡片内容 */
function copyCodeCard(cardId) {
    const full = document.getElementById(cardId + '_full');
    const preview = document.getElementById(cardId + '_preview');
    const raw = full?.querySelector('pre')?.dataset?.raw
        || preview?.querySelector('pre')?.textContent
        || '';
    navigator.clipboard.writeText(raw).then(() => showToast('已复制', 'success'))
        .catch(() => showToast('复制失败', 'warning'));
}

/** 从聊天跳转到仓库文件页 */
function openRepoFileFromChat(filePath) {
    if (!currentProjectId) { showToast('请先选择项目', 'warning'); return; }
    switchTab('repo');
    setTimeout(() => viewRepoFile(filePath, null), 450);
}

/** 从 git read_file 的消息文本中尝试提取文件路径 */
function extractPathFromGitMsg(msg) {
    // 匹配常见格式：路径/文件名.ext 或 `path/to/file.ext`
    const m = msg.match(/`([\w\-./]+\.\w+)`/) || msg.match(/([\w\-./]+\.\w+)/);
    return m ? m[1] : '';
}

/**
 * 显示欢迎消息
 */
function showChatWelcome() {
    const container = document.getElementById('chatMessages');
    if (currentProjectId) {
        container.innerHTML = `
            <div class="chat-welcome">
                <div class="chat-welcome-icon">🤖</div>
                <div class="chat-welcome-title">AI 开发助手</div>
                <div class="chat-welcome-desc">
                    我可以帮你：查看项目状态、创建需求、管理需求执行<br>
                    <small>💡 试试说：</small><br>
                    <small>"帮我创建一个用户登录功能需求"</small><br>
                    <small>"暂停 XX 需求" / "恢复 XX 需求" / "关闭 XX 需求"</small>
                </div>
            </div>
        `;
    } else {
        container.innerHTML = `
            <div class="chat-welcome">
                <div class="chat-welcome-icon">🤖</div>
                <div class="chat-welcome-title">AI 开发助手</div>
                <div class="chat-welcome-desc">
                    我可以帮你创建新项目、了解系统功能<br>
                    <small>💡 试试说：</small><br>
                    <small>"帮我创建一个新项目"</small><br>
                    <small>"这个系统能做什么？"</small>
                </div>
            </div>
        `;
    }
}

/**
 * 显示 Job 选择提示
 */
function showJobHint() {
    // 移除可能存在的 job header
    document.querySelector('.chat-job-header')?.remove();

    const container = document.getElementById('chatMessages');
    container.innerHTML = `
        <div class="chat-job-hint">
            <div class="hint-icon">🔧</div>
            <div class="hint-text">
                在看板中点击工单卡片<br>
                或在 Pipeline 中点击 Job 节点<br>
                即可查看该工单的 AI 对话记录
            </div>
        </div>
    `;
}

/**
 * 选中工单并加载对话 — 可从看板卡片点击触发
 */
function selectTicketForChat(ticketId, ticketTitle) {
    chatCurrentTicketId = ticketId;
    chatCurrentTicketTitle = ticketTitle || '';

    // 如果面板未打开，先打开
    if (!chatPanelOpen) {
        toggleChatPanel();
    }

    if (chatMode === 'job') {
        // 已在工单模式，直接滚动定位
        scrollToTicketSection(ticketId);
    } else {
        // 切换到工单模式（会自动加载全部并定位）
        setChatMode('job');
    }
}

/**
 * 清除 Job 选择
 */
function clearJobSelection() {
    chatCurrentTicketId = null;
    chatCurrentTicketTitle = '';
    // 移除高亮，Feed 保持显示
    document.querySelectorAll('.ticket-section-highlight').forEach(el => el.classList.remove('ticket-section-highlight'));
}

/**
 * 清空聊天面板
 */
function clearChatPanel() {
    if (chatMode === 'global') {
        chatHistory = [];
        showChatWelcome();
    } else {
        clearJobSelection();
    }
}

/**
 * 处理键盘事件
 */
function handleChatKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendChatMessage();
    }
}

/**
 * 自动调整输入框高度
 */
function autoResizeChatInput() {
    const textarea = document.getElementById('chatInput');
    if (!textarea) return;
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
}

/**
 * 滚动聊天到底部
 */
function scrollChatToBottom() {
    const body = document.getElementById('chatPanelBody');
    if (body) {
        requestAnimationFrame(() => {
            body.scrollTop = body.scrollHeight;
        });
    }
}

/**
 * 获取状态颜色
 */
function getStatusColor(status) {
    const colors = {
        'pending': 'var(--text-muted)',
        'submitted': 'var(--info)',
        'analyzing': 'var(--warning, #f0a020)',
        'decomposed': 'var(--accent)',
        'in_progress': 'var(--primary-light)',
        'paused': '#e67e22',
        'completed': 'var(--success)',
        'architecture_in_progress': 'var(--info)',
        'architecture_done': 'var(--success)',
        'development_in_progress': 'var(--info)',
        'development_done': 'var(--success)',
        'acceptance_passed': 'var(--success)',
        'acceptance_rejected': 'var(--error)',
        'testing_in_progress': 'var(--info)',
        'testing_done': 'var(--success)',
        'testing_failed': 'var(--error)',
        'deploying': 'var(--info)',
        'deployed': 'var(--success)',
        'cancelled': 'var(--text-muted)',
    };
    return colors[status] || 'var(--text-muted)';
}


// ==================== Roadmap 甘特图 + 列表 ====================

let _roadmapData = null;
let _roadmapView = 'gantt';

/** 切换 Roadmap 视图模式 */
function switchRoadmapView(view) {
    _roadmapView = view;
    document.querySelectorAll('.roadmap-view-btn').forEach(b => b.classList.remove('active'));
    const btn = document.getElementById(view === 'gantt' ? 'roadmapViewGantt' : 'roadmapViewList');
    if (btn) btn.classList.add('active');

    const ganttC = document.getElementById('roadmapGanttContainer');
    const listC = document.getElementById('roadmapListContainer');
    if (ganttC) ganttC.style.display = view === 'gantt' ? '' : 'none';
    if (listC) listC.style.display = view === 'list' ? '' : 'none';

    if (_roadmapData) {
        if (view === 'gantt') renderRoadmapGantt(_roadmapData);
        else renderRoadmapList(_roadmapData);
    }
}

/** 加载 Roadmap 数据 */
async function loadRoadmap() {
    if (!currentProjectId) return;

    const ganttC = document.getElementById('roadmapGanttContainer');
    const listC = document.getElementById('roadmapListContainer');
    const summaryEl = document.getElementById('roadmapSummary');

    try {
        const raw = await api(`/projects/${currentProjectId}/roadmap`);

        // 合并所有需求为扁平数组（甘特图/列表兼容）
        const allReqs = [];
        (raw.milestones || []).forEach(ms => {
            (ms.requirements || []).forEach(r => allReqs.push(r));
        });
        (raw.unassigned_requirements || []).forEach(r => allReqs.push(r));
        raw.requirements = allReqs;

        _roadmapData = raw;

        // 渲染汇总卡片
        renderRoadmapSummary(_roadmapData, summaryEl);

        // 渲染当前视图
        if (_roadmapView === 'gantt') renderRoadmapGantt(_roadmapData);
        else renderRoadmapList(_roadmapData);

    } catch (e) {
        const html = `<div class="empty-state"><div class="emoji">❌</div><p>加载失败: ${e.message}</p></div>`;
        if (ganttC) ganttC.innerHTML = html;
        if (listC) listC.innerHTML = html;
    }
}

/** AI 重新规划里程碑 */
async function regenerateRoadmap() {
    if (!currentProjectId) return;
    if (!confirm('确认让 AI 重新生成里程碑规划？现有里程碑将被替换。')) return;

    showToast('🤖 AI 正在规划里程碑...', 'info');
    try {
        await api(`/projects/${currentProjectId}/milestones/generate`, { method: 'POST' });
        showToast('✅ 里程碑规划完成', 'success');
        await loadRoadmap();
    } catch (e) {
        showToast('❌ 规划失败: ' + e.message, 'error');
    }
}

/** 渲染汇总卡片 */
function renderRoadmapSummary(data, el) {
    if (!el || !data) return;
    const summary = data.summary || {};
    const milestones = data.milestones || [];
    const msTotal = milestones.length;
    const msDone = milestones.filter(m => m.status === 'completed').length;
    const msDelayed = milestones.filter(m => m.status === 'delayed').length;

    el.innerHTML = `
        <div class="roadmap-summary-cards">
            <div class="roadmap-stat-card">
                <div class="roadmap-stat-value">${msTotal}</div>
                <div class="roadmap-stat-label">里程碑</div>
            </div>
            <div class="roadmap-stat-card roadmap-stat-progress">
                <div class="roadmap-stat-value">${msDone}</div>
                <div class="roadmap-stat-label">已完成</div>
            </div>
            ${msDelayed > 0 ? `<div class="roadmap-stat-card" style="border-color:rgba(239,68,68,0.3);">
                <div class="roadmap-stat-value" style="color:#ef4444;">${msDelayed}</div>
                <div class="roadmap-stat-label">已延期</div>
            </div>` : ''}
            <div class="roadmap-stat-card">
                <div class="roadmap-stat-value">${summary.total_requirements || 0}</div>
                <div class="roadmap-stat-label">总需求</div>
            </div>
            <div class="roadmap-stat-card roadmap-stat-active">
                <div class="roadmap-stat-value">${summary.in_progress_requirements || 0}</div>
                <div class="roadmap-stat-label">进行中</div>
            </div>
            <div class="roadmap-stat-card">
                <div class="roadmap-stat-value">${summary.total_tickets || 0}</div>
                <div class="roadmap-stat-label">总工单</div>
            </div>
            <div class="roadmap-stat-card roadmap-stat-done">
                <div class="roadmap-stat-value">${summary.done_tickets || 0}</div>
                <div class="roadmap-stat-label">已完成工单</div>
            </div>
            <div class="roadmap-stat-card roadmap-stat-overall">
                <div class="roadmap-stat-value">${summary.overall_progress || 0}%</div>
                <div class="roadmap-stat-label">总体进度</div>
                <div class="roadmap-progress-bar-mini">
                    <div class="roadmap-progress-fill-mini" style="width:${summary.overall_progress || 0}%"></div>
                </div>
            </div>
        </div>
    `;
}


// ==================== 甘特图渲染（SVG + 里程碑） ====================

function renderRoadmapGantt(data) {
    const container = document.getElementById('roadmapGanttContainer');
    if (!container || !data) return;

    const milestones = data.milestones || [];
    const reqs = data.requirements || [];

    if (milestones.length === 0 && reqs.length === 0) {
        container.innerHTML = `<div class="roadmap-ai-hint">
            <div class="emoji">🗺️</div>
            <p>暂无里程碑数据</p>
            <button class="btn btn-primary" onclick="regenerateRoadmap()">🤖 让 AI 生成 Roadmap</button>
        </div>`;
        return;
    }

    // 时间范围
    const tr = data.time_range || {};
    let rangeStart = tr.start ? new Date(tr.start) : new Date();
    let rangeEnd = tr.end ? new Date(tr.end) : new Date();

    // 里程碑时间也纳入范围
    milestones.forEach(ms => {
        if (ms.planned_start) {
            const d = new Date(ms.planned_start);
            if (d < rangeStart) rangeStart = d;
        }
        if (ms.planned_end) {
            const d = new Date(ms.planned_end);
            if (d > rangeEnd) rangeEnd = d;
        }
    });

    // 至少覆盖 7 天
    const minSpan = 7 * 24 * 3600 * 1000;
    if (rangeEnd - rangeStart < minSpan) {
        rangeEnd = new Date(rangeStart.getTime() + minSpan);
    }

    // 向前后各扩展 2 天
    rangeStart = new Date(rangeStart.getTime() - 2 * 86400000);
    rangeEnd = new Date(rangeEnd.getTime() + 2 * 86400000);

    const totalMs = rangeEnd - rangeStart;
    const totalDays = Math.ceil(totalMs / 86400000);

    const ROW_HEIGHT = 36;
    const LABEL_WIDTH = 260;
    const DAY_WIDTH = Math.max(40, Math.min(80, 900 / totalDays));
    const CHART_WIDTH = totalDays * DAY_WIDTH;
    const HEADER_HEIGHT = 50;
    const PADDING_TOP = 10;

    if (!window._roadmapExpanded) window._roadmapExpanded = {};

    // 构建行数据：先里程碑分组，再未分组需求
    const rows = [];
    const reqByMs = {};  // milestone_id -> [req]
    const unassignedReqs = [];

    reqs.forEach(req => {
        const msId = req.milestone_id;
        if (msId) {
            if (!reqByMs[msId]) reqByMs[msId] = [];
            reqByMs[msId].push(req);
        } else {
            unassignedReqs.push(req);
        }
    });

    // 里程碑行
    milestones.forEach(ms => {
        const expanded = window._roadmapExpanded[`ms_${ms.id}`] !== false; // 默认展开
        rows.push({ type: 'milestone', data: ms, expanded });
        const msReqs = reqByMs[ms.id] || [];
        if (expanded) {
            msReqs.forEach(req => {
                const reqExpanded = !!window._roadmapExpanded[req.id];
                rows.push({ type: 'req', data: req, expanded: reqExpanded });
                if (reqExpanded && req.tickets && req.tickets.length > 0) {
                    req.tickets.forEach(t => rows.push({ type: 'ticket', data: t }));
                }
            });
        }
    });

    // 未分组需求
    if (unassignedReqs.length > 0) {
        rows.push({ type: 'separator', label: '📋 未关联里程碑' });
        unassignedReqs.forEach(req => {
            const reqExpanded = !!window._roadmapExpanded[req.id];
            rows.push({ type: 'req', data: req, expanded: reqExpanded });
            if (reqExpanded && req.tickets && req.tickets.length > 0) {
                req.tickets.forEach(t => rows.push({ type: 'ticket', data: t }));
            }
        });
    }

    const TOTAL_HEIGHT = HEADER_HEIGHT + PADDING_TOP + rows.length * ROW_HEIGHT + 20;
    const SVG_WIDTH = LABEL_WIDTH + CHART_WIDTH + 20;

    const fmtDate = (d) => `${d.getMonth() + 1}/${d.getDate()}`;
    const fmtMonth = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;

    const phaseColors = {
        'planned': '#8b95a5', 'analyzing': '#f0a020', 'in_progress': '#3b82f6',
        'paused': '#e67e22', 'completed': '#22c55e', 'cancelled': '#6b7280',
        'architecture': '#8b5cf6', 'development': '#3b82f6',
        'testing': '#f59e0b', 'deployment': '#10b981',
    };

    const msColors = { 'planned': '#f59e0b', 'in_progress': '#3b82f6', 'completed': '#22c55e', 'delayed': '#ef4444', 'cancelled': '#6b7280' };

    const xPos = (dateStr) => {
        if (!dateStr) return LABEL_WIDTH;
        const d = new Date(dateStr);
        const ms = d - rangeStart;
        return LABEL_WIDTH + (ms / totalMs) * CHART_WIDTH;
    };

    let svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${SVG_WIDTH}" height="${TOTAL_HEIGHT}" class="roadmap-gantt-svg">`;

    svg += `<style>
        .gantt-label { font-size: 12px; fill: var(--text-primary, #e0e0e0); cursor: pointer; }
        .gantt-label:hover { fill: var(--accent, #60a5fa); }
        .gantt-label-ticket { font-size: 11px; fill: var(--text-secondary, #a0a0a0); cursor: pointer; }
        .gantt-label-ticket:hover { fill: var(--accent, #60a5fa); }
        .gantt-header-text { font-size: 11px; fill: var(--text-muted, #888); font-weight: 500; }
        .gantt-month-text { font-size: 10px; fill: var(--text-muted, #666); font-weight: 600; }
        .gantt-grid-line { stroke: var(--border-subtle, rgba(255,255,255,0.06)); stroke-width: 1; }
        .gantt-today-line { stroke: var(--accent, #60a5fa); stroke-width: 1.5; stroke-dasharray: 4 3; opacity: 0.7; }
        .gantt-progress-bg { rx: 4; ry: 4; fill: rgba(255,255,255,0.1); }
        .gantt-progress-fill { rx: 4; ry: 4; }
        .gantt-bar-ticket { rx: 3; ry: 3; cursor: pointer; opacity: 0.8; }
        .gantt-bar-ticket:hover { opacity: 1; filter: brightness(1.2); }
        .gantt-expand-icon { font-size: 11px; fill: var(--text-muted, #888); cursor: pointer; }
        .gantt-expand-icon:hover { fill: var(--text-primary, #fff); }
        .gantt-pct { font-size: 10px; fill: #fff; font-weight: 500; }
        .gantt-row-bg:hover { fill: rgba(255,255,255,0.03); }
        .gantt-ms-row-bg { fill: rgba(245,158,11,0.03); }
        .gantt-ms-row-bg:hover { fill: rgba(245,158,11,0.06); }
        .gantt-separator-text { font-size: 11px; fill: var(--text-muted, #888); font-weight: 500; }
    </style>`;

    svg += `<rect width="${SVG_WIDTH}" height="${TOTAL_HEIGHT}" fill="var(--bg-primary, #1a1a2e)" rx="8"/>`;

    // 时间表头 - 月份
    let prevMonth = '';
    for (let i = 0; i < totalDays; i++) {
        const d = new Date(rangeStart.getTime() + i * 86400000);
        const month = fmtMonth(d);
        if (month !== prevMonth) {
            const x = LABEL_WIDTH + i * DAY_WIDTH;
            svg += `<text x="${x + 4}" y="16" class="gantt-month-text">${month}</text>`;
            prevMonth = month;
        }
    }

    // 时间表头 - 日期
    for (let i = 0; i < totalDays; i++) {
        const d = new Date(rangeStart.getTime() + i * 86400000);
        const x = LABEL_WIDTH + i * DAY_WIDTH;
        svg += `<text x="${x + DAY_WIDTH / 2}" y="36" text-anchor="middle" class="gantt-header-text">${fmtDate(d)}</text>`;
    }

    svg += `<line x1="0" y1="${HEADER_HEIGHT}" x2="${SVG_WIDTH}" y2="${HEADER_HEIGHT}" class="gantt-grid-line" stroke-width="2"/>`;

    for (let i = 0; i <= totalDays; i++) {
        const x = LABEL_WIDTH + i * DAY_WIDTH;
        svg += `<line x1="${x}" y1="${HEADER_HEIGHT}" x2="${x}" y2="${TOTAL_HEIGHT}" class="gantt-grid-line"/>`;
    }

    // Today 线
    const nowMs = Date.now();
    if (nowMs >= rangeStart.getTime() && nowMs <= rangeEnd.getTime()) {
        const todayX = LABEL_WIDTH + ((nowMs - rangeStart.getTime()) / totalMs) * CHART_WIDTH;
        svg += `<line x1="${todayX}" y1="${HEADER_HEIGHT}" x2="${todayX}" y2="${TOTAL_HEIGHT}" class="gantt-today-line"/>`;
        svg += `<text x="${todayX}" y="${HEADER_HEIGHT - 4}" text-anchor="middle" style="font-size:9px;fill:var(--accent,#60a5fa);">Today</text>`;
    }

    // 行渲染
    rows.forEach((row, idx) => {
        const y = HEADER_HEIGHT + PADDING_TOP + idx * ROW_HEIGHT;
        const barY = y + 6;

        if (row.type === 'separator') {
            svg += `<rect x="0" y="${y}" width="${SVG_WIDTH}" height="${ROW_HEIGHT}" fill="rgba(255,255,255,0.02)"/>`;
            svg += `<text x="12" y="${y + 22}" class="gantt-separator-text">${row.label}</text>`;
            svg += `<line x1="0" y1="${y + ROW_HEIGHT}" x2="${SVG_WIDTH}" y2="${y + ROW_HEIGHT}" class="gantt-grid-line" opacity="0.5"/>`;
            return;
        }

        if (row.type === 'milestone') {
            const ms = row.data;
            const color = msColors[ms.status] || '#f59e0b';
            const msClass = `ms-${ms.status}`;

            svg += `<rect x="0" y="${y}" width="${SVG_WIDTH}" height="${ROW_HEIGHT}" class="gantt-ms-row-bg"/>`;
            svg += `<line x1="0" y1="${y + ROW_HEIGHT}" x2="${SVG_WIDTH}" y2="${y + ROW_HEIGHT}" class="gantt-grid-line" opacity="0.5"/>`;

            // 展开/收起图标
            const expandIcon = row.expanded ? '▾' : '▸';
            svg += `<text x="8" y="${y + 22}" class="gantt-expand-icon" onclick="toggleRoadmapMs('${ms.id}')">${expandIcon}</text>`;

            // 里程碑名称 ◆
            const truncTitle = ms.title.length > 22 ? ms.title.substring(0, 22) + '…' : ms.title;
            svg += `<text x="24" y="${y + 22}" class="gantt-milestone-label ${msClass}">`;
            svg += `<title>${ms.title} (${ms.progress}%)</title>◆ ${_svgEsc(truncTitle)}</text>`;

            // 里程碑范围条
            if (ms.planned_start && ms.planned_end) {
                const x1 = xPos(ms.planned_start);
                const x2 = xPos(ms.planned_end);
                const barW = Math.max(10, x2 - x1);
                const barH = 18;

                // 预估范围（浅色底）
                svg += `<rect x="${x1}" y="${barY + 2}" width="${barW}" height="${barH}" fill="${color}" class="gantt-ms-range-bar"/>`;

                // 进度填充
                const fillW = barW * (ms.progress || 0) / 100;
                svg += `<rect x="${x1}" y="${barY + 2}" width="${fillW}" height="${barH}" fill="${color}" class="gantt-ms-range-fill"/>`;

                // 进度文字
                if (barW > 40) {
                    svg += `<text x="${x1 + barW / 2}" y="${barY + barH / 2 + 5}" text-anchor="middle" class="gantt-pct">${ms.progress || 0}%</text>`;
                }

                // 尾部钻石标记（里程碑结束节点）
                const diamondX = x2;
                const diamondY = barY + barH / 2 + 2;
                const ds = 6; // diamond size
                svg += `<polygon points="${diamondX},${diamondY - ds} ${diamondX + ds},${diamondY} ${diamondX},${diamondY + ds} ${diamondX - ds},${diamondY}" class="gantt-milestone-diamond ${msClass}">`;
                svg += `<title>🏁 ${ms.title} - ${ms.planned_end}</title></polygon>`;
            }

            // 关联需求数量标签
            const reqCount = (reqByMs[ms.id] || []).length;
            if (reqCount > 0) {
                const endX = ms.planned_end ? xPos(ms.planned_end) + 14 : LABEL_WIDTH + 10;
                svg += `<text x="${endX}" y="${barY + 16}" style="font-size:10px;fill:var(--text-muted,#888);">${reqCount} 需求</text>`;
            }

        } else if (row.type === 'req') {
            const req = row.data;
            const hasTickets = req.tickets && req.tickets.length > 0;
            const expandIcon = hasTickets ? (row.expanded ? '▾' : '▸') : '·';
            const barH = 20;

            svg += `<rect x="0" y="${y}" width="${SVG_WIDTH}" height="${ROW_HEIGHT}" fill="transparent" class="gantt-row-bg"/>`;
            svg += `<line x1="0" y1="${y + ROW_HEIGHT}" x2="${SVG_WIDTH}" y2="${y + ROW_HEIGHT}" class="gantt-grid-line" opacity="0.3"/>`;

            // 展开图标
            const indentX = req.milestone_id ? 24 : 8;
            if (hasTickets) {
                svg += `<text x="${indentX}" y="${y + 22}" class="gantt-expand-icon" onclick="toggleRoadmapReq('${req.id}')">${expandIcon}</text>`;
            }

            // 需求名称
            const labelX = indentX + (hasTickets ? 14 : 4);
            const maxLen = req.milestone_id ? 18 : 22;
            const truncTitle = req.title.length > maxLen ? req.title.substring(0, maxLen) + '…' : req.title;
            svg += `<text x="${labelX}" y="${y + 22}" class="gantt-label" onclick="showPipelineForReq('${req.id}')">`;
            svg += `<title>${req.title}</title>${_svgEsc(truncTitle)}</text>`;

            // 甘特条
            const x1 = xPos(req.start);
            const x2 = xPos(req.end);
            const barW = Math.max(8, x2 - x1);
            const color = phaseColors[req.phase] || '#3b82f6';

            svg += `<rect x="${x1}" y="${barY + 1}" width="${barW}" height="${barH}" class="gantt-progress-bg"/>`;
            const fillW = barW * req.progress / 100;
            svg += `<rect x="${x1}" y="${barY + 1}" width="${fillW}" height="${barH}" fill="${color}" class="gantt-progress-fill" onclick="showPipelineForReq('${req.id}')"><title>${req.title} (${req.progress}%)</title></rect>`;
            if (barW > 40) {
                svg += `<text x="${x1 + barW / 2}" y="${barY + barH / 2 + 4}" text-anchor="middle" class="gantt-pct">${req.progress}%</text>`;
            }
            if (req.ticket_count > 0) {
                svg += `<text x="${x1 + barW + 6}" y="${barY + barH / 2 + 4}" style="font-size:10px;fill:var(--text-muted,#888);">${req.ticket_count} 工单</text>`;
            }

        } else if (row.type === 'ticket') {
            const ticket = row.data;
            const barH = 16;

            svg += `<rect x="0" y="${y}" width="${SVG_WIDTH}" height="${ROW_HEIGHT}" fill="transparent" class="gantt-row-bg"/>`;
            svg += `<line x1="0" y1="${y + ROW_HEIGHT}" x2="${SVG_WIDTH}" y2="${y + ROW_HEIGHT}" class="gantt-grid-line" opacity="0.2"/>`;

            const truncTitle = ticket.title.length > 16 ? ticket.title.substring(0, 16) + '…' : ticket.title;
            svg += `<text x="50" y="${y + 20}" class="gantt-label-ticket" onclick="openTicketDrawer('${ticket.id}')">`;
            svg += `<title>${ticket.title}</title>↳ ${_svgEsc(truncTitle)}</text>`;

            const x1 = xPos(ticket.start);
            const x2 = xPos(ticket.end);
            const barW = Math.max(6, x2 - x1);
            const color = phaseColors[ticket.phase] || '#6b7280';

            svg += `<rect x="${x1}" y="${barY + 3}" width="${barW}" height="${barH}" fill="${color}" class="gantt-bar-ticket" onclick="openTicketDrawer('${ticket.id}')">`;
            svg += `<title>${ticket.title} [${ticket.status}]</title></rect>`;

            if (ticket.assigned_agent && barW > 50) {
                svg += `<text x="${x1 + 4}" y="${barY + barH / 2 + 5}" style="font-size:9px;fill:#fff;opacity:0.8;">${ticket.assigned_agent.replace('Agent', '')}</text>`;
            }
        }
    });

    svg += '</svg>';
    container.innerHTML = `<div class="roadmap-gantt-scroll">${svg}</div>`;
}

/** SVG 转义 */
function _svgEsc(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/** 切换里程碑展开/收起 */
function toggleRoadmapMs(msId) {
    if (!window._roadmapExpanded) window._roadmapExpanded = {};
    const key = `ms_${msId}`;
    window._roadmapExpanded[key] = window._roadmapExpanded[key] === false ? true : false;
    if (_roadmapData) renderRoadmapGantt(_roadmapData);
}

/** 切换需求展开/收起 */
function toggleRoadmapReq(reqId) {
    if (!window._roadmapExpanded) window._roadmapExpanded = {};
    window._roadmapExpanded[reqId] = !window._roadmapExpanded[reqId];
    if (_roadmapData) {
        if (_roadmapView === 'gantt') renderRoadmapGantt(_roadmapData);
    }
}

/** 从甘特图点击跳转到 Pipeline */
function showPipelineForReq(reqId) {
    if (typeof showPipeline === 'function') {
        showPipeline(reqId);
    } else {
        currentPipelineReqId = reqId;
        switchTab('pipeline');
    }
}


// ==================== Roadmap 列表视图（里程碑分组） ====================

function renderRoadmapList(data) {
    const container = document.getElementById('roadmapListContainer');
    if (!container || !data) return;

    const milestones = data.milestones || [];
    const reqs = data.requirements || [];

    if (milestones.length === 0 && reqs.length === 0) {
        container.innerHTML = `<div class="roadmap-ai-hint">
            <div class="emoji">📋</div>
            <p>暂无里程碑数据</p>
            <button class="btn btn-primary" onclick="regenerateRoadmap()">🤖 让 AI 生成 Roadmap</button>
        </div>`;
        return;
    }

    const priorityLabels = { critical: '🔴 紧急', high: '🟠 高', medium: '🟡 中', low: '🟢 低' };
    const phaseLabels = {
        planned: '📝 计划中', analyzing: '🔍 分析中', in_progress: '🚀 进行中',
        paused: '⏸️ 已暂停', completed: '✅ 已完成', cancelled: '❌ 已取消',
    };
    const msStatusLabels = {
        planned: '计划中', in_progress: '进行中', completed: '已完成', delayed: '已延期', cancelled: '已取消'
    };
    const msIcons = {
        planned: '🏁', in_progress: '🚀', completed: '✅', delayed: '⚠️', cancelled: '❌'
    };

    // 按里程碑分组
    const reqByMs = {};
    const unassignedReqs = [];
    reqs.forEach(req => {
        if (req.milestone_id) {
            if (!reqByMs[req.milestone_id]) reqByMs[req.milestone_id] = [];
            reqByMs[req.milestone_id].push(req);
        } else {
            unassignedReqs.push(req);
        }
    });

    let html = '';

    // 各里程碑分组
    milestones.forEach(ms => {
        const msClass = `ms-${ms.status}`;
        const msReqs = reqByMs[ms.id] || [];
        const icon = msIcons[ms.status] || '🏁';

        html += `<div class="roadmap-milestone-group">
            <div class="roadmap-milestone-header ${msClass}" onclick="toggleMsListGroup('${ms.id}')">
                <div class="roadmap-ms-icon">${icon}</div>
                <div class="roadmap-ms-info">
                    <div class="roadmap-ms-title">◆ ${_htmlEsc(ms.title)}</div>
                    <div class="roadmap-ms-desc">${_htmlEsc(ms.description || '')}</div>
                </div>
                <div class="roadmap-ms-meta">
                    <span class="roadmap-ms-status-tag ${msClass}">${msStatusLabels[ms.status] || ms.status}</span>
                    <div class="roadmap-ms-progress-wrap">
                        <div class="roadmap-ms-progress-bar">
                            <div class="roadmap-ms-progress-fill" style="width:${ms.progress || 0}%"></div>
                        </div>
                        <span class="roadmap-ms-progress-pct">${ms.progress || 0}%</span>
                    </div>
                    <span class="roadmap-ms-date">${formatShortDate(ms.planned_start)} → ${formatShortDate(ms.planned_end)}</span>
                </div>
            </div>
            <div class="roadmap-ms-reqs" id="ms-reqs-${ms.id}">`;

        if (msReqs.length === 0) {
            html += `<div class="roadmap-no-tickets" style="margin:8px 0;">暂无关联需求</div>`;
        } else {
            html += '<div class="roadmap-list">';
            msReqs.forEach(req => { html += _renderReqListItem(req, priorityLabels, phaseLabels); });
            html += '</div>';
        }

        html += `</div></div>`;
    });

    // 未分组需求
    if (unassignedReqs.length > 0) {
        html += `<div class="roadmap-unassigned-group">
            <div class="roadmap-unassigned-header">📋 未关联里程碑 (${unassignedReqs.length})</div>
            <div class="roadmap-list">`;
        unassignedReqs.forEach(req => { html += _renderReqListItem(req, priorityLabels, phaseLabels); });
        html += '</div></div>';
    }

    container.innerHTML = html;
}

/** 渲染单个需求列表项 */
function _renderReqListItem(req, priorityLabels, phaseLabels) {
    const phaseClass = `roadmap-phase-${req.phase}`;
    const priorityLabel = priorityLabels[req.priority] || req.priority;
    const phaseLabel = phaseLabels[req.phase] || req.phase;
    const tickets = req.tickets || [];

    return `
    <div class="roadmap-list-item ${phaseClass}">
        <div class="roadmap-list-header" onclick="toggleRoadmapListItem('${req.id}')">
            <div class="roadmap-list-expand">${tickets.length > 0 ? '▸' : '·'}</div>
            <div class="roadmap-list-info">
                <div class="roadmap-list-title">${_htmlEsc(req.title)}</div>
                <div class="roadmap-list-meta">
                    <span class="roadmap-badge ${phaseClass}">${phaseLabel}</span>
                    <span class="roadmap-meta-item">${priorityLabel}</span>
                    <span class="roadmap-meta-item">🎫 ${req.ticket_count || 0} 工单</span>
                    ${req.module ? `<span class="roadmap-meta-item">📦 ${req.module}</span>` : ''}
                </div>
            </div>
            <div class="roadmap-list-progress">
                <div class="roadmap-progress-bar">
                    <div class="roadmap-progress-fill" style="width:${req.progress}%"></div>
                </div>
                <span class="roadmap-progress-text">${req.progress}%</span>
            </div>
            <div class="roadmap-list-dates">
                <span class="roadmap-date">${formatShortDate(req.start)}</span>
                <span class="roadmap-date-sep">→</span>
                <span class="roadmap-date">${formatShortDate(req.end)}</span>
            </div>
            <button class="btn btn-sm roadmap-list-action" onclick="event.stopPropagation(); showPipelineForReq('${req.id}')">Pipeline ▸</button>
        </div>
        <div class="roadmap-list-tickets" id="roadmap-tickets-${req.id}" style="display:none;">
            ${renderRoadmapTicketTable(tickets)}
        </div>
    </div>`;
}

function renderRoadmapTicketTable(tickets) {
    if (!tickets || tickets.length === 0) return '<div class="roadmap-no-tickets">暂无工单</div>';

    const statusLabels = {
        'pending': '待启动', 'architecture_in_progress': '架构中', 'architecture_done': '架构完成',
        'development_in_progress': '开发中', 'development_done': '开发完成',
        'acceptance_passed': '验收通过', 'acceptance_rejected': '验收不通过',
        'testing_in_progress': '测试中', 'testing_done': '测试通过', 'testing_failed': '测试不通过',
        'deploying': '部署中', 'deployed': '已部署', 'cancelled': '已取消',
    };

    let html = '<table class="roadmap-ticket-table"><thead><tr>';
    html += '<th>工单</th><th>状态</th><th>类型</th><th>模块</th><th>Agent</th><th>时间</th>';
    html += '</tr></thead><tbody>';

    tickets.forEach(t => {
        const statusLabel = statusLabels[t.status] || t.status;
        html += `<tr class="roadmap-ticket-row" onclick="openTicketDrawer('${t.id}')">
            <td class="roadmap-ticket-title">${_htmlEsc(t.title)}</td>
            <td><span class="status-tag status-${t.phase}">${statusLabel}</span></td>
            <td>${t.type || '-'}</td>
            <td>${t.module || '-'}</td>
            <td>${t.assigned_agent ? t.assigned_agent.replace('Agent', '') : '-'}</td>
            <td class="roadmap-ticket-date">${formatShortDate(t.start)} → ${formatShortDate(t.end)}</td>
        </tr>`;
    });

    html += '</tbody></table>';
    return html;
}

/** 展开/收起列表中的需求工单 */
function toggleRoadmapListItem(reqId) {
    const el = document.getElementById(`roadmap-tickets-${reqId}`);
    if (!el) return;
    const isHidden = el.style.display === 'none';
    el.style.display = isHidden ? '' : 'none';

    const item = el.closest('.roadmap-list-item');
    if (item) {
        const arrow = item.querySelector('.roadmap-list-expand');
        if (arrow && arrow.textContent !== '·') {
            arrow.textContent = isHidden ? '▾' : '▸';
        }
    }
}

/** 展开/收起里程碑下的需求 */
function toggleMsListGroup(msId) {
    const el = document.getElementById(`ms-reqs-${msId}`);
    if (!el) return;
    const isHidden = el.style.display === 'none';
    el.style.display = isHidden ? '' : 'none';
}

/** 短日期格式 */
function formatShortDate(isoStr) {
    if (!isoStr) return '-';
    try {
        const d = new Date(isoStr);
        return `${d.getMonth() + 1}/${d.getDate()}`;
    } catch { return '-'; }
}

/** HTML 转义 */
function _htmlEsc(s) {
    const el = document.createElement('div');
    el.textContent = s || '';
    return el.innerHTML;
}


// ==================== CI/CD Pipeline ====================

const CI_STAGE_META = {
    develop_build: { name: 'Develop 构建测试', icon: '🔨', desc: '构建 develop 分支，测试通过后合入 master' },
    master_build:  { name: 'Master 构建测试',  icon: '🧪', desc: '构建 master 分支，集成测试通过后触发部署' },
    deploy:        { name: '部署上线',         icon: '🚀', desc: 'master 构建通过后自动部署到生产环境' },
};

async function loadCICD() {
    if (!currentProjectId) return;
    try {
        const [statusRes, buildsRes] = await Promise.all([
            fetch(`${API}/projects/${currentProjectId}/ci/status`),
            fetch(`${API}/projects/${currentProjectId}/ci/builds?limit=30`),
        ]);
        const status = await statusRes.json();
        const buildsData = await buildsRes.json();
        renderCICDPipeline(status);
        renderCICDBuildHistory(buildsData.builds || []);
    } catch (e) {
        console.error('loadCICD error:', e);
        document.getElementById('cicdPipelineFlow').innerHTML = '<div class="empty-state"><p>加载 CI/CD 数据失败</p></div>';
    }
}

function renderCICDPipeline(status) {
    const container = document.getElementById('cicdPipelineFlow');
    if (!container) return;

    const stages = status.stages || {};
    let html = '<div class="cicd-stages-row">';

    const stageOrder = ['develop_build', 'master_build', 'deploy'];
    stageOrder.forEach((type, idx) => {
        const meta = CI_STAGE_META[type];
        const stage = stages[type] || {};
        const latest = stage.latest;

        let stageStatus = 'pending';
        let statusText = '未构建';
        let statusClass = 'pending';
        let commitText = '-';
        let timeText = '-';
        let durationText = '-';

        if (latest) {
            stageStatus = latest.status;
            const statusLabels = { pending: '排队中', running: '构建中', success: '成功', failed: '失败', cancelled: '已取消' };
            statusText = statusLabels[latest.status] || latest.status;
            statusClass = latest.status;
            commitText = latest.commit_hash ? latest.commit_hash.substring(0, 8) : '-';
            if (latest.created_at) {
                try { timeText = new Date(latest.created_at).toLocaleString('zh-CN', {month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}); } catch {}
            }
            if (latest.started_at && latest.completed_at) {
                try {
                    const dur = Math.round((new Date(latest.completed_at) - new Date(latest.started_at)) / 1000);
                    durationText = dur >= 60 ? `${Math.floor(dur/60)}m ${dur%60}s` : `${dur}s`;
                } catch {}
            }
        }

        html += `
        <div class="cicd-stage cicd-stage-${statusClass}">
            <div class="cicd-stage-header">
                <span class="cicd-stage-icon">${meta.icon}</span>
                <span class="cicd-stage-name">${meta.name}</span>
            </div>
            <div class="cicd-stage-status">
                <span class="cicd-status-dot cicd-dot-${statusClass}"></span>
                <span class="cicd-status-text">${statusText}</span>
            </div>
            <div class="cicd-stage-details">
                <div class="cicd-detail-row"><span class="cicd-detail-label">Commit</span><span class="cicd-detail-value">${commitText}</span></div>
                <div class="cicd-detail-row"><span class="cicd-detail-label">时间</span><span class="cicd-detail-value">${timeText}</span></div>
                <div class="cicd-detail-row"><span class="cicd-detail-label">耗时</span><span class="cicd-detail-value">${durationText}</span></div>
            </div>
            ${latest && latest.error_message ? `<div class="cicd-stage-error">${_htmlEsc(latest.error_message)}</div>` : ''}
            <div class="cicd-stage-desc">${meta.desc}</div>
        </div>
        ${idx < stageOrder.length - 1 ? '<div class="cicd-connector"><span>→</span></div>' : ''}`;
    });

    html += '</div>';
    container.innerHTML = html;
}

function renderCICDBuildHistory(builds) {
    const container = document.getElementById('cicdBuildHistory');
    if (!container) return;

    if (!builds.length) {
        container.innerHTML = '<div class="empty-state" style="padding:24px;"><p>暂无构建记录</p><p style="font-size:12px;color:var(--text-muted);">点击上方按钮手动触发构建，或等待系统自动调度</p></div>';
        return;
    }

    const typeLabels = { develop_build: 'Develop', master_build: 'Master', deploy: '部署' };
    const statusIcons = { pending: '⏳', running: '🔄', success: '✅', failed: '❌', cancelled: '⚪' };

    let html = '<table class="cicd-table"><thead><tr>';
    html += '<th>状态</th><th>类型</th><th>分支</th><th>Commit</th><th>触发</th><th>时间</th><th>耗时</th><th>操作</th>';
    html += '</tr></thead><tbody>';

    builds.forEach(b => {
        const statusIcon = statusIcons[b.status] || '❓';
        const typeLabel = typeLabels[b.build_type] || b.build_type;
        const triggerLabel = b.trigger === 'auto' ? '自动' : '手动';
        let timeStr = '-';
        let durStr = '-';

        if (b.created_at) {
            try { timeStr = new Date(b.created_at).toLocaleString('zh-CN', {month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'}); } catch {}
        }
        if (b.started_at && b.completed_at) {
            try {
                const dur = Math.round((new Date(b.completed_at) - new Date(b.started_at)) / 1000);
                durStr = dur >= 60 ? `${Math.floor(dur/60)}m ${dur%60}s` : `${dur}s`;
            } catch {}
        }

        const cancelBtn = (b.status === 'pending' || b.status === 'running')
            ? `<button class="btn btn-sm" onclick="cancelCIBuild('${b.id}')">取消</button>`
            : '';

        html += `<tr class="cicd-row-${b.status}">`;
        html += `<td>${statusIcon} ${b.status}</td>`;
        html += `<td><span class="cicd-type-badge cicd-type-${b.build_type}">${typeLabel}</span></td>`;
        html += `<td>${b.branch}</td>`;
        html += `<td><code>${b.commit_hash ? b.commit_hash.substring(0, 8) : '-'}</code></td>`;
        html += `<td>${triggerLabel}</td>`;
        html += `<td>${timeStr}</td>`;
        html += `<td>${durStr}</td>`;
        html += `<td>${cancelBtn}</td>`;
        html += '</tr>';

        if (b.error_message) {
            html += `<tr class="cicd-error-row"><td colspan="8" class="cicd-error-cell">${_htmlEsc(b.error_message)}</td></tr>`;
        }
    });

    html += '</tbody></table>';
    container.innerHTML = html;
}

async function triggerCIBuild(buildType) {
    if (!currentProjectId) return;
    const labels = { develop_build: 'Develop 构建', master_build: 'Master 构建', deploy: '部署' };
    if (!confirm(`确定要手动触发 ${labels[buildType] || buildType} 吗？`)) return;

    try {
        const res = await fetch(`${API}/projects/${currentProjectId}/ci/builds/trigger`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ build_type: buildType }),
        });
        if (res.ok) {
            showToast(`${labels[buildType]} 已触发`, 'success');
            setTimeout(() => loadCICD(), 1000);
        } else {
            const err = await res.json();
            showToast(`触发失败: ${err.detail || '未知错误'}`, 'error');
        }
    } catch (e) {
        showToast(`触发失败: ${e.message}`, 'error');
    }
}

async function cancelCIBuild(buildId) {
    if (!currentProjectId) return;
    try {
        const res = await fetch(`${API}/projects/${currentProjectId}/ci/builds/${buildId}/cancel`, { method: 'POST' });
        if (res.ok) {
            showToast('构建已取消', 'info');
            loadCICD();
        } else {
            showToast('取消失败', 'error');
        }
    } catch (e) {
        showToast(`取消失败: ${e.message}`, 'error');
    }
}

// ==================== BUG 管理 ====================

const BUG_STATUS_LABELS = { open:'待处理', in_dev:'修复中', in_test:'测试中', fixed:'已修复' };
const BUG_PRIORITY_LABELS = { critical:'🔴 紧急', high:'🟠 高', medium:'🟡 中', low:'🟢 低' };
const BUG_STATUS_COLORS  = { open:'var(--danger,#ea4a5a)', in_dev:'var(--warning,#f0a500)', in_test:'var(--primary)', fixed:'var(--success,#34d058)' };

/** 加载 BUG 列表 */
async function loadBugs() {
    if (!currentProjectId) return;
    const filter = document.getElementById('bugStatusFilter')?.value || '';
    const url = `/projects/${currentProjectId}/bugs` + (filter ? `?status=${filter}` : '');
    try {
        const data = await api(url);
        renderBugList(data.bugs || []);
    } catch (e) {
        showToast('加载 BUG 列表失败: ' + e.message, 'error');
    }
}

/** 渲染 BUG 列表 */
function renderBugList(bugs) {
    const el = document.getElementById('bugList');
    if (!el) return;
    if (!bugs.length) {
        el.innerHTML = '<div class="empty-state"><div class="emoji">🐛</div><p>暂无 BUG，项目很健康！</p></div>';
        return;
    }
    el.innerHTML = bugs.map(b => {
        const statusColor = BUG_STATUS_COLORS[b.status] || 'var(--text-muted)';
        const statusLabel = BUG_STATUS_LABELS[b.status] || b.status;
        const priorityLabel = BUG_PRIORITY_LABELS[b.priority] || b.priority;
        const fixedInfo = b.fixed_at ? `<span class="bug-meta-item">✅ 修复于 ${b.fixed_at.slice(0,10)}</span>` : '';
        const versionInfo = b.version_id ? `<span class="bug-meta-item">📦 已并入版本</span>` : '';
        const canFix = b.status === 'open';
        const ticketLink = b.ticket_id
            ? `<button class="btn btn-sm btn-ticket-link" onclick="event.stopPropagation();openTicketDrawer('${b.ticket_id}')" title="查看关联工单">🎫 查看工单</button>`
            : '';
        return `
        <div class="bug-card" data-bug-id="${b.id}">
            <div class="bug-card-header">
                <span class="bug-status-badge" style="background:${statusColor}20;color:${statusColor};border:1px solid ${statusColor}40;">${statusLabel}</span>
                <span class="bug-priority">${priorityLabel}</span>
                <span class="bug-id">#${b.id.slice(-6)}</span>
            </div>
            <div class="bug-card-title">${escapeHtml(b.title)}</div>
            <div class="bug-card-desc">${escapeHtml((b.description || '').slice(0, 120))}${(b.description || '').length > 120 ? '...' : ''}</div>
            <div class="bug-card-meta">
                <span class="bug-meta-item">🕐 ${b.created_at.slice(0,10)}</span>
                ${fixedInfo}
                ${versionInfo}
            </div>
            <div class="bug-card-actions">
                ${canFix ? `<button class="btn btn-sm btn-primary" onclick="startBugFix('${b.id}')">🔧 开始修复</button>` : ''}
                ${ticketLink}
                <button class="btn btn-sm" onclick="deleteBug('${b.id}')">🗑 删除</button>
            </div>
        </div>`;
    }).join('');
}

/** 显示上报 BUG 模态框 */
async function showCreateBugModal() {
    if (!currentProjectId) return;
    try {
        const data = await api(`/projects/${currentProjectId}/requirements`);
        const sel = document.getElementById('bugRequirementId');
        if (sel) {
            sel.innerHTML = '<option value="">不关联</option>' +
                (data.requirements || []).map(r =>
                    `<option value="${r.id}">${escapeHtml(r.title)}</option>`
                ).join('');
        }
    } catch (_) {}
    document.getElementById('bugTitle').value = '';
    document.getElementById('bugDescription').value = '';
    document.getElementById('bugPriority').value = 'high';
    openModal('createBugModal');
}

/** 提交 BUG */
async function submitBug() {
    const title = document.getElementById('bugTitle').value.trim();
    const description = document.getElementById('bugDescription').value.trim();
    const priority = document.getElementById('bugPriority').value;
    const requirementId = document.getElementById('bugRequirementId').value || null;
    if (!title) { showToast('请填写 BUG 标题', 'warning'); return; }
    if (!description) { showToast('请填写复现步骤/现象描述', 'warning'); return; }
    try {
        await api(`/projects/${currentProjectId}/bugs`, {
            method: 'POST',
            body: { title, description, priority, requirement_id: requirementId },
        });
        closeModal('createBugModal');
        showToast(`BUG「${title}」已上报`, 'success');
        loadBugs();
    } catch (e) {
        showToast('上报失败: ' + e.message, 'error');
    }
}

/** 触发 BUG 修复工作流 */
async function startBugFix(bugId) {
    if (!currentProjectId) return;
    try {
        await api(`/projects/${currentProjectId}/bugs/${bugId}/start-fix`, { method: 'POST' });
        showToast('修复工作流已启动，DevAgent 开始处理...', 'success');
        loadBugs();
    } catch (e) {
        showToast('启动失败: ' + e.message, 'error');
    }
}

/** 删除 BUG */
async function deleteBug(bugId) {
    if (!confirm('确认删除该 BUG？')) return;
    try {
        await api(`/projects/${currentProjectId}/bugs/${bugId}`, { method: 'DELETE' });
        showToast('BUG 已删除', 'success');
        loadBugs();
    } catch (e) {
        showToast('删除失败: ' + e.message, 'error');
    }
}

/** 聊天中确认上报 BUG */
async function doConfirmBug(cardId) {
    const card = document.getElementById(cardId);
    if (!card || !currentProjectId) return;
    const title = card.dataset.title || '';
    const description = card.dataset.description || '';
    const priority = card.dataset.priority || 'high';
    const requirementId = card.dataset.requirementId || null;
    const images = card.dataset.images ? JSON.parse(card.dataset.images) : [];
    const btns = card.querySelector('.confirm-req-btns');
    if (btns) btns.innerHTML = '<span style="color:var(--text-muted);font-size:12px">⏳ 上报中...</span>';
    try {
        await api(`/projects/${currentProjectId}/chat/confirm-create-bug`, {
            method: 'POST',
            body: { title, description, priority, requirement_id: requirementId || null, images },
        });
        card.style.borderLeftColor = 'var(--success, #34d058)';
        card.querySelector('.action-title').textContent = '✅ BUG 已上报';
        if (btns) btns.innerHTML = `<span class="action-link" onclick="switchTab('bugs')">查看 BUG 列表 →</span>`;
        showToast(`BUG「${title}」已上报`, 'success');
        setTimeout(() => { if (typeof loadBugs === 'function') loadBugs(); }, 500);
    } catch (e) {
        card.style.borderLeftColor = 'var(--danger, #ea4a5a)';
        card.querySelector('.action-title').textContent = '⚠️ 上报失败';
        if (btns) btns.innerHTML = `<span style="color:var(--danger);font-size:12px">${escapeHtml(e.message)}</span>`;
    }
}

// ==================== 知识库管理 ====================

/** 当前知识库编辑器状态 */
let _knowledgeEditorScope = null;   // 'global' | 'project'
let _knowledgeEditorFilename = null; // null = 新建

/** 在项目列表页打开全局知识库 modal（不需要打开项目） */
async function showGlobalKnowledgeModal() {
    const modalId = 'globalKnowledgeModal';
    let modal = document.getElementById(modalId);
    if (modal) modal.remove();

    modal = document.createElement('div');
    modal.id = modalId;
    modal.className = 'modal-overlay active';
    modal.innerHTML = `
        <div class="modal modal-lg">
            <div class="modal-header">
                <h3>📚 全局知识库</h3>
                <button class="btn-icon" onclick="document.getElementById('${modalId}').remove()">&times;</button>
            </div>
            <div class="modal-body" style="padding-bottom:0;">
                <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px;">
                    所有项目共享，适合放编码规范、技术栈说明、安全规则等。（上限 2000 字符/次注入）
                </p>
                <div style="display:flex;justify-content:flex-end;margin-bottom:8px;">
                    <button class="btn btn-primary" onclick="showKnowledgeEditor('global', null)">+ 新建文档</button>
                </div>
                <div id="globalKnowledgeModalList"><div class="loading-sm">加载中...</div></div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="document.getElementById('${modalId}').remove()">关闭</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    _loadGlobalKnowledgeIntoModal();
}

async function _loadGlobalKnowledgeIntoModal() {
    const container = document.getElementById('globalKnowledgeModalList');
    if (!container) return;
    try {
        const res = await api('/knowledge/global');
        renderKnowledgeDocList(container, res.docs || [], 'global', null);
    } catch (e) {
        container.innerHTML = `<div class="empty-state-sm">加载失败: ${escHtml(e.message)}</div>`;
    }
}

/** 加载全局 + 项目知识库文档列表 */
async function loadKnowledgeDocs() {
    // 全局知识库
    const globalList = document.getElementById('globalDocsList');
    if (globalList) {
        globalList.innerHTML = '<div class="loading-sm">加载中...</div>';
        try {
            const res = await api('/knowledge/global');
            renderKnowledgeDocList(globalList, res.docs || [], 'global', null);
        } catch (e) {
            globalList.innerHTML = `<div class="empty-state-sm">加载失败: ${escHtml(e.message)}</div>`;
        }
    }

    // 项目知识库
    const projectList = document.getElementById('projectDocsList');
    if (projectList) {
        if (!currentProjectId) {
            projectList.innerHTML = '<div class="empty-state-sm">请先选择一个项目</div>';
            return;
        }
        projectList.innerHTML = '<div class="loading-sm">加载中...</div>';
        try {
            const res = await api(`/knowledge/projects/${currentProjectId}`);
            renderKnowledgeDocList(projectList, res.docs || [], 'project', currentProjectId);
        } catch (e) {
            projectList.innerHTML = `<div class="empty-state-sm">加载失败: ${escHtml(e.message)}</div>`;
        }
    }
}

/** 渲染文档卡片列表 */
function renderKnowledgeDocList(container, docs, scope, projectId) {
    if (!docs || docs.length === 0) {
        container.innerHTML = '<div class="empty-state-sm">暂无文档，点击「+ 新建文档」添加</div>';
        return;
    }
    container.innerHTML = docs.map(doc => `
        <div class="knowledge-doc-item">
            <div class="knowledge-doc-info">
                <span class="knowledge-doc-icon">📄</span>
                <span class="knowledge-doc-name">${escHtml(doc.filename)}</span>
                <span class="knowledge-doc-size">${_formatDocSize(doc.size || 0)}</span>
            </div>
            <div class="knowledge-doc-actions">
                <button class="btn-sm btn-ghost" onclick="showKnowledgeEditor('${scope}', ${projectId ? `'${projectId}'` : 'null'}, '${escHtml(doc.filename)}')">编辑</button>
                <button class="btn-sm btn-danger-ghost" onclick="deleteKnowledgeDoc('${scope}', ${projectId ? `'${projectId}'` : 'null'}, '${escHtml(doc.filename)}')">删除</button>
            </div>
        </div>
    `).join('');
}

function _formatDocSize(bytes) {
    if (bytes < 1024) return bytes + 'B';
    return (bytes / 1024).toFixed(1) + 'KB';
}

/** 打开知识库编辑器（新建或编辑） */
async function showKnowledgeEditor(scope, projectId, filename) {
    _knowledgeEditorScope = scope;
    _knowledgeEditorFilename = filename || null;

    // 构建 modal
    const isNew = !filename;
    const title = isNew
        ? (scope === 'global' ? '新建全局文档' : '新建项目文档')
        : `编辑：${filename}`;

    let initialContent = '';
    if (!isNew) {
        try {
            const url = scope === 'global'
                ? `/knowledge/global/${encodeURIComponent(filename)}`
                : `/knowledge/projects/${projectId}/${encodeURIComponent(filename)}`;
            const data = await api(url);
            initialContent = data.content || '';
        } catch (e) {
            showToast('加载文档失败: ' + e.message, 'error');
            return;
        }
    }

    const modalId = 'knowledgeEditorModal';
    let modal = document.getElementById(modalId);
    if (modal) modal.remove();

    modal = document.createElement('div');
    modal.id = modalId;
    modal.className = 'modal-overlay active';
    modal.innerHTML = `
        <div class="modal modal-lg">
            <div class="modal-header">
                <h3 class="modal-title">${escHtml(title)}</h3>
                <button class="btn-icon" onclick="closeKnowledgeEditor()">&times;</button>
            </div>
            <div class="modal-body">
                ${isNew ? `
                <div class="form-group" style="margin-bottom:12px;">
                    <label>文件名（.md）</label>
                    <input id="knowledgeDocFilename" type="text"
                        placeholder="例如: coding-standards.md" />
                </div>` : ''}
                <div class="form-group">
                    <label>内容（Markdown）</label>
                    <textarea id="knowledgeDocContent" class="knowledge-editor-textarea"
                        placeholder="# 文档标题&#10;&#10;在此填写知识库内容..."
                        rows="18">${escHtml(initialContent)}</textarea>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="closeKnowledgeEditor()">取消</button>
                <button class="btn btn-primary" onclick="saveKnowledgeDoc('${scope}', ${projectId ? `'${projectId}'` : 'null'})">保存</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);

    // 聚焦到内容或文件名输入框
    setTimeout(() => {
        const filenameInput = document.getElementById('knowledgeDocFilename');
        const contentInput = document.getElementById('knowledgeDocContent');
        if (filenameInput) filenameInput.focus();
        else if (contentInput) contentInput.focus();
    }, 50);
}

/** 关闭知识库编辑器 */
function closeKnowledgeEditor() {
    const modal = document.getElementById('knowledgeEditorModal');
    if (modal) modal.remove();
    _knowledgeEditorScope = null;
    _knowledgeEditorFilename = null;
}

/** 保存知识库文档（新建或更新） */
async function saveKnowledgeDoc(scope, projectId) {
    const isNew = !_knowledgeEditorFilename;
    let filename = _knowledgeEditorFilename;

    if (isNew) {
        const filenameInput = document.getElementById('knowledgeDocFilename');
        if (!filenameInput || !filenameInput.value.trim()) {
            showToast('请输入文件名', 'error');
            return;
        }
        filename = filenameInput.value.trim();
    }

    const contentEl = document.getElementById('knowledgeDocContent');
    const content = contentEl ? contentEl.value : '';

    const url = scope === 'global'
        ? '/knowledge/global'
        : `/knowledge/projects/${projectId}`;

    const saveBtn = document.querySelector('#knowledgeEditorModal .btn-primary');
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = '保存中...'; }

    try {
        await api(url, { method: 'PUT', body: { filename, content } });
        showToast('文档已保存', 'success');
        closeKnowledgeEditor();
        // 刷新设置页列表 + 全局知识库 modal（如果打开着）
        if (document.getElementById('globalDocsList')) loadKnowledgeDocs();
        if (document.getElementById('globalKnowledgeModalList')) _loadGlobalKnowledgeIntoModal();
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
        if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = '保存'; }
    }
}

/** 删除知识库文档 */
async function deleteKnowledgeDoc(scope, projectId, filename) {
    if (!confirm(`确认删除文档「${filename}」？此操作不可撤销。`)) return;

    const url = scope === 'global'
        ? `/knowledge/global/${encodeURIComponent(filename)}`
        : `/knowledge/projects/${projectId}/${encodeURIComponent(filename)}`;

    try {
        await api(url, { method: 'DELETE' });
        showToast(`「${filename}」已删除`, 'success');
        if (document.getElementById('globalDocsList')) loadKnowledgeDocs();
        if (document.getElementById('globalKnowledgeModalList')) _loadGlobalKnowledgeIntoModal();
    } catch (e) {
        showToast('删除失败: ' + e.message, 'error');
    }
}

// ==================== Agent 技能系统（Tool Use）====================

/** 读取后端 agent-tools 状态并同步 UI 开关 */
async function loadAgentToolsStatus() {
    const toggle = document.getElementById('agentToolsToggle');
    const label  = document.getElementById('agentToolsLabel');
    if (!toggle) return;
    try {
        const res = await api('/settings/agent-tools');
        const enabled = res && res.enabled;
        toggle.checked = !!enabled;
        label.textContent = enabled ? '已开启（Agentic 模式）' : '已关闭（One-shot 模式）';
        label.style.color = enabled ? 'var(--accent)' : 'var(--text-muted)';
    } catch (e) {
        // 后端未实现此接口时静默
        label.textContent = '（需后端 ENABLE_AGENT_TOOLS=true）';
    }
}

/** 切换 Agent Tool Use 开关（同步设置到后端） */
async function toggleAgentTools(enabled) {
    const label = document.getElementById('agentToolsLabel');
    try {
        await api('/settings/agent-tools', {
            method: 'POST',
            body: JSON.stringify({ enabled }),
        });
        label.textContent = enabled ? '已开启（Agentic 模式）' : '已关闭（One-shot 模式）';
        label.style.color = enabled ? 'var(--accent)' : 'var(--text-muted)';
        showToast(enabled ? 'Agentic 模式已开启' : 'One-shot 模式已开启', 'success');
    } catch (e) {
        showToast('切换失败：' + e.message + '（请在后端设置 ENABLE_AGENT_TOOLS 环境变量）', 'warning');
        // 回滚 UI
        const toggle = document.getElementById('agentToolsToggle');
        if (toggle) toggle.checked = !enabled;
    }
}
