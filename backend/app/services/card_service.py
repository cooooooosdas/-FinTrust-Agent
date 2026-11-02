"""银行卡服务：卡片查询、虚拟卡申请、冻结/挂失模拟。"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.models import Card, Transaction, utcnow
from app.security.audit import write_audit_log
from app.security.policy import ActionType, RiskLevel, policy_engine
from app.services.account_service import cents_to_yuan, get_account, mask_card_no, yuan_to_cents


def list_cards(db: Session, account_id: int) -> List[Card]:
    from sqlalchemy import select

    return list(
        db.execute(select(Card).where(Card.account_id == account_id).order_by(Card.id)).scalars()
    )


def get_card(db: Session, card_id: int) -> Card:
    card = db.get(Card, card_id)
    if card is None:
        raise NotFoundError(f"银行卡 {card_id} 不存在")
    return card


def apply_virtual_card(
    db: Session,
    *,
    account_id: int,
    card_name: str,
    daily_limit: float,
    expire_month: str,
    confirm: bool = False,
) -> Dict[str, Any]:
    """申请虚拟卡。属于黄色操作，需用户确认后真正发卡。"""
    account = get_account(db, account_id)
    decision = policy_engine.evaluate(ActionType.CARD_APPLY_VIRTUAL)

    if decision.requires_confirmation and not confirm:
        return {
            "status": "awaiting_confirm",
            "risk_level": decision.level.value,
            "risk": {
                "level": decision.level.value,
                "label": decision.level.label,
                "color": decision.level.color,
                "reason": decision.reason,
                "rules": decision.rules,
            },
            "summary": {"卡片名称": card_name, "单日限额": daily_limit, "有效期": expire_month},
            "next_action": "confirm",
            "is_simulated": True,
            "simulation_notice": f"{settings.simulation_tag} · 虚拟卡为本地模拟，不具备真实支付能力",
        }

    limit_cents = yuan_to_cents(daily_limit)
    if limit_cents <= 0:
        raise ValidationError("单日限额必须大于 0")

    card_no = _generate_virtual_card_no()
    card = Card(
        account_id=account.id,
        card_no=card_no,
        card_type="virtual",
        card_name=card_name.strip() or "虚拟卡",
        network="金枢虚拟卡",
        status="active",
        daily_limit_cents=limit_cents,
        expire_month=expire_month,
        is_virtual=True,
        is_simulated=True,
        created_at=utcnow(),
    )
    db.add(card)
    db.commit()
    db.refresh(card)

    write_audit_log(
        db,
        action="card.apply_virtual",
        decision="allow",
        risk_level=decision.level.value,
        reason=decision.reason,
        target_type="card",
        target_id=str(card.id),
        detail={"card_name": card.card_name, "daily_limit": daily_limit},
    )

    return {
        "status": "issued",
        "card": {
            "id": card.id,
            "account_id": card.account_id,
            "card_no": card.card_no,
            "masked_card_no": mask_card_no(card.card_no),
            "card_type": card.card_type,
            "card_name": card.card_name,
            "network": card.network,
            "status": card.status,
            "daily_limit": cents_to_yuan(card.daily_limit_cents),
            "expire_month": card.expire_month,
            "is_virtual": card.is_virtual,
            "is_simulated": card.is_simulated,
            "created_at": card.created_at,
        },
        "risk_level": decision.level.value,
        "is_simulated": True,
        "simulation_notice": f"{settings.simulation_tag} · 虚拟卡为本地模拟，不具备真实支付能力",
    }


def freeze_card(db: Session, *, card_id: int, confirm: bool = False) -> Dict[str, Any]:
    """冻结/解冻卡片（黄色操作）。"""
    card = get_card(db, card_id)
    decision = policy_engine.evaluate(ActionType.CARD_FREEZE)

    if decision.requires_confirmation and not confirm:
        return {
            "status": "awaiting_confirm",
            "risk_level": decision.level.value,
            "risk": {
                "level": decision.level.value,
                "label": decision.level.label,
                "color": decision.level.color,
                "reason": decision.reason,
                "rules": decision.rules,
            },
            "summary": {"卡片": mask_card_no(card.card_no), "当前状态": card.status},
            "next_action": "confirm",
            "is_simulated": True,
            "simulation_notice": f"{settings.simulation_tag}",
        }

    target_status = "active" if card.status == "frozen" else "frozen"
    card.status = target_status
    db.commit()
    db.refresh(card)

    write_audit_log(
        db,
        action="card.freeze" if target_status == "frozen" else "card.unfreeze",
        decision="allow",
        risk_level=decision.level.value,
        reason=decision.reason,
        target_type="card",
        target_id=str(card.id),
        detail={"masked_card_no": mask_card_no(card.card_no), "status": target_status},
    )

    return {
        "status": "updated",
        "card_id": card.id,
        "card_status": card.status,
        "masked_card_no": mask_card_no(card.card_no),
        "risk_level": decision.level.value,
        "is_simulated": True,
        "simulation_notice": f"{settings.simulation_tag}",
    }


def report_card_lost(
    db: Session,
    *,
    card_id: int,
    reason: str = "",
    mfa_code: Optional[str] = None,
    mfa_challenge_id: Optional[str] = None,
    actor: str = "demo-user",
) -> Dict[str, Any]:
    """挂失银行卡（红色操作，必须通过模拟 MFA）。"""
    from app.security.mfa import mfa_service

    card = get_card(db, card_id)
    decision = policy_engine.evaluate(ActionType.CARD_LOST)

    if decision.requires_mfa and not mfa_code:
        # 复用已持久化的挑战，绝不重新发码（保证后续校验可用同一 challenge_id 匹配）
        challenge = mfa_service.get(db, mfa_challenge_id) if mfa_challenge_id else None
        demo_code = None
        if challenge is None:
            view = mfa_service.issue(
                db,
                operation="card_lost",
                account_id=card.account_id,
                target_id=str(card.id),
            )
            challenge = mfa_service.get(db, view.challenge_id)
            demo_code = view.code
        write_audit_log(
            db,
            action="card.lost_mfa_required",
            decision="mfa",
            risk_level=decision.level.value,
            reason=decision.reason,
            actor=actor,
            target_type="card",
            target_id=str(card.id),
            detail={"challenge_id": challenge.challenge_id},
        )
        return {
            "status": "awaiting_mfa",
            "risk_level": decision.level.value,
            "risk": {
                "level": decision.level.value,
                "label": decision.level.label,
                "color": decision.level.color,
                "reason": decision.reason,
                "rules": decision.rules,
            },
            "challenge_id": challenge.challenge_id,
            "demo_code": demo_code,  # 演示模式直接回传验证码
            "expires_in": settings.mfa_ttl_seconds,
            "summary": {"卡片": mask_card_no(card.card_no), "挂失原因": reason or "未填写"},
            "next_action": "mfa",
            "is_simulated": True,
            "simulation_notice": f"{settings.simulation_tag} · 挂失为模拟操作，不会影响任何真实卡片",
        }

    # 校验：必须使用发起时下发的 challenge_id，绝不重新生成验证码
    challenge = mfa_service.get(db, mfa_challenge_id) if mfa_challenge_id else None
    if challenge is None:
        raise ValidationError(
            "验证码不存在或已失效",
            code="MFA_INVALID",
            detail={"card_id": card.id},
        )
    ok, message = mfa_service.verify(
        db,
        challenge.challenge_id,
        mfa_code or "",
        expected_account_id=card.account_id,
        expected_operation="card_lost",
        expected_target_id=str(card.id),
    )
    if not ok:
        write_audit_log(
            db,
            action="card.lost_mfa_failed",
            decision="block",
            risk_level=decision.level.value,
            reason=message,
            actor=actor,
            target_type="card",
            target_id=str(card.id),
        )
        raise ValidationError(message, code="MFA_INVALID", detail={"card_id": card.id})

    card.status = "lost"
    db.commit()
    db.refresh(card)

    write_audit_log(
        db,
        action="card.reported_lost",
        decision="allow",
        risk_level=decision.level.value,
        reason=decision.reason,
        actor=actor,
        target_type="card",
        target_id=str(card.id),
        detail={"masked_card_no": mask_card_no(card.card_no), "reason": reason},
    )

    return {
        "status": "lost",
        "card_id": card.id,
        "card_status": card.status,
        "masked_card_no": mask_card_no(card.card_no),
        "risk_level": decision.level.value,
        "is_simulated": True,
        "simulation_notice": f"{settings.simulation_tag} · 挂失为模拟操作，不会影响任何真实卡片",
    }


def _generate_virtual_card_no() -> str:
    """生成 16 位虚拟卡号（本地模拟，不对应任何真实 BIN）。"""
    return "".join(str(random.randint(0, 9)) for _ in range(16))


def card_transactions(db: Session, card_id: int, limit: int = 20) -> List[Transaction]:
    from sqlalchemy import select

    return list(
        db.execute(
            select(Transaction)
            .where(Transaction.card_id == card_id)
            .order_by(Transaction.occurred_at.desc())
            .limit(limit)
        ).scalars()
    )


__all__ = [
    "list_cards",
    "get_card",
    "apply_virtual_card",
    "freeze_card",
    "report_card_lost",
    "card_transactions",
]
