"""统一请求限流模块（P2-T1）。

基于 SQLite 的窗口计数器 + 原子条件更新（``INSERT ... ON CONFLICT`` / 条件 UPDATE）。
不依赖 Redis / Celery 等外部基础设施。

限流键通过 HMAC 脱敏后落库，避免长期保存原始 IP / 用户名。

设计限制（如实声明）：
- SQLite 单写者模型下，计数更新依赖 ``BEGIN IMMEDIATE`` 串行化，适合竞赛演示的单实例部署。
- 多进程 / 多实例部署时，进程内缓存与数据库计数可能出现短暂不一致，需换共享存储。
"""

from __future__ import annotations

import time
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.models import RateLimitRecord, utcnow
from app.security.crypto import hmac_sha256_hex


class RateLimitedError(AppError):
    status_code = 429
    code = "RATE_LIMITED"
    message = "请求过于频繁，请稍后再试"


def _secret() -> str:
    return settings.auth_session_secret or "fintrust-dev-rate-limit-secret"


def _hmac_key(raw: str) -> str:
    """对限流键做 HMAC 脱敏，避免持久化原始 IP / 用户名。"""
    return hmac_sha256_hex(_secret(), raw)


def _window_start(seconds: int) -> int:
    """固定窗口起点（Unix 秒，向下取整到窗口大小）。"""
    now = int(time.time())
    return (now // seconds) * seconds


def check_and_increment(
    db: Session,
    *,
    scope: str,
    identifier: str,
    limit: int,
    window_seconds: int,
) -> tuple[bool, int]:
    """执行限流检查并原子递增。

    返回 ``(是否放行, 剩余可重试秒数)``。
    超限抛 :class:`RateLimitedError`。
    """
    if not settings.rate_limiter_enabled:
        return True, 0

    key = _hmac_key(f"{scope}:{identifier}")
    window = _window_start(window_seconds)

    # 原子递增：优先 UPDATE，无记录则 INSERT（捕获并发竞态）
    result = db.execute(
        update(RateLimitRecord)
        .where(RateLimitRecord.key == key, RateLimitRecord.window_start == window)
        .values(count=RateLimitRecord.count + 1)
    )
    if result.rowcount == 0:
        try:
            db.add(RateLimitRecord(key=key, window_start=window, count=1))
            db.commit()
        except IntegrityError:
            db.rollback()
            db.execute(
                update(RateLimitRecord)
                .where(RateLimitRecord.key == key, RateLimitRecord.window_start == window)
                .values(count=RateLimitRecord.count + 1)
            )
            db.commit()
    else:
        db.commit()

    # 读取当前计数
    record = db.execute(
        select(RateLimitRecord).where(
            RateLimitRecord.key == key, RateLimitRecord.window_start == window
        )
    ).scalar_one_or_none()
    count = record.count if record else 0

    if count > limit:
        retry_after = window_seconds - (int(time.time()) % window_seconds)
        raise RateLimitedError(
            detail={"retry_after": retry_after},
            status_code=429,
        )

    return True, 0


def get_retry_after(window_seconds: int) -> int:
    return window_seconds - (int(time.time()) % window_seconds)


__all__ = [
    "RateLimitedError",
    "check_and_increment",
    "get_retry_after",
    "_hmac_key",
    "_window_start",
]
