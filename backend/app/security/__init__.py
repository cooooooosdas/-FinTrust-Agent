"""安全与权限模块。

设计原则：**权限判定完全由后端策略引擎完成，大模型只负责理解意图与抽取参数，
永远不能决定自身可执行的操作范围。**
"""

from app.security.audit import write_audit_log
from app.security.circuit_breaker import CircuitBreaker, circuit_breaker
from app.security.idempotency import IdempotencyStore, idempotency_store
from app.security.mfa import MfaService, mfa_service
from app.security.policy import (
    GREEN,
    RED,
    YELLOW,
    PolicyDecision,
    PolicyEngine,
    RiskLevel,
    policy_engine,
)

__all__ = [
    "write_audit_log",
    "CircuitBreaker",
    "circuit_breaker",
    "IdempotencyStore",
    "idempotency_store",
    "MfaService",
    "mfa_service",
    "GREEN",
    "YELLOW",
    "RED",
    "PolicyDecision",
    "PolicyEngine",
    "RiskLevel",
    "policy_engine",
]
