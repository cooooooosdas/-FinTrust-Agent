"""账单分析服务：消费分类、月度统计、异常交易识别。

所有统计基于真实数据库流水计算，不返回任何硬编码的假数据。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Transaction, utcnow
from app.services.account_service import cents_to_yuan

#: 消费分类的标准顺序（未命中的分类排在最后）
CATEGORY_ORDER = [
    "餐饮美食",
    "交通出行",
    "购物消费",
    "生活缴费",
    "娱乐休闲",
    "医疗健康",
    "教育学习",
    "住房物业",
    "金融理财",
    "转账支出",
    "工资收入",
    "其他收入",
    "其他",
]

#: 各分类的参考月均支出，用于判断"异常"（分）
CATEGORY_BASELINE_CENTS: Dict[str, int] = {
    "餐饮美食": 60000,
    "交通出行": 30000,
    "购物消费": 150000,
    "生活缴费": 80000,
    "娱乐休闲": 50000,
    "医疗健康": 100000,
    "教育学习": 60000,
    "住房物业": 300000,
    "金融理财": 50000,
    "转账支出": 100000,
}


def _month_range(month_str: str) -> tuple[datetime, datetime]:
    """把 'YYYY-MM' 解析为 (start, end)。"""
    year, _, mon = month_str.partition("-")
    year, mon = int(year), int(mon or 1)
    start = datetime(year, mon, 1)
    if mon == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, mon + 1, 1)
    return start, end


def current_month_str() -> str:
    return utcnow().strftime("%Y-%m")


def _month_shift(month_str: str, delta: int) -> str:
    year, mon = month_str.split("-")
    y, m = int(year), int(mon)
    index = y * 12 + (m - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def fetch_transactions(
    db: Session,
    account_id: int,
    *,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    category: Optional[str] = None,
    direction: Optional[str] = None,
    keyword: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
) -> List[Transaction]:
    """按条件筛选交易流水。"""
    stmt = select(Transaction).where(Transaction.account_id == account_id)
    if start is not None:
        stmt = stmt.where(Transaction.occurred_at >= start)
    if end is not None:
        stmt = stmt.where(Transaction.occurred_at < end)
    if category:
        stmt = stmt.where(Transaction.category == category)
    if direction:
        stmt = stmt.where(Transaction.direction == direction)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            Transaction.merchant.like(like)
            | Transaction.counterparty.like(like)
            | Transaction.remark.like(like)
        )
    if min_amount is not None:
        stmt = stmt.where(Transaction.amount_cents >= int(min_amount * 100))
    if max_amount is not None:
        stmt = stmt.where(Transaction.amount_cents <= int(max_amount * 100))
    stmt = stmt.order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
    return list(db.execute(stmt).scalars())


def category_breakdown(transactions: List[Transaction]) -> List[Dict]:
    """按分类汇总支出。"""
    totals: Dict[str, Dict[str, int]] = defaultdict(lambda: {"amount": 0, "count": 0})
    for tx in transactions:
        if tx.direction != "expense":
            continue
        totals[tx.category]["amount"] += tx.amount_cents
        totals[tx.category]["count"] += 1

    grand_total = sum(v["amount"] for v in totals.values())
    items = [
        {
            "category": cat,
            "amount": cents_to_yuan(data["amount"]),
            "count": data["count"],
            "ratio": round(data["amount"] / grand_total, 4) if grand_total else 0.0,
        }
        for cat, data in totals.items()
    ]
    items.sort(
        key=lambda x: (
            CATEGORY_ORDER.index(x["category"]) if x["category"] in CATEGORY_ORDER else 999,
            -x["amount"],
        )
    )
    return items


def monthly_trend(db: Session, account_id: int, months: int = 6) -> List[Dict]:
    """近 N 个月的收支趋势。"""
    now = utcnow()
    result: List[Dict] = []
    for i in range(months - 1, -1, -1):
        month = _month_shift(now.strftime("%Y-%m"), -i)
        start, end = _month_range(month)
        rows = db.execute(
            select(Transaction.direction, func.sum(Transaction.amount_cents))
            .where(
                Transaction.account_id == account_id,
                Transaction.occurred_at >= start,
                Transaction.occurred_at < end,
            )
            .group_by(Transaction.direction)
        ).all()
        sums = {direction: int(total or 0) for direction, total in rows}
        result.append(
            {
                "month": month,
                "expense": cents_to_yuan(sums.get("expense", 0)),
                "income": cents_to_yuan(sums.get("income", 0)),
            }
        )
    return result


def detect_anomalies(transactions: List[Transaction]) -> List[Dict]:
    """异常交易识别。

    规则：
    1. 单笔金额显著超过该分类基线（3 倍且超过 1000 元）；
    2. 交易时间落在凌晨 0:00-5:00（非常规消费时段）；
    3. 夜间高额消费（凌晨且单笔 ≥ 800 元）直接判为高风险。
    """
    anomalies: List[Dict] = []
    for tx in transactions:
        if tx.direction != "expense":
            continue
        score = 0.0
        reasons: List[str] = []

        baseline = CATEGORY_BASELINE_CENTS.get(tx.category, 50000)
        if tx.amount_cents >= baseline * 3 and tx.amount_cents >= 100000:
            score += 55
            reasons.append(f"单笔金额 {cents_to_yuan(tx.amount_cents):.2f} 元，为「{tx.category}」基线的 3 倍以上")

        hour = tx.occurred_at.hour
        if 0 <= hour < 5:
            score += 25
            reasons.append(f"交易发生在凌晨 {hour:02d}:{tx.occurred_at.minute:02d}，属于非常规时段")

        if 0 <= hour < 5 and tx.amount_cents >= 80000:
            score += 25
            reasons.append("夜间高额交易，需人工复核")

        if tx.status not in ("success", "settled"):
            score += 20
            reasons.append(f"交易状态为 {tx.status}")

        if score >= 50:
            anomalies.append(
                {
                    "transaction_id": tx.id,
                    "occurred_at": tx.occurred_at.isoformat() if tx.occurred_at else "",
                    "merchant": tx.merchant,
                    "category": tx.category,
                    "amount": cents_to_yuan(tx.amount_cents),
                    "direction": tx.direction,
                    "score": round(min(100.0, score), 1),
                    "reason": "；".join(reasons),
                }
            )

    anomalies.sort(key=lambda a: (-a["score"], a["occurred_at"]))
    return anomalies


def resolve_period(period: Optional[str]) -> tuple[datetime, datetime, str]:
    """把周期标识解析为 (start, end, 展示名)。

    支持：
    - ``current_month`` / ``本月``：当前自然月
    - ``last_month``  / ``上月``：上一个自然月
    - ``last_30d``   / ``近30天``：滚动 30 天
    - ``last_90d``   / ``近90天``：滚动 90 天
    - ``last_180d``  / ``近180天``：滚动 180 天
    - ``YYYY-MM``：指定自然月
    """
    today = utcnow()
    p = (period or "current_month").strip()

    if p in ("current_month", "本月", "this_month"):
        start, end = _month_range(today.strftime("%Y-%m"))
        return start, end, today.strftime("%Y-%m")
    if p in ("last_month", "上月", "last_month_period"):
        start, end = _month_range(_month_shift(today.strftime("%Y-%m"), -1))
        return start, end, _month_shift(today.strftime("%Y-%m"), -1)
    if p in ("last_30d", "近30天", "30d"):
        return today - timedelta(days=30), today + timedelta(days=1), f"近 30 天"
    if p in ("last_90d", "近90天", "90d"):
        return today - timedelta(days=90), today + timedelta(days=1), "近 90 天"
    if p in ("last_180d", "近180天", "180d"):
        return today - timedelta(days=180), today + timedelta(days=1), "近 180 天"
    if len(p) == 7 and p[4] == "-":
        start, end = _month_range(p)
        return start, end, p
    # 兜底按当前月处理
    start, end = _month_range(today.strftime("%Y-%m"))
    return start, end, today.strftime("%Y-%m")


def spending_stats(
    db: Session,
    account_id: int,
    month: Optional[str] = None,
    *,
    period: Optional[str] = None,
    trend_months: int = 6,
) -> Dict:
    """生成完整的账单统计结果。

    ``month`` 与 ``period`` 二选一：``month`` 形如 ``2026-11``，``period`` 支持
    ``current_month`` / ``last_month`` / ``last_30d`` 等滚动窗口。
    """
    if period is None and month:
        period = month
    start, end, label = resolve_period(period)

    transactions = fetch_transactions(db, account_id, start=start, end=end)

    expense_cents = sum(tx.amount_cents for tx in transactions if tx.direction == "expense")
    income_cents = sum(tx.amount_cents for tx in transactions if tx.direction == "income")

    span_days = max(1, (end - start).days)
    elapsed_days = max(1, min(span_days, (utcnow() - start).days + 1))

    # 异常识别需要更长窗口的历史，否则样本不足
    anomaly_window = fetch_transactions(
        db, account_id, start=start - timedelta(days=45), end=end
    )
    anomalies = detect_anomalies(anomaly_window)

    return {
        "month": label,
        "period_start": start,
        "period_end": end,
        "total_expense": cents_to_yuan(expense_cents),
        "total_income": cents_to_yuan(income_cents),
        "transaction_count": len(transactions),
        "daily_average": cents_to_yuan(round(expense_cents / elapsed_days)),
        "max_single": cents_to_yuan(max((tx.amount_cents for tx in transactions), default=0)),
        "categories": category_breakdown(transactions),
        "trend": monthly_trend(db, account_id, months=trend_months),
        "anomalies": anomalies,
    }


def natural_query(db: Session, account_id: int, question: str) -> Dict:
    """账单自然语言查询。

    解析常见模式：分类、时间范围、方向、金额区间、关键词，
    命中则直接过滤，未命中则返回当月全量 + 概览。
    """
    q = question.strip()
    q_lower = q.lower()

    direction: Optional[str] = None
    if any(k in q for k in ("收入", "工资", "进账", "入账", "收到")):
        direction = "income"
    elif any(k in q for k in ("支出", "花费", "消费", "花了", "付款", "支出情况")):
        direction = "expense"

    category: Optional[str] = None
    for cat in CATEGORY_ORDER:
        for token in _category_tokens(cat):
            if token in q:
                category = cat
                break
        if category:
            break

    start = end = None
    if "本月" in q or "这个月" in q or "当月" in q:
        start, end = _month_range(current_month_str())
    elif "上月" in q or "上个月" in q or "上月" in q:
        start, end = _month_range(_month_shift(current_month_str(), -1))
    elif "近七天" in q or "最近七天" in q or "一周" in q:
        end = utcnow()
        start = end - timedelta(days=7)
    elif "近三天" in q or "最近三天" in q:
        end = utcnow()
        start = end - timedelta(days=3)
    elif "今年" in q or "本年" in q:
        start = datetime(utcnow().year, 1, 1)
        end = utcnow()

    keyword: Optional[str] = None
    for token in ("星巴克", "麦当劳", "饿了么", "滴滴", "京东", "淘宝", "美团", "中石化", "国家电网"):
        if token in q:
            keyword = token
            break

    transactions = fetch_transactions(
        db, account_id, start=start, end=end, category=category, direction=direction, keyword=keyword
    )
    return {
        "transactions": transactions,
        "matched": {
            "direction": direction,
            "category": category,
            "keyword": keyword,
            "start": start,
            "end": end,
        },
        "stats": {
            "count": len(transactions),
            "total": cents_to_yuan(
                sum(tx.amount_cents for tx in transactions if tx.direction == "expense")
            ),
            "income": cents_to_yuan(
                sum(tx.amount_cents for tx in transactions if tx.direction == "income")
            ),
        },
    }


def _category_tokens(category: str) -> List[str]:
    mapping = {
        "餐饮美食": ["餐饮", "吃饭", "外卖", "美食", "餐"],
        "交通出行": ["交通", "打车", "出行", "加油", "地铁"],
        "购物消费": ["购物", "买", "消费", "网购"],
        "生活缴费": ["缴费", "水电", "物业", "话费", "燃气"],
        "娱乐休闲": ["娱乐", "电影", "游戏", "休闲", "健身"],
        "医疗健康": ["医疗", "医院", "药品", "看病", "体检"],
        "教育学习": ["教育", "学习", "课程", "培训", "书"],
        "住房物业": ["房", "房贷", "租金", "住宿"],
        "金融理财": ["理财", "基金", "利息", "证券"],
        "转账支出": ["转账", "汇款"],
        "工资收入": ["工资", "薪水", "薪资"],
    }
    return mapping.get(category, [category])


__all__ = [
    "spending_stats",
    "fetch_transactions",
    "category_breakdown",
    "monthly_trend",
    "detect_anomalies",
    "natural_query",
    "resolve_period",
    "current_month_str",
    "CATEGORY_ORDER",
]
