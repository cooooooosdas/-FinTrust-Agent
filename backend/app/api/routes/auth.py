"""认证路由：登录 / 登出 / 当前用户。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import current_user, db_session, get_raw_token
from app.core.errors import UnauthorizedError
from app.models import User
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


@router.post("/login", summary="登录")
def login(payload: LoginRequest, request: Request, db: Session = Depends(db_session)) -> LoginResponse:
    from app.api.deps import client_ip
    from app.core.config import settings
    from app.security.rate_limiter import check_and_increment

    # 单 IP 登录限流
    check_and_increment(
        db, scope="login", identifier=f"ip:{client_ip(request)}",
        limit=settings.rate_limit_login_per_minute, window_seconds=60,
    )

    user = auth_service.authenticate(db, payload.username, payload.password)
    if user is None:
        # 用户名 + IP 失败限流（防针对单用户名的拒绝服务）
        try:
            check_and_increment(
                db, scope="login_fail", identifier=f"{payload.username}:{client_ip(request)}",
                limit=settings.rate_limit_login_fail_max, window_seconds=settings.rate_limit_login_fail_window * 60,
            )
        except Exception:
            pass
        raise UnauthorizedError("用户名或密码错误")
    raw_token, _session = auth_service.create_session(db, user)
    allowed = auth_service.account_ids_for_user(db, user.id)
    return LoginResponse(
        access_token=raw_token,
        token_type="bearer",
        expires_in=settings.session_ttl_minutes * 60,
        user={"id": user.id, "username": user.username, "account_ids": allowed},
    )


@router.post("/logout", summary="登出")
def logout(
    db: Session = Depends(db_session),
    raw_token: str | None = Depends(get_raw_token),
) -> dict:
    if raw_token:
        auth_service.revoke_session(db, raw_token)
    return {"status": "ok"}


@router.get("/me", summary="当前用户")
def me(user: User = Depends(current_user), db: Session = Depends(db_session)) -> dict:
    allowed = auth_service.account_ids_for_user(db, user.id)
    return {
        "id": user.id,
        "username": user.username,
        "status": user.status,
        "account_ids": allowed,
    }


__all__ = ["router"]
