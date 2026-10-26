"""H5 / Phaser 套件的失败反思信号构建器。

当 SOP 阶段 `h5_typecheck` 或 `h5_playtest` 打回（status = `h5_typecheck_failed`
/ `h5_playtest_failed`）时，由 `plugins.registry.build_plugin_reflection_signal`
自动分发到此模块，将：
  1. 结构化编译/运行时错误（精确到文件、行、列、错误码或 browser 异常源）
  2. Phaser 3 + TypeScript 常见 API 误用提示（hints）
  3. 剥除 ANSI 控制符后的控制台原始输出尾部（raw_tail）
组装成供 `ReflectionAction` 与 `DevAgent.fix_issues` 消费的失败诊断上下文。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

HANDLED_FAILURE_TYPES = frozenset({
    "h5_typecheck_failed",
    "h5_playtest_failed",
})

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "").strip()


def enrich_fix_context(
    failure_type: str,
    reject_detail: Dict[str, Any],
    context: Dict[str, Any],
) -> None:
    """从最近一条 reject 日志 detail 中提取 H5 诊断字段写入 DevAgent context。"""
    det = reject_detail or {}
    context["compile_errors"] = det.get("errors") or []
    context["compile_warnings"] = det.get("warnings") or []
    context["compile_command"] = det.get("command") or ""
    context["compile_hints"] = det.get("hints") or []
    context["compile_raw_tail"] = det.get("raw_tail") or ""
    context["compile_err_brief"] = det.get("err_brief") or det.get("message") or ""


def build_reflection_signal(
    failure_type: str,
    context: Dict[str, Any],
) -> str:
    """将 H5 类型检查或运行时试玩失败格式化为 ReflectionAction 的 failure_signal 段落。"""
    compile_errors: List[Dict[str, Any]] = context.get("compile_errors") or []
    compile_warnings: List[ Any ] = context.get("compile_warnings") or []
    compile_cmd: str = str(context.get("compile_command") or "")
    hints: List[str] = list(context.get("compile_hints") or [])
    raw_tail: str = _strip_ansi(str(context.get("compile_raw_tail") or ""))
    err_brief: str = _strip_ansi(str(context.get("compile_err_brief") or ""))

    if failure_type == "h5_typecheck_failed" and compile_errors and not hints:
        try:
            from plugins.h5.actions.h5_typecheck import phaser_api_hints
            hints = phaser_api_hints(compile_errors)
        except Exception:
            pass

    is_typecheck = failure_type == "h5_typecheck_failed"
    stage_label = (
        "H5 类型检查（tsc --noEmit）"
        if is_typecheck
        else "H5 运行时试玩（vite build + 无头浏览器）"
    )
    lines = [
        f"{stage_label}未通过（结构化错误 {len(compile_errors)} 条，警告 {len(compile_warnings)} 条）。"
    ]
    if compile_cmd:
        lines.append(f"执行命令: `{compile_cmd}`")
    if err_brief:
        lines.append(f"错误摘要: {err_brief}")

    if compile_errors:
        lines.append("\n具体错误列表（最多前 15 条）：")
        for e in compile_errors[:15]:
            if is_typecheck:
                lines.append(
                    f"  - {e.get('file', '?')}:{e.get('line', '?')}:{e.get('column', '?')} "
                    f"{e.get('code', '')} — {(e.get('msg') or '')[:200]}"
                )
            else:
                lines.append(
                    f"  - [{e.get('source', 'browser')}] {(e.get('msg') or '')[:240]}"
                )

    if hints:
        lines.append("\nPhaser 3 / TypeScript 针对性修复提示（优先按此修复）：")
        for h in hints[:6]:
            lines.append(f"  - {h}")

    if not is_typecheck:
        lines.append(
            "\n⚠️ H5 运行时试玩常见根因：\n"
            "  - `index.html` 缺少 `#game-container` 或 `<script type=\"module\" src=\"/src/main.ts\">`\n"
            "  - `Scene.create()` 中访问了尚未初始化的 `this.physics.add`（需在 `gameConfig.physics` 启用 `arcade`）\n"
            "  - 纹理/资源 key 未在 `preload()` 或 `generateTexture()` 中注册就直接 `this.add.sprite()`\n"
            "  - 在浏览器端源码里误 import 了 `node:fs` / `node:path` 等 Node 专属模块导致 `vite build` 失败"
        )
    else:
        lines.append(
            "\n⚠️ Phaser 3 + TypeScript 常见类型坑：\n"
            "  - 颜色参数（`add.rectangle`、`fillStyle`、`lineStyle`、`setStrokeStyle`）只接受 `number`（如 `0x1e293b`），不能传 `'#1e293b'` 字符串（`cameras.main.setBackgroundColor` 除外）\n"
            "  - `this.input.keyboard` 可能为 `null`，用可选链或非空断言 `this.input.keyboard!`\n"
            "  - Arcade 物理 Body 需精确区分 `Phaser.Physics.Arcade.Body` 与 `StaticBody`"
        )

    if raw_tail and not compile_errors:
        lines.append(
            f"\n命令原始输出尾部（未解析出标准结构化错误，请直接根据原始输出定位）：\n```\n{raw_tail[-1500:]}\n```"
        )
    elif raw_tail:
        lines.append(f"\n命令原始输出尾部：\n```\n{raw_tail[-800:]}\n```")

    return "\n".join(lines)


_HEX_STRING_PROP_RE = re.compile(r"(['\"])#([0-9a-fA-F]{6})\1")


def _try_patch_single_ts_error(
    lines: List[str],
    err: Dict[str, Any],
    repo_root: Any,
    file_rel_path: str,
) -> bool:
    """尝试对单条 TypeScript 编译错误执行行级确定性修复。成功返回 True 并原地修改 `lines`。"""
    code = str(err.get("code") or "")
    msg = str(err.get("msg") or "")
    ln_idx = int(err.get("line") or 0) - 1
    if not (0 <= ln_idx < len(lines)):
        return False
    orig_line = lines[ln_idx]

    # 1. TS2345: string -> number（Phaser 颜色参数）
    if code == "TS2345" and "type 'string' is not assignable to parameter of type 'number'" in msg:
        if _HEX_STRING_PROP_RE.search(orig_line):
            lines[ln_idx] = _HEX_STRING_PROP_RE.sub(r"0x\2", orig_line)
            return True
        m_ident = re.match(r"^(\s*)([A-Za-z_$][\w$.]*)(\s*,?\s*)$", orig_line)
        if m_ident:
            indent, expr, tail = m_ident.groups()
            lines[ln_idx] = f"{indent}Number.parseInt(String({expr}).replace(/^#/, ''), 16){tail}"
            return True
        return False

    # 2. TS2307: Cannot find module '...'（幻觉导入不存在的本地模块，或导入缺类型声明的第三方包如 pngjs）
    if code == "TS2307":
        m_mod = re.search(r"Cannot find module ['\"]([^'\"]+)['\"]", msg)
        mod_path = m_mod.group(1) if m_mod else ""
        if mod_path.startswith(".") and "import " in orig_line:
            # 提取被导入的标识符，并在全文件内把它在数组中的引用（如 `[BootScene, PreloadScene, GameScene, UIScene]`）一并移除
            imported_idents = re.findall(r"\b([A-Za-z_$][\w$]*)\b", orig_line.split("from")[0].replace("import", "").replace("type", ""))
            lines[ln_idx] = f"// [AutoFix: removed missing module {mod_path}]"
            for ident in imported_idents:
                if not ident:
                    continue
                for i in range(len(lines)):
                    if i == ln_idx or lines[i].lstrip().startswith("//"):
                        continue
                    lines[i] = re.sub(rf"\b{re.escape(ident)}\s*,\s*", "", lines[i])
                    lines[i] = re.sub(rf",\s*\b{re.escape(ident)}\b", "", lines[i])
            return True
        if mod_path and not mod_path.startswith(".") and "import " in orig_line:
            # 第三方模块缺少类型声明（如 `import { PNG } from 'pngjs';`）→ 在上一行注入 `// @ts-ignore`
            indent_m = re.match(r"^(\s*)", orig_line)
            ind = indent_m.group(1) if indent_m else ""
            lines[ln_idx] = f"{ind}// @ts-ignore\n{orig_line}"
            return True
        return False

    # 3. TS6133: 'xxx' is declared but its value is never read（未使用变量/导入）
    if code == "TS6133":
        m_var = re.search(r"'([^']+)' is declared but its value is never read", msg)
        var_name = m_var.group(1) if m_var else ""
        if not var_name:
            return False
        if orig_line.lstrip().startswith("import "):
            # 从命名导入 `{ A, B }` 中删掉 var_name，若只剩它一个则注释整行
            if "{" in orig_line and "}" in orig_line:
                new_line = re.sub(rf"\b{re.escape(var_name)}\s*,\s*", "", orig_line)
                new_line = re.sub(rf",\s*\b{re.escape(var_name)}\b", "", new_line)
                new_line = re.sub(rf"\{{\s*{re.escape(var_name)}\s*\}}", "{}", new_line)
                if "{}" in new_line or re.search(r"\{\s*\}", new_line):
                    lines[ln_idx] = f"// {orig_line}"
                else:
                    lines[ln_idx] = new_line
                return True
            lines[ln_idx] = f"// {orig_line}"
            return True
        # 普通 `const barBg = ...` → 若右侧有调用则保留右侧表达式，否则加 `void var_name;`
        if re.match(rf"^\s*(?:const|let|var)\s+{re.escape(var_name)}\b", orig_line):
            lines[ln_idx] = orig_line + f" void {var_name};"
            return True
        return False

    # 4. TS2353: 'fontWeight' does not exist in type 'TextStyle'（Phaser TextStyle 用 fontStyle 而非 fontWeight）
    if code == "TS2353" and "'fontWeight' does not exist in type 'TextStyle'" in msg:
        if "fontWeight" in orig_line:
            lines[ln_idx] = orig_line.replace("fontWeight", "fontStyle")
            return True
        return False

    # 5. TS2532: Object is possibly 'undefined'（noUncheckedIndexedAccess 下数组/Buffer 下标如 short[1] / a.data[o + 1]）
    if code == "TS2532" and "Object is possibly 'undefined'" in msg:
        patched = re.sub(r"(\b[A-Za-z_$][\w$.]*\[[^\[\]]+\])(?!\!)", r"\1!", orig_line)
        if patched != orig_line:
            lines[ln_idx] = patched
            return True
        return False

    # 6. TS2339: Property 'PNG' does not exist on type '{ sync: ... }'（require('pngjs') 解构写法）
    if code == "TS2339" and "Property 'PNG' does not exist on type" in msg:
        if "const { PNG }" in orig_line:
            lines[ln_idx] = orig_line.replace("const { PNG }", "const PNG")
            return True
        return False

    return False


def apply_deterministic_fixes(
    failure_type: str,
    repo_path: str,
    compile_errors: List[Dict[str, Any]],
    existing_code: Dict[str, str],
) -> Dict[str, str]:
    """H5 套件自带的确定性快修器（0 LLM 调用，秒级修正常见确定性报错）。

    覆盖高频 TypeScript / Phaser 编译错误：
      1. TS2345 (`string` -> `number` 颜色参数)
      2. TS2307 (`Cannot find module '../scenes/...'` 幻觉导入不存在的场景)
      3. TS6133 (`'xxx' is declared but its value is never read` 未使用变量/导入)
      4. TS2353 (`'fontWeight' does not exist in type 'TextStyle'` -> `fontStyle`)
      5. TS2532 (`Object is possibly 'undefined'` 数组正则捕获组下标加 `!`)
      6. TS2339 (`const { PNG } = require('pngjs') as { sync: ... }` 解构类型不匹配)
    返回 `{rel_path: new_content}`（仅包含该文件内所有报错均已被确定性修复的文件）。
    """
    if failure_type != "h5_typecheck_failed" or not compile_errors:
        return {}

    from pathlib import Path
    root = Path(repo_path) if repo_path else None

    by_file: Dict[str, List[Dict[str, Any]]] = {}
    for err in compile_errors:
        fp = (err.get("file") or "").replace("\\", "/").lstrip("./")
        if fp:
            by_file.setdefault(fp, []).append(err)

    fixed_files: Dict[str, str] = {}
    for fp, errs in by_file.items():
        # 优先从磁盘读取真实完整文件（existing_code 对 >15000 字符的大文件带了 `/* ... [文件截断显示] ... */` 标记，
        # 直接改 existing_code 并写盘会把磁盘文件尾巴截断！）
        content = None
        if root and (root / fp).is_file():
            try:
                content = (root / fp).read_text(encoding="utf-8", errors="replace")
            except Exception:
                content = None
        if content is None:
            raw_mem = existing_code.get(fp)
            if raw_mem and "文件截断显示" not in raw_mem:
                content = raw_mem
        if not content:
            continue

        lines = content.splitlines()
        all_lines_patched = True
        for e in errs:
            if not _try_patch_single_ts_error(lines, e, root, fp):
                all_lines_patched = False
                break

        if all_lines_patched:
            new_content = "\n".join(lines) + ("\n" if content.endswith("\n") else "")
            if new_content != content:
                fixed_files[fp] = new_content

    return fixed_files

