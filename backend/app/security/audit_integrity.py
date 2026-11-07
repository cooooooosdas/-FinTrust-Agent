"""审计完整性哈希链（P2-T3）。

审计事件按追加顺序形成哈希链：
    event_hash = HMAC-SHA256(密钥, previous_hash + 规范化内容)

密钥通过 ``AUDIT_HMAC_KEY`` 环境变量管理，绝不写入数据库或 Git。

信任边界（如实声明）：哈希链 + HMAC 可检测记录篡改 / 删除 / 重排，但**不能**
声称在数据库管理员同时掌握密钥时仍绝对不可篡改。
"""

from __future__ import annotations

import hmac
import json
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AuditLog, utcnow
from app.security.crypto import hmac_sha256_hex

#: 完整性密钥（环境变量 AUDIT_HMAC_KEY，缺省用 auth_session_secret 兜底）
def _hmac_key() -> str:
    return settings.audit_hmac_key or settings.auth_session_secret or "fintrust-dev-audit-hmac-key"


def _canonical(log: AuditLog) -> str:
    """规范化序列化（字段顺序固定，保证同一事件哈希确定）。"""
    obj = {
        "id": log.id,
        "actor": log.actor,
        "action": log.action,
        "target_type": log.target_type,
        "target_id": log.target_id,
        "risk_level": log.risk_level,
        "decision": log.decision,
        "reason": log.reason,
        "detail_json": log.detail_json,
        "ip_address": log.ip_address,
        "is_simulation": log.is_simulation,
        "created_at": log.created_at.isoformat() if log.created_at else "",
    }
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_event_hash(previous_hash: str, canonical_content: str) -> str:
    return hmac_sha256_hex(_hmac_key(), previous_hash + canonical_content)


def sign_audit_log(db: Session, log: AuditLog) -> None:
    """为新审计事件计算哈希链字段（previous_hash + event_hash + sequence_id）。

    必须在同一事务内顺序执行（调用方保证）。
    """
    key = _hmac_key()
    # 上一个已签名事件
    prev = db.execute(
        select(AuditLog).where(AuditLog.sequence_id.isnot(None)).order_by(AuditLog.sequence_id.desc()).limit(1)
    ).scalar_one_or_none()

    previous_hash = prev.event_hash if prev else ""
    next_seq = (prev.sequence_id + 1) if prev else 1

    canonical = _canonical(log)
    event_hash = hmac_sha256_hex(key, previous_hash + canonical)

    log.sequence_id = next_seq
    log.previous_hash = previous_hash
    log.event_hash = event_hash
    log.integrity_version = 1


def verify_integrity(db: Session) -> Tuple[bool, str, dict]:
    """验证审计哈希链完整性。

    返回 (是否通过, 摘要, 详情)。
    """
    key = _hmac_key()
    logs = db.execute(
        select(AuditLog).where(AuditLog.sequence_id.isnot(None)).order_by(AuditLog.sequence_id)
    ).scalars().all()

    total = len(logs)
    checked = 0
    first_error = None
    previous_hash = ""

    for i, log in enumerate(logs):
        # 校验 sequence_id 连续性
        if log.sequence_id != i + 1:
            first_error = first_error or {
                "sequence_id": log.sequence_id,
                "audit_id": log.id,
                "reason": f"sequence_id 不连续（期望 {i + 1}，实际 {log.sequence_id}）",
            }
            return False, "AUDIT INTEGRITY: FAILED", first_error

        canonical = _canonical(log)
        expected = hmac_sha256_hex(key, previous_hash + canonical)
        if not hmac.compare_digest(expected, log.event_hash):
            first_error = first_error or {
                "sequence_id": log.sequence_id,
                "audit_id": log.id,
                "reason": "event_hash 校验失败（记录被修改或密钥不一致）",
            }
            return False, "AUDIT INTEGRITY: FAILED", first_error

        if log.previous_hash != previous_hash:
            first_error = first_error or {
                "sequence_id": log.sequence_id,
                "audit_id": log.id,
                "reason": "previous_hash 不匹配（记录被删除或重排）",
            }
            return False, "AUDIT INTEGRITY: FAILED", first_error

        previous_hash = log.event_hash
        checked += 1

    return True, "AUDIT INTEGRITY: PASS", {"total": total, "checked": checked}


__all__ = [
    "compute_event_hash",
    "sign_audit_log",
    "verify_integrity",
    "_canonical",
    "_hmac_key",
]
