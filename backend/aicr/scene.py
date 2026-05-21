"""AICR 场景定义"""
from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field


class AICRScene(str, Enum):
    AUTOAICR = "autoaicr"
    PRECOMMIT = "precommit"


@dataclass
class AICRIssue:
    rule: str          # 规则名（keep-scope / null-deref 等）
    message: str       # 问题描述
    severity: str = "warning"   # warning / error


@dataclass
class AICRResult:
    scene: AICRScene
    issues: list[AICRIssue] = field(default_factory=list)
    suggestions: list[AICRIssue] = field(default_factory=list)  # severity=suggestion
    passed: bool = True
    raw_response: str = ""

    @property
    def has_issues(self) -> bool:
        return bool(self.issues)

    def to_markdown(self) -> str:
        if not self.issues and not self.suggestions:
            return ""
        lines = []
        if self.issues:
            lines.append(f"AutoAICR 发现 {len(self.issues)} 项提示：" if self.scene == AICRScene.AUTOAICR
                         else f"PreCommit 扫描：{len(self.issues)} 项需处理")
            for issue in self.issues:
                lines.append(f"- [{issue.rule}] {issue.message}")
        if self.suggestions:
            lines.append(f"建议（不阻断）：{len(self.suggestions)} 项")
            for s in self.suggestions:
                lines.append(f"- [{s.rule}] {s.message}")
        return "\n".join(lines)
