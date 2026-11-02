"""幂等控制。

同一 `Idempotency-Key` + endpoint 在有效期内重复提交时，直接返回首次执行的结果，
避免重复扣款。所有写操作（转账、虚拟卡、挂失）都必须携带幂等键。

并发安全：依赖 ``(key, endpoint)`` 的数据库唯一约束兜底。当两个并发请求携带同一键
同时插入时，第二个会命中唯一约束，此时**重查**并返回已有记录，而不是抛出 500。
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.errors import IdempotencyConflictError
from app.models import IdempotencyRecord
from app.models import utcnow

#: 幂等记录有效期（秒）。过期后可被复用 / 清理。
IDEMPOTENCY_TTL_SECONDS = 3600


def build_request_hash(payload: Any) -> str:
    """对请求体生成稳定哈希，用于检测同键不同参的冲突。"""
    try:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    except TypeError:
        raw = str(payload)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class IdempotencyStore:
    """基于 SQLite 的幂等记录存储。"""

    def __init__(self) -> None:
        self._db: Optional[Session] = None

    # ------------------------------------------------------------------
    def begin(self, key: str, endpoint: str, payload: Any) -> Optional[Dict[str, Any]]:
        """开始一次幂等操作。

        返回 ``None`` 表示可以执行；返回 dict 表示命中已有记录（已完成则含
        ``response``；进行中则含 ``in_progress=True``）。
        """
        request_hash = build_request_hash(payload)
        db = self._session()
        try:
            # 先清理过期记录，避免 in_progress 残留永久阻塞
            self._expire_stale(db)

            record = db.execute(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.key == key,
                    IdempotencyRecord.endpoint == endpoint,
                )
            ).scalar_one_or_none()

            if record is not None:
                if record.request_hash != request_hash:
                    raise IdempotencyConflictError(
                        "同一幂等键对应了不同的请求参数，请更换 Idempotency-Key",
                        detail={"idempotency_key": key},
                    )
                if record.status == "done":
                    return json.loads(record.response_json or "{}")
                return {"in_progress": True}

            db.add(
                IdempotencyRecord(
                    key=key,
                    endpoint=endpoint,
                    request_hash=request_hash,
                    status="in_progress",
                    response_json="{}",
                )
            )
            try:
                db.commit()
            except IntegrityError:
                # 并发插入竞态：另一个请求已抢先写入，重查并按其结果处理
                db.rollback()
                record = db.execute(
                    select(IdempotencyRecord).where(
                        IdempotencyRecord.key == key,
                        IdempotencyRecord.endpoint == endpoint,
                    )
                ).scalar_one_or_none()
                if record is None:
                    return None
                if record.request_hash != request_hash:
                    raise IdempotencyConflictError(
                        "同一幂等键对应了不同的请求参数，请更换 Idempotency-Key",
                        detail={"idempotency_key": key},
                    )
                if record.status == "done":
                    return json.loads(record.response_json or "{}")
                return {"in_progress": True}
            return None
        finally:
            db.close()

    # ------------------------------------------------------------------
    def complete(self, key: str, endpoint: str, response: Any) -> None:
        """标记幂等操作完成并保存响应。"""
        db = self._session()
        try:
            record = db.execute(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.key == key,
                    IdempotencyRecord.endpoint == endpoint,
                )
            ).scalar_one_or_none()
            if record is None:
                record = IdempotencyRecord(
                    key=key,
                    endpoint=endpoint,
                    request_hash=build_request_hash(response),
                    status="done",
                )
                db.add(record)
            record.status = "done"
            record.response_json = json.dumps(response, ensure_ascii=False, default=str)
            record.updated_at = utcnow()
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ------------------------------------------------------------------
    def fail(self, key: str, endpoint: str) -> None:
        """操作失败时释放幂等键，允许用户重试。"""
        db = self._session()
        try:
            record = db.execute(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.key == key,
                    IdempotencyRecord.endpoint == endpoint,
                )
            ).scalar_one_or_none()
            if record is not None and record.status == "in_progress":
                db.delete(record)
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    # ------------------------------------------------------------------
    @staticmethod
    def _expire_stale(db: Session) -> None:
        """清理超过 TTL 的幂等记录（含 in_progress 残留）。"""
        cutoff = utcnow().timestamp() - IDEMPOTENCY_TTL_SECONDS
        from datetime import datetime, timezone

        cutoff_dt = datetime.fromtimestamp(cutoff, tz=timezone.utc).replace(tzinfo=None)
        stale = db.execute(
            select(IdempotencyRecord).where(IdempotencyRecord.updated_at < cutoff_dt)
        ).scalars().all()
        for record in stale:
            db.delete(record)
        if stale:
            db.commit()

    # ------------------------------------------------------------------
    @staticmethod
    def _session() -> Session:
        return SessionLocal()


idempotency_store = IdempotencyStore()

__all__ = ["IdempotencyStore", "idempotency_store", "build_request_hash", "IDEMPOTENCY_TTL_SECONDS"]
