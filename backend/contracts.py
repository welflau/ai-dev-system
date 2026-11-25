"""跨层共享的常量（L0）。

本模块不导入任何项目内模块。L1 的 orchestrator 和 L3 的 action 都从这里取，
彼此不用互相导入。
"""

# 父 Ticket 等待子 Ticket 的中间状态（写入 tickets.status）
WAITING_SUBTASKS_STATUS = "waiting_subtasks"
