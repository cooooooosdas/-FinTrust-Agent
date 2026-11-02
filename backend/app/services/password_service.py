"""密码修改服务（P1-T3）。

流程：申请 → 策略引擎判定 PASSWORD_CHANGE 为红色 → 生成持久化 MFA 挑战 →
校验旧密码 + MFA + 新密码策略 → 更新哈希 → 撤销旧会话。
"""

from __future__ import annotations

from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import PermissionDeniedError, ValidationError
from app.models import User, utcnow
from app.security.audit import write_audit_log
from app.security.mfa import mfa_service
from app.security.password import hash_password, verify_password
from app.security.policy import ActionType, policy_engine
from app.services import auth_service

MIN_PASSWORD_LENGTH = 8


def _password_strength_ok(password: str) -> bool:
    if len(password) < MIN_PASSWORD_LENGTH:
        return False
    has_alpha = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    return has_alpha and has_digit


def request_password_change(db: Session, user: User) -> Dict:
    """申请修改密码：策略引擎判定 + 生成持久化 MFA 挑战。"""
    decision = policy_engine.evaluate(ActionType.PASSWORD_CHANGE)
    if decision.requires_mfa:
        view = mfa_service.issue(
            db,
            operation="password_change",
            user_id=user.id,
            account_id=None,
            target_id=str(user.id),
        )
        write_audit_log(
            db,
            action="password.change_mfa_required",
            decision="mfa",
            risk_level=decision.level.value,
            reason=decision.reason,
            actor=user.username,
            target_type="user",
            target_id=str(user.id),
            detail={"challenge_id": view.challenge_id},
        )
        return {
            "status": "awaiting_mfa",
            "risk_level": decision.level.value,
            "challenge_id": view.challenge_id,
            "demo_code": view.code,  # 仅演示模式有明文
            "expires_in": settings.mfa_ttl_seconds,
        }
    raise ValidationError("密码修改必须经过多因子验证")


def change_password(
    db: Session,
    user: User,
    *,
    old_password: str,
    new_password: str,
    mfa_code: str,
    mfa_challenge_id: str,
) -> Dict:
    """校验旧密码 + MFA + 新密码策略后更新密码哈希，并撤销旧会话。"""
    # 1. 校验旧密码
    if not verify_password(old_password, user.password_hash):
        raise ValidationError("旧密码错误", code="OLD_PASSWORD_INVALID")

    # 2. 新密码不能与旧密码相同
    if new_password == old_password:
        raise ValidationError("新密码不能与旧密码相同", code="PASSWORD_SAME")

    # 3. 密码强度
    if not _password_strength_ok(new_password):
        raise ValidationError(
            f"新密码强度不足：至少 {MIN_PASSWORD_LENGTH} 位，且需包含字母和数字",
            code="PASSWORD_WEAK",
        )

    # 4. MFA 校验（绑定用户与操作）
    ok, message = mfa_service.verify(
        db,
        mfa_challenge_id,
        mfa_code,
        expected_user_id=user.id,
        expected_operation="password_change",
        expected_target_id=str(user.id),
    )
    if not ok:
        write_audit_log(
            db,
            action="password.change_mfa_failed",
            decision="block",
            risk_level="red",
            reason=message,
            actor=user.username,
            target_type="user",
            target_id=str(user.id),
        )
        raise ValidationError(message, code="MFA_INVALID")

    # 5. 更新密码哈希（任何失败之前都不得提前改密码）
    user.password_hash = hash_password(new_password)
    user.updated_at = utcnow()
    db.commit()

    # 6. 撤销旧会话
    auth_service.revoke_all_sessions(db, user.id)

    # 7. 审计
    write_audit_log(
        db,
        action="password.changed",
        decision="allow",
        risk_level="red",
        reason="密码修改成功，旧会话已撤销",
        actor=user.username,
        target_type="user",
        target_id=str(user.id),
    )

    return {"status": "changed", "message": "密码修改成功，请重新登录"}


__all__ = ["request_password_change", "change_password", "MIN_PASSWORD_LENGTH"]
