"""交易状态机引擎（P1-T1）。

统一七状态与合法迁移规则，禁止在路由中随意修改 status。
所有状态迁移通过 :func:`transition` 执行，并**只追加**写入状态迁移审计记录。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, FrozenSet, Set

from sqlalchemy.orm import Session

from app.models import OrderStatusTransition, TransferOrder, utcnow

# 七状态
PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
PENDING_MFA = "PENDING_MFA"
EXECUTING = "EXECUTING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"
EXPIRED = "EXPIRED"

# 终态：不可再迁移
TERMINAL_STATES: FrozenSet[str] = frozenset({SUCCEEDED, FAILED, CANCELLED, EXPIRED})

# 合法迁移表
_ALLOWED: Dict[str, Set[str]] = {
    PENDING_CONFIRMATION: {EXECUTING, PENDING_MFA, CANCELLED, EXPIRED},
    PENDING_MFA: {EXECUTING, FAILED, CANCELLED, EXPIRED},
    EXECUTING: {SUCCEEDED, FAILED},
    # 终态无出边
    SUCCEEDED: set(),
    FAILED: set(),
    CANCELLED: set(),
    EXPIRED: set(),
}


class InvalidTransitionError(Exception):
    """非法状态迁移。"""

    def __init__(self, from_status: str, to_status: str) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"非法状态迁移：{from_status} → {to_status}")


@dataclass
class TransitionResult:
    from_status: str
    to_status: str
    order: TransferOrder


def allowed(from_status: str, to_status: str) -> bool:
    return to_status in _ALLOWED.get(from_status, set())


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATES


def transition(
    db: Session,
    order: TransferOrder,
    to_status: str,
    *,
    actor: str = "system",
    reason: str = "",
    trace_id: str = "",
    commit: bool = True,
) -> TransitionResult:
    """执行一次状态迁移，写入只追加审计记录，并更新对应时间戳。

    非法迁移抛 :class:`InvalidTransitionError`，且不产生任何副作用。
    相同状态迁移（from == to）视为幂等操作，直接返回，不写审计、不抛错。
    """
    from_status = order.status
    if from_status == to_status:
        return TransitionResult(from_status=from_status, to_status=to_status, order=order)
    if not allowed(from_status, to_status):
        raise InvalidTransitionError(from_status, to_status)

    _stamp_timestamp(order, to_status)
    order.status = to_status
    order.version = (order.version or 0) + 1

    transition_record = OrderStatusTransition(
        order_no=order.order_no,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        reason=reason,
        trace_id=trace_id,
        created_at=utcnow(),
    )
    db.add(transition_record)
    if commit:
        db.commit()
    return TransitionResult(from_status=from_status, to_status=to_status, order=order)


def _stamp_timestamp(order: TransferOrder, to_status: str) -> None:
    now = utcnow()
    if to_status == EXECUTING:
        order.executing_at = now
    elif to_status == SUCCEEDED:
        order.executed_at = now
    elif to_status == FAILED:
        order.failed_at = now
    elif to_status == CANCELLED:
        order.cancelled_at = now
    elif to_status == EXPIRED:
        order.expired_at = now


# ----------------------------------------------------------------------
# 旧状态映射（用于数据库迁移，把 V0.1.0/P0 的旧状态安全迁移到新状态）
# ----------------------------------------------------------------------
LEGACY_STATUS_MAP: Dict[str, str] = {
    "ready": PENDING_CONFIRMATION,
    "awaiting_confirm": PENDING_CONFIRMATION,
    "awaiting_mfa": PENDING_MFA,
    "executed": SUCCEEDED,
    "rejected": FAILED,
    "pending": PENDING_CONFIRMATION,
}


def normalize_legacy_status(status: str) -> str:
    return LEGACY_STATUS_MAP.get(status, status)


__all__ = [
    "PENDING_CONFIRMATION",
    "PENDING_MFA",
    "EXECUTING",
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
    "EXPIRED",
    "TERMINAL_STATES",
    "allowed",
    "is_terminal",
    "transition",
    "InvalidTransitionError",
    "TransitionResult",
    "LEGACY_STATUS_MAP",
    "normalize_legacy_status",
]
