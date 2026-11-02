"""银行卡路由。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import current_user, db_session
from app.core.config import settings
from app.core.errors import NotFoundError
from app.models import User
from app.schemas import CardOut, CardLossRequest, VirtualCardApplyRequest
from app.services import auth_service, card_service
from app.services.account_service import cents_to_yuan, mask_card_no

router = APIRouter(prefix="/cards", tags=["cards"])


def _to_out(card) -> CardOut:
    return CardOut(
        id=card.id,
        account_id=card.account_id,
        card_no=card.card_no,
        masked_card_no=mask_card_no(card.card_no),
        card_type=card.card_type,
        card_name=card.card_name,
        network=card.network,
        status=card.status,
        daily_limit=cents_to_yuan(card.daily_limit_cents),
        expire_month=card.expire_month,
        is_virtual=card.is_virtual,
        is_simulated=card.is_simulated,
        created_at=card.created_at,
    )


def _ensure_card_owner(db: Session, user: User, card_id: int):
    """校验卡片归属：卡片所属账户必须在用户授权范围内。"""
    card = card_service.get_card(db, card_id)
    auth_service.ensure_account_access(db, user, card.account_id)
    return card


@router.get("", response_model=list[CardOut], summary="银行卡列表")
def list_cards(
    db: Session = Depends(db_session),
    account_id: int = Query(default=1),
    user: User = Depends(current_user),
) -> list[CardOut]:
    auth_service.ensure_account_access(db, user, account_id)
    cards = card_service.list_cards(db, account_id)
    return [_to_out(c) for c in cards]


@router.get("/{card_id}", response_model=CardOut, summary="银行卡详情")
def get_card(
    card_id: int,
    db: Session = Depends(db_session),
    user: User = Depends(current_user),
) -> CardOut:
    card = _ensure_card_owner(db, user, card_id)
    return _to_out(card)


@router.post("/virtual", summary="申请虚拟卡（黄色：需确认）")
def apply_virtual_card(
    payload: VirtualCardApplyRequest,
    db: Session = Depends(db_session),
    confirm: bool = Query(default=False, description="用户已明确确认"),
    user: User = Depends(current_user),
) -> dict:
    # 虚拟卡默认绑定当前用户第一个授权账户
    allowed = auth_service.account_ids_for_user(db, user.id)
    if not allowed:
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("当前用户没有任何授权账户")
    account_id = allowed[0]
    result = card_service.apply_virtual_card(
        db,
        account_id=account_id,
        card_name=payload.card_name,
        daily_limit=payload.daily_limit,
        expire_month=payload.expire_month,
        confirm=confirm,
    )
    return result


@router.post("/freeze", summary="冻结 / 解冻卡片（黄色：需确认）")
def freeze_card(
    card_id: int = Query(...),
    db: Session = Depends(db_session),
    confirm: bool = Query(default=False, description="用户已明确确认"),
    user: User = Depends(current_user),
) -> dict:
    _ensure_card_owner(db, user, card_id)
    return card_service.freeze_card(db, card_id=card_id, confirm=confirm)


@router.post("/lost", summary="银行卡挂失（红色：需多因子验证）")
def report_lost(
    payload: CardLossRequest,
    db: Session = Depends(db_session),
    mfa_code: Optional[str] = Query(default=None, description="模拟 MFA 验证码"),
    mfa_challenge_id: Optional[str] = Query(default=None, description="MFA 挑战 ID"),
    user: User = Depends(current_user),
) -> dict:
    _ensure_card_owner(db, user, payload.card_id)
    return card_service.report_card_lost(
        db,
        card_id=payload.card_id,
        reason=payload.reason,
        mfa_code=mfa_code,
        mfa_challenge_id=mfa_challenge_id,
        actor=user.username,
    )
