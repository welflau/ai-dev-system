"""
SOP 配置加载器
从 YAML 文件加载工作流定义，转换为 orchestrator 可用的 transition_rules
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger("sop")

# SOP 目录
SOP_DIR = Path(__file__).parent


def load_sop(name: str = "default_sop") -> Dict[str, Any]:
    """加载 SOP 配置文件，返回完整配置"""
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML 未安装，使用内置解析")
        return _load_sop_fallback(name)

    sop_file = SOP_DIR / f"{name}.yaml"
    if not sop_file.exists():
        logger.warning("SOP 文件不存在: %s, 使用默认配置", sop_file)
        return _default_sop()

    with open(sop_file, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    logger.info("✅ SOP 已加载: %s (v%s, %d 阶段)",
                config.get("name", name), config.get("version", "?"), len(config.get("stages", [])))
    return config


def sop_to_transition_rules(config: Dict[str, Any]) -> Dict[str, Dict]:
    """将 SOP 配置转换为 orchestrator 的 transition_rules 格式"""
    stages = config.get("stages", [])
    rules = {}

    for stage in stages:
        trigger = stage.get("trigger_on")
        if not trigger:
            continue

        rule = {
            "agent": stage["agent"],
            "action": stage["action"],
            "next_status": _get_next_status(stage),
        }

        # 可选字段
        if stage.get("pass_threshold"):
            rule["pass_threshold"] = stage["pass_threshold"]
        if stage.get("optional"):
            rule["optional"] = True
        if stage.get("config"):
            rule["config"] = stage["config"]

        rules[trigger] = rule

    logger.info("📋 转换规则: %d 条状态转换", len(rules))
    return rules


def get_sop_stages(config: Dict[str, Any]) -> List[Dict]:
    """获取所有阶段定义（供前端展示）"""
    stages = config.get("stages", [])
    result = []
    for s in stages:
        result.append({
            "id": s.get("id", ""),
            "name": s.get("name", s.get("id", "")),
            "agent": s.get("agent", ""),
            "action": s.get("action", ""),
            "trigger_on": s.get("trigger_on", ""),
            "success_status": s.get("success_status", ""),
            "reject_status": s.get("reject_status"),
            "reject_goto": s.get("reject_goto"),
            "description": s.get("description", ""),
            "optional": s.get("optional", False),
            "pass_threshold": s.get("pass_threshold"),
            "config": s.get("config", {}),
        })
    return result


def get_sop_metadata(config: Dict[str, Any]) -> Dict:
    """获取 SOP 元信息"""
    return {
        "name": config.get("name", "未命名流程"),
        "version": config.get("version", "1.0"),
        "description": config.get("description", ""),
        "stage_count": len(config.get("stages", [])),
    }


def _get_next_status(stage: Dict) -> Optional[str]:
    """推断阶段执行后的中间状态（in_progress）"""
    agent = stage.get("agent", "")
    action = stage.get("action", "")

    # 常见的 in_progress 状态映射
    status_map = {
        ("ArchitectAgent", "design_architecture"): "architecture_in_progress",
        ("DevAgent", "develop"): "development_in_progress",
        ("DevAgent", "rework"): "development_in_progress",
        ("DevAgent", "fix_issues"): "development_in_progress",
        ("TestAgent", "run_tests"): "testing_in_progress",
    }

    return status_map.get((agent, action))


def _default_sop() -> Dict[str, Any]:
    """内置默认 SOP（不依赖 YAML 文件）"""
    return {
        "name": "默认开发流程",
        "version": "1.0",
        "description": "内置默认流程",
        "stages": [
            {"id": "architecture", "agent": "ArchitectAgent", "action": "design_architecture",
             "trigger_on": "pending", "success_status": "architecture_done"},
            {"id": "development", "agent": "DevAgent", "action": "develop",
             "trigger_on": "architecture_done", "success_status": "development_done"},
            {"id": "acceptance", "agent": "ProductAgent", "action": "acceptance_review",
             "trigger_on": "development_done", "success_status": "acceptance_passed",
             "reject_status": "acceptance_rejected", "reject_goto": "rework"},
            {"id": "testing", "agent": "TestAgent", "action": "run_tests",
             "trigger_on": "acceptance_passed", "success_status": "testing_done",
             "reject_status": "testing_failed", "reject_goto": "fix_issues", "pass_threshold": 60},
            {"id": "rework", "agent": "DevAgent", "action": "rework",
             "trigger_on": "acceptance_rejected", "success_status": "development_done"},
            {"id": "fix_issues", "agent": "DevAgent", "action": "fix_issues",
             "trigger_on": "testing_failed", "success_status": "development_done"},
        ],
    }


def _load_sop_fallback(name: str) -> Dict[str, Any]:
    """不依赖 PyYAML 的简单解析（兜底）"""
    sop_file = SOP_DIR / f"{name}.yaml"
    if not sop_file.exists():
        return _default_sop()

    # 简易 YAML 解析（只处理本项目用到的简单格式）
    import re
    content = sop_file.read_text(encoding="utf-8")

    config = {"stages": []}
    current_stage = None

    for line in content.split("\n"):
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue

        # 顶层字段
        if re.match(r'^(name|version|description):', line):
            key, val = line.split(":", 1)
            val = val.strip().strip('"').strip("'")
            config[key.strip()] = val
            continue

        # 新阶段
        if line_stripped.startswith("- id:"):
            current_stage = {"id": line_stripped.split(":", 1)[1].strip()}
            config["stages"].append(current_stage)
            continue

        # 阶段属性
        if current_stage and ":" in line_stripped:
            key, val = line_stripped.split(":", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val.lower() == "true":
                val = True
            elif val.lower() == "false":
                val = False
            elif val.isdigit():
                val = int(val)
            if key in ("id", "name", "agent", "action", "trigger_on", "success_status",
                       "reject_status", "reject_goto", "description", "optional", "pass_threshold"):
                current_stage[key] = val

    logger.info("✅ SOP 已加载(fallback): %s (%d 阶段)", config.get("name", name), len(config["stages"]))
    return config
