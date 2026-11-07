"""API 依赖：数据库会话、认证主体与账户归属校验、请求限流。"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, Query, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import UnauthorizedError
from app.models import User
from app.services import auth_service


def db_session(db: Session = Depends(get_db)) -> Session:
    return db


def get_account_id(
    account_id: Optional[int] = Query(default=None, description="账户 ID，缺省使用演示默认账户"),
) -> int:
    return account_id or 1


def get_idempotency_key(
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    body_key: Optional[str] = Query(default=None, alias="idempotency_key"),
) -> Optional[str]:
    """幂等键优先取请求头，其次取查询参数。"""
    return idempotency_key or body_key


def get_raw_token(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> Optional[str]:
    """从 Authorization: Bearer <token> 提取原始 token。"""
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def current_user(
    db: Session = Depends(db_session),
    raw_token: Optional[str] = Depends(get_raw_token),
) -> User:
    """解析当前认证用户，未认证抛 401。所有受保护接口必须依赖此函数。"""
    if not raw_token:
        raise UnauthorizedError("缺少认证凭证")
    session = auth_service.resolve_session(db, raw_token)
    if session is None:
        raise UnauthorizedError("会话已失效，请重新登录")
    user = db.get(User, session.user_id)
    if user is None or user.status != "active":
        raise UnauthorizedError("用户不存在或已禁用")
    return user


def current_user_optional(
    db: Session = Depends(db_session),
    raw_token: Optional[str] = Depends(get_raw_token),
) -> Optional[User]:
    """可选认证（不强制），用于健康检查等无需强制认证的场景。"""
    if not raw_token:
        return None
    session = auth_service.resolve_session(db, raw_token)
    if session is None:
        return None
    return db.get(User, session.user_id)


def require_account(
    account_id: int,
):
    """返回一个依赖，校验当前用户对 account_id 的归属（不属于则 403）。"""

    def _dep(user: User = Depends(current_user), db: Session = Depends(db_session)) -> User:
        auth_service.ensure_account_access(db, user, account_id)
        return user

    return _dep


def current_actor(user: User = Depends(current_user)) -> str:
    """返回当前认证主体标识（用于审计日志 actor 字段）。"""
    return user.username


# ----------------------------------------------------------------------
# 请求限流
# ----------------------------------------------------------------------
# 说明：下面 rate_limit / rate_limit_by_ip 两个依赖工厂目前**未被任何路由接入**。
# 现行限流由各路由直接调用 app.security.rate_limiter.check_and_increment，
# 以便按各自 scope / identifier / window 精确控制。这两个工厂保留为后续统一
# 接入的扩展点，勿误以为它们已在请求链路上生效。
def client_ip(request: Request) -> str:
    """获取真实客户端 IP。默认不信任 X-Forwarded-For（仅本地直连）。"""
    # Settings 当前未定义 trusted_proxy 字段，getattr 恒返回 ""，
    # 即 X-Forwarded-For 分支不可达；保留占位以便后续显式配置后启用。
    trusted_proxy = getattr(settings, "trusted_proxy", "")
    if trusted_proxy:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(
    scope: str,
    limit: int,
    window_seconds: int,
):
    """返回一个限流依赖工厂：基于 identifier 维度限流。"""

    def _dep(
        request: Request,
        db: Session = Depends(db_session),
        user: User = Depends(current_user),
    ) -> None:
        from app.security.rate_limiter import check_and_increment

        # 维度：优先用户身份，其次 IP
        identifier = f"user:{user.username}"
        check_and_increment(db, scope=scope, identifier=identifier, limit=limit, window_seconds=window_seconds)

    return _dep


def rate_limit_by_ip(
    scope: str,
    limit: int,
    window_seconds: int,
):
    """登录等匿名接口的 IP 维度限流依赖。"""

    def _dep(
        request: Request,
        db: Session = Depends(db_session),
    ) -> None:
        from app.security.rate_limiter import check_and_increment

        ip = client_ip(request)
        check_and_increment(db, scope=scope, identifier=f"ip:{ip}", limit=limit, window_seconds=window_seconds)

    return _dep


__all__ = [
    "db_session",
    "get_account_id",
    "get_idempotency_key",
    "get_raw_token",
    "current_user",
    "current_user_optional",
    "require_account",
    "current_actor",
    "client_ip",
    "rate_limit",
    "rate_limit_by_ip",
]
