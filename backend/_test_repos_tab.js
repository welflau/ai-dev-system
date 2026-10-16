/**
 * 仓库页 Git / P4 双子 Tab + 懒加载文件树：结构断言
 *   node backend/_test_repos_tab.js
 *
 * 为什么是结构断言而不是跑浏览器：这些断言要钉住的是"代码里还在不在"——
 * 比如"目录节点渲染时 children 是空的"，这是懒加载的定义本身。真在浏览器里
 * 跑一遍反而看不出全量和懒加载的区别（小项目两种写法都能出正确的树）。
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const app = fs.readFileSync(path.join(ROOT, 'frontend/app.js'), 'utf8').replace(/\r\n/g, '\n');
const html = fs.readFileSync(path.join(ROOT, 'frontend/index.html'), 'utf8').replace(/\r\n/g, '\n');
const css = fs.readFileSync(path.join(ROOT, 'frontend/styles.css'), 'utf8').replace(/\r\n/g, '\n');

let pass = 0, fail = 0;
function check(name, cond, detail) {
    if (cond) { pass++; console.log(`[OK] ${name}${detail ? ' -- ' + detail : ''}`); }
    else { fail++; console.log(`[FAIL] ${name}${detail ? ' -- ' + detail : ''}`); }
}

// 取 #tab-repo 那一段 html（到下一个 tab-content 为止）
const repoStart = html.indexOf('id="tab-repo"');
const repoEnd = html.indexOf('id="tab-pipeline"', repoStart);
const tabRepo = html.slice(repoStart, repoEnd > 0 ? repoEnd : undefined);

// ── 1. 两个子 Tab，且复用已有的 .inner-tab 样式 ──────────────────
check('#tab-repo 里有 Git 子 Tab',
    /data-vcs-tab="git"/.test(tabRepo) && /switchRepoVcsTab\('git'\)/.test(tabRepo));
check('#tab-repo 里有 P4 子 Tab',
    /data-vcs-tab="p4"/.test(tabRepo) && /switchRepoVcsTab\('p4'\)/.test(tabRepo));
// 复用「Agent 配置」页已有的 .inner-tabs/.inner-tab，不另造一套
check('子 Tab 复用 .inner-tab class（不是新造一套）',
    /class="inner-tabs"[^>]*id="repoVcsTabs"/.test(tabRepo)
    && /class="inner-tab active" data-vcs-tab="git"/.test(tabRepo));
check('.inner-tab 基础样式本来就存在（确实是复用）', /^\.inner-tab \{/m.test(css));
check('仓库选择器容器存在', /id="repoPicker"/.test(tabRepo));
check('两个子 Tab 都有计数位',
    /id="repoVcsCountGit"/.test(tabRepo) && /id="repoVcsCountP4"/.test(tabRepo));

// ── 2. 入口换成 loadRepoPage ─────────────────────────────────────
check("switchTab('repo') 走 loadRepoPage 而不是直接 loadRepoTree",
    /if \(tab === 'repo'\) loadRepoPage\(\);/.test(app));
check('刷新按钮强制重新识别仓库', /onclick="loadRepoPage\(true\)"/.test(tabRepo));
check('loadRepoPage 先拉 /repos 再加载树',
    /async function loadRepoPage/.test(app)
    && /\/repos\$\{q\}`\)/.test(app)
    && /_renderRepoVcsBar\(\);\n\s*await loadRepoTree\(\);/.test(app));

// ── 3. 懒加载：目录节点渲染时不带子节点 ──────────────────────────
// 这条是整个改动的核心。旧版 renderFileTree 递归渲染整棵树，
// 对 OG 的 103 万文件仓库连接口都返回不了。
const rft = app.slice(app.indexOf('function renderFileTree'),
                      app.indexOf('async function toggleTreeDir'));
check('renderFileTree 存在且只有一份', (app.match(/function renderFileTree\(/g) || []).length === 1);
check('目录节点渲染成未加载态 data-loaded="0"', /data-loaded="\$\{preloaded \? '1' : '0'\}"/.test(rft));
check('目录节点带 data-dir-path（懒加载时要用它请求下一层）',
    /data-dir-path="\$\{escapeHtml\(node\.path\)\}"/.test(rft));
check('子容器默认折叠且为空', /<div class="tree-children collapsed">/.test(rft));
check('展开箭头看 has_children（后端给的，不递归数）',
    /node\.has_children !== undefined/.test(rft));

// ── 4. toggleTreeDir 首次展开拉数据 ──────────────────────────────
const ttd = app.slice(app.indexOf('async function toggleTreeDir'),
                      app.indexOf('async function loadRepoBranchSelector'));
check('toggleTreeDir 是 async（要等请求）', /async function toggleTreeDir/.test(app));
check('首次展开才请求（data-loaded 判断）', /el\.dataset\.loaded !== '1'/.test(ttd));
check('展开时调 _fetchRepoLevel 拉这一层', /await _fetchRepoLevel\(el\.dataset\.dirPath/.test(ttd));
check('拉完标记 loaded=1，避免重复请求', /el\.dataset\.loaded = '1';/.test(ttd));
check('请求失败也解锁（不卡在转圈上）',
    /catch \(e\)[\s\S]{0,400}tree-load-error[\s\S]{0,200}el\.dataset\.loaded = '1'/.test(ttd));
check('空目录不发请求', /el\.dataset\.hasChildren === '0'/.test(ttd));
check('_fetchRepoLevel 走按仓库根的 tree 接口',
    /\/repos\/\$\{_repoCurrentKey\}\/tree\$\{q\}/.test(app));

// ── 5. P4 子 Tab 下隐藏分支/提交记录 ─────────────────────────────
const bar = app.slice(app.indexOf('function _renderRepoVcsBar'),
                      app.indexOf('function _renderRepoPicker'));
check('P4 子 Tab 下隐藏分支选择器',
    /const isGit = _repoVcsTab === 'git'/.test(bar)
    && /branchSel\.style\.display = isGit \? '' : 'none'/.test(bar));
check('P4 子 Tab 下隐藏提交记录按钮', /logBtn\.style\.display = isGit \? '' : 'none'/.test(bar));
check('切到 P4 时收起已经打开的 Git Log 面板', /toggleGitLogPanel\(\)/.test(bar));
// 空的一侧置灰但不隐藏 —— 隐藏了用户会以为功能没做
check('为空的子 Tab 置灰而不是隐藏',
    /classList\.toggle\('disabled', n === 0\)/.test(bar) && !/style\.display = 'none'/.test(
        bar.slice(bar.indexOf('#repoVcsTabs'), bar.indexOf('_renderRepoPicker'))));
check('.inner-tab.disabled 有对应样式（只是变淡，仍可点）',
    /\.repo-vcs-bar \.inner-tab\.disabled \{[\s\S]{0,80}opacity/.test(css));

// ── 6. 向后兼容：聊天/产出文件跳转仍打主仓库 ─────────────────────
check('openRepoFileFromChat 仍然存在', /function openRepoFileFromChat\(filePath\)/.test(app));
check('openRepoFileFromChat 仍走 switchTab(repo) + viewRepoFile',
    /switchTab\('repo'\);[\s\S]{0,300}viewRepoFile\(path, null\)/.test(app));
// 仓库页会恢复上次选的仓库；聊天里的路径是主仓库相对路径，必须强制切回去
check('聊天跳转强制回主仓库', /_repoForcePrimaryOnce = true;[\s\S]{0,120}viewRepoFile\(path, null\)/.test(app));
check('产出文件跳转也强制回主仓库',
    /async function openArtifactFile[\s\S]{0,300}_repoForcePrimaryOnce = true/.test(app));
check('_applyForcePrimary 在加载树之前生效',
    app.indexOf('_applyForcePrimary();') < app.indexOf('await loadRepoTree();')
    && app.indexOf('_applyForcePrimary();') > 0);
check('主仓库继续走 /git/file（保留按分支读历史版本的能力）',
    /_isPrimaryRepo\(\)\s*\n?\s*\? `\/projects\/\$\{currentProjectId\}\/git\/file\?path=/.test(app));
check('非主仓库走 /repos/{key}/file',
    /: `\/projects\/\$\{currentProjectId\}\/repos\/\$\{_repoCurrentKey\}\/file\?path=/.test(app));
check('图片预览也按仓库分流',
    /repos\/\$\{_repoCurrentKey\}\/file-raw\?path=/.test(app));
check('没有残留调用已删除的旧 loadRepoTree 入口写法',
    !/switchTab\('repo'\); loadRepoTree\(\);/.test(app));

// ── 7. 两栖仓库在 UI 上要能看出来 ────────────────────────────────
// 同一条仓库会在两个子 Tab 下各出现一次，不标一下用户会以为看重了
check('也在 P4 的 git 仓库有 badge', /r\.also_p4 && _repoVcsTab === 'git'/.test(app));
check('也是 Git 的 P4 仓库有 badge', /r\.also_p4 && _repoVcsTab === 'p4'/.test(app));
check('P4 分组包含 also_p4 的仓库（前端按后端分组取数）',
    /_repoList\.p4/.test(app));
check('other 分组挂在 Git 侧，不被丢掉',
    /\.\.\.\(_repoList\.other \|\| \[\]\)/.test(app));

// ── 8. 状态持久化 / 切项目重置 ───────────────────────────────────
check('子 Tab 和仓库选择按项目记到 localStorage',
    /ads_repo_pref_\$\{pid\}/.test(app) && /localStorage\.setItem\(_repoPrefKey/.test(app));
check('切项目重新识别（_repoLoadedFor 比对）',
    /_repoLoadedFor !== currentProjectId/.test(app));
check('识别失败退回单仓库模式而不是白屏',
    /仓库识别失败，退回单仓库模式/.test(app));
check('没有仓库 key 时 _fetchRepoLevel 退回 /git/tree',
    /const tree = await api\(`\/projects\/\$\{currentProjectId\}\/git\/tree`\)/.test(app));

// ── 9. CSS ───────────────────────────────────────────────────────
check('.repo-vcs-bar 有样式', /^\.repo-vcs-bar \{/m.test(css));
check('.repo-picker 有样式', /^\.repo-picker \{/m.test(css));
check('.tree-truncated 有样式（超过 500 条的提示）', /\.tree-truncated/.test(css));
check('.tree-item.loading 有样式', /\.tree-item\.loading \{/.test(css));
// 多插了一条 bar，workspace 的 flex:1 不能被它稀释
check('子 Tab 栏不参与拉伸（否则 workspace 撑不满）',
    /#tab-repo \.repo-vcs-bar \{[\s\S]{0,60}flex-shrink: 0/.test(css));
check('.repo-workspace 仍然 flex:1 + min-height:0',
    /#tab-repo \.repo-workspace \{[\s\S]{0,80}flex: 1;[\s\S]{0,40}min-height: 0/.test(css));

console.log(`\n=== ${pass} 通过 / ${fail} 失败 ===`);
process.exit(fail ? 1 : 0);
