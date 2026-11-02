"""收款人路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import current_user, db_session
from app.core.errors import NotFoundError
from app.models import User
from app.schemas import PayeeCreateRequest, PayeeOut
from app.services import auth_service
from app.services.account_service import cents_to_yuan, list_payees, mask_account_no

router = APIRouter(prefix="/payees", tags=["payees"])


def _to_out(p) -> PayeeOut:
    return PayeeOut(
        id=p.id,
        account_id=p.account_id,
        name=p.name,
        account_no=p.account_no,
        masked_account_no=mask_account_no(p.account_no),
        bank_name=p.bank_name,
        card_last4=p.card_last4,
        is_frequent=p.is_frequent,
        single_limit=cents_to_yuan(p.single_limit_cents),
        total_count=p.total_count,
        last_used_at=p.last_used_at,
        created_at=p.created_at,
    )


@router.get("", response_model=list[PayeeOut], summary="收款人列表")
def get_payees(
    db: Session = Depends(db_session),
    account_id: int = Query(default=1),
    user: User = Depends(current_user),
) -> list[PayeeOut]:
    auth_service.ensure_account_access(db, user, account_id)
    return [_to_out(p) for p in list_payees(db, account_id)]


@router.post("", response_model=PayeeOut, status_code=201, summary="新增收款人")
def create_payee(
    payload: PayeeCreateRequest,
    db: Session = Depends(db_session),
    user: User = Depends(current_user),
) -> PayeeOut:
    from app.models import Payee

    auth_service.ensure_account_access(db, user, payload.account_id)

    exists = db.query(Payee).filter(
        Payee.account_id == payload.account_id,
        Payee.account_no == payload.account_no,
    ).first()
    if exists is not None:
        raise NotFoundError("该收款人已存在")

    payee = Payee(
        account_id=payload.account_id,
        name=payload.name.strip(),
        account_no=payload.account_no.strip(),
        bank_name=payload.bank_name.strip() or "金枢银行",
        card_last4=payload.card_last4.strip() or payload.account_no[-4:],
        is_frequent=False,
        single_limit_cents=10000000,
        total_count=0,
    )
    db.add(payee)
    db.commit()
    db.refresh(payee)
    return _to_out(payee)
