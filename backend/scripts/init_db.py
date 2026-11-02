"""数据库初始化 + 演示数据种子脚本。

用法：
    cd backend
    python scripts/init_db.py          # 建表 + 灌入种子数据（已有数据时跳过灌数）
    python scripts/init_db.py --reset  # 删除已有数据库文件后重建
    python scripts/init_db.py --seed   # 只补种子数据（不清库）

说明：所有种子数据均为**模拟数据**，用于竞赛演示，与任何真实银行账户无关。
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.core.database import Base, SessionLocal, engine, init_db  # noqa: E402
from app.models import Account, Card, Payee, Transaction, utcnow  # noqa: E402

SEED = 20260101

ACCOUNTS = [
    {
        "account_no": "6217001234567890",
        "holder_name": "徐舒和",
        "account_type": "deposit",
        "bank_name": "金枢银行",
        "currency": "CNY",
        "balance_cents": 12_865_300,
        "available_cents": 12_815_300,
        "status": "active",
    },
    {
        "account_no": "6222029876543210",
        "holder_name": "徐舒和",
        "account_type": "credit",
        "bank_name": "金枢银行",
        "currency": "CNY",
        "balance_cents": -32_180,
        "available_cents": 967_820,
        "status": "active",
    },
]

CARDS = [
    {
        "account_no": "6217001234567890",
        "card_no": "6217001234567890",
        "card_type": "debit",
        "card_name": "金枢储蓄卡",
        "network": "银联",
        "status": "active",
        "daily_limit_cents": 500_000,
        "expire_month": "2029/06",
        "is_virtual": False,
    },
    {
        "account_no": "6222029876543210",
        "card_no": "6222029876543210",
        "card_type": "credit",
        "card_name": "金枢信用卡·白金",
        "network": "银联",
        "status": "active",
        "daily_limit_cents": 1_000_000,
        "expire_month": "2030/03",
        "is_virtual": False,
    },
    {
        "account_no": "6217001234567890",
        "card_no": "6288330099887766",
        "card_type": "virtual",
        "card_name": "网购虚拟卡",
        "network": "金枢虚拟卡",
        "status": "active",
        "daily_limit_cents": 200_000,
        "expire_month": "2027/12",
        "is_virtual": True,
    },
]

PAYEES = [
    ("张明远", "6212261234567890", "工商银行", "7890", True, 3),
    ("李思远", "6217009876543210", "金枢银行", "3210", True, 5),
    ("王雨桐", "6228480398765432", "招商银行", "5432", True, 2),
    ("陈可欣", "6217005566778899", "金枢银行", "8899", False, 1),
    ("赵启航", "6222023344556677", "建设银行", "6677", False, 0),
]

# (分类, 商户, 单笔金额区间(元), 出现概率)
EXPENSE_TEMPLATES = [
    ("餐饮美食", "星巴克臻选", (28, 68), 0.30),
    ("餐饮美食", "海底捞火锅", (168, 460), 0.10),
    ("餐饮美食", "美团外卖", (18, 96), 0.24),
    ("餐饮美食", "瑞幸咖啡", (9, 32), 0.22),
    ("交通出行", "滴滴出行", (12, 88), 0.28),
    ("交通出行", "中国石化加油站", (280, 520), 0.08),
    ("交通出行", "地铁乘车码", (4, 22), 0.18),
    ("购物消费", "京东商城", (89, 1580), 0.20),
    ("购物消费", "淘宝天猫", (39, 980), 0.18),
    ("购物消费", "优衣库", (149, 690), 0.08),
    ("生活缴费", "国家电网", (86, 320), 0.05),
    ("生活缴费", "中国移动话费", (58, 128), 0.05),
    ("生活缴费", "物业服务费", (180, 680), 0.03),
    ("娱乐休闲", "万达影城", (48, 160), 0.10),
    ("娱乐休闲", "Steam 游戏", (38, 398), 0.08),
    ("娱乐休闲", "乐刻健身", (99, 299), 0.05),
    ("医疗健康", "市三医院门诊", (60, 860), 0.05),
    ("医疗健康", "老百姓大药房", (26, 320), 0.06),
    ("教育学习", "得到课程", (49, 299), 0.07),
    ("教育学习", "多抓鱼书店", (32, 180), 0.05),
    ("住房物业", "住房公积金还贷", (3200, 4600), 0.04),
    ("金融理财", "基金定投扣款", (1000, 3000), 0.06),
]


def reset_database() -> None:
    """清空所有业务表（保留表结构），比删除文件更稳妥，不受文件锁影响。"""
    from app.models import (
        Account,
        AgentMessage,
        AgentSession,
        AuditLog,
        Card,
        IdempotencyRecord,
        Payee,
        Transaction,
        TransferOrder,
    )

    db = SessionLocal()
    try:
        models = [
            AgentMessage,
            AgentSession,
            AuditLog,
            IdempotencyRecord,
            TransferOrder,
            Transaction,
            Payee,
            Card,
            Account,
        ]
        for model in models:
            deleted = db.query(model).delete()
            print(f"  已清空 {model.__tablename__}（{deleted} 行）")
        db.commit()
    finally:
        db.close()


def seed(db) -> None:
    """灌入演示数据。"""
    rng = random.Random(SEED)

    accounts: dict[str, Account] = {}
    for item in ACCOUNTS:
        acc = Account(**item, created_at=utcnow())
        db.add(acc)
        accounts[item["account_no"]] = acc
    db.flush()

    cards: list[Card] = []
    for item in CARDS:
        account = accounts[item.pop("account_no")]
        card = Card(
            account_id=account.id,
            card_no=item["card_no"],
            card_type=item["card_type"],
            card_name=item["card_name"],
            network=item["network"],
            status=item["status"],
            daily_limit_cents=item["daily_limit_cents"],
            expire_month=item["expire_month"],
            is_virtual=item["is_virtual"],
            is_simulated=True,
            created_at=utcnow(),
        )
        db.add(card)
        cards.append(card)
    db.flush()

    # 所有收款人归属于主储蓄账户
    main_account_id = accounts["6217001234567890"].id
    for name, payee_acc_no, bank, last4, frequent, count in PAYEES:
        db.add(
            Payee(
                account_id=main_account_id,
                name=name,
                account_no=payee_acc_no,
                bank_name=bank,
                card_last4=last4,
                is_frequent=frequent,
                single_limit_cents=1_000_000,
                total_count=count,
                last_used_at=utcnow() - timedelta(days=rng.randint(1, 40)),
                created_at=utcnow(),
            )
        )

    # ---- 交易流水：滚动 180 天窗口（保证任意运行日期都有完整可用数据）----
    now = utcnow()
    today = now.date()
    transactions: list[Transaction] = []

    HISTORY_DAYS = 180
    for day_offset in range(HISTORY_DAYS, -1, -1):
        day = today - timedelta(days=day_offset)
        day_start = datetime(day.year, day.month, day.day)

        # 工资：每月 10 号代发
        if day.day == 10:
            salary_time = day_start.replace(hour=9, minute=12, second=0)
            transactions.append(
                Transaction(
                    account_id=accounts["6217001234567890"].id,
                    card_id=None,
                    direction="income",
                    category="工资收入",
                    amount_cents=rng.choice([1850000, 1920000, 2050000, 2180000]),
                    balance_after_cents=0,  # 稍后统一回填
                    merchant="金枢银行代发工资",
                    counterparty="云图科技（上海）有限公司",
                    remark="月度代发工资",
                    status="success",
                    channel="transfer",
                    is_simulated=True,
                    occurred_at=salary_time,
                )
            )

        # 日常消费
        for category, merchant, (low, high), probability in EXPENSE_TEMPLATES:
            if rng.random() > probability:
                continue
            amount = rng.randint(low * 100, high * 100)
            hour = rng.choice([8, 9, 11, 12, 13, 14, 18, 19, 20, 21, 22])
            minute = rng.randint(0, 59)
            occurred = day_start.replace(hour=hour, minute=minute, second=0)
            if occurred > now:
                continue
            transactions.append(
                Transaction(
                    account_id=accounts["6217001234567890"].id,
                    card_id=rng.choice(cards[:2]).id,
                    direction="expense",
                    category=category,
                    amount_cents=amount,
                    balance_after_cents=0,  # 稍后统一回填
                    merchant=merchant,
                    counterparty=merchant,
                    remark="",
                    status="success",
                    channel=rng.choice(["mobile", "online", "pos"]),
                    is_simulated=True,
                    occurred_at=occurred,
                )
            )

    # ---- 人为注入若干异常交易，便于演示异常识别能力 ----
    anomalies = [
        ("购物消费", "境外数码旗舰店", 899_900, 2, 3),   # 凌晨大额
        ("餐饮美食", "深夜烧烤城", 68_800, 3, 2),          # 凌晨消费
        ("医疗健康", "私立国际医院", 386_000, 9, 20),      # 超出分类基线
        ("娱乐休闲", "境外博彩平台", 520_000, 2, 15),      # 夜间高额
    ]
    for category, merchant, amount_cents, hour, day_ago in anomalies:
        occurred = (now - timedelta(days=day_ago)).replace(hour=hour, minute=37, second=0)
        if occurred > now:
            occurred = (now - timedelta(days=day_ago)).replace(hour=12, minute=37, second=0)
        transactions.append(
            Transaction(
                account_id=accounts["6217001234567890"].id,
                card_id=cards[0].id,
                direction="expense",
                category=category,
                amount_cents=amount_cents,
                balance_after_cents=0,
                merchant=merchant,
                counterparty=merchant,
                remark="",
                status="success",
                channel="online",
                is_simulated=True,
                occurred_at=occurred,
            )
        )

    # ---- 历史转账支出 ----
    transfer_time = (now - timedelta(days=4)).replace(hour=11, minute=5, second=0)
    transactions.append(
        Transaction(
            account_id=accounts["6217001234567890"].id,
            card_id=None,
            direction="expense",
            category="转账支出",
            amount_cents=320_000,
            balance_after_cents=0,
            merchant="转账至 张明远",
            counterparty="张明远",
            remark="[TR20260101001] 项目结算款",
            status="success",
            channel="agent",
            is_simulated=True,
            occurred_at=transfer_time,
        )
    )

    # ---- 回填余额：按时间正序累计，使 balance_after 连续可信 ----
    transactions.sort(key=lambda t: t.occurred_at)
    total_spend = sum(t.amount_cents for t in transactions if t.direction == "expense")
    total_income = sum(t.amount_cents for t in transactions if t.direction == "income")
    target_balance = 12_865_300  # ¥128,653.00，足以演示大额红色转账链路
    running = target_balance + total_spend - total_income
    for tx in transactions:
        if tx.direction == "expense":
            running -= tx.amount_cents
        else:
            running += tx.amount_cents
        tx.balance_after_cents = running

    for tx in transactions:
        db.add(tx)

    # ---- 演示用审计日志（让「安全审计中心」开箱即有内容）----
    from app.models import AuditLog

    audit_seed = [
        ("agent.chat", "allow", "green", "意图 account_overview：命中「余额/账户总览」关键词", "agent_session", "sess_demo_001", 3),
        ("agent.chat", "allow", "green", "意图 bill_analysis：命中「账单/消费统计」关键词", "agent_session", "sess_demo_001", 3),
        ("agent.chat", "allow", "green", "意图 transfer：命中「转账/汇款」关键词", "agent_session", "sess_demo_002", 2),
        ("transfer.preview", "confirm", "yellow", "向非常用联系人转账，需人工确认。", "transfer_order", "TR20260101103000001", 2),
        ("transfer.preview", "mfa", "red", "单笔金额 88000.00 元达到大额阈值 50000.00 元。", "transfer_order", "TR20260101103000002", 1),
        ("transfer.mfa_required", "mfa", "red", "高风险操作触发多因子验证", "transfer_order", "TR20260101103000002", 1),
        ("transfer.executed", "allow", "yellow", "向非常用联系人转账，需人工确认。", "transaction", "8801", 1),
        ("transfer.executed", "allow", "green", "金额与收款人均在常规区间，自动执行。", "transaction", "8802", 1),
        ("card.apply_virtual", "allow", "yellow", "写操作需用户明确确认后执行。", "card", "4", 1),
        ("card.reported_lost", "allow", "red", "敏感操作（银行卡挂失）必须通过模拟多因子身份验证。", "card", "3", 1),
    ]
    for idx, (action, decision, level, reason, target_type, target_id, days_ago) in enumerate(audit_seed):
        db.add(
            AuditLog(
                actor="demo-user",
                action=action,
                target_type=target_type,
                target_id=target_id,
                risk_level=level,
                decision=decision,
                reason=reason,
                detail_json="{}",
                ip_address="127.0.0.1",
                is_simulation=True,
                created_at=now - timedelta(days=days_ago, hours=idx * 37 % 24),
            )
        )

    # 校正账户余额与可用余额
    accounts["6217001234567890"].balance_cents = target_balance
    accounts["6217001234567890"].available_cents = target_balance - 50_000
    accounts["6222029876543210"].balance_cents = -32_180
    accounts["6222029876543210"].available_cents = 967_820

    db.commit()
    print(f"  已写入 {len(transactions)} 条模拟交易、{len(cards)} 张卡、{len(PAYEES)} 位收款人")


def recreate_tables() -> None:
    """删除并重建全部表（用于表结构变更后重建数据库）。"""
    from app.core.database import Base

    Base.metadata.drop_all(bind=engine)
    print("  已删除全部旧表")
    Base.metadata.create_all(bind=engine)
    print("  已按最新模型重建表结构")


def main() -> None:
    parser = argparse.ArgumentParser(description="金枢 FinTrust Agent 数据库初始化")
    parser.add_argument("--reset", action="store_true", help="清空所有业务表后重新灌入种子数据")
    parser.add_argument("--recreate", action="store_true", help="删除并重建全部表（表结构变更后使用）")
    parser.add_argument("--seed", action="store_true", help="仅补种子数据")
    parser.add_argument("--no-seed", action="store_true", help="仅建表不灌数据")
    args = parser.parse_args()

    print(f"数据库路径：{settings.database_url}")
    if args.recreate:
        print("→ 正在重建表结构…")
        recreate_tables()
    elif args.reset:
        print("→ 正在重置数据…")
        reset_database()

    print("→ 正在建表…")
    init_db()
    print("  表结构已就绪")

    if not args.no_seed:
        db = SessionLocal()
        try:
            existing = db.query(Account).count()
            if existing > 0 and not args.seed and not args.reset:
                print(f"  检测到已有 {existing} 个账户，跳过种子数据（可使用 --seed 强制补灌）")
            else:
                print("→ 正在写入演示种子数据…")
                seed(db)
        finally:
            db.close()

    print("✅ 数据库初始化完成")


if __name__ == "__main__":
    main()
