"""持久化多因子身份验证 (MFA)。

验证码使用 ``secrets`` 生成，**仅以 HMAC 摘要形式落库**（不存明文）。
挑战绑定 用户 / 账户 / 操作类型 / 目标对象，避免跨交易复用。
服务器重启后仍能验证尚未过期的挑战。

本地演示模式可向前端返回验证码明文（明确标注为模拟 MFA）；正式模式不返回明文。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import MfaChallenge, utcnow


@dataclass
class ChallengeView:
    """对外可见的挑战信息（可含演示验证码）。"""

    challenge_id: str
    operation: str
    code: Optional[str]  # 仅演示模式返回明文
    expires_in: int
    attempts_remaining: int


def _secret() -> str:
    return settings.mfa_secret_key or "fintrust-dev-mfa-secret"


def _code_hash(code: str) -> str:
    return hmac.new(_secret().encode("utf-8"), code.encode("utf-8"), hashlib.sha256).hexdigest()


class MfaService:
    """基于数据库的持久化 MFA 服务。"""

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    def issue(
        self,
        db: Session,
        operation: str,
        *,
        user_id: Optional[int] = None,
        account_id: Optional[int] = None,
        target_id: str = "",
        challenge_id: Optional[str] = None,
    ) -> ChallengeView:
        """生成并持久化一个 MFA 挑战。返回视图（含演示验证码）。"""
        from app.security.rate_limiter import check_and_increment

        # MFA 挑战创建限流（3次/10分钟，按用户+操作）
        identifier = f"user:{user_id or 'anon'}:{operation}"
        check_and_increment(
            db, scope="mfa_create", identifier=identifier,
            limit=settings.rate_limit_mfa_create_per_10min, window_seconds=600,
        )

        cid = challenge_id or f"mfa_{secrets.token_hex(8)}"
        code = f"{secrets.randbelow(1_000_000):06d}"
        record = MfaChallenge(
            challenge_id=cid,
            user_id=user_id,
            account_id=account_id,
            operation=operation,
            target_id=target_id,
            code_hash=_code_hash(code),
            created_at=utcnow(),
            expires_at=utcnow() + timedelta(seconds=settings.mfa_ttl_seconds),
            attempts_remaining=settings.mfa_max_attempts,
            status="pending",
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        # 演示模式返回明文验证码
        demo_code = code if settings.is_demo_mode else None
        return ChallengeView(
            challenge_id=cid,
            operation=operation,
            code=demo_code,
            expires_in=settings.mfa_ttl_seconds,
            attempts_remaining=settings.mfa_max_attempts,
        )

    # ------------------------------------------------------------------
    def get(self, db: Session, challenge_id: str) -> Optional[MfaChallenge]:
        return db.execute(
            select(MfaChallenge).where(MfaChallenge.challenge_id == challenge_id)
        ).scalar_one_or_none()

    # ------------------------------------------------------------------
    def verify(
        self,
        db: Session,
        challenge_id: str,
        code: str,
        *,
        expected_user_id: Optional[int] = None,
        expected_account_id: Optional[int] = None,
        expected_operation: Optional[str] = None,
        expected_target_id: Optional[str] = None,
    ) -> tuple[bool, str]:
        """校验验证码，返回 (是否通过, 原因)。

        校验：存在性、是否消费、是否过期、次数、绑定（用户/账户/操作/目标）、验证码摘要。
        验证成功后立即消费（一次性）。
        """
        record = self.get(db, challenge_id)
        if record is None:
            return False, "验证码不存在或已失效"
        if record.status == "consumed":
            return False, "该验证码已被使用"
        if record.status == "locked":
            return False, "验证码已锁定，请重新获取"
        if utcnow() >= record.expires_at:
            record.status = "expired"
            db.commit()
            return False, "验证码已过期，请重新获取"
        if record.attempts_remaining <= 0:
            record.status = "locked"
            db.commit()
            return False, "尝试次数过多，请重新获取验证码"

        # 绑定校验
        if expected_user_id is not None and record.user_id != expected_user_id:
            return False, "验证码与用户不匹配"
        if expected_account_id is not None and record.account_id != expected_account_id:
            return False, "验证码与账户不匹配"
        if expected_operation is not None and record.operation != expected_operation:
            return False, "验证码与操作类型不匹配"
        if expected_target_id is not None and record.target_id != expected_target_id:
            return False, "验证码与目标对象不匹配"

        # 验证码摘要比较（恒定时间）
        provided_hash = _code_hash(str(code).strip())
        if not hmac.compare_digest(provided_hash, record.code_hash):
            record.attempts_remaining -= 1
            if record.attempts_remaining <= 0:
                record.status = "locked"
            db.commit()
            left = max(0, record.attempts_remaining)
            return False, f"验证码错误，还可尝试 {left} 次"

        record.status = "consumed"
        record.consumed_at = utcnow()
        db.commit()
        return True, "验证通过"


mfa_service = MfaService()

__all__ = ["MfaService", "ChallengeView", "mfa_service"]
