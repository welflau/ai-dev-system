#!/usr/bin/env node
/**
 * ue_build.js — 自动检测 UE 引擎路径并编译 UE 项目。
 *
 * 用法：
 *   node scripts/ue_build.js --project <.uproject路径或项目目录>
 *   node scripts/ue_build.js --project F:/UEProjects/TestGame --target Editor
 *   node scripts/ue_build.js --project . --engine G:/EpicGames/UE_5.3
 *
 * 选项：
 *   --project <path>   .uproject 文件路径或项目根目录（必填）
 *   --target <type>    编译目标：Editor（默认）| Game | Client | Server
 *   --config <type>    编译配置：Development（默认）| Debug | Shipping
 *   --engine <path>    手动指定引擎路径（跳过自动检测）
 *   --dry-run          只打印命令，不实际编译
 *
 * 退出码：
 *   0 = 编译成功
 *   1 = 编译失败（含错误摘要）
 *   2 = 引擎未找到
 *   3 = 项目文件无效
 */

'use strict';

const fs            = require('fs');
const path          = require('path');
const { execSync, spawnSync } = require('child_process');

// ── 参数解析 ────────────────────────────────────────────────────────────────

function parseArgs(argv) {
  const args = { project: null, target: 'Editor', config: 'Development', engine: null, dryRun: false };
  for (let i = 2; i < argv.length; i++) {
    switch (argv[i]) {
      case '--project':  args.project  = argv[++i]; break;
      case '--target':   args.target   = argv[++i]; break;
      case '--config':   args.config   = argv[++i]; break;
      case '--engine':   args.engine   = argv[++i]; break;
      case '--dry-run':  args.dryRun   = true; break;
    }
  }
  return args;
}

// ── 项目文件解析 ─────────────────────────────────────────────────────────────

function resolveUproject(projectArg) {
  const p = path.resolve(projectArg);
  if (p.endsWith('.uproject') && fs.existsSync(p)) return p;

  // 目录 → 在其中查找 .uproject
  if (fs.statSync(p).isDirectory()) {
    const found = fs.readdirSync(p).find(f => f.endsWith('.uproject'));
    if (found) return path.join(p, found);
  }
  throw new Error(`找不到 .uproject 文件: ${projectArg}`);
}

function readUproject(uprojectPath) {
  try {
    return JSON.parse(fs.readFileSync(uprojectPath, 'utf8'));
  } catch (e) {
    throw new Error(`.uproject 解析失败: ${e.message}`);
  }
}

// ── 引擎路径检测（Windows 注册表） ────────────────────────────────────────────

function findEngineFromRegistry(engineAssociation) {
  if (process.platform !== 'win32') return null;

  try {
    // 精确版本查找
    const key = `HKEY_LOCAL_MACHINE\\SOFTWARE\\EpicGames\\Unreal Engine\\${engineAssociation}`;
    const result = execSync(`reg query "${key}" /v InstalledDirectory 2>nul`, { encoding: 'utf8' });
    const match = result.match(/InstalledDirectory\s+REG_SZ\s+(.+)/);
    if (match) return match[1].trim();
  } catch (_) {}

  try {
    // HKCU 也查一下
    const key = `HKEY_CURRENT_USER\\SOFTWARE\\EpicGames\\Unreal Engine\\${engineAssociation}`;
    const result = execSync(`reg query "${key}" /v InstalledDirectory 2>nul`, { encoding: 'utf8' });
    const match = result.match(/InstalledDirectory\s+REG_SZ\s+(.+)/);
    if (match) return match[1].trim();
  } catch (_) {}

  return null;
}

function findEngineFromCommonPaths(engineAssociation) {
  const drives = ['C', 'D', 'E', 'F', 'G', 'H'];
  const dirs   = ['Epic Games', 'EpicGames', 'Program Files/Epic Games'];
  for (const drive of drives) {
    for (const dir of dirs) {
      const candidate = path.join(`${drive}:`, dir, `UE_${engineAssociation}`);
      if (fs.existsSync(path.join(candidate, 'Engine'))) return candidate;
    }
  }
  return null;
}

