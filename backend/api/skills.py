"""
Skills 状态 API —— 只读返回 skills.json 中所有 Skill 的状态，供前端 Agent 配置页展示
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("")
async def list_skills():
    """返回所有 Skill 的状态（名字、描述、注入到哪些 Agent、优先级、prompt 是否存在）"""
    from skills import skill_loader

    status = skill_loader.get_all_skills_status()
    skills = [
        {
            "id": sid,
            "name": info["name"],
            "description": info["description"],
            "enabled": info["enabled"],
            "inject_to": info["inject_to"],
            "priority": info["priority"],
            "prompt_exists": info["prompt_exists"],
        }
        for sid, info in status.items()
    ]
    return {"skills": skills, "total": len(skills)}
