"""安全审计路由。"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, db_session
from app.core.config import settings
from app.models import AuditLog, User, utcnow
from app.schemas import AuditLogOut, AuditPage

router = APIRouter(prefix="/audit", tags=["audit"])


def _to_out(log: AuditLog) -> AuditLogOut:
    try:
        detail = json.loads(log.detail_json or "{}")
    except json.JSONDecodeError:
        detail = {}
    return AuditLogOut(
        id=log.id,
        actor=log.actor,
        action=log.action,
        target_type=log.target_type,
        target_id=log.target_id,
        risk_level=log.risk_level,
        decision=log.decision,
        reason=log.reason,
        detail=detail,
        ip_address=log.ip_address,
        is_simulation=log.is_simulation,
        created_at=log.created_at,
    )


@router.get("", response_model=AuditPage, summary="安全审计日志")
def list_audit(
    db: Session = Depends(db_session),
    risk_level: Optional[str] = Query(default=None, description="green / yellow / red"),
    action: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    user: User = Depends(current_user),
) -> AuditPage:
    from app.security.rate_limiter import check_and_increment

    check_and_increment(
        db, scope="audit_query", identifier=f"user:{user.username}",
        limit=settings.rate_limit_audit_per_minute, window_seconds=60,
    )
    stmt = select(AuditLog)
    count_stmt = select(func.count(AuditLog.id))
    # 数据隔离：只能查看自己的审计记录
    stmt = stmt.where(AuditLog.actor == user.username)
    count_stmt = count_stmt.where(AuditLog.actor == user.username)
    if risk_level:
        stmt = stmt.where(AuditLog.risk_level == risk_level)
        count_stmt = count_stmt.where(AuditLog.risk_level == risk_level)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"%{action}%"))
        count_stmt = count_stmt.where(AuditLog.action.like(f"%{action}%"))

    total = db.execute(count_stmt).scalar() or 0
    offset = (page - 1) * page_size
    rows = db.execute(
        stmt.order_by(desc(AuditLog.created_at)).offset(offset).limit(page_size)
    ).scalars()

    by_level = {
        level: db.execute(
            select(func.count(AuditLog.id)).where(
                AuditLog.risk_level == level, AuditLog.actor == user.username
            )
        ).scalar()
        or 0
        for level in ("green", "yellow", "red")
    }
    by_decision = {
        decision: db.execute(
            select(func.count(AuditLog.id)).where(
                AuditLog.decision == decision, AuditLog.actor == user.username
            )
        ).scalar()
        or 0
        for decision in ("allow", "confirm", "mfa", "block")
    }

    return AuditPage(
        items=[_to_out(r) for r in rows],
        total=int(total),
        page=page,
        page_size=page_size,
        summary={"by_risk_level": by_level, "by_decision": by_decision, "total": int(total)},
    )


@router.get("/integrity", summary="审计完整性验证")
def audit_integrity(
    db: Session = Depends(db_session),
    user: User = Depends(current_user),
) -> dict:
    """验证审计哈希链完整性（只读，不修改数据）。"""
    from app.security.audit_integrity import verify_integrity

    ok, summary, detail = verify_integrity(db)
    return {
        "status": summary,
        "passed": ok,
        "detail": detail,
        "verified_at": utcnow().isoformat(),
    }