function findEngine(engineAssociation, engineOverride) {
  if (engineOverride) {
    if (!fs.existsSync(path.join(engineOverride, 'Engine'))) {
      throw new Error(`指定的引擎路径无效: ${engineOverride}`);
    }
    return engineOverride;
  }

  const fromReg = findEngineFromRegistry(engineAssociation);
  if (fromReg) return fromReg;

  const fromPath = findEngineFromCommonPaths(engineAssociation);
  if (fromPath) return fromPath;

  throw new Error(
    `未找到 UE ${engineAssociation} 引擎。\n` +
    `请用 --engine <路径> 手动指定，例如：\n` +
    `  node scripts/ue_build.js --project . --engine G:/EpicGames/UE_${engineAssociation}`
  );
}

// ── UBT 路径 ──────────────────────────────────────────────────────────────────

function getUBTPath(engineRoot) {
  const candidates = [
    path.join(engineRoot, 'Engine', 'Binaries', 'DotNET', 'UnrealBuildTool', 'UnrealBuildTool.exe'),
    path.join(engineRoot, 'Engine', 'Build', 'BatchFiles', 'Build.bat'),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  throw new Error(`找不到 UnrealBuildTool: ${engineRoot}`);
}

// ── 错误解析 ──────────────────────────────────────────────────────────────────

function parseErrors(output) {
  const errors   = [];
  const warnings = [];
  for (const line of output.split('\n')) {
    if (/error [A-Z]\d+:/i.test(line) || /error:/i.test(line)) {
      errors.push(line.trim());
    } else if (/warning [A-Z]\d+:/i.test(line)) {
      warnings.push(line.trim());
    }
  }
  return { errors, warnings };
}

// ── 主流程 ────────────────────────────────────────────────────────────────────

function main() {
  const args = parseArgs(process.argv);

  if (!args.project) {
    console.error('错误：必须指定 --project <路径>');
    process.exit(3);
  }

  // 解析项目
  let uprojectPath;
  try {
    uprojectPath = resolveUproject(args.project);
  } catch (e) {
    console.error(`[ue_build] ${e.message}`);
    process.exit(3);
  }

  const projectDir  = path.dirname(uprojectPath);
  const projectName = path.basename(uprojectPath, '.uproject');

  let uproject;
  try {
    uproject = readUproject(uprojectPath);
  } catch (e) {
    console.error(`[ue_build] ${e.message}`);
    process.exit(3);
  }

  const engineAssociation = uproject.EngineAssociation || '5.3';
  console.log(`[ue_build] 项目:  ${projectName}`);
  console.log(`[ue_build] 引擎:  UE ${engineAssociation}`);
  console.log(`[ue_build] 目标:  ${projectName}${args.target} ${args.config} Win64`);

  // 检测引擎
  let engineRoot;
  try {
    engineRoot = findEngine(engineAssociation, args.engine);
    console.log(`[ue_build] 路径:  ${engineRoot}`);
  } catch (e) {
    console.error(`[ue_build] ${e.message}`);
    process.exit(2);
  }

  // 构建 UBT 命令
  const ubt     = getUBTPath(engineRoot);
  const cmdArgs = [
    `${projectName}${args.target}`,
    'Win64',
    args.config,
    `-Project=${uprojectPath}`,
    '-WaitMutex',
  ];

  console.log(`\n[ue_build] 执行: "${ubt}" ${cmdArgs.join(' ')}\n`);

  if (args.dryRun) {
    console.log('[ue_build] --dry-run 模式，跳过实际编译');
    process.exit(0);
  }

  // 执行编译
  const result = spawnSync(ubt, cmdArgs, {
    encoding: 'utf8',
    stdio:    'pipe',
    timeout:  600000,  // 10 分钟
  });

  const output = (result.stdout || '') + (result.stderr || '');
  process.stdout.write(output);

  const { errors, warnings } = parseErrors(output);

  console.log('\n' + '─'.repeat(60));
  if (result.status === 0) {
    console.log(`[ue_build] ✅ 编译成功`);
    if (warnings.length) console.log(`[ue_build]    警告 ${warnings.length} 个`);
  } else {
    console.log(`[ue_build] ❌ 编译失败（退出码 ${result.status}）`);
    if (errors.length) {
      console.log(`[ue_build] 错误摘要（${errors.length} 个）:`);
      errors.slice(0, 10).forEach(e => console.log(`  ${e}`));
      if (errors.length > 10) console.log(`  ... 共 ${errors.length} 个错误`);
    }
    process.exit(1);
  }
}

main();
