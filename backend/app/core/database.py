"""数据库引擎与会话管理。"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


connect_args = {}
if settings.database_url.startswith("sqlite"):
    # check_same_thread=False 允许跨线程复用连接（TestClient/多线程并发）；
    # timeout 设置 SQLite 写锁等待，避免并发写事务在锁竞争时立即抛错。
    connect_args = {"check_same_thread": False, "timeout": 30}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    echo=False,
    future=True,
    # 并发转账测试会开 20 个线程，SQLite 单写者模型下需要足够连接池与重试窗口。
    pool_size=30,
    max_overflow=30,
    pool_timeout=60,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
    """开启 SQLite 外键约束与 WAL 模式，提升并发读写表现。"""
    if not settings.database_url.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求一个数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """根据 ORM 元数据创建全部表（幂等）。"""
    from app import models  # noqa: F401  确保所有模型完成注册

    Base.metadata.create_all(bind=engine)


__all__ = ["Base", "engine", "SessionLocal", "get_db", "init_db"]
