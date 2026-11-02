"""账户总览路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import current_user, db_session
from app.core.config import settings
from app.models import User
from app.schemas import AccountSummary, OverviewResponse
from app.services import analytics_service, auth_service
from app.services.account_service import (
    cents_to_yuan,
    get_default_account,
    list_accounts,
    list_cards,
    list_payees,
    mask_account_no,
    mask_card_no,
    recent_transactions,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _account_summary(db: Session, account) -> AccountSummary:
    cards = list_cards(db, account.id)
    return AccountSummary(
        id=account.id,
        account_no=account.account_no,
        holder_name=account.holder_name,
        account_type=account.account_type,
        bank_name=account.bank_name,
        currency=account.currency,
        balance=cents_to_yuan(account.balance_cents),
        available=cents_to_yuan(account.available_cents),
        status=account.status,
        card_count=len(cards),
        created_at=account.created_at,
    )


@router.get("", summary="账户列表")
def accounts_list(
    db: Session = Depends(db_session),
    user: User = Depends(current_user),
) -> list[AccountSummary]:
    allowed = auth_service.account_ids_for_user(db, user.id)
    return [_account_summary(db, acc) for acc in list_accounts(db) if acc.id in allowed]


@router.get("/overview", response_model=OverviewResponse, summary="账户总览")
def account_overview(
    db: Session = Depends(db_session),
    account_id: int = Query(default=1, description="账户 ID"),
    user: User = Depends(current_user),
) -> OverviewResponse:
    # 账户归属校验：无权访问返回 403
    auth_service.ensure_account_access(db, user, account_id)

    account = get_default_account(db) if account_id <= 1 else None
    if account is None:
        from app.services.account_service import get_account

        account = get_account(db, account_id)

    cards = list_cards(db, account.id)
    payees = list_payees(db, account.id)
    txs = recent_transactions(db, account.id, limit=8)
    stats = analytics_service.spending_stats(db, account.id, period="last_30d")

    return OverviewResponse(
        account=_account_summary(db, account),
        cards=[
            {
                "id": c.id,
                "account_id": c.account_id,
                "card_no": c.card_no,
                "masked_card_no": mask_card_no(c.card_no),
                "card_type": c.card_type,
                "card_name": c.card_name,
                "network": c.network,
                "status": c.status,
                "daily_limit": cents_to_yuan(c.daily_limit_cents),
                "expire_month": c.expire_month,
                "is_virtual": c.is_virtual,
                "is_simulated": c.is_simulated,
                "created_at": c.created_at,
            }
            for c in cards
        ],
        recent_transactions=[
            {
                "id": t.id,
                "account_id": t.account_id,
                "card_id": t.card_id,
                "direction": t.direction,
                "category": t.category,
                "amount": cents_to_yuan(t.amount_cents),
                "balance_after": cents_to_yuan(t.balance_after_cents),
                "merchant": t.merchant,
                "counterparty": t.counterparty,
                "remark": t.remark,
                "status": t.status,
                "channel": t.channel,
                "is_simulated": t.is_simulated,
                "occurred_at": t.occurred_at,
            }
            for t in txs
        ],
        stats=stats,
        payees=[
            {
                "id": p.id,
                "account_id": p.account_id,
                "name": p.name,
                "account_no": p.account_no,
                "masked_account_no": mask_account_no(p.account_no),
                "bank_name": p.bank_name,
                "card_last4": p.card_last4,
                "is_frequent": p.is_frequent,
                "single_limit": cents_to_yuan(p.single_limit_cents),
                "total_count": p.total_count,
                "last_used_at": p.last_used_at,
                "created_at": p.created_at,
            }
            for p in payees
        ],
        simulation_notice=(
            f"{settings.simulation_tag}：本系统为竞赛演示环境，所有账户、余额、卡片与交易均为本地模拟数据，"
            "不连接任何真实银行账户，不执行任何真实资金交易。"
        ),
    )


class PasswordChangeChallengeRequest(BaseModel):
    pass


class PasswordChangeRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=1, max_length=128)
    mfa_code: str = Field(..., min_length=1, max_length=16)
    mfa_challenge_id: str = Field(..., min_length=1, max_length=64)


@router.post("/password/change/challenge", summary="申请修改密码（红色，生成 MFA 挑战）")
def password_change_challenge(
    db: Session = Depends(db_session),
    user: User = Depends(current_user),
) -> dict:
    from app.services import password_service

    return password_service.request_password_change(db, user)


@router.post("/password/change", summary="修改密码（校验旧密码 + MFA）")
def password_change(
    payload: PasswordChangeRequest,
    db: Session = Depends(db_session),
    user: User = Depends(current_user),
) -> dict:
    from app.services import password_service

    return password_service.change_password(
        db,
        user,
        old_password=payload.old_password,
        new_password=payload.new_password,
        mfa_code=payload.mfa_code,
        mfa_challenge_id=payload.mfa_challenge_id,
    )
