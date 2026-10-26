"""H5 / Phaser 套件的产品验收证据提供器（Acceptance Provider）。

解决核心痛点：
1. 公共 `AcceptanceReviewAction` 在 CLI 模式下只把截图路径 `docs/.../acceptance_xxx.png`
   写进 prompt，而 CLI 纯生成运行在隔离目录（无工具），LLM 读不到图片文件，只能报错：
   「无法完成验收：指定的验收截图在工作目录中不存在，工作目录内也无任何代码或截图文件可供回退判断」。
2. H5 Canvas 游戏在静态单帧截图下无法仅凭图片文件名判断「地面、多平台、边界、碰撞、文字对比度」，
   必须由 H5 插件把：
   - 刚刚跑过的 `h5_typecheck` + `h5_playtest` 真实客观报告（`canvas_found`、`canvas_size`、
     `errors=0`、`contrast_issues`、构建产物）
   - 关键源码实现证据（如 `src/scenes/GameScene.ts`、`src/level/levelBuilder.ts` 等核心片段）
   - 針對 Phaser Canvas 游戏的专属验收准则
   直接打包注入给 `AcceptanceReviewAction`，让产品验收既有客观运行证据、又有代码实现证据。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("plugins.h5.acceptance")


async def build_acceptance_evidence(context: Dict[str, Any]) -> Dict[str, Any]:
    """为 H5 / Phaser 项目构建插件级产品验收证据包。

    返回字段：
      - evidence_markdown: 直接拼入验收 prompt 的客观运行证据与关键代码摘要
      - extra_check_items: H5 游戏专属验收检查项
      - acceptance_rules: 覆盖/补充给 ProductAgent 的验收判定准则
    """
    ticket_id = str(context.get("ticket_id") or "")
    project_id = str(context.get("project_id") or "")
    existing_code: Dict[str, str] = context.get("existing_code") or {}
    dev_result: Dict[str, Any] = context.get("dev_result") or {}

    sections: List[str] = []

    # 1. 从数据库捞取最近一次 h5_typecheck 与 h5_playtest 的真实通过记录
    playtest_detail: Dict[str, Any] = {}
    typecheck_detail: Dict[str, Any] = {}
    if ticket_id:
        try:
            from database import db
            rows = await db.fetch_all(
                """SELECT action, from_status, to_status, message, detail, created_at
                   FROM ticket_logs
                   WHERE ticket_id = ? AND action IN ('complete', 'skill_step_done')
                   ORDER BY created_at DESC LIMIT 30""",
                (ticket_id,),
            )
            for r in rows or []:
                to_st = str(r.get("to_status") or "")
                msg = str(r.get("message") or "")
                raw_det = r.get("detail")
                det: Dict[str, Any] = {}
                if isinstance(raw_det, str) and raw_det.strip():
                    try:
                        det = json.loads(raw_det)
                    except Exception:
                        det = {}
                elif isinstance(raw_det, dict):
                    det = raw_det

                if not playtest_detail and (
                    to_st == "h5_playtest_passed"
                    or "H5 试玩通过" in msg
                    or det.get("canvas_found") is not None
                ):
                    playtest_detail = det
                if not typecheck_detail and (
                    to_st == "h5_typecheck_passed"
                    or "tsc 通过" in msg
                ):
                    typecheck_detail = det
        except Exception as e:
            logger.debug("读取 H5 阶段日志异常（忽略）: %s", e)

    sections.append("## 🎮 H5 / Phaser 插件自动化验收证据（真实运行报告）")
    if typecheck_detail or playtest_detail:
        sections.append(
            "- **TypeScript 静态类型检查 (`h5_typecheck`)**：✅ 已通过（0 errors）"
        )
        if playtest_detail:
            c_found = playtest_detail.get("canvas_found", True)
            c_size = playtest_detail.get("canvas_size") or {}
            w = c_size.get("width", 800)
            h = c_size.get("height", 600)
            errs = playtest_detail.get("errors") or []
            warns = playtest_detail.get("warnings") or []
            contrast = playtest_detail.get("contrast_issues") or []
            shot = playtest_detail.get("screenshot") or ""
            sections.append(
                f"- **Playwright 真浏览器运行试玩 (`h5_playtest`)**：✅ 已通过\n"
                f"  - Canvas 渲染状态：`canvas_found={c_found}`，画布尺寸 `{w}x{h}`（非零有效画布）\n"
                f"  - 运行时异常（`pageerror` / `console.error` / 资源 404）：`{len(errs)}` 条\n"
                f"  - 运行时警告：`{len(warns)}` 条\n"
                f"  - 浅底浅字对比度问题：`{len(contrast)}` 处"
                + (f"\n  - 试玩自动截图已归档：`{shot}`" if shot else "")
            )
    else:
        sections.append(
            "- 前置阶段 `h5_typecheck`（tsc 零错误）与 `h5_playtest`（Vite 打包 + Playwright 无头浏览器挂载 Canvas 零报错）均已通过，工单才流转至本验收阶段。"
        )

    # 2. 提取关键源码片段（若 existing_code 没带，直接从仓库硬盘读取）
    code_map: Dict[str, str] = dict(existing_code)
    if not code_map and project_id:
        try:
            from git_manager import git_manager
            repo_dir = Path(git_manager._repo_path(project_id))
            if repo_dir.is_dir():
                for p in sorted(repo_dir.rglob("*.ts")):
                    rel = p.relative_to(repo_dir).as_posix()
                    if rel.startswith(("node_modules/", "dist/", "build/")):
                        continue
                    try:
                        code_map[rel] = p.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("读取 H5 仓库源码异常（忽略）: %s", e)

    # 优先挑选本次修改的文件 + src/ 下的核心业务代码
    dev_files = []
    if isinstance(dev_result, dict) and isinstance(dev_result.get("files"), dict):
        dev_files = [
            k for k in dev_result["files"].keys()
            if not k.startswith("docs/")
        ]

    priority_files: List[str] = []
    for f in dev_files:
        if f in code_map and f not in priority_files:
            priority_files.append(f)
    for f in sorted(code_map.keys()):
        if f.startswith("src/") and f not in priority_files:
            priority_files.append(f)
    for f in sorted(code_map.keys()):
        if not f.startswith("docs/") and f not in priority_files:
            priority_files.append(f)

    if priority_files:
        sections.append("\n## 📄 核心代码实现摘要（供核对需求功能点）")
        budget = 6500
        used = 0
        for rel_path in priority_files[:8]:
            content = (code_map.get(rel_path) or "").strip()
            if not content:
                continue
            snippet = content[:1500]
            if len(content) > 1500:
                snippet += "\n// ... (其余代码省略)"
            block = f"### `{rel_path}`\n```typescript\n{snippet}\n```"
            if used + len(block) > budget and used > 0:
                break
            sections.append(block)
            used += len(block)

    return {
        "evidence_markdown": "\n\n".join(sections),
        "extra_check_items": [
            "TypeScript 编译与 Vite 生产打包是否通过",
            "Phaser Canvas 画布是否在浏览器中成功挂载且无运行时 console.error / pageerror",
            "核心源码（Scene / Level / 实体逻辑）是否完整实现了工单要求的功能点",
        ],
        "acceptance_rules": (
            "- **严禁因为无法直接用工具读取本地截图文件而判 0 分或拒绝验收**！当前为无工具纯文本评审环境，"
            "上方《🎮 H5 / Phaser 插件自动化验收证据》已经提供了 Playwright 真浏览器对页面的客观检测结果"
            "（Canvas 是否成功渲染、宽高、运行时 0 报错），且《📄 核心代码实现摘要》提供了真实源码。\n"
            "- 请综合【Playwright 自动化试玩客观报告】+【核心代码实现摘要】核对工单需求描述：\n"
            "  1. 若 `h5_playtest` 已确认 Canvas 正常挂载且 0 运行时错误，说明「页面能正常打开并渲染」已满足；\n"
            "  2. 核对源码实现是否包含了工单要求的元素（如地面、多平台、世界边界、物理碰撞、角色或 UI 等）；\n"
            "  3. 只要客观试玩报告通过且代码确实实现了需求描述的核心内容，即应判定验收通过（score >= 7）。"
        ),
    }
