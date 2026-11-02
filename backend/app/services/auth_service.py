"""身份认证与账户归属服务（P1-T2）。"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import PermissionDeniedError, UnauthorizedError, ValidationError
from app.models import Session, User, UserAccount, utcnow
from app.security.password import hash_password, token_hash, verify_password


def _session_secret() -> str:
    return settings.auth_session_secret or "fintrust-dev-session-secret"


def authenticate(db: Session, username: str, password: str) -> Optional[User]:
    """校验用户名密码，返回用户（失败返回 None）。"""
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        return None
    if user.status != "active":
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def create_session(db: Session, user: User) -> Tuple[str, Session]:
    """创建会话，返回 (明文 token, Session 记录)。服务端仅存 token 哈希。"""
    raw_token = secrets.token_urlsafe(48)
    record = Session(
        user_id=user.id,
        token_hash=token_hash(raw_token, _session_secret()),
        created_at=utcnow(),
        expires_at=utcnow() + timedelta(minutes=settings.session_ttl_minutes),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return raw_token, record


def resolve_session(db: Session, raw_token: str) -> Optional[Session]:
    """根据明文 token 解析有效会话（未过期、未撤销）。"""
    if not raw_token:
        return None
    th = token_hash(raw_token, _session_secret())
    record = db.execute(select(Session).where(Session.token_hash == th)).scalar_one_or_none()
    if record is None:
        return None
    if record.revoked_at is not None:
        return None
    if record.expires_at is not None and utcnow() >= record.expires_at:
        return None
    return record


def revoke_session(db: Session, raw_token: str) -> None:
    """注销会话。"""
    th = token_hash(raw_token, _session_secret())
    record = db.execute(select(Session).where(Session.token_hash == th)).scalar_one_or_none()
    if record is not None and record.revoked_at is None:
        record.revoked_at = utcnow()
        db.commit()


def revoke_all_sessions(db: Session, user_id: int) -> None:
    """撤销某用户的所有会话（密码修改后使用）。"""
    records = db.execute(
        select(Session).where(Session.user_id == user_id, Session.revoked_at.is_(None))
    ).scalars().all()
    now = utcnow()
    for r in records:
        r.revoked_at = now
    db.commit()


def account_ids_for_user(db: Session, user_id: int) -> List[int]:
    """返回该用户被授权的 account_id 集合。"""
    rows = db.execute(
        select(UserAccount.account_id).where(UserAccount.user_id == user_id)
    ).scalars().all()
    return list(rows)


def ensure_account_access(db: Session, user: User, account_id: int) -> None:
    """校验用户是否有权访问指定账户，否则抛 PermissionDeniedError。"""
    allowed = account_ids_for_user(db, user.id)
    if account_id not in allowed:
        raise PermissionDeniedError(
            f"无权访问账户 {account_id}",
            detail={"account_id": account_id},
        )


def create_demo_user(
    db: Session,
    username: str,
    password: str,
    account_id: int,
) -> User:
    """创建演示用户并绑定账户（幂等：已存在则跳过）。"""
    existing = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if existing is not None:
        return existing
    user = User(
        username=username,
        password_hash=hash_password(password),
        status="active",
    )
    db.add(user)
    db.flush()
    db.add(UserAccount(user_id=user.id, account_id=account_id, permission="owner"))
    db.commit()
    db.refresh(user)
    return user


__all__ = [
    "authenticate",
    "create_session",
    "resolve_session",
    "revoke_session",
    "revoke_all_sessions",
    "account_ids_for_user",
    "ensure_account_access",
    "create_demo_user",
]
