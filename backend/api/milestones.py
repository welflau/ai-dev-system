"""
AI 自动开发系统 - 里程碑 API
支持 AI 自动生成初版 Roadmap + 手动管理 + 需求驱动修正
"""
import json
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, BackgroundTasks
from database import db
from models import MilestoneCreate, MilestoneUpdate, MilestoneStatus
from utils import generate_id, now_iso

logger = logging.getLogger("milestones")

router = APIRouter(prefix="/api/projects/{project_id}/milestones", tags=["milestones"])


# ==================== AI 生成 Roadmap ====================


async def generate_roadmap_for_project(project_id: str, project_name: str, description: str):
    """AI 根据项目描述生成初版 Roadmap（里程碑列表）

    在项目创建后异步调用，不阻塞创建流程。
    如果 LLM 不可用，使用规则引擎降级生成。
    """
    try:
        from llm_client import llm_client, set_llm_context, clear_llm_context

        logger.info("🗺️ 开始为项目 %s 生成初版 Roadmap...", project_name)

        # 检查是否已有里程碑（避免重复生成）
        existing = await db.fetch_all(
            "SELECT id FROM milestones WHERE project_id = ?", (project_id,)
        )
        if existing:
            logger.info("项目 %s 已有 %d 个里程碑，跳过生成", project_id[:12], len(existing))
            return

        milestones_data = None

        if llm_client.is_configured:
            set_llm_context(
                project_id=project_id,
                agent_type="RoadmapPlanner",
                action="generate_roadmap",
            )
            try:
                milestones_data = await _generate_with_llm(
                    llm_client, project_name, description
                )
            except Exception as e:
                logger.warning("LLM 生成 Roadmap 失败，降级到规则引擎: %s", e)
            finally:
                clear_llm_context()

        if not milestones_data:
            milestones_data = _generate_fallback(project_name, description)

        # 写入数据库
        now = now_iso()
        base_date = datetime.now()

        for idx, ms in enumerate(milestones_data):
            ms_id = generate_id("MS")
            # 计算预估时间
            offset_days = ms.get("start_offset_days", idx * 14)
            duration_days = ms.get("duration_days", 14)

            planned_start = (base_date + timedelta(days=offset_days)).isoformat()
            planned_end = (base_date + timedelta(days=offset_days + duration_days)).isoformat()

            await db.insert("milestones", {
                "id": ms_id,
                "project_id": project_id,
                "title": ms["title"],
                "description": ms.get("description", ""),
                "sort_order": idx,
                "status": MilestoneStatus.PLANNED.value,
                "planned_start": planned_start,
                "planned_end": planned_end,
                "actual_start": None,
                "actual_end": None,
                "source": "ai_generated",
                "progress": 0,
                "created_at": now,
                "updated_at": now,
            })

        logger.info("✅ 项目 %s 已生成 %d 个里程碑", project_name, len(milestones_data))

    except Exception as e:
        logger.error("❌ 生成 Roadmap 失败: %s", e, exc_info=True)


async def _generate_with_llm(llm_client, project_name: str, description: str) -> list:
    """使用 LLM 生成里程碑列表"""
    prompt = f"""你是一位资深的项目规划专家。根据以下项目信息，生成合理的项目里程碑(Milestone)规划。

## 项目信息
- 名称：{project_name}
- 描述：{description or '暂无详细描述'}

## 要求
1. 生成 3~6 个里程碑，按时间顺序排列
2. 每个里程碑应该是一个有意义的交付节点
3. 包含合理的时间预估（天数）
4. 第一个里程碑应该是基础架构/MVP

## 输出格式
严格输出 JSON 数组，不要包含任何其他文字。每个元素：
```json
[
  {{
    "title": "里程碑标题（简洁，10字以内）",
    "description": "关键交付物和验收标准",
    "duration_days": 14,
    "start_offset_days": 0,
    "dependencies": []
  }}
]
```

start_offset_days 是从项目启动日算起的偏移天数。
dependencies 是依赖的里程碑索引数组（从0开始）。
duration_days 一般 7~30 天。
"""

    messages = [
        {"role": "system", "content": "你是项目规划专家。只输出 JSON 数组，不要任何额外说明。"},
        {"role": "user", "content": prompt},
    ]

    response = await llm_client.chat(messages, temperature=0.3, max_tokens=2000)

    # 解析 JSON
    import re
    json_match = re.search(r'\[.*\]', response, re.DOTALL)
    if not json_match:
        raise ValueError(f"LLM 返回无法解析为 JSON: {response[:200]}")

    milestones = json.loads(json_match.group())

    # 验证格式
    if not isinstance(milestones, list) or len(milestones) == 0:
        raise ValueError("LLM 返回的里程碑列表为空")

    for ms in milestones:
        if "title" not in ms:
            raise ValueError(f"里程碑缺少 title 字段: {ms}")
        ms.setdefault("description", "")
        ms.setdefault("duration_days", 14)
        ms.setdefault("start_offset_days", 0)

    return milestones[:6]  # 最多 6 个


