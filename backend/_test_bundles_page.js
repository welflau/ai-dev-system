/**
 * 「套件与插件」页 + Plugin 来源徽章：结构断言
 *   node backend/_test_bundles_page.js
 *
 * 钉住三件容易在后续改动里悄悄坏掉的事：
 *   1. ConfigPack 是「搬」不是「抄」—— 旧的 inner-panel-packs 必须已经没了，
 *      不然两个面板抢同一批 DOM id，谁后渲染谁赢。
 *   2. inner-tab 切换必须按页限定 —— 这个 class 现在两个页面在用。
 *   3. plugin 这个来源要在 6 处都接上（meta / 芯片 / 分组顺序 / 5 个面板标题 /
 *      详情 registry），漏一处就是「有数字点进去空白」或「undefined undefined」。
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

// ── 1. 新页存在，且挂在 Agent 分组下 ────────────────────────────────
const bStart = html.indexOf('id="tab-bundles"');
const bEnd = html.indexOf('id="tab-settings-knowledge"', bStart);
const tabBundles = bStart >= 0 ? html.slice(bStart, bEnd > 0 ? bEnd : undefined) : '';

check('#tab-bundles 页面存在', bStart >= 0);
check('侧栏 Agent 分组里有入口',
    /data-tab="bundles" onclick="switchTab\('bundles'\)"/.test(html));
check('bundles 登记进 NAV_GROUPS.agent',
    /agent:\s*\{ tabs: \['agents', 'settings-agents', 'bundles'\]/.test(app));
check('bundles 有页面标签文案', /bundles: '套件与插件'/.test(app));
check("switchTab('bundles') 会渲染", /if \(tab === 'bundles'\) switchBundleTab\(_bundleTab\)/.test(app));

// ── 2. ConfigPack 是搬迁：旧位置必须已清空 ─────────────────────────
check('旧的 inner-panel-packs 面板已移除', !/id="inner-panel-packs"/.test(html));
check('「Agent / 扩展」的 ConfigPack inner-tab 已移除',
    !/data-inner-tab="packs" onclick="switchAgentConfigTab/.test(html));
check('switchAgentConfigTab 不再加载 packs',
    !/switchAgentConfigTab[\s\S]{0,600}?if \(inner === 'packs'\) loadProjectPacks/.test(app));
check("switchTab('settings-agents') 不再加载 packs",
    !/if \(tab === 'settings-agents'\) \{[\s\S]{0,300}?loadProjectPacks\(\)/.test(app));
check('ConfigPack 的 DOM id 原样复用（不是另造一套）',
    /id="installedPacksList"/.test(tabBundles) && /id="availablePacksList"/.test(tabBundles));
check('搜索框注入改指向新面板',
    /_injectPackSearchBox[\s\S]{0,300}?getElementById\('bundle-panel-packs'\)/.test(app));
check('能力横幅深链改跳新页',
    /_pendingPackHighlight = 'superpowers';\s*\n\s*switchTab\('bundles'\);/.test(app));

// ── 3. inner-tab 切换按页限定 ───────────────────────────────────────
// 全局 querySelectorAll('.inner-tab') 会把另一页的标签一起取消激活
check('_switchInnerTab 按 root 限定查询',
    /function _switchInnerTab\(rootId, panelPrefix, inner\)[\s\S]{0,400}?root\.querySelectorAll\('\.inner-tab'\)/.test(app));
check('switchAgentConfigTab 走限定版',
    /function switchAgentConfigTab[\s\S]{0,200}?_switchInnerTab\('tab-settings-agents', 'inner-panel-'/.test(app));
check('switchBundleTab 走限定版',
    /function switchBundleTab[\s\S]{0,200}?_switchInnerTab\('tab-bundles', 'bundle-panel-'/.test(app));
check('没有残留的全局 .inner-tab 全量切换',
    !/document\.querySelectorAll\('\.inner-tab'\)/.test(app));

// ── 4. 作用域必须标出来（一个可装卸、一个只读）─────────────────────
check('ConfigPack 标「项目级 · 可装可卸」',
    /bundle-scope-project">项目级 · 可装可卸/.test(tabBundles));
check('Plugin 标「本机级 · 只读」',
    /bundle-scope-machine">本机级 · 只读/.test(tabBundles));
check('ADS 套件标「进程级 · trait 启用」',
    /bundle-scope-process">进程级 · trait 启用/.test(tabBundles));
check('作用域徽章有样式',
    /\.bundle-scope-project \{/.test(css)
    && /\.bundle-scope-machine \{/.test(css)
    && /\.bundle-scope-process \{/.test(css));
check('有 ADS 套件 inner-tab', /data-inner-tab="ads" onclick="switchBundleTab\('ads'\)"/.test(tabBundles));
check('switchBundleTab 会加载 ADS 套件',
    /if \(inner === 'ads'\) loadAdsPluginList/.test(app));
check('ADS 列表走 /api/plugins/ads', /\/plugins\/ads/.test(app));
check('Plugin 面板说明写明 ADS 只读不改动', /只读取不改动/.test(tabBundles));
check('页面没有「市场」字样（ADS 装不了插件，不能这么承诺）',
    !/>\s*[^<]*市场<\/h2>/.test(tabBundles) && !/📦 插件市场/.test(tabBundles));

// ── 5. 「扫到几百个」和「装了几个」要分开 ───────────────────────────
check('有「含市场里未安装的」开关（默认不勾）',
    /id="bundlePluginShowAll"/.test(tabBundles)
    && !/id="bundlePluginShowAll"[^>]*\bchecked\b/.test(tabBundles));
check('摘要区分 已启用 / 已安装 / 市场可见',
    /已启用 <strong/.test(app) && /已安装 <strong/.test(app) && /市场可见 <strong/.test(app));
check('未安装的显示为「市场可见」而不是「已禁用」',
    /!p\.installed[\s\S]{0,120}?label: '市场可见'/.test(app));
check('三态齐全（市场可见 / 已启用 / 已禁用）',
    /label: '市场可见'/.test(app) && /label: '✅ 已启用'/.test(app) && /label: '⚪ 已禁用'/.test(app));

// ── 6. plugin 这个来源要在各处都接上 ───────────────────────────────
check('_SOURCE_META 有 plugin', /plugin:\s*\{ label: 'Plugin'/.test(app));
check('来源过滤芯片有 Plugin',
    /\{ key: 'plugin',\s*label: 'Plugin',\s*n: counts\.plugin \|\| 0/.test(app));
check('_renderSourceGroups 分组顺序含 plugin',
    /for \(const key of \['builtin', 'project', 'user', 'pack', 'openspec', 'plugin'\]\)[\s\S]{0,200}?const sm = _SOURCE_META\[key\]/.test(app));
check('详情 registry 分组顺序与渲染一致（下标定位靠它）',
    (app.match(/\['builtin', 'project', 'user', 'pack', 'openspec', 'plugin'\]/g) || []).length >= 2);
check('有分组标题兜底表（漏写不会渲染出 undefined）',
    /const _DEFAULT_GROUP_TITLES = \{[\s\S]{0,400}?plugin:\s*\{ icon: '🧩'/.test(app));

// 5 个面板都要写上 Plugin 分组标题
for (const [label, needle] of [
    ['MCP', "title: 'Plugin MCP'"],
    ['Skill', "title: 'Plugin Skill'"],
    ['Command', "title: 'Plugin Command'"],
    ['Rule', "title: 'Plugin Rule'"],
    ['Hook', "title: 'Plugin Hook'"],
]) {
    check(`${label} 面板有 Plugin 分组标题`, app.includes(needle));
}

// ── 7. 容器分组：Pack 和 Plugin 都要按容器名再分一层 ───────────────
check('渲染按容器字段分组（pack_name / plugin_name）',
    /containerField = key === 'pack' \? 'pack_name'\s*\n\s*: key === 'plugin' \? 'plugin_name' : null/.test(app));
check('registry 也按容器分组（否则左侧列表分组名和右侧对不上）',
    (app.match(/key === 'plugin' \? 'plugin_name' : null/g) || []).length >= 2);
check('来源徽章后缀统一走 _srcSuffix',
    /function _srcSuffix\(item\)[\s\S]{0,200}?item\.pack_name \|\| item\.plugin_name/.test(app));
check('没有残留的 pack_name 内联后缀',
    !/\.pack_name \? ' · '\+escapeHtml\(/.test(app));
check('搜索字段含 plugin_name / marketplace',
    /'pack_name', 'plugin_name', 'marketplace'/.test(app));

// ── 8. needs_auth 要说真实原因，不能伪装成「未启用」 ───────────────
check('MCP 行优先显示「需在 Client 侧授权」',
    /srv\.needs_auth\s*\n?\s*\?[\s\S]{0,300}?需在 Client 侧授权/.test(app));
check('该提示排在 status / enabled 判断之前',
    app.indexOf('srv.needs_auth') < app.indexOf('const transportBadge'));
check('MCP 点击载荷带 needs_auth', /needs_auth:!!srv\.needs_auth/.test(app));

// ── 9. 插件详情弹窗 ────────────────────────────────────────────────
check('showPluginDetail 走 /plugins/detail', /\/plugins\/detail\?\$\{qs\}/.test(app));
check('详情按需建弹窗（不往 index.html 堆骨架）',
    /getElementById\('pluginDetailModal'\)[\s\S]{0,200}?createElement\('div'\)/.test(app)
    && !/id="pluginDetailModal"/.test(html));
check('详情写明只读、启停去宿主 Client', /ADS 只读取插件内容，不改动它/.test(app));
check('MCP 明细标注需授权', /需在 Client 侧授权[\s\S]{0,60}?<\/span>/.test(app));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
