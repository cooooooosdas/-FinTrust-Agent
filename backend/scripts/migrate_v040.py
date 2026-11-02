"""V0.4.0 数据库迁移脚本（幂等，不重置数据）。

为 audit_logs 增加完整性哈希链列，并创建防篡改触发器；
新建 rate_limit_records 表。
不删除任何旧表、不清空数据、不重置余额与流水。

用法：
    cd backend
    python scripts/migrate_v040.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import engine, init_db  # noqa: E402

#: 需要为 audit_logs 新增的列（列名 -> SQL 定义）
NEW_COLUMNS = [
    ("sequence_id", "INTEGER"),
    ("previous_hash", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("event_hash", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("integrity_version", "INTEGER NOT NULL DEFAULT 1"),
]

#: 防篡改触发器：阻止直接 UPDATE/DELETE 已签名审计记录（逐条执行）
TRIGGER_STATEMENTS = [
    """
    CREATE TRIGGER IF NOT EXISTS trg_audit_no_update
    BEFORE UPDATE ON audit_logs
    FOR EACH ROW
    WHEN OLD.sequence_id IS NOT NULL
    BEGIN
        SELECT RAISE(ABORT, 'audit_logs are append-only and cannot be updated');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_audit_no_delete
    BEFORE DELETE ON audit_logs
    FOR EACH ROW
    WHEN OLD.sequence_id IS NOT NULL
    BEGIN
        SELECT RAISE(ABORT, 'audit_logs are append-only and cannot be deleted');
    END
    """,
]


def _existing_columns(conn) -> set[str]:
    rows = conn.exec_driver_sql("PRAGMA table_info(audit_logs)").fetchall()
    return {row[1] for row in rows}


def migrate() -> None:
    # 1) 新建所有缺失的表（rate_limit_records 等，幂等）
    init_db()

    conn = engine.connect()
    try:
        existing = _existing_columns(conn)
        added = []
        for col_name, col_def in NEW_COLUMNS:
            if col_name not in existing:
                conn.exec_driver_sql(f"ALTER TABLE audit_logs ADD COLUMN {col_name} {col_def}")
                added.append(col_name)
        conn.commit()
        print(f"  新增列：{added if added else '（无需新增，列已存在）'}")

        # 2) 创建防篡改触发器（逐条执行）
        for stmt in TRIGGER_STATEMENTS:
            conn.exec_driver_sql(stmt)
        conn.commit()
        print("  防篡改触发器已就绪（audit_logs 只追加）")
    finally:
        conn.close()

    print("✅ V0.4.0 数据库迁移完成")


if __name__ == "__main__":
    migrate()
