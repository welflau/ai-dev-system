"""
ReflectionAction — 失败反思 Action

触发：DevAgent 的 rework / fix_issues 场景。开发失败（被 ProductAgent 验收打回
或 TestAgent 测试失败）后，让 LLM 做一次结构化反思：诊断根因、指出漏掉的需求点、
指定下一次的具体修改策略。反思结果作为结构化 context 注入下一次的代码生成 prompt，
替代原先"把 rejection_reason 拼到 ticket_description 末尾"的朴素做法。

对标 MagicAI 的 Reflexion 框架 / 论文 Shinn et al. 2023 "Reflexion: Language
Agents with Verbal Reinforcement Learning"。

输入 context：
  ticket_description     : 原工单描述
  failure_type           : "acceptance_rejected" / "testing_failed"
  rejection_reason       : 验收打回理由（失败类型 = acceptance_rejected）
  test_issues            : 测试 issue 列表（失败类型 = testing_failed）
  previous_code          : dict[path -> content] 上次产出的代码
  retry_count            : 当前第几次重试（从 1 开始）
  previous_reflections   : list[dict] 历次反思（最多 3 条，按时间正序）

输出 data：
  {
    "reflection": {
      "root_cause": str,
      "missed_requirements": list[str],
      "previous_attempt_issue": str,
      "strategy_change": str,
      "specific_changes": list[str],
      "confidence": float,
    },
    "retry_count": int,
  }

降级：LLM 调用失败 / JSON 解析失败时，返回最小反思（confidence <= 0.3），
不阻塞主流程。
"""
import json
import logging
from typing import Any, Dict, List

from actions.base import ActionBase, ActionResult
from llm_client import llm_client

logger = logging.getLogger("actions.reflection")


_SYSTEM_PROMPT = """你是一位资深技术主管，正在复盘一次失败的开发工单。
你的任务：诊断失败的根本原因，提出精确的下一次尝试策略。

硬要求：
- 根因必须具体到文件/函数/逻辑，不能说"代码没写好"这种废话
- 遇到多次失败时，必须和上一次的策略**本质不同**，否则就是在兜圈
- 输出严格 JSON，不要 markdown 包裹，按用户消息里的字段
- 如果用户消息给出了"历史相似失败（跨工单）"且有标记为 ✅已解决 的案例，本次 strategy_change
  **优先借鉴**该成功策略；对 ❌未解决 的案例要明确说明这次为什么能避开同样的坑"""


def _format_reflection_brief(r: Dict[str, Any]) -> str:
    """历次反思的一行摘要（用在当前反思的 prompt 里，控制 token）"""
    root = (r.get("root_cause") or "?")[:120]
    strategy = (r.get("strategy_change") or "?")[:120]
    return f"根因: {root}；策略: {strategy}"


def _format_similar_failures(cases: List[Dict[str, Any]]) -> str:
    """跨工单相似失败渲染成 prompt 段落。
    每条列出：标记（已解决/未解决）+ 工单标题 + 根因 + 策略 + 具体修改。"""
    if not cases:
        return ""
    lines = ["\n## 历史相似失败（跨工单，供参考避免重复踩坑）"]
    for i, c in enumerate(cases, 1):
        mark = "✅已解决" if c.get("resolved") else "❌未解决"
        title = c.get("ticket_title") or "(无标题)"
        module = c.get("module") or "?"
        lines.append(f"\n[案例 {i} — {mark} | module={module}] 工单「{title}」")
        if c.get("root_cause"):
            lines.append(f"  根因: {c['root_cause']}")
        if c.get("strategy_change"):
            lines.append(f"  策略: {c['strategy_change']}")
        changes = c.get("specific_changes") or []
        if changes:
            lines.append("  具体修改:")
            for ch in changes[:3]:
                lines.append(f"    - {ch}")
    lines.append("\n⚠️ 若上面有 ✅已解决 策略，优先借鉴；❌未解决 策略则要说清本次为什么能规避。")
    return "\n".join(lines)


def _format_previous_code(previous_code: Dict[str, str], max_files: int = 5,
                         max_chars_per_file: int = 200) -> str:
    """上次代码摘要（前几个文件的前几百字）"""
    if not previous_code:
        return "(无)"
    lines = []
    for path, content in list(previous_code.items())[:max_files]:
        snippet = (content or "")[:max_chars_per_file].replace("\n", " ")
        lines.append(f"- `{path}`: {snippet}...")
    if len(previous_code) > max_files:
        lines.append(f"  ... 还有 {len(previous_code) - max_files} 个文件")
    return "\n".join(lines)


def _parse_json_lenient(raw: str) -> Dict[str, Any]:
    """容错 JSON 解析：剥 markdown 包裹；提取第一对大括号内容"""
    s = (raw or "").strip()
    # 剥 ```json ... ``` 包裹
    if s.startswith("```"):
        lines = [ln for ln in s.split("\n") if not ln.strip().startswith("```")]
        s = "\n".join(lines).strip()
    # 直接解
    try:
        return json.loads(s)
    except Exception:
        pass
    # 提取第一对平衡大括号
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        return json.loads(s[start:end + 1])
    raise ValueError("无法从 LLM 输出解析出 JSON")


