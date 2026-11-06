"""
ticket_classifier.py — 直接工单的请求分类器

对齐 MagicAI 的 Phase -1 请求分类（agent_session.py:202-231 +
agent_session_config.py:60-124）：
  1. MODIFY 模式判定：has_modify and not has_new，或短消息
  2. 关键词评分：MODIFY_KEYWORD_AGENT_MAP 评分 → 细分降级档位

ADS 落地为 start_from 三档（受 SOP 状态机限制，不能像 MagicAI
任意组合 Agent，只能跳前置整段）：
  pending                 → 完整 SOP（A 大类变更 / 判不准）
  architecture_done       → 跳过规划+架构（B 小改，涉及设计/资产）
  development_in_progress → 立即开发（B' 原子任务，纯代码/测试修改）

保守原则：只降级不升级，判不准走 pending（宁可多跑，不可漏做）。
详见 docs/20261105_06_请求分类前置层设计方案.md
"""
from __future__ import annotations

from typing import Dict, List

# ── 词表（对齐 MagicAI agent_session.py:208-217）────────────────
_MODIFY_INDICATORS = [
    '修改', '调整', '改', '更改', '变更', '设置', '参数',
    'modify', 'change', 'adjust', 'update', 'fix', 'set',
    '速度', '大小', '颜色', 'speed', 'size', 'color',
    '添加', '删除', '移除', 'add', 'remove', 'delete',
]

_NEW_PROJECT_INDICATORS = [
    '新游戏', '新项目', '创建', '开发一个', '做一个',
    'new game', 'new project', 'create', 'build a',
]

# ── 关键词评分（对齐 MODIFY_KEYWORD_AGENT_MAP，映射 ADS Role）────
_MODIFY_KEYWORD_AGENT_MAP: Dict[str, List[str]] = {
    "DevAgent": [
        "速度", "参数", "修改", "调整", "变量", "脚本", "代码", "函数", "方法",
        "修复", "bug", "fix", "实现", "implement", "逻辑", "功能", "feature",
        "碰撞", "物理", "信号", "signal", "input", "输入", "配置", "config",
        "speed", "health", "damage", "score", "level", "gravity",
    ],
    "ArtAgent": [
        "美术", "素材", "图片", "sprite", "贴图", "纹理", "texture", "ui",
        "图标", "icon", "动画", "animation", "资产", "asset", "颜色", "color",
        "像素", "pixel", "字体", "font", "主题", "theme", "背景", "background",
    ],
    "PlannerAgent": [
        "设计", "策划", "文档", "需求", "规划", "plan", "design", "requirement",
        "玩法", "gameplay", "关卡", "level design", "机制", "mechanic",
    ],
    "TestAgent": [
        "测试", "test", "验证", "verify", "检查", "check", "qa",
        "质量", "quality", "编译", "compile", "运行", "run",
    ],
    "DeployAgent": [
        "发布", "publish", "导出", "export", "打包", "build", "部署", "deploy",
    ],
}

# 需要「设计/资产」阶段的 Agent（涉及它们 → 跳过规划，但不跳过美术）
_DESIGN_HEAVY_AGENTS = ("PlannerAgent", "ArtAgent")

# 短消息阈值（对齐 MagicAI：len(message) < 100 → 大概率 MODIFY/QUESTION）
_SHORT_MESSAGE_THRESHOLD = 100


def classify_start_from(
    title: str,
    description: str = "",
    ticket_type: str = "feature",
) -> str:
    """自动判断直接工单的 start_from。

    Returns:
        "pending" / "architecture_done" / "development_in_progress"
    """
    msg = f"{title} {description}".strip()
    msg_lower = msg.lower()

    # bugfix → 立即开发（bug 修复不需设计/规划）
    if ticket_type == "bugfix":
        return "development_in_progress"

    # 空标题/空描述 → 无法分类，走完整流程
    if not msg:
        return "pending"

    # A 大类变更：新建词 → pending（完整 SOP）
    if any(ind in msg_lower for ind in _NEW_PROJECT_INDICATORS):
        return "pending"

    # B 小改：修改词 或 短消息 → 关键词评分
    has_modify = any(ind in msg_lower for ind in _MODIFY_INDICATORS)
    if has_modify or len(msg) < _SHORT_MESSAGE_THRESHOLD:
        scores = _score_agents(msg_lower)

        # 涉及设计/资产（Planner/Art）→ 跳过规划，仍走美术+开发
        if any(a in scores for a in _DESIGN_HEAVY_AGENTS):
            return "architecture_done"
        # 纯代码/测试修改 → 立即开发
        if scores:
            return "development_in_progress"

    # 判不准 → pending（保守：短消息/修改词不足以证明是小改）
    return "pending"


def _score_agents(msg_lower: str) -> Dict[str, int]:
    """关键词评分：每个 Agent 得分 = 命中关键词数（对齐 infer_agents_for_modify）。"""
    scores: Dict[str, int] = {}
    for agent, keywords in _MODIFY_KEYWORD_AGENT_MAP.items():
        s = sum(1 for kw in keywords if kw.lower() in msg_lower)
        if s > 0:
            scores[agent] = s
    return scores
