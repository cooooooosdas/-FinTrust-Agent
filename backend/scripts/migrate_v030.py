"""V0.3.0 数据库迁移脚本（幂等，不重置数据）。

为 transfer_orders 增加七状态机所需的新列，并把旧状态安全迁移到新状态；
新建 users / user_accounts / sessions / mfa_challenges / order_status_transitions 表。
不删除任何旧表、不清空任何数据、不重置余额与流水。

用法：
    cd backend
    python scripts/migrate_v030.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import inspect, text  # noqa: E402

from app.core.database import Base, SessionLocal, engine, init_db  # noqa: E402
from app.models import TransferOrder, utcnow  # noqa: E402
from app.security.order_state import normalize_legacy_status  # noqa: E402

#: 需要为 transfer_orders 新增的列（列名 -> SQL 定义）
NEW_COLUMNS = [
    ("fail_reason", "VARCHAR(256) NOT NULL DEFAULT ''"),
    ("version", "INTEGER NOT NULL DEFAULT 0"),
    ("expires_at", "DATETIME"),
    ("confirmed_at", "DATETIME"),
    ("mfa_verified_at", "DATETIME"),
    ("executing_at", "DATETIME"),
    ("executed_at", "DATETIME"),
    ("failed_at", "DATETIME"),
    ("cancelled_at", "DATETIME"),
    ("expired_at", "DATETIME"),
]


def _existing_columns(conn) -> set[str]:
    rows = conn.exec_driver_sql("PRAGMA table_info(transfer_orders)").fetchall()
    return {row[1] for row in rows}


def migrate() -> None:
    # 1) 新建所有表（幂等 create_all 只会补缺的表）
    init_db()

    conn = engine.connect()
    try:
        existing = _existing_columns(conn)
        added = []
        for col_name, col_def in NEW_COLUMNS:
            if col_name not in existing:
                conn.exec_driver_sql(f"ALTER TABLE transfer_orders ADD COLUMN {col_name} {col_def}")
                added.append(col_name)
        conn.commit()
        print(f"  新增列：{added if added else '（无需新增，列已存在）'}")
    finally:
        conn.close()

    # 2) 旧状态 → 新状态（安全、可追踪）
    db = SessionLocal()
    try:
        from app.security.order_state import LEGACY_STATUS_MAP

        updated = 0
        orders = db.query(TransferOrder).all()
        for order in orders:
            new_status = normalize_legacy_status(order.status)
            if new_status != order.status:
                # 旧 executed → SUCCEEDED，回填执行时间
                if order.status == "executed" and order.executed_at is None:
                    order.executed_at = order.updated_at or utcnow()
                order.status = new_status
                updated += 1
        db.commit()
        print(f"  状态迁移：{updated} 个旧工单状态已映射（其余无需迁移）")
        print(f"  映射规则：{LEGACY_STATUS_MAP}")
    finally:
        db.close()

    print("✅ V0.3.0 数据库迁移完成")


if __name__ == "__main__":
    migrate()
