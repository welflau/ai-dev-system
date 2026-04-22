"""
Self-Consistency 投票 —— 对发散/主观型 Action（拆单、架构设计）做多候选 + Critic 选优。

对标 MagicAI 对比分析 `docs/20260418_01_MagicAI对比分析.md` ⭐⭐⭐ 最后一项。
论文：Shinn et al., Wang et al. 2022 *Self-Consistency Improves Chain of Thought Reasoning*

## 核心流程

1. 并行跑 N 次 ActionNode.fill（高温 0.8 获得差异化候选）
2. 过滤 instruct_content 非空的成功候选
3. >1 个候选 → LLM judge 按评分标准选 best
4. judge 失败兜底：返回候选 0 + warning

## 开销

N=3 候选 + 1 次 judge = **4× 单次 LLM 成本**。默认关闭（SOP config opt-in）。
只建议给 architecture / decompose 这类低频 + 主观的 stage 开启。

详见 docs/20260422_01_SelfConsistency投票实现方案.md
"""
import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Tuple

from actions.action_node import ActionNode

logger = logging.getLogger("voting")


_JUDGE_SYSTEM_PROMPT = """你是一位资深技术评审，正在从多个候选方案里挑出最优的一个。

判分标准（按重要性降序）：
1. **完整性**：方案是否覆盖任务所有要点，没有漏掉明显需求
2. **可执行性**：具体到文件/模块/步骤，不空泛、不模板化
3. **与任务契合度**：没拆出无关工单 / 没设计过度复杂的架构 / 没重复已有功能
4. **内部一致性**：内部各字段之间不矛盾（如复杂度=simple 但拆了 5 个工单）

输出严格 JSON，不要 markdown 包裹。"""


async def fill_with_consistency(
    node_factory: Callable[[], ActionNode],
    req: str,
    llm,
    *,
    n: int = 3,
    temperature: float = 0.8,
    max_tokens: int = 4000,
    task_desc: str = "",
) -> Tuple[ActionNode, List[ActionNode], Dict[str, Any]]:
    """并行生成 N 个候选 → LLM judge → 返回 (best_node, all_nodes, judge_info)

    Args:
        node_factory: 无参 callable，每次返回一个全新的 ActionNode 实例。
                      必须每次 new 新的（ActionNode 持有 instruct_content 状态）。
        req: 传给 ActionNode.fill 的 req 参数
        llm: llm_client 实例（需有 chat / chat_json 方法）
        n: 候选数量（默认 3；>5 不建议）
        temperature: 候选温度（默认 0.8；越高越发散）
        max_tokens: 每个候选的 max_tokens
        task_desc: 给 judge 看的任务描述（短的一两句话）

    Returns:
        (best_node, all_candidates, judge_info)
        - best_node: 被选中的 ActionNode（instruct_content 已填充）
        - all_candidates: 所有成功候选（含 best_node）
        - judge_info: {"best_index": int, "reasoning": str, "fallback": bool}

    Raises:
        ValueError: 如果 N 个候选全部失败
    """
    if n < 1:
        n = 1

    # Phase 1: 并行生成 N 个候选
    logger.info("🗳️  Self-Consistency: 生成 %d 个候选 (temp=%.1f)", n, temperature)
    tasks = [
        _fill_one(node_factory(), req, llm, max_tokens, temperature, idx=i)
        for i in range(n)
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    # 过滤成功候选
    candidates: List[ActionNode] = []
    for i, r in enumerate(raw_results):
        if isinstance(r, Exception):
            logger.warning("候选 #%d 异常: %s: %s", i, type(r).__name__, r)
            continue
        if r is None or r.instruct_content is None:
            logger.warning("候选 #%d 返回无效", i)
            continue
        candidates.append(r)

    if not candidates:
        raise ValueError(f"Self-Consistency: {n} 个候选全部失败")

    if len(candidates) == 1:
        logger.info("✅ Self-Consistency: 只 1 个候选成功，直接返回")
        return candidates[0], candidates, {
            "best_index": 0,
            "reasoning": "(唯一成功候选，跳过 judge)",
            "fallback": False,
        }

    # Phase 2: Judge 选 best
    best_idx, judge_info = await _judge_candidates(candidates, task_desc, llm)
    logger.info(
        "🏆 Self-Consistency: judge 选中候选 #%d / %d (fallback=%s)",
        best_idx, len(candidates), judge_info.get("fallback"),
    )
    return candidates[best_idx], candidates, judge_info


async def _fill_one(
    node: ActionNode, req: str, llm, max_tokens: int, temperature: float, idx: int,
) -> ActionNode:
    """跑一个候选。失败时 raise（上层 gather(return_exceptions=True) 捕获）。"""
    await node.fill(req=req, llm=llm, max_tokens=max_tokens, temperature=temperature)
    return node


async def _judge_candidates(
    candidates: List[ActionNode], task_desc: str, llm,
) -> Tuple[int, Dict[str, Any]]:
    """LLM judge 从候选里挑 best。失败时 fallback 返回候选 0。"""
    # 构造候选展示（用 raw_content 避免 Pydantic 序列化开销）
    candidates_text = []
    for i, node in enumerate(candidates):
        raw = node.raw_content or "{}"
        # 限制单候选长度，避免 judge prompt 爆
        if len(raw) > 2000:
            raw = raw[:2000] + "...(截断)"
        label = chr(ord("A") + i)
        candidates_text.append(f"### 候选 {label} (index={i})\n```json\n{raw}\n```")

    user_prompt = f"""## 任务
{task_desc or '从以下候选中选最优方案'}

## 候选方案
{chr(10).join(candidates_text)}

## 输出格式
{{
  "best_index": 0,
  "reasoning": "简短理由（不超过 80 字），说明为何选中 best_index 对应的候选"
}}

只输出 JSON，不要 markdown 包裹。"""

    messages = [
        {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        raw = await llm.chat(messages, temperature=0.2, max_tokens=400)
        parsed = _parse_judge_json(raw)
        best_idx = int(parsed.get("best_index", 0))
        # 防越界
        if best_idx < 0 or best_idx >= len(candidates):
            logger.warning("judge 返回 best_index 越界: %d，fallback 到 0", best_idx)
            best_idx = 0
        return best_idx, {
            "best_index": best_idx,
            "reasoning": (parsed.get("reasoning") or "")[:300],
            "fallback": False,
        }
    except Exception as e:
        logger.warning("Judge 调用/解析失败（%s），fallback 到候选 0", e)
        return 0, {
            "best_index": 0,
            "reasoning": f"(judge 失败: {type(e).__name__})",
            "fallback": True,
        }


def _parse_judge_json(raw: str) -> Dict[str, Any]:
    """容错 JSON 解析：剥 markdown 包裹；提取第一对大括号。"""
    s = (raw or "").strip()
    if s.startswith("```"):
        lines = [ln for ln in s.split("\n") if not ln.strip().startswith("```")]
        s = "\n".join(lines).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        return json.loads(s[start:end + 1])
    raise ValueError("无法从 judge 输出解析 JSON")
