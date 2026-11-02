"""转账路由。

权限判定全部在后端完成：前端无法通过隐藏按钮绕过任何策略。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, db_session
from app.core.config import settings
from app.core.errors import AppError
from app.models import User
from app.schemas import (
    TransferExecuteRequest,
    TransferPolicyInfo,
    TransferPreview,
    TransferPreviewRequest,
    TransferResult,
)
from app.security.idempotency import idempotency_store
from app.services import auth_service, transfer_service

router = APIRouter(prefix="/transfers", tags=["transfers"])

EXECUTE_ENDPOINT = "POST:/api/v1/transfers/execute"


@router.get("/policy", response_model=TransferPolicyInfo, summary="三级权限策略说明")
def get_policy() -> TransferPolicyInfo:
    info = transfer_service.policy_info()
    return TransferPolicyInfo(**info)


@router.get("/daily-total", summary="当日累计转出金额")
def daily_total(
    db: Session = Depends(db_session),
    account_id: int = Query(default=1),
    user: User = Depends(current_user),
) -> dict:
    auth_service.ensure_account_access(db, user, account_id)
    total_cents = transfer_service.daily_transfer_total(db, account_id)
    thresholds = transfer_service.policy_engine.describe_thresholds()
    return {
        "daily_total": round(total_cents / 100, 2),
        "yellow_single_max": thresholds["yellow_single_max"],
        "red_single_min": thresholds["red_single_min"],
        "red_daily_total": thresholds["red_daily_total"],
        "yellow_daily_max": thresholds["yellow_daily_max"],
    }


@router.post("/preview", response_model=TransferPreview, summary="转账预览与风险定级")
def preview(
    payload: TransferPreviewRequest,
    request: Request,
    db: Session = Depends(db_session),
    user: User = Depends(current_user),
) -> TransferPreview:
    from app.security.rate_limiter import check_and_increment

    auth_service.ensure_account_access(db, user, payload.account_id)
    check_and_increment(
        db, scope="transfer_preview", identifier=f"account:{payload.account_id}",
        limit=settings.rate_limit_transfer_preview_per_minute, window_seconds=60,
    )
    result = transfer_service.preview_transfer(
        db,
        account_id=payload.account_id,
        payee_id=payload.payee_id,
        payee_name=payload.payee_name,
        payee_account_no=payload.payee_account_no,
        amount=payload.amount,
        remark=payload.remark,
    )
    return TransferPreview(**result)


@router.post("/execute", response_model=TransferResult, summary="执行转账")
def execute(
    payload: TransferExecuteRequest,
    request: Request,
    db: Session = Depends(db_session),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(current_user),
) -> TransferResult:
    """执行转账。

    - 黄色：必须带 ``confirm=true``，否则返回 409 CONFIRMATION_REQUIRED；
    - 红色：必须带正确的 ``mfa_code``，否则返回 428 MFA_REQUIRED。
    """
    # 校验工单归属：工单账户必须属于当前用户
    order = transfer_service.get_transfer_order(db, payload.order_no)
    auth_service.ensure_account_access(db, user, order.account_id)

    from app.security.rate_limiter import check_and_increment

    check_and_increment(
        db, scope="transfer_execute", identifier=f"account:{order.account_id}",
        limit=settings.rate_limit_transfer_execute_per_minute, window_seconds=60,
    )

    key = idempotency_key or payload.order_no
    payload_hash = {
        "order_no": payload.order_no,
        "confirm": payload.confirm,
        "mfa_code": "***" if payload.mfa_code else None,
    }

    cached = idempotency_store.begin(key, EXECUTE_ENDPOINT, payload_hash)
    if cached is not None:
        if cached.get("in_progress"):
            raise AppError("同一请求正在处理中，请稍候再试", code="IDEMPOTENCY_IN_PROGRESS")
        return TransferResult(**cached)

    try:
        result = transfer_service.execute_transfer(
            db,
            order_no=payload.order_no,
            confirm=payload.confirm,
            mfa_code=payload.mfa_code,
            mfa_challenge_id=payload.mfa_challenge_id,
            idempotency_key=key,
            actor=user.username,
            trace_id=_trace_id(request),
        )
    except Exception:
        idempotency_store.fail(key, EXECUTE_ENDPOINT)
        raise

    idempotency_store.complete(key, EXECUTE_ENDPOINT, result)
    return TransferResult(**result)


@router.post("/{order_no}/cancel", summary="取消转账工单")
def cancel_order(
    order_no: str,
    request: Request,
    db: Session = Depends(db_session),
    user: User = Depends(current_user),
) -> dict:
    """用户主动取消待确认/待验证的转账工单。终态不可取消。"""
    order = transfer_service.get_transfer_order(db, order_no)
    auth_service.ensure_account_access(db, user, order.account_id)
    return transfer_service.cancel_transfer(
        db,
        order_no,
        actor=user.username,
        trace_id=_trace_id(request),
    )


@router.get("/{order_no}/transitions", summary="查询工单状态迁移记录")
def order_transitions(
    order_no: str,
    db: Session = Depends(db_session),
    user: User = Depends(current_user),
) -> dict:
    """返回工单的状态迁移审计记录（只追加，不可覆盖）。"""
    from app.models import OrderStatusTransition

    order = transfer_service.get_transfer_order(db, order_no)
    auth_service.ensure_account_access(db, user, order.account_id)

    rows = db.execute(
        select(OrderStatusTransition)
        .where(OrderStatusTransition.order_no == order_no)
        .order_by(OrderStatusTransition.id)
    ).scalars().all()
    return {
        "order_no": order_no,
        "transitions": [
            {
                "from_status": t.from_status,
                "to_status": t.to_status,
                "actor": t.actor,
                "reason": t.reason,
                "trace_id": t.trace_id,
                "created_at": t.created_at,
            }
            for t in rows
        ],
    }


def _trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", "")