def _generate_fallback(project_name: str, description: str) -> list:
    """规则引擎降级生成里程碑"""
    logger.info("[规则引擎] 为项目 %s 生成默认里程碑", project_name)

    return [
        {
            "title": "需求分析与架构设计",
            "description": "完成需求梳理、技术选型、系统架构设计",
            "duration_days": 7,
            "start_offset_days": 0,
        },
        {
            "title": "核心功能开发",
            "description": "实现核心业务功能和基础 API",
            "duration_days": 21,
            "start_offset_days": 7,
        },
        {
            "title": "功能完善与集成",
            "description": "完善辅助功能、前后端集成、UI 优化",
            "duration_days": 14,
            "start_offset_days": 28,
        },
        {
            "title": "测试与优化",
            "description": "全面测试、性能优化、Bug 修复",
            "duration_days": 10,
            "start_offset_days": 42,
        },
        {
            "title": "部署上线",
            "description": "部署环境搭建、数据迁移、上线发布",
            "duration_days": 5,
            "start_offset_days": 52,
        },
    ]


# ==================== 需求创建时自动修正 Roadmap ====================


async def auto_associate_requirement(project_id: str, requirement_id: str,
                                     title: str, description: str, ticket_count: int = 0):
    """需求创建/拆单完成后，自动关联里程碑 + 修正预估

    调用时机：
    1. 需求拆单完成后（orchestrator 中 handle_requirement 结束时）
    2. 手动创建需求时（如果已有里程碑）
    """
    try:
        milestones = await db.fetch_all(
            "SELECT * FROM milestones WHERE project_id = ? ORDER BY sort_order",
            (project_id,),
        )
        if not milestones:
            return  # 没有里程碑，跳过

        # 尝试用 LLM 智能匹配
        matched_ms_id = None
        from llm_client import llm_client

        if llm_client.is_configured:
            try:
                matched_ms_id = await _match_milestone_with_llm(
                    llm_client, milestones, title, description
                )
            except Exception as e:
                logger.warning("LLM 匹配里程碑失败: %s", e)

        # 降级：匹配第一个未完成的里程碑
        if not matched_ms_id:
            for ms in milestones:
                if ms["status"] in ("planned", "in_progress"):
                    matched_ms_id = ms["id"]
                    break

        if matched_ms_id:
            # 关联需求到里程碑
            await db.update("requirements", {
                "milestone_id": matched_ms_id,
                "updated_at": now_iso(),
            }, "id = ?", (requirement_id,))

            # 更新里程碑进度
            await update_milestone_progress(project_id, matched_ms_id)

            logger.info("需求 %s 已关联到里程碑 %s", requirement_id[:12], matched_ms_id[:12])

    except Exception as e:
        logger.error("自动关联里程碑失败: %s", e, exc_info=True)


async def _match_milestone_with_llm(llm_client, milestones: list, req_title: str, req_desc: str) -> str:
    """LLM 智能匹配需求到最合适的里程碑"""
    ms_list = "\n".join(
        f"  [{i}] {ms['title']} — {ms.get('description', '')[:50]} (状态: {ms['status']})"
        for i, ms in enumerate(milestones)
    )

    prompt = f"""你是项目管理助手。请判断以下需求应该属于哪个里程碑。

## 里程碑列表
{ms_list}

## 新需求
- 标题：{req_title}
- 描述：{req_desc[:300]}

请只回复里程碑的索引编号（如 0、1、2），不要其他内容。
如果需求与所有里程碑都不太匹配，回复最接近的那个。
"""

    messages = [
        {"role": "system", "content": "只回复数字索引，不要任何其他文字。"},
        {"role": "user", "content": prompt},
    ]

    response = await llm_client.chat(messages, temperature=0.1, max_tokens=10)

    # 解析索引
    import re
    idx_match = re.search(r'\d+', response.strip())
    if idx_match:
        idx = int(idx_match.group())
        if 0 <= idx < len(milestones):
            return milestones[idx]["id"]

    return None


