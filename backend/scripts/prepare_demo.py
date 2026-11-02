"""竞赛演示准备脚本（V1.0.0）。

用途：演示前一键把**独立演示库**恢复到可预期的初始状态，并输出检查清单。

⚠️ 本脚本只操作演示库（默认 `data/demo_v100.db`），**不触碰开发库 `data/fintrust.db`**。
   如需指定其它库，用 `--database` 覆盖。

用法：
    cd backend
    .venv/Scripts/python.exe scripts/prepare_demo.py
    .venv/Scripts/python.exe scripts/prepare_demo.py --database sqlite:///./data/demo_v100.db --reset-daily
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402


def _business_day_window() -> tuple:
    """与 transfer_service 一致的业务时区自然日窗口。"""
    from app.services.transfer_service import _business_day_window as _win

    return _win()


def reset_daily_total(db: Session, account_id: int = 1) -> int:
    """清空指定账户的当日「转账支出」流水，使演示场景的权限判定从零累计开始。"""
    from app.models import Transaction

    start, end = _business_day_window()
    deleted = (
        db.query(Transaction)
        .filter(
            Transaction.account_id == account_id,
            Transaction.category == "转账支出",
            Transaction.occurred_at >= start,
            Transaction.occurred_at < end,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def check(db: Session) -> list[tuple[str, bool, str]]:
    """演示前检查清单。"""
    checks: list[tuple[str, bool, str]] = []

    # 1. 演示账号
    rows = db.execute(text("SELECT username, status FROM users ORDER BY id")).fetchall()
    names = {r[0]: r[1] for r in rows}
    ok = names.get("demo_user_1") == "active" and names.get("demo_user_2") == "active"
    checks.append(("演示账号 demo_user_1 / demo_user_2 均存在且 active", ok, str(names)))

    # 2. 账户绑定
    binds = db.execute(text("SELECT user_id, account_id, permission FROM user_accounts")).fetchall()
    ok = {(r[0], r[1]) for r in binds} >= {(1, 1), (2, 2)}
    checks.append(("账户隔离绑定（用户1→账户1，用户2→账户2）", ok, str(binds)))

    # 3. 收款人
    payees = db.execute(
        text("SELECT COUNT(*) FROM payees WHERE account_id = 1")
    ).scalar_one()
    checks.append(("账户1 收款人数量 ≥ 3", payees >= 3, f"{payees} 位"))

    # 4. 银行卡
    cards = db.execute(text("SELECT COUNT(*) FROM cards WHERE account_id = 1")).scalar_one()
    checks.append(("账户1 银行卡数量 ≥ 2", cards >= 2, f"{cards} 张"))

    # 5. 历史流水
    txs = db.execute(text("SELECT COUNT(*) FROM transactions WHERE account_id = 1")).scalar_one()
    checks.append(("账户1 历史流水充足（≥100 条）", txs >= 100, f"{txs} 条"))

    # 6. 当日累计
    start, end = _business_day_window()
    daily = db.execute(
        text(
            "SELECT COALESCE(SUM(amount_cents),0) FROM transactions "
            "WHERE account_id = 1 AND category = '转账支出' "
            "AND occurred_at >= :s AND occurred_at < :e"
        ),
        {"s": start, "e": end},
    ).scalar_one()
    ok = daily == 0
    checks.append(
        ("当日累计为 0（否则 800 元场景会直接触发红色）", ok, f"{daily / 100:.2f} 元")
    )

    # 7. 审计完整性
    try:
        from app.security.audit_integrity import verify_integrity

        passed, summary, detail = verify_integrity(db)
        checks.append((f"审计完整性 {summary}", passed, str(detail)))
    except Exception as exc:  # noqa: BLE001
        checks.append(("审计完整性验证", False, f"{exc.__class__.__name__}: {exc}"))

    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="金枢竞赛演示准备")
    parser.add_argument("--database", default=None, help="演示库 DATABASE_URL")
    parser.add_argument("--reset-daily", action="store_true", help="清空当日累计（使权限场景从零开始）")
    args = parser.parse_args()

    if args.database:
        import os

        os.environ["DATABASE_URL"] = args.database
        # 重新载入配置与引擎
        for mod in ("app.core.config", "app.core.database"):
            if mod in sys.modules:
                del sys.modules[mod]
        from app.core import config as _cfg
        from app.core import database as _db

        _cfg.settings.DATABASE_URL = args.database  # type: ignore[attr-defined]
        _db.engine.dispose()
        import app.core.database as dbmod

        dbmod.engine = _db.engine  # type: ignore[assignment]

    db = SessionLocal()
    try:
        if args.reset_daily:
            n = reset_daily_total(db, account_id=1)
            print(f"→ 已清空当日「转账支出」流水 {n} 条（账户 1）")

        print("→ 演示前检查清单：")
        results = check(db)
        for name, ok, detail in results:
            mark = "✓" if ok else "✗"
            print(f"  {mark} {name}  [{detail}]")

        failed = [r for r in results if not r[1]]
        print()
        if failed:
            print(f"⚠️  {len(failed)} 项未通过，请先处理后再演示")
            return 1
        print("✅ 演示环境就绪：800 元 → 黄色确认；1500 元 → 红色 MFA")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
