"""
ADS 异步权限审批模块（Phase 3）

高风险操作（rm -rf、force-push 等）在执行前挂起协程，
等待用户通过前端审批，超时自动拒绝（fail-closed）。
"""
from permissions.gate import PermissionGate, permission_gate, PermissionDeniedError

__all__ = ["permission_gate", "PermissionGate", "PermissionDeniedError"]
