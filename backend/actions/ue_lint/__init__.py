"""UE 项目 DevAgent 自测 Layer 1：静态预检规则集（v0.19.x）

详见 `docs/20260426_01_DevAgent_UE项目自测方案.md`。

主入口 `run_all_rules(files_written, repo_path, context)` 按顺序跑 R1-R7
7 条规则，收集 `List[Issue]` 返回。blocking=True 的 issue 会让 SelfTestAction
返回 fail，DevAgent 不再推进到 engine_compile stage，直接走 fix_issues 循环。
"""

from actions.ue_lint.rules import run_all_rules, Issue

__all__ = ["run_all_rules", "Issue"]