async def update_milestone_progress(project_id: str, milestone_id: str):
    """根据关联需求和工单的实际状态更新里程碑进度"""
    try:
        # 获取关联到此里程碑的需求
        reqs = await db.fetch_all(
            "SELECT id, status FROM requirements WHERE milestone_id = ? AND project_id = ?",
            (milestone_id, project_id),
        )

        if not reqs:
            return

        # 获取这些需求下的所有工单
        req_ids = [r["id"] for r in reqs]
        if not req_ids:
            return

        placeholders = ",".join(["?"] * len(req_ids))
        tickets = await db.fetch_all(
            f"SELECT status FROM tickets WHERE requirement_id IN ({placeholders})",
            tuple(req_ids),
        )

        # 计算进度
        if not tickets:
            total_reqs = len(reqs)
            completed_reqs = sum(1 for r in reqs if r["status"] == "completed")
            progress = int(completed_reqs / total_reqs * 100) if total_reqs > 0 else 0
        else:
            total = len(tickets)
            done = sum(1 for t in tickets if t["status"] in ("deployed", "testing_done"))
            partial = sum(1 for t in tickets if t["status"] in (
                "development_done", "acceptance_passed", "testing_in_progress", "deploying",
            ))
            in_dev = sum(1 for t in tickets if t["status"] in (
                "architecture_in_progress", "architecture_done",
                "development_in_progress", "acceptance_rejected", "testing_failed",
            ))
            score = done * 1.0 + partial * 0.7 + in_dev * 0.3
            progress = min(100, int(score / total * 100))

        # 判定里程碑状态
        now = now_iso()
        ms = await db.fetch_one("SELECT * FROM milestones WHERE id = ?", (milestone_id,))
        if not ms:
            return

        update_data = {"progress": progress, "updated_at": now}

        if progress >= 100:
            update_data["status"] = MilestoneStatus.COMPLETED.value
            update_data["actual_end"] = now
        elif progress > 0:
            new_status = MilestoneStatus.IN_PROGRESS.value
            # 检查是否延期
            if ms.get("planned_end"):
                try:
                    planned_end = datetime.fromisoformat(ms["planned_end"])
                    if datetime.now() > planned_end and progress < 100:
                        new_status = MilestoneStatus.DELAYED.value
                except Exception:
                    pass
            update_data["status"] = new_status
            if not ms.get("actual_start"):
                update_data["actual_start"] = now

        await db.update("milestones", update_data, "id = ?", (milestone_id,))

    except Exception as e:
        logger.error("更新里程碑进度失败: %s", e, exc_info=True)


async def refresh_all_milestones(project_id: str):
    """刷新项目下所有里程碑的进度（在工单状态变更时调用）"""
    milestones = await db.fetch_all(
        "SELECT id FROM milestones WHERE project_id = ? AND status NOT IN ('completed', 'cancelled')",
        (project_id,),
    )
    for ms in milestones:
        await update_milestone_progress(project_id, ms["id"])


# ==================== REST API ====================


@router.get("")
async def list_milestones(project_id: str):
    """获取项目里程碑列表"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    milestones = await db.fetch_all(
        "SELECT * FROM milestones WHERE project_id = ? ORDER BY sort_order, created_at",
        (project_id,),
    )

    # 附带每个里程碑下的需求数量
    for ms in milestones:
        req_count = await db.fetch_one(
            "SELECT COUNT(*) as count FROM requirements WHERE milestone_id = ?", (ms["id"],)
        )
        ms["requirement_count"] = req_count["count"] if req_count else 0

    return {"milestones": milestones, "total": len(milestones)}


@router.post("")
async def create_milestone(project_id: str, req: MilestoneCreate):
    """手动创建里程碑"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    ms_id = generate_id("MS")
    now = now_iso()

    await db.insert("milestones", {
        "id": ms_id,
        "project_id": project_id,
        "title": req.title,
        "description": req.description or "",
        "sort_order": req.sort_order,
        "status": MilestoneStatus.PLANNED.value,
        "planned_start": req.planned_start,
        "planned_end": req.planned_end,
        "actual_start": None,
        "actual_end": None,
        "source": "manual",
        "progress": 0,
        "created_at": now,
        "updated_at": now,
    })

    return {"id": ms_id, "message": "里程碑已创建"}


@router.put("/{milestone_id}")
async def update_milestone(project_id: str, milestone_id: str, req: MilestoneUpdate):
    """更新里程碑"""
    ms = await db.fetch_one(
        "SELECT * FROM milestones WHERE id = ? AND project_id = ?",
        (milestone_id, project_id),
    )
    if not ms:
        raise HTTPException(404, "里程碑不存在")

    update_data = {}
    for field in ("title", "description", "planned_start", "planned_end", "sort_order", "status"):
        val = getattr(req, field, None)
        if val is not None:
            update_data[field] = val

    if update_data:
        update_data["updated_at"] = now_iso()
        await db.update("milestones", update_data, "id = ?", (milestone_id,))

    return {"message": "里程碑已更新"}


@router.delete("/{milestone_id}")
async def delete_milestone(project_id: str, milestone_id: str):
    """删除里程碑"""
    ms = await db.fetch_one(
        "SELECT * FROM milestones WHERE id = ? AND project_id = ?",
        (milestone_id, project_id),
    )
    if not ms:
        raise HTTPException(404, "里程碑不存在")

    # 解除关联的需求
    await db.execute(
        "UPDATE requirements SET milestone_id = NULL WHERE milestone_id = ?",
        (milestone_id,),
    )

    await db.delete("milestones", "id = ?", (milestone_id,))

    return {"message": "里程碑已删除"}


@router.post("/generate")
async def generate_milestones(project_id: str, background_tasks: BackgroundTasks):
    """手动触发 AI 重新生成里程碑"""
    project = await db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        raise HTTPException(404, "项目不存在")

    # 删除现有 AI 生成的里程碑
    await db.delete("milestones", "project_id = ? AND source = 'ai_generated'", (project_id,))
    # 解除关联
    await db.execute(
        "UPDATE requirements SET milestone_id = NULL WHERE project_id = ? AND milestone_id IS NOT NULL",
        (project_id,),
    )

    background_tasks.add_task(
        generate_roadmap_for_project,
        project_id,
        project["name"],
        project.get("description", ""),
    )

    return {"message": "正在重新生成 Roadmap，请稍候刷新"}
