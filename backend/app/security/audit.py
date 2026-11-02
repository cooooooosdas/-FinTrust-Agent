"""安全审计写入。

所有受安全策略管辖的操作（无论放行、要求确认、要求 MFA 还是被拦截）
都必须落一条审计日志，且**只追加不可修改**。
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models import AuditLog, utcnow


def write_audit_log(
    db: Session,
    *,
    action: str,
    decision: str,
    risk_level: str,
    reason: str,
    actor: str = "demo-user",
    target_type: str = "",
    target_id: str = "",
    detail: Optional[Dict[str, Any]] = None,
    ip_address: str = "127.0.0.1",
    is_simulation: bool = True,
) -> AuditLog:
    """写入一条审计日志并立即提交（含完整性哈希链签名）。"""
    log = AuditLog(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        risk_level=risk_level,
        decision=decision,
        reason=reason,
        detail_json=json.dumps(detail or {}, ensure_ascii=False, default=str),
        ip_address=ip_address,
        is_simulation=is_simulation,
        created_at=utcnow(),
    )
    db.add(log)
    # 先提交拿到自增 id（哈希链规范化内容需要 id）
    db.commit()
    db.refresh(log)

    # 再在独立写锁内做哈希链签名（顺序追加）
    _sign_with_lock(db, log)
    return log


def _sign_with_lock(db: Session, log: AuditLog) -> None:
    """在 IMMEDIATE 写锁内为审计事件计算哈希链字段。"""
    from app.core.config import settings
    from app.security.audit_integrity import sign_audit_log

    if settings.database_url.startswith("sqlite"):
        try:
            if db.in_transaction():
                db.rollback()
            conn = db.connection()
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        except Exception:
            pass

    try:
        sign_audit_log(db, log)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(log)


__all__ = ["write_audit_log"]
