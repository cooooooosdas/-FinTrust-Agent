"""交易流水与账单分析路由。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import current_user, db_session
from app.core.errors import ValidationError
from app.models import User
from app.schemas import (
    AnomalyItem,
    CategoryBreakdown,
    MonthlyTrend,
    SpendingStats,
    TransactionOut,
    TransactionPage,
)
from app.services import analytics_service, auth_service
from app.services.account_service import cents_to_yuan

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _to_out(t) -> TransactionOut:
    return TransactionOut(
        id=t.id,
        account_id=t.account_id,
        card_id=t.card_id,
        direction=t.direction,
        category=t.category,
        amount=cents_to_yuan(t.amount_cents),
        balance_after=cents_to_yuan(t.balance_after_cents),
        merchant=t.merchant,
        counterparty=t.counterparty,
        remark=t.remark,
        status=t.status,
        channel=t.channel,
        is_simulated=t.is_simulated,
        occurred_at=t.occurred_at,
    )


def _parse_date(value: str | None, field: str) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValidationError(f"{field} 时间格式无法解析：{value}")


@router.get("", response_model=TransactionPage, summary="交易流水分页查询")
def list_transactions(
    db: Session = Depends(db_session),
    account_id: int = Query(default=1),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    category: str | None = Query(default=None),
    direction: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    min_amount: float | None = Query(default=None),
    max_amount: float | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    user: User = Depends(current_user),
) -> TransactionPage:
    auth_service.ensure_account_access(db, user, account_id)
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if end is not None:
        end = end.replace(hour=23, minute=59, second=59)

    items = analytics_service.fetch_transactions(
        db,
        account_id,
        start=start,
        end=end,
        category=category,
        direction=direction,
        keyword=keyword,
        min_amount=min_amount,
        max_amount=max_amount,
    )
    total = len(items)
    offset = (page - 1) * page_size
    page_items = items[offset : offset + page_size]
    expense_total = sum(t.amount_cents for t in items if t.direction == "expense")

    return TransactionPage(
        items=[_to_out(t) for t in page_items],
        total=total,
        page=page,
        page_size=page_size,
        total_amount=cents_to_yuan(expense_total),
    )


@router.get("/stats", response_model=SpendingStats, summary="账单统计")
def transaction_stats(
    db: Session = Depends(db_session),
    account_id: int = Query(default=1),
    month: str | None = Query(default=None, description="YYYY-MM，缺省为当月"),
    period: str | None = Query(
        default=None,
        description="周期：current_month / last_month / last_30d / last_90d / last_180d",
    ),
    user: User = Depends(current_user),
) -> SpendingStats:
    auth_service.ensure_account_access(db, user, account_id)
    stats = analytics_service.spending_stats(db, account_id, month, period=period)
    return SpendingStats(
        month=stats["month"],
        total_expense=stats["total_expense"],
        total_income=stats["total_income"],
        transaction_count=stats["transaction_count"],
        daily_average=stats["daily_average"],
        max_single=stats["max_single"],
        categories=[CategoryBreakdown(**c) for c in stats["categories"]],
        trend=[MonthlyTrend(**t) for t in stats["trend"]],
        anomalies=[AnomalyItem(**a) for a in stats["anomalies"]],
    )


@router.get("/categories", summary="消费分类汇总")
def categories(
    db: Session = Depends(db_session),
    account_id: int = Query(default=1),
    month: str | None = Query(default=None),
    period: str | None = Query(default=None),
    user: User = Depends(current_user),
) -> list[CategoryBreakdown]:
    auth_service.ensure_account_access(db, user, account_id)
    stats = analytics_service.spending_stats(db, account_id, month, period=period)
    return [CategoryBreakdown(**c) for c in stats["categories"]]


@router.get("/anomalies", response_model=list[AnomalyItem], summary="异常交易列表")
def anomalies(
    db: Session = Depends(db_session),
    account_id: int = Query(default=1),
    user: User = Depends(current_user),
) -> list[AnomalyItem]:
    auth_service.ensure_account_access(db, user, account_id)
    stats = analytics_service.spending_stats(db, account_id)
    return [AnomalyItem(**a) for a in stats["anomalies"]]
