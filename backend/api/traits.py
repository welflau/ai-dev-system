"""
Traits 只读 API —— 暴露 trait_taxonomy 和 presets 给前端查看

v0.17 Phase A 附加项。完整的编辑 UI 留给 Phase E。

端点：
- GET /api/traits/taxonomy   返回分类法（11 维度 + 约束规则）
- GET /api/traits/presets    返回 7 个内置 preset + 冲突规则
- POST /api/traits/match     用 user_text 试一次 preset 推荐（调试用）
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

import yaml
from pathlib import Path

router = APIRouter(prefix="/api/traits", tags=["traits"])


_TAX_PATH = Path(__file__).resolve().parent.parent / "skills" / "rules" / "trait_taxonomy.yaml"
_PRE_PATH = Path(__file__).resolve().parent.parent / "skills" / "rules" / "presets.yaml"


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise HTTPException(500, f"{path.name} 不存在")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        raise HTTPException(500, f"解析 {path.name} 失败: {e}")


@router.get("/taxonomy")
async def get_taxonomy():
    """返回 trait 分类法。"""
    data = _load_yaml(_TAX_PATH)
    # 拍平成前端好用的 shape：[{dim, description, values}]
    dimensions = []
    total_values = 0
    for key, val in data.items():
        if not isinstance(val, dict) or "values" not in val:
            continue
        dimensions.append({
            "dim": key,
            "description": val.get("description", ""),
            "values": val.get("values", []),
        })
        total_values += len(val.get("values", []))
    return {
        "dimensions": dimensions,
        "total_dimensions": len(dimensions),
        "total_values": total_values,
        "constraints": data.get("constraints", {}),
    }


@router.get("/presets")
async def get_presets():
    """返回所有内置 preset + 冲突规则 + 匹配配置。"""
    data = _load_yaml(_PRE_PATH)
    presets_raw = data.get("presets", {})
    presets = [
        {
            "preset_id": pid,
            "label": p.get("label", pid),
            "description": p.get("description", ""),
            "traits": p.get("traits", []),
            "keywords": p.get("keywords", []),
            "source": p.get("source", "builtin"),
        }
        for pid, p in presets_raw.items()
    ]
    return {
        "presets": presets,
        "conflict_rules": data.get("conflict_rules", []),
        "matching": data.get("matching", {}),
        "total": len(presets),
    }


class MatchRequest(BaseModel):
    message: str
    top_n: Optional[int] = 3


@router.post("/match")
async def match_presets(req: MatchRequest):
    """调试：给一段 user_text，返回 preset 匹配结果。"""
    from skills import preset_matcher

    matches = preset_matcher.match(req.message, top_n=req.top_n or 3)
    return {
        "message": req.message,
        "matches": [m.to_dict() for m in matches],
        "total": len(matches),
    }
