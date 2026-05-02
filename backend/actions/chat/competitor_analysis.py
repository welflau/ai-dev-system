"""
CompetitorAnalysisAction — 竞品反拆

流程：
1. 抓取竞品 URL 的页面内容
2. LLM 分析产出结构化反拆报告（系统设计/核心循环/商业化/UX 亮点）
3. 保存到 G_DesignKnowledge/planning/competitors/{game_slug}/
4. 触发 planning_knowledge 表同步，策划 Agent 下次可检索

触发方式：
  用户在项目 AI 助手里说：「分析一下 {游戏名} 这个游戏」
  ChatAssistant 调用此 Action，URL 从对话中提取
"""
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict

from actions.base import ActionBase, ActionResult
from actions.action_node import ActionNode
from pydantic import BaseModel

logger = logging.getLogger("action.competitor_analysis")


class CompetitorAnalysisOutput(BaseModel):
    game_name: str = ""          # 竞品名称
    genre: str = ""              # 游戏/产品类型
    core_loop: str = ""          # 核心循环描述
    system_design: str = ""      # 系统设计亮点（背包/战斗/成长/社交等）
    ux_highlights: str = ""      # UX/交互设计亮点
    monetization: str = ""       # 商业化策略
    strengths: str = ""          # 优势（可借鉴）
    weaknesses: str = ""         # 不足（可规避）
    key_insights: str = ""       # 核心洞察（3条以内）


class CompetitorAnalysisAction(ActionBase):

    @property
    def name(self) -> str:
        return "competitor_analysis"

    @property
    def description(self) -> str:
        return "抓取并分析竞品游戏/产品，产出结构化反拆报告存入策划知识库"

    @property
    def tool_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "分析竞品游戏或产品，产出结构化反拆报告（核心循环/系统设计/UX亮点/商业化）"
                "并自动存入策划知识库，后续策划设计时可自动检索参考。\n"
                "用户说「分析 XXX 游戏」「竞品调研 XXX」「看看 XXX 是怎么设计的」时调用。"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "竞品网站/App Store/Steam 页面 URL",
                    },
                    "game_name": {
                        "type": "string",
                        "description": "竞品名称（如 URL 不够明确时补充）",
                    },
                    "focus": {
                        "type": "string",
                        "description": "重点分析方向（如 战斗系统/商业化/UX），默认全面分析",
                    },
                },
                "required": ["url"],
            },
        }

    async def run(self, context: Dict[str, Any]) -> ActionResult:
        from llm_client import llm_client

        url        = (context.get("url") or "").strip()
        game_name  = (context.get("game_name") or "").strip()
        focus      = (context.get("focus") or "全面分析").strip()
        project_id = context.get("project_id", "")

        if not url:
            return ActionResult(success=False, error="URL 不能为空")

        # Step 1: 抓取页面内容
        page_content = await self._fetch_page(url)
        if not page_content:
            return ActionResult(success=False, error=f"无法获取页面内容：{url}")

        # Step 2: LLM 分析
        req_context = f"""## 竞品分析任务

URL：{url}
竞品名称：{game_name or '（从内容中识别）'}
分析重点：{focus}

## 页面内容
{page_content[:4000]}

## 分析要求

请对这个游戏/产品进行结构化反拆：
- **core_loop**：用户每次打开做什么，核心循环（操作→反馈→奖励→再操作）
- **system_design**：系统设计亮点（背包/战斗/成长/社交/关卡 等）每项2-3句
- **ux_highlights**：UX/交互设计值得借鉴的地方
- **monetization**：商业化策略（内购/广告/订阅/道具类型/定价）
- **strengths**：3-5 个可以借鉴的优势
- **weaknesses**：2-3 个明显不足或玩家痛点
- **key_insights**：最重要的 3 条洞察（对我们做类似产品最有用的点）"""

        node = ActionNode(
            key="competitor_analysis",
            expected_type=CompetitorAnalysisOutput,
            instruction="[MODE: EXPLORE] 你是游戏/产品分析师，对竞品进行专业的结构化反拆。保持客观，挖掘可借鉴的设计。",
        )

        await node.fill(req=req_context, llm=llm_client, max_tokens=4000)
        output = node.instruct_content

        if not output or not output.core_loop:
            return ActionResult(success=False, error="分析未能产出有效内容，请检查 URL 是否可访问")

        detected_name = output.game_name or game_name or _slug_from_url(url)
        output.game_name = detected_name

        # Step 3: 构建报告 Markdown
        report_md = _build_report_md(output, url, focus)

        # Step 4: 保存到 G_DesignKnowledge
        saved_path = await _save_to_design_knowledge(detected_name, report_md)

        # Step 5: 触发知识库同步
        if saved_path:
            await _sync_to_db(saved_path, detected_name, output, project_id)

        logger.info("✅ 竞品反拆完成: %s → %s", detected_name, saved_path or "仅返回结果")

        return ActionResult(
            success=True,
            data={
                "type": "competitor_analysis",
                "game_name": detected_name,
                "url": url,
                "report": report_md,
                "saved_path": saved_path or "",
                "message": f"竞品「{detected_name}」分析完成{'，已存入策划知识库' if saved_path else ''}",
            },
        )

    async def _fetch_page(self, url: str) -> str:
        """抓取页面文本内容"""
        try:
            import ssl, urllib.request, re as _re
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")

            # 简单提取文本
            text = _re.sub(r"<style[^>]*>.*?</style>", " ", raw, flags=_re.DOTALL)
            text = _re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=_re.DOTALL)
            text = _re.sub(r"<[^>]+>", " ", text)
            text = _re.sub(r"[ \t]+", " ", text)
            text = _re.sub(r"\n{3,}", "\n\n", text)
            return text.strip()[:5000]
        except Exception as e:
            logger.warning("页面抓取失败 %s: %s", url, e)
            return ""