def _minimal_reflection(failure_type: str, rejection_reason: str,
                        test_issues: List[str], error: str) -> Dict[str, Any]:
    """LLM 失败时的降级反思（只透传失败信号）"""
    if failure_type == "acceptance_rejected":
        strategy = rejection_reason or "按验收反馈重写"
    else:
        issues = "; ".join(test_issues[:3]) if test_issues else "测试失败"
        strategy = f"修复测试问题: {issues}"
    return {
        "root_cause": f"反思 LLM 调用失败，降级仅透传失败信号（{error}）",
        "missed_requirements": [],
        "previous_attempt_issue": "",
        "strategy_change": strategy,
        "specific_changes": [],
        "confidence": 0.3,
    }


class ReflectionAction(ActionBase):

    @property
    def name(self) -> str:
        return "reflect"

    @property
    def description(self) -> str:
        return "对失败的工单做结构化反思，输出根因 + 策略调整 + 具体修改指令"

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        ticket_desc = context.get("ticket_description", "") or ""
        failure_type = context.get("failure_type", "unknown")
        rejection_reason = context.get("rejection_reason", "") or ""
        test_issues = context.get("test_issues") or []
        previous_code = context.get("previous_code") or {}
        retry_count = int(context.get("retry_count") or 1)
        previous_reflections = context.get("previous_reflections") or []
        similar_failures = context.get("similar_failures") or []

        # 构建失败信号段
        compile_errors = context.get("compile_errors") or []
        compile_warnings = context.get("compile_warnings") or []
        compile_cmd = context.get("compile_command") or ""

        if failure_type == "acceptance_rejected":
            failure_signal = f"ProductAgent 验收不通过。理由：\n{rejection_reason}"
        elif failure_type == "testing_failed":
            issues_text = "\n".join(f"  - {i}" for i in test_issues[:10]) if test_issues else "(无具体 issue)"
            failure_signal = f"TestAgent 测试不通过。问题列表：\n{issues_text}"
        elif failure_type == "engine_compile_failed":
            # v0.18 Phase D：UE 编译失败场景 —— errors 已结构化
            lines = []
            lines.append(f"UnrealBuildTool 编译失败 ({len(compile_errors)} errors, {len(compile_warnings)} warnings)。")
            if compile_cmd:
                lines.append(f"编译命令: `{compile_cmd}`")
            lines.append("\n错误列表（最多前 10 条）：")
            for e in compile_errors[:10]:
                fname = (e.get("file") or "?").split("\\")[-1].split("/")[-1]
                lines.append(
                    f"  - [{e.get('category', '?')}] {fname}:{e.get('line', '?')} "
                    f"{e.get('code', '')} — {(e.get('msg') or '')[:180]}"
                )
            if compile_warnings:
                lines.append("\n部分警告（前 3 条）：")
                for w in compile_warnings[:3]:
                    fname = (w.get("file") or "?").split("\\")[-1].split("/")[-1]
                    lines.append(
                        f"  - [{w.get('category', '?')}] {fname}:{w.get('line', '?')} "
                        f"{w.get('code', '')} — {(w.get('msg') or '')[:120]}"
                    )
            lines.append(
                "\n⚠️ UE 常见坑：\n"
                "  - 同名头文件（UHT 禁止）\n"
                "  - 漏 UCLASS/UFUNCTION/UPROPERTY 宏\n"
                "  - Build.cs 缺模块依赖（Core/CoreUObject/Engine/InputCore/EnhancedInput 等）\n"
                "  - include 的头文件路径错误（.generated.h 要匹配 class 名）\n"
                "  - GENERATED_BODY() 遗漏 或位置错\n"
                "  - 在 .cpp 直接 new FClass() 但 class 没继承 UObject 走不了 GC\n"
                "\n🚫 重要：这是 Unreal Engine C++ 项目，修复时只能输出 .h/.cpp/.Build.cs 文件！\n"
                "  绝对不能输出 Python/JavaScript/HTML/Flask/FastAPI 代码。\n"
                "  如果你觉得需要写 Python——你理解错了编译错误，请重新分析上面的 error 列表。"
            )
            failure_signal = "\n".join(lines)
        elif failure_type == "play_test_failed":
            # v0.19 Phase ②：UE Automation 测试失败
            failed_tests = context.get("failed_tests") or []
            summary = context.get("playtest_summary") or {}
            pt_cmd = context.get("playtest_command") or ""
            lines = []
            lines.append(
                f"UE Automation 测试失败 ({summary.get('failed', len(failed_tests))}/"
                f"{summary.get('total', 0)} failed)。"
            )
            if pt_cmd:
                lines.append(f"测试命令: `{pt_cmd}`")
            lines.append("\n失败测试（最多前 5 个）：")
            for t in failed_tests[:5]:
                name = t.get("name", "?")
                errs = "; ".join((t.get("errors") or [])[:2])[:200] or "(未捕获 error 行)"
                lines.append(f"  - {name}")
                lines.append(f"    → {errs}")
            lines.append(
                "\n⚠️ UE Automation 常见失败原因：\n"
                "  - Functional Test actor 未正确 Register（需 PostRegisterAllComponents 注册）\n"
                "  - 资产引用路径过期（BP 重命名后 C++ 里的 SoftObjectPath 没更新）\n"
                "  - Enhanced Input mapping 缺失（IA / IMC 没在 BP 或 DefaultInput.ini 里绑）\n"
                "  - Tick 逻辑依赖某帧已初始化但未用 FTimerHandle/GameState 等待\n"
                "  - nullrhi 模式下 UMG/渲染相关断言（检查是否强依赖真 GPU）\n"
                "  - Spawn/Replication 依赖客户端世界，单机 playtest 跑不到"
            )
            failure_signal = "\n".join(lines)
        elif failure_type == "self_test_failed":
            # v0.19.x A 方案：UE 静态预检（Layer 1）失败
            issues = context.get("ue_blocking_issues") or []
            lines = []
            lines.append(
                f"UE 自测失败（Layer 1 静态预检）：{len(issues)} 条 blocking issues。"
                f"**每条都是静态可发现的 UE C++ 常见错**，请按 suggest 逐条修复。"
            )
            lines.append("\n问题清单：")
            for idx, iss in enumerate(issues[:10], 1):
                rule = iss.get("rule", "?")
                file = iss.get("file", "?")
                line = iss.get("line")
                msg = (iss.get("msg") or "").replace("\n", " ")[:220]
                suggest = iss.get("suggest") or ""
                lines.append(
                    f"{idx}. [{rule}] {file}:{line or '?'} — {msg}"
                )
                if suggest:
                    lines.append(f"   → 建议: {suggest}")
            lines.append(
                "\n⚠️ 这些错在下游 UBT 编译会必然暴露（3-5 分钟后），"
                "但我们在开发阶段就用静态规则提前拦住。请严格按 suggest 修正，不要引入新的同类问题。\n"
                "\n🚫 提醒：这是 UE C++ 项目。修复时只输出 .h/.cpp/.Build.cs，绝对不能写 Python/JS/HTML！"
            )
            failure_signal = "\n".join(lines)
        else:
            failure_signal = f"失败类型: {failure_type}"

        # 历次反思段（最多 3 条）
        prev_block = ""
        if previous_reflections:
            keep = previous_reflections[-3:]
            lines = [f"[第 {i} 次反思] {_format_reflection_brief(r)}"
                     for i, r in enumerate(keep, 1)]
            prev_block = (
                "\n## 历次反思（以下策略执行后仍然失败）\n"
                + "\n".join(lines)
                + "\n⚠️ 上面的策略都没生效，这次**必须**换一种本质不同的思路。"
            )

        code_block = "\n## 上次产出的代码摘要\n" + _format_previous_code(previous_code)

        # 跨工单相似失败段（Failure Library 检索结果；可能为空）
        similar_block = _format_similar_failures(similar_failures)

        user_prompt = f"""## 任务
复盘开发失败并产出结构化反思。

## 原工单描述
{ticket_desc}

## 本次失败信号（第 {retry_count} 次重试）
{failure_signal}
{code_block}
{prev_block}
{similar_block}

## 输出要求：严格 JSON（不要 markdown 包裹）
{{
  "root_cause": "一句话说清失败根本原因。要具体到文件/函数/逻辑，不接受『代码没写好』这种空话",
  "missed_requirements": ["上一次漏掉/误解的具体需求点 1", "条目 2"],
  "previous_attempt_issue": "上一次的自测环节为什么没拦住这个问题",
  "strategy_change": "本次策略与上次的本质区别",
  "specific_changes": ["具体修改 1（到文件 / 位置）", "修改 2"],
  "confidence": 0.0
}}
输出纯 JSON。"""

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            raw = await llm_client.chat(messages, temperature=0.3, max_tokens=2000)
            reflection = _parse_json_lenient(raw)
            # 字段兜底（LLM 可能漏字段）
            reflection.setdefault("root_cause", "")
            reflection.setdefault("missed_requirements", [])
            reflection.setdefault("previous_attempt_issue", "")
            reflection.setdefault("strategy_change", rejection_reason or "")
            reflection.setdefault("specific_changes", [])
            reflection.setdefault("confidence", 0.5)
            # 类型兜底
            if not isinstance(reflection["missed_requirements"], list):
                reflection["missed_requirements"] = [str(reflection["missed_requirements"])]
            if not isinstance(reflection["specific_changes"], list):
                reflection["specific_changes"] = [str(reflection["specific_changes"])]
            try:
                reflection["confidence"] = float(reflection["confidence"])
            except (TypeError, ValueError):
                reflection["confidence"] = 0.5

            logger.info(
                "🔍 Reflection #%d: %s",
                retry_count,
                (reflection.get("root_cause") or "")[:120],
            )
        except Exception as e:
            logger.warning("Reflection 降级（LLM 或 JSON 解析失败）: %s", e)
            reflection = _minimal_reflection(failure_type, rejection_reason, test_issues, str(e))

        return ActionResult(
            success=True,
            data={"reflection": reflection, "retry_count": retry_count},
        )
