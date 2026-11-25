"""SOP 编辑器的流程视图、配置读写和热重载路由。"""
from fastapi import APIRouter, HTTPException

from runtime_facade import get_orchestrator
from services import sop_config
from sop import loader

router = APIRouter(prefix="/api/sop")


@router.get("")
async def get_sop():
    """获取当前 SOP 配置（流程定义）"""
    orch = get_orchestrator()
    return sop_config.workflow_view(orch._sop_config, orch.transition_rules)


@router.get("/config")
async def get_sop_config_full():
    """获取 SOP 的完整原始配置（含 pipeline_view / global / 每个 stage 的 config 嵌套）

    供 SOP 编辑器使用，返回可直接回传 PUT 的完整结构。
    """
    return get_orchestrator()._sop_config or {}


@router.put("/config")
async def update_sop_config(body: dict):
    """更新 SOP 配置（SOP 编辑器用）

    流程：
    1. 校验入参（字段齐全、id 唯一、reject_goto / pipeline_view 引用合法）
    2. 备份当前 yaml 到 sop/backups/default_sop_YYYYMMDD-HHMMSS.yaml
    3. 写入新 yaml
    4. 热重载 orchestrator
    """
    try:
        return sop_config.save_config(body, loader.SOP_DIR, get_orchestrator().reload_sop)
    except sop_config.InvalidSopConfig as exc:
        raise HTTPException(400, {"detail": str(exc), "errors": exc.errors}) from exc
    except sop_config.SopSaveError as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/reload")
async def reload_sop():
    """热重载 SOP 配置"""
    config = get_orchestrator().reload_sop()
    return {"status": "ok", "message": "SOP 已重载", "name": config.get("name", "?") if config else "内置默认"}