def _slug_from_url(url: str) -> str:
    """从 URL 提取游戏名"""
    parts = url.rstrip("/").split("/")
    name = parts[-1] or parts[-2] if len(parts) > 1 else "unknown"
    return re.sub(r"[^a-zA-Z0-9一-鿿]", "_", name)[:30]


def _build_report_md(output: CompetitorAnalysisOutput, url: str, focus: str) -> str:
    return f"""# 竞品反拆：{output.game_name}

> URL：{url}
> 分析重点：{focus}
> 类型：{output.genre}

## 核心循环
{output.core_loop}

## 系统设计亮点
{output.system_design}

## UX / 交互设计
{output.ux_highlights}

## 商业化策略
{output.monetization}

## 优势（可借鉴）
{output.strengths}

## 不足（可规避）
{output.weaknesses}

## 核心洞察
{output.key_insights}
"""


async def _save_to_design_knowledge(game_name: str, report_md: str) -> str:
    """保存报告到 G_DesignKnowledge"""
    from config import settings
    kb_path = Path(settings.GLOBAL_KNOWLEDGE_LOCAL_PATH)
    if not kb_path.exists():
        return ""

    slug = re.sub(r"[^\w一-鿿]", "_", game_name)[:30]
    save_dir = kb_path / "planning" / "competitors"
    save_dir.mkdir(parents=True, exist_ok=True)
    file_path = save_dir / f"{slug}.md"
    try:
        file_path.write_text(report_md, encoding="utf-8")
        rel = str(file_path.relative_to(kb_path)).replace("\\", "/")
        return rel
    except Exception as e:
        logger.warning("保存报告失败: %s", e)
        return ""


async def _sync_to_db(rel_path: str, game_name: str, output: CompetitorAnalysisOutput,
                      project_id: str) -> None:
    """将报告同步到 planning_knowledge 表"""
    try:
        from database import db
        from utils import now_iso
        asset_id = "DKB-comp-" + hashlib.md5(rel_path.encode()).hexdigest()[:8]
        tags = json.dumps(
            ["competitor", output.genre, game_name] + output.key_insights.split()[:3],
            ensure_ascii=False,
        )
        content = f"# {game_name}\n\n核心循环：{output.core_loop}\n\n洞察：{output.key_insights}"
        await db.execute("""
            INSERT INTO planning_knowledge
            (id, filename, title, category, subcategory, tags, content, summary, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(filename) DO UPDATE SET
                content=excluded.content, summary=excluded.summary, updated_at=excluded.updated_at
        """, (asset_id, rel_path, game_name, "competitors", output.genre,
              tags, content, content[:200], now_iso()))
        logger.info("planning_knowledge 已入库: %s", game_name)
    except Exception as e:
        logger.warning("竞品报告入库失败: %s", e)
