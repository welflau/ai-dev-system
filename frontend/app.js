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

    // 内容区切换
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    const tabEl = document.getElementById(`tab-${tab}`);
    if (tabEl) tabEl.classList.add('active');

    // 按需加载数据
    if (tab === 'board') refreshBoard();
    if (tab === 'requirements') loadRequirements();
    if (tab === 'ticket-list') loadTicketList();
    if (tab === 'pipeline' && currentPipelineReqId) loadPipeline(currentPipelineReqId);
    if (tab === 'repo') loadRepoTree();
    if (tab === 'stats') loadStats();
    if (tab === 'logs') loadLogs();
    if (tab === 'settings-general') loadSettingsGeneral();
    if (tab === 'settings-repo') loadSettingsRepo();
    if (tab === 'settings-agents') loadAgentList();
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
    openModal('createProjectModal');
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

        let message = `项目「${name}」创建成功`;
        if (data.push_success) {
            message += '，并已推送到远程仓库';
        } else {
            message += '（首次推送失败，请检查远程仓库权限）';
        }
        showToast(message, data.push_success ? 'success' : 'warning');

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
                <h4>产出文件 (${artifacts.length})</h4>
                ${artifacts.map(a => {
                    let filesHtml = '';
                    try {
                        const parsed = JSON.parse(a.content || '{}');
                        if (parsed.files && Array.isArray(parsed.files)) {
                            filesHtml = '<div style="margin-top:6px;">';
                            parsed.files.forEach(f => {
                                const fileName = typeof f === 'string' ? f : (f.path || f.name || f.filename || JSON.stringify(f));
                                filesHtml += `<div style="font-size:12px; color:var(--text-secondary); padding:2px 0;">📄 ${escHtml(fileName)}</div>`;
                            });
                            filesHtml += '</div>';
                        }
                    } catch {}

                    return `
                    <div style="background:var(--bg-elevated); padding:10px; border-radius:var(--radius-sm); margin-bottom:8px; cursor:pointer;" onclick="toggleArtifactContent(this)">
                        <div style="display:flex; align-items:center; gap:8px; font-size:13px;">
                            <span>${getArtifactIcon(a.type)}</span>
                            <span style="font-weight:500;">${escHtml(a.name || a.type)}</span>
                            <span class="tag tag-module" style="font-size:11px;">${escHtml(a.type)}</span>
                            <span style="font-size:11px; color:var(--text-muted); margin-left:auto;">${formatDate(a.created_at)}</span>
                        </div>
                        ${filesHtml}
                        <div class="artifact-content" style="display:none; margin-top:8px; padding:8px; background:var(--bg); border-radius:4px; font-size:12px; color:var(--text-secondary); max-height:300px; overflow-y:auto; white-space:pre-wrap; word-break:break-all;">${escHtml(tryFormatJson(a.content))}</div>
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

/** 渲染 TAPD 风格工单列表表格 */
function renderTicketListTable(container, tickets) {
    if (tickets.length === 0) {
        container.innerHTML = `<div class="empty-state"><div class="emoji">🎫</div><p>暂无工单</p></div>`;
        return;
    }

    let html = `
    <div class="tl-table-header">
        <span class="tl-table-summary">全部工单 <span class="tl-table-count">(${tickets.length})</span></span>
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

    tickets.forEach(t => {
        const statusColor = getStatusColor(t.status);
        const priorityLabel = {1:'P1',2:'P2',3:'P3',4:'P4',5:'P5'};
        const pLabel = priorityLabel[t.priority] || `P${t.priority}`;
        const shortId = (t.id || '').slice(-6);

        html += `
            <tr class="tl-table-row" onclick="openTicketDrawer('${t.id}')">
                <td class="tl-col-id"><span class="tl-id-badge">#${shortId}</span></td>
                <td class="tl-col-title">
                    <span class="tl-title-text">${escHtml(t.title)}</span>
                    ${t.description ? `<span class="tl-title-desc">${escHtml(t.description)}</span>` : ''}
                </td>
                <td class="tl-col-status">
                    <span class="tl-status-badge" style="border-left:3px solid ${statusColor};">
                        ${escHtml(t.status_label || getStatusLabel(t.status))}
                    </span>
                </td>
                <td class="tl-col-type"><span class="tag tag-type" style="font-size:11px;">${escHtml(t.type || 'feature')}</span></td>
                <td class="tl-col-module">${escHtml(t.module || '-')}</td>
                <td class="tl-col-agent">${t.assigned_agent ? `<span class="tag tag-agent" style="font-size:11px;">${escHtml(t.assigned_agent)}</span>` : '<span style="color:var(--text-muted);">未分配</span>'}</td>
                <td class="tl-col-priority"><span class="tag tag-priority-${t.priority}" style="font-size:11px;">${pLabel}</span></td>
                <td class="tl-col-req"><span class="tl-req-link" onclick="event.stopPropagation(); openPipeline('${t.req_id}');">${escHtml(t.req_title || '-')}</span></td>
                <td class="tl-col-time">${formatDateTime(t.created_at)}</td>
            </tr>`;
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

    tickets.forEach(t => {
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
                <div class="tl-board-card" onclick="openTicketDrawer('${t.id}')">
                    <div class="tl-board-card-title">${escHtml(t.title)}</div>
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

            html += `<div class="pl-job-card ${isActive ? 'active' : ''} ${jobCls === 'pending' ? 'job-pending' : ''}" data-job-id="${job.id}" onclick="selectJob('${job.id}', '${stage.key}')">
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
        let reqActions = '';
        if (data.status === 'submitted') {
            reqActions += `<button class="btn btn-primary btn-sm" onclick="decomposeReq('${data.id}')">🤖 AI 拆单</button>`;
            reqActions += `<button class="btn btn-sm" style="color:var(--error); margin-left:8px;" onclick="cancelReq('${data.id}')">✗ 取消</button>`;
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

async function loadRepoTree() {
    const container = document.getElementById('repoTree');
    if (!currentProjectId) {
        container.innerHTML = '<div class="empty-state"><div class="emoji">📂</div><p>请先选择项目</p></div>';
        return;
    }

    container.innerHTML = '<div class="empty-state"><div class="emoji">⏳</div><p>加载中...</p></div>';

    try {
        const tree = await api(`/projects/${currentProjectId}/git/tree`);
        if (!tree.children || tree.children.length === 0) {
            container.innerHTML = '<div class="empty-state"><div class="emoji">📂</div><p>仓库为空或尚未初始化</p></div>';
            return;
        }
        container.innerHTML = renderFileTree(tree.children, 0);
    } catch (err) {
        container.innerHTML = `<div class="empty-state"><div class="emoji">❌</div><p>加载失败: ${err.message}</p></div>`;
    }
}

function renderFileTree(nodes, depth) {
    let html = '';
    for (const node of nodes) {
        const indent = depth * 20;
        if (node.type === 'directory') {
            const hasChildren = node.children && node.children.length > 0;
            html += `<div class="tree-item tree-dir" style="padding-left:${indent}px" onclick="toggleTreeDir(this)">
                <span class="tree-icon">${hasChildren ? '📂' : '📁'}</span>
                <span class="tree-name">${escapeHtml(node.name)}</span>
            </div>`;
            if (hasChildren) {
                html += `<div class="tree-children">${renderFileTree(node.children, depth + 1)}</div>`;
            }
        } else {
            const ext = node.name.split('.').pop().toLowerCase();
            const icon = getFileIcon(ext);
            const size = node.size ? formatFileSize(node.size) : '';
            html += `<div class="tree-item tree-file" style="padding-left:${indent}px" onclick="viewRepoFile('${escapeHtml(node.path)}')">
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
        children.classList.toggle('collapsed');
        const icon = el.querySelector('.tree-icon');
        icon.textContent = children.classList.contains('collapsed') ? '📁' : '📂';
    }
}

async function viewRepoFile(path) {
    const viewer = document.getElementById('repoFileViewer');
    const pathEl = document.getElementById('fileViewerPath');
    const contentEl = document.getElementById('fileViewerContent');

    viewer.style.display = 'block';
    pathEl.textContent = path;
    contentEl.textContent = '加载中...';

    try {
        const data = await api(`/projects/${currentProjectId}/git/file?path=${encodeURIComponent(path)}`);
        contentEl.textContent = data.content || '(空文件)';
    } catch (err) {
        contentEl.textContent = `加载失败: ${err.message}`;
    }
}

function closeFileViewer() {
    document.getElementById('repoFileViewer').style.display = 'none';
}

async function loadGitLog() {
    const panel = document.getElementById('gitLogPanel');
    const list = document.getElementById('gitLogList');
    panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    if (panel.style.display === 'none') return;

    list.innerHTML = '<div class="log-panel-empty">加载中...</div>';

    try {
        const data = await api(`/projects/${currentProjectId}/git/log?limit=30`);
        const commits = data.commits || [];
        if (commits.length === 0) {
            list.innerHTML = '<div class="log-panel-empty">暂无提交记录</div>';
            return;
        }

        list.innerHTML = commits.map(c => `
            <div class="git-commit-item">
                <div class="git-commit-hash">${escapeHtml(c.short_hash)}</div>
                <div class="git-commit-msg">${escapeHtml(c.message)}</div>
                <div class="git-commit-meta">
                    <span>${escapeHtml(c.author)}</span>
                    <span>${formatTime(c.date)}</span>
                </div>
            </div>
        `).join('');
    } catch (err) {
        list.innerHTML = `<div class="log-panel-empty">加载失败: ${err.message}</div>`;
    }
}

function getFileIcon(ext) {
    const icons = {
        py: '🐍', js: '📜', ts: '📘', html: '🌐', css: '🎨',
        md: '📝', json: '📋', yml: '⚙️', yaml: '⚙️', toml: '⚙️',
        txt: '📄', sh: '💻', dockerfile: '🐳', sql: '🗃️',
        png: '🖼️', jpg: '🖼️', svg: '🖼️', gif: '🖼️',
    };
    return icons[ext] || '📄';
}

function formatFileSize(bytes) {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
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

/**
 * 切换聊天面板显示/隐藏
 */
function toggleChatPanel() {
    chatPanelOpen = !chatPanelOpen;
    const layout = document.querySelector('.project-layout');
    const panel = document.getElementById('chatPanel');
    const toggleBtn = document.getElementById('chatToggleBtn');

    if (chatPanelOpen) {
        layout?.classList.add('chat-open');
        toggleBtn?.classList.add('active');
        // 加载聊天历史
        if (chatMode === 'global') {
            loadChatHistory();
        }
    } else {
        layout?.classList.remove('chat-open');
        toggleBtn?.classList.remove('active');
    }
}

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
        if (chatCurrentTicketId) {
            loadTicketConversations(chatCurrentTicketId);
            inputArea.style.display = 'none'; // Job 模式只读
        } else {
            showJobHint();
            inputArea.style.display = 'none';
        }
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
    if (!currentProjectId) return;

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
            appendChatBubble(msg.role, msg.content, msg.created_at, msg.action_data ? JSON.parse(msg.action_data) : null);
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
 * 发送聊天消息
 */
async function sendChatMessage() {
    if (chatSending || chatMode !== 'global') return;

    const input = document.getElementById('chatInput');
    const message = input.value.trim();
    if (!message) return;
    if (!currentProjectId) {
        showToast('请先选择一个项目', 'warning');
        return;
    }

    chatSending = true;
    const sendBtn = document.getElementById('chatSendBtn');
    sendBtn.disabled = true;
    input.value = '';
    autoResizeChatInput();

    // 移除欢迎消息
    const welcome = document.querySelector('.chat-welcome');
    if (welcome) welcome.remove();

    // 添加用户消息气泡
    appendChatBubble('user', message);
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

        const resp = await originalApi(`/projects/${currentProjectId}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: message,
                history: historyToSend,
            }),
        });

        // 移除加载动画
        document.getElementById('chatTyping')?.remove();

        const reply = resp.reply || '(无回复)';
        const action = resp.action || null;

        // 更新历史
        chatHistory.push({ role: 'user', content: message });
        chatHistory.push({ role: 'assistant', content: reply });

        // 添加回复气泡
        appendChatBubble('assistant', reply, null, action);
        scrollChatToBottom();

        // 如果创建了需求，刷新需求列表
        if (action && action.type === 'requirement_created') {
            showToast(`需求「${action.title}」已创建`, 'success');
            // 延迟刷新，避免 UI 卡顿
            setTimeout(() => {
                if (typeof loadRequirements === 'function') loadRequirements();
                if (typeof refreshBoard === 'function') refreshBoard();
            }, 500);
        }

    } catch (e) {
        document.getElementById('chatTyping')?.remove();
        appendChatBubble('assistant', `⚠️ 请求失败: ${e.message}\n\n请检查 LLM 是否已配置。`);
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
function appendChatBubble(role, content, timestamp = null, action = null) {
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
    }

    msgEl.innerHTML = `
        <div class="chat-msg-avatar">${avatar}</div>
        <div class="chat-msg-content">
            <div class="chat-msg-bubble">${formatChatContent(content)}</div>
            ${actionHtml}
            <div class="chat-msg-time">${timeStr}</div>
        </div>
    `;
    container.appendChild(msgEl);
}

/**
 * 格式化聊天内容（简单 Markdown 支持）
 */
function formatChatContent(content) {
    if (!content) return '';
    let text = escapeHtml(content);
    // 代码块
    text = text.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre style="background:var(--bg);padding:8px;border-radius:6px;font-size:12px;overflow-x:auto;margin:4px 0;"><code>$2</code></pre>');
    // 行内代码
    text = text.replace(/`([^`]+)`/g, '<code style="background:var(--bg);padding:1px 4px;border-radius:3px;font-size:12px;">$1</code>');
    // 加粗
    text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // 换行
    text = text.replace(/\n/g, '<br>');
    return text;
}

/**
 * 显示欢迎消息
 */
function showChatWelcome() {
    const container = document.getElementById('chatMessages');
    container.innerHTML = `
        <div class="chat-welcome">
            <div class="chat-welcome-icon">🤖</div>
            <div class="chat-welcome-title">AI 开发助手</div>
            <div class="chat-welcome-desc">
                我可以帮你：查看项目状态、创建需求、回答技术问题<br>
                <small>试试说 "帮我创建一个用户登录功能需求"</small>
            </div>
        </div>
    `;
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

    // 切换到 Job 模式
    setChatMode('job');
}

/**
 * 清除 Job 选择
 */
function clearJobSelection() {
    chatCurrentTicketId = null;
    chatCurrentTicketTitle = '';
    document.querySelector('.chat-job-header')?.remove();
    showJobHint();
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
