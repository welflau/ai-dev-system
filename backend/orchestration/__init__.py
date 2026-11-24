"""从 orchestrator.py 拆出的协作者（L1）。

`orchestrator.py` 保留 `TicketOrchestrator` 外壳和单例，具体逻辑逐步搬到这个包里。
方案：docs/20261124_01_代码重构方案.md（R2）。

这个包里的模块不导入 `orchestrator`，依赖只能是单向的 orchestrator → orchestration。
"""
