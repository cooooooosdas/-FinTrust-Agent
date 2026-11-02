"""账户总览服务。"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models import Account, Card, Payee, Transaction


def get_account(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise NotFoundError(f"账户 {account_id} 不存在", detail={"account_id": account_id})
    return account


def get_default_account(db: Session) -> Account:
    """返回演示默认账户（余额最高的一个）。"""
    account = db.execute(
        select(Account).order_by(Account.id).limit(1)
    ).scalar_one_or_none()
    if account is None:
        raise NotFoundError("系统中没有可用账户，请先执行数据库初始化")
    return account


def list_accounts(db: Session) -> List[Account]:
    return list(db.execute(select(Account).order_by(Account.id)).scalars())


def list_cards(db: Session, account_id: int) -> List[Card]:
    return list(
        db.execute(
            select(Card).where(Card.account_id == account_id).order_by(Card.id)
        ).scalars()
    )


def list_payees(db: Session, account_id: int) -> List[Payee]:
    return list(
        db.execute(
            select(Payee)
            .where(Payee.account_id == account_id)
            .order_by(Payee.is_frequent.desc(), Payee.total_count.desc(), Payee.id)
        ).scalars()
    )


def recent_transactions(db: Session, account_id: int, limit: int = 8) -> List[Transaction]:
    return list(
        db.execute(
            select(Transaction)
            .where(Transaction.account_id == account_id)
            .order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
            .limit(limit)
        ).scalars()
    )


def mask_account_no(account_no: str) -> str:
    """账号脱敏：保留前 4 位与后 4 位。"""
    if len(account_no) <= 8:
        return "*" * len(account_no)
    return f"{account_no[:4]}****{account_no[-4:]}"


def mask_card_no(card_no: str) -> str:
    if len(card_no) <= 8:
        return "*" * len(card_no)
    return f"{card_no[:4]} **** **** {card_no[-4:]}"


def cents_to_yuan(cents: int) -> float:
    return round(cents / 100, 2)


def yuan_to_cents(yuan: float) -> int:
    return int(round(float(yuan) * 100))


def get_account_by_no(db: Session, account_no: str) -> Optional[Account]:
    return db.execute(
        select(Account).where(Account.account_no == account_no)
    ).scalar_one_or_none()


__all__ = [
    "get_account",
    "get_default_account",
    "list_accounts",
    "list_cards",
    "list_payees",
    "recent_transactions",
    "mask_account_no",
    "mask_card_no",
    "cents_to_yuan",
    "yuan_to_cents",
    "get_account_by_no",
]
