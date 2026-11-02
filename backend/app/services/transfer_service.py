"""智能转账服务。

执行链路（全部在后端完成）：
    参数校验 → 幂等检查 → 收款人解析 → 策略引擎定级 →
    （黄色：等确认 / 红色：等 MFA）→ 余额校验 → 扣款与入账 → 写审计日志
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import (
    AppError,
    ConfirmationRequiredError,
    MFARequiredError,
    NotFoundError,
    PolicyBlockedError,
    ValidationError,
)
from app.models import Account, Payee, Transaction, TransferOrder, utcnow
from app.security.audit import write_audit_log
from app.security.policy import ActionType, RiskLevel, policy_engine
from app.services.account_service import (
    cents_to_yuan,
    get_account,
    mask_account_no,
    yuan_to_cents,
)

#: 备注中的敏感词（命中则升级为红色）
SENSITIVE_KEYWORDS = ["投资", "理财", "博彩", "赌博", "洗钱", "借款", "还款", "代付", "刷单"]

TRANSFER_ENDPOINT = "POST:/api/v1/transfers/execute"


# ----------------------------------------------------------------------
# 业务时区（日累计以「交易发生日」为准，默认 Asia/Shanghai）
# ----------------------------------------------------------------------
def _business_tz():
    """返回业务时区对象。Windows 无 tzdata 时回退到固定 UTC+8（Asia/Shanghai）。"""
    name = getattr(settings, "business_timezone", "Asia/Shanghai")
    try:
        return ZoneInfo(name)
    except Exception:
        # Asia/Shanghai 固定为 UTC+8，无夏令时
        return timezone(timedelta(hours=8))


def _business_day_window() -> tuple[datetime, datetime]:
    """返回当前业务时区「自然日」在 UTC 下的起止时刻（naive UTC，与库内一致）。"""
    tz = _business_tz()
    now_local = datetime.now(tz)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


# ----------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------
def daily_transfer_total(db: Session, account_id: int) -> int:
    """当日（业务时区自然日）已成功转出的累计金额（分）。"""
    start, end = _business_day_window()
    total = db.execute(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.account_id == account_id,
            Transaction.direction == "expense",
            Transaction.category == "转账支出",
            Transaction.occurred_at >= start,
            Transaction.occurred_at < end,
        )
    ).scalar()
    return int(total or 0)


def resolve_payee(
    db: Session,
    account_id: int,
    *,
    payee_id: Optional[int],
    payee_name: Optional[str],
    payee_account_no: Optional[str],
) -> Tuple[Optional[Payee], str, str]:
    """解析收款人。返回 (payee 记录或 None, 姓名, 账号)。"""
    if payee_id is not None:
        payee = db.get(Payee, payee_id)
        if payee is None:
            raise NotFoundError(f"收款人 {payee_id} 不存在")
        if payee.account_id != account_id:
            raise ValidationError("收款人不属于当前账户")
        return payee, payee.name, payee.account_no

    if payee_account_no:
        payee = db.execute(
            select(Payee)
            .where(
                Payee.account_id == account_id,
                Payee.account_no == payee_account_no,
            )
            .limit(1)
        ).scalars().first()
        if payee is not None:
            return payee, payee.name, payee.account_no
        return None, payee_name or "", payee_account_no

    if payee_name:
        payee = db.execute(
            select(Payee)
            .where(
                Payee.account_id == account_id,
                Payee.name == payee_name,
            )
            .order_by(Payee.total_count.desc())
        ).scalar_one_or_none()
        if payee is not None:
            return payee, payee.name, payee.account_no
        return None, payee_name, ""

    raise ValidationError("请提供收款人 ID、姓名或账号中的至少一项")


def _remark_has_sensitive(remark: str) -> bool:
    return any(word in (remark or "") for word in SENSITIVE_KEYWORDS)


# ----------------------------------------------------------------------
# 预览（不执行任何资金操作）
# ----------------------------------------------------------------------
def preview_transfer(
    db: Session,
    *,
    account_id: int,
    payee_id: Optional[int],
    payee_name: Optional[str],
    payee_account_no: Optional[str],
    amount: float,
    remark: str = "",
) -> Dict[str, Any]:
    """生成转账预览与风险定级，不改动任何资金数据。"""
    account = get_account(db, account_id)
    payee, resolved_name, resolved_no = resolve_payee(
        db, account_id, payee_id=payee_id, payee_name=payee_name, payee_account_no=payee_account_no
    )

    amount_cents = yuan_to_cents(amount)
    if amount_cents <= 0:
        raise ValidationError("转账金额必须大于 0")

    daily_before = daily_transfer_total(db, account_id)

    decision = policy_engine.evaluate(
        ActionType.TRANSFER,
        amount_cents=amount_cents,
        daily_total_cents=daily_before,
        is_frequent_payee=bool(payee and payee.is_frequent),
        is_new_payee=payee is None,
        target_is_self=bool(resolved_no and resolved_no == account.account_no),
        remark_contains_sensitive=_remark_has_sensitive(remark),
    )

    # 创建工单（状态由决策决定）。工单号用 UUID 保证全局唯一，杜绝内存地址冲突。
    order = TransferOrder(
        order_no=f"TR{utcnow().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}",
        idempotency_key="",
        account_id=account_id,
        payee_id=payee.id if payee else None,
        payee_name=resolved_name,
        payee_account_no=resolved_no,
        amount_cents=amount_cents,
        remark=remark,
        risk_level=decision.level.value,
        status=_order_status(decision),
        policy_json=json.dumps(
            {
                "decision": decision.decision,
                "reason": decision.reason,
                "rules": decision.rules,
                "requires_confirmation": decision.requires_confirmation,
                "requires_mfa": decision.requires_mfa,
                "daily_total_before": decision.daily_total_before,
                "daily_total_after": decision.daily_total_after,
            },
            ensure_ascii=False,
        ),
        is_simulated=True,
        expires_at=utcnow() + timedelta(minutes=settings.transfer_order_ttl_minutes),
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    write_audit_log(
        db,
        action="transfer.preview",
        decision=decision.decision,
        risk_level=decision.level.value,
        reason=decision.reason,
        target_type="transfer_order",
        target_id=order.order_no,
        detail={
            "amount": cents_to_yuan(amount_cents),
            "payee": resolved_name,
            "daily_total_before": decision.daily_total_before,
            "daily_total_after": decision.daily_total_after,
            "rules": decision.rules,
        },
    )

    return {
        "order_no": order.order_no,
        "risk_level": decision.level.value,
        "risk": {
            "level": decision.level.value,
            "label": decision.level.label,
            "color": decision.level.color,
            "reason": decision.reason,
            "rules": decision.rules,
        },
        "daily_total_before": decision.daily_total_before,
        "daily_total_after": decision.daily_total_after,
        "daily_limit_remaining": decision.daily_limit_remaining,
        "payee_name": resolved_name,
        "payee_account_no": resolved_no,
        "masked_payee_account_no": mask_account_no(resolved_no) if resolved_no else "未提供",
        "amount": cents_to_yuan(amount_cents),
        "remark": remark,
        "next_action": decision.next_action,
        "requires_confirmation": decision.requires_confirmation,
        "requires_mfa": decision.requires_mfa,
        "is_simulated": True,
        "simulation_notice": f"{settings.simulation_tag} · 本系统不连接任何真实银行账户，资金变动均为本地模拟",
    }


def _order_status(decision) -> str:
    """预览阶段根据决策给定初始状态（七状态机）。"""
    from app.security.order_state import PENDING_CONFIRMATION, PENDING_MFA

    # 阻断的工单直接进入 FAILED（不可执行）
    if decision.blocked:
        return "FAILED"
    if decision.requires_mfa:
        return PENDING_MFA
    # 写操作最低黄色 → 一律等待确认
    return PENDING_CONFIRMATION


# ----------------------------------------------------------------------
# 执行
# ----------------------------------------------------------------------
def execute_transfer(
    db: Session,
    *,
    order_no: str,
    confirm: bool = False,
    mfa_code: Optional[str] = None,
    mfa_challenge_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    actor: str = "system",
    trace_id: str = "",
) -> Dict[str, Any]:
    """执行转账（七状态机）。

    关键安全约束（P0 + P1）：
    1. 执行时**重新**读取账户、重算当日累计、重新调用策略引擎判定，绝不信任快照。
    2. 权限升级时不得扣款，返回 428；反向不降级。
    3. 余额扣减用条件 UPDATE + BEGIN IMMEDIATE 串行化。
    4. 状态经状态机引擎迁移：PENDING_* → EXECUTING → SUCCEEDED/FAILED；
       失败必须独立事务落库（不能随主事务回滚丢失）。
    """
    from app.security.mfa import mfa_service
    from app.security.order_state import (
        EXECUTING,
        FAILED,
        PENDING_CONFIRMATION,
        PENDING_MFA,
        SUCCEEDED,
        is_terminal,
        transition,
    )

    # 使用 IMMEDIATE 事务串行化写路径（SQLite 单写者模型）
    _begin_immediate(db)

    order = db.execute(
        select(TransferOrder).where(TransferOrder.order_no == order_no)
    ).scalar_one_or_none()
    if order is None:
        db.rollback()
        raise NotFoundError(f"转账工单 {order_no} 不存在")

    # ---------- 过期检查（请求触发） ----------
    if order.status in (PENDING_CONFIRMATION, PENDING_MFA):
        if order.expires_at is not None and utcnow() >= order.expires_at:
            transition(
                db, order, "EXPIRED", actor=actor, reason="工单超过有效期，自动过期", trace_id=trace_id, commit=True
            )
            db.rollback()
            raise PolicyBlockedError(
                "该转账工单已过期，无法执行",
                detail={"order_no": order.order_no, "status": "EXPIRED"},
            )

    # ---------- 幂等：已成功则返回首次结果 ----------
    if order.status == SUCCEEDED:
        tx = db.execute(
            select(Transaction).where(
                Transaction.account_id == order.account_id,
                Transaction.remark.like(f"[{order.order_no}]%"),
            )
            .order_by(Transaction.id.desc())
        ).scalars().first()
        account = db.get(Account, order.account_id)
        db.rollback()
        return {
            "order_no": order.order_no,
            "status": SUCCEEDED,
            "transaction_id": tx.id if tx else None,
            "amount": cents_to_yuan(order.amount_cents),
            "payee_name": order.payee_name,
            "balance_after": cents_to_yuan(account.balance_cents if account else 0),
            "is_simulated": True,
            "simulation_notice": f"{settings.simulation_tag} · 该工单已执行过，幂等返回首次结果",
            "message": "该转账已执行（幂等返回）",
        }

    # ---------- 终态拒绝执行 ----------
    if is_terminal(order.status):
        db.rollback()
        raise PolicyBlockedError(
            f"该转账工单当前状态为 {order.status}，无法执行",
            detail={"order_no": order.order_no, "status": order.status},
        )

    if order.status == EXECUTING:
        db.rollback()
        raise AppError(
            "该转账正在执行中，请勿重复提交",
            code="TRANSFER_IN_PROGRESS",
            detail={"order_no": order.order_no},
        )

    # ---------- 执行时重新判定风险（不信任预览快照） ----------
    account = get_account(db, order.account_id)
    daily_before = daily_transfer_total(db, order.account_id)

    payee = db.get(Payee, order.payee_id) if order.payee_id else None
    resolved_no = order.payee_account_no
    decision = policy_engine.evaluate(
        ActionType.TRANSFER,
        amount_cents=order.amount_cents,
        daily_total_cents=daily_before,
        is_frequent_payee=bool(payee and payee.is_frequent),
        is_new_payee=payee is None and bool(resolved_no) and not bool(order.payee_id),
        target_is_self=bool(resolved_no and resolved_no == account.account_no),
        remark_contains_sensitive=_remark_has_sensitive(order.remark),
    )
    risk_level = decision.level.value

    # 读取预览快照的判定，用于「反向不降级」判断
    preview_policy = json.loads(order.policy_json or "{}")
    preview_required_mfa = bool(preview_policy.get("requires_mfa"))

    # 同步工单上的风险等级与策略快照（以执行时判定为准）
    order.risk_level = risk_level
    order.policy_json = json.dumps(
        {
            "decision": decision.decision,
            "reason": decision.reason,
            "rules": decision.rules,
            "requires_confirmation": decision.requires_confirmation,
            "requires_mfa": decision.requires_mfa,
            "daily_total_before": decision.daily_total_before,
            "daily_total_after": decision.daily_total_after,
        },
        ensure_ascii=False,
    )

    # ---------- 阻断：迁移到 FAILED ----------
    if decision.blocked:
        transition(db, order, FAILED, actor=actor, reason=decision.reason, trace_id=trace_id, commit=True)
        db.rollback()
        write_audit_log(
            db,
            action="transfer.policy_blocked",
            decision="block",
            risk_level=risk_level,
            reason=decision.reason,
            actor=actor,
            target_type="transfer_order",
            target_id=order.order_no,
            detail={"rules": decision.rules, "daily_total_after": decision.daily_total_after},
        )
        raise PolicyBlockedError(decision.reason, detail={"order_no": order.order_no, "rules": decision.rules})

    # ---------- 需确认：未确认则拒绝（状态置 PENDING_CONFIRMATION） ----------
    if decision.requires_confirmation and not confirm:
        transition(
            db, order, PENDING_CONFIRMATION, actor=actor, reason="等待用户确认", trace_id=trace_id, commit=True
        )
        db.commit()  # 确保释放 IMMEDIATE 写锁（transition 幂等分支可能未提交）
        raise ConfirmationRequiredError(
            "该操作需要您确认后才会执行",
            detail={
                "order_no": order.order_no,
                "risk_level": risk_level,
                "summary": {
                    "收款人": order.payee_name,
                    "金额": cents_to_yuan(order.amount_cents),
                    "备注": order.remark or "无",
                },
                "rules": decision.rules,
            },
        )

    # ---------- 需 MFA：未通过则拒绝（含执行时升级场景） ----------
    requires_mfa = decision.requires_mfa or preview_required_mfa
    if requires_mfa:
        if not mfa_code:
            transition(db, order, PENDING_MFA, actor=actor, reason="等待多因子验证", trace_id=trace_id, commit=True)
            # 复用已持久化的挑战，绝不重新发码（保证验证码可匹配）
            challenge = mfa_service.get(db, order.mfa_challenge_id) if order.mfa_challenge_id else None
            demo_code = None
            if challenge is None:
                view = mfa_service.issue(
                    db,
                    operation="transfer",
                    account_id=order.account_id,
                    target_id=order.order_no,
                )
                order.mfa_challenge_id = view.challenge_id
                db.commit()
                challenge = mfa_service.get(db, view.challenge_id)
                demo_code = view.code  # 仅演示模式有明文
            write_audit_log(
                db,
                action="transfer.mfa_required",
                decision="mfa",
                risk_level=risk_level,
                reason="高风险操作触发多因子验证",
                actor=actor,
                target_type="transfer_order",
                target_id=order.order_no,
                detail={"amount": cents_to_yuan(order.amount_cents), "challenge_id": challenge.challenge_id},
            )
            raise MFARequiredError(
                "该操作需要通过多因子身份验证",
                detail={
                    "order_no": order.order_no,
                    "risk_level": risk_level,
                    "challenge_id": challenge.challenge_id,
                    "demo_code": demo_code,  # 演示模式直接回传验证码
                    "expires_in": settings.mfa_ttl_seconds,
                    "summary": {
                        "收款人": order.payee_name,
                        "金额": cents_to_yuan(order.amount_cents),
                    },
                },
            )

        # 校验：优先工单持久化的挑战，其次请求携带；绝不重新生成验证码
        challenge_id = order.mfa_challenge_id or mfa_challenge_id
        challenge = mfa_service.get(db, challenge_id) if challenge_id else None
        if challenge is None:
            db.rollback()
            raise MFARequiredError(
                "验证码不存在或已失效",
                detail={"order_no": order.order_no, "challenge_id": challenge_id},
            )
        ok, message = mfa_service.verify(
            db,
            challenge.challenge_id,
            mfa_code,
            expected_account_id=order.account_id,
            expected_operation="transfer",
            expected_target_id=order.order_no,
        )
        if not ok:
            db.rollback()
            write_audit_log(
                db,
                action="transfer.mfa_failed",
                decision="block",
                risk_level=risk_level,
                reason=message,
                actor=actor,
                target_type="transfer_order",
                target_id=order.order_no,
            )
            raise MFARequiredError(message, detail={"order_no": order.order_no, "challenge_id": challenge.challenge_id})

        # MFA 通过，记录时间戳，再次完整重判一次（防止验证窗口内累计又变化）
        order.mfa_verified_at = utcnow()
        daily_before = daily_transfer_total(db, order.account_id)
        decision = policy_engine.evaluate(
            ActionType.TRANSFER,
            amount_cents=order.amount_cents,
            daily_total_cents=daily_before,
            is_frequent_payee=bool(payee and payee.is_frequent),
            is_new_payee=payee is None and bool(resolved_no) and not bool(order.payee_id),
            target_is_self=bool(resolved_no and resolved_no == account.account_no),
            remark_contains_sensitive=_remark_has_sensitive(order.remark),
        )
        risk_level = decision.level.value
        if decision.blocked:
            transition(db, order, FAILED, actor=actor, reason=decision.reason, trace_id=trace_id, commit=True)
            db.rollback()
            raise PolicyBlockedError(decision.reason, detail={"order_no": order.order_no, "rules": decision.rules})
        if decision.requires_confirmation and not confirm:
            transition(
                db, order, PENDING_CONFIRMATION, actor=actor, reason="等待用户确认", trace_id=trace_id, commit=True
            )
            raise ConfirmationRequiredError(
                "该操作需要您确认后才会执行",
                detail={"order_no": order.order_no, "risk_level": risk_level, "rules": decision.rules},
            )

    # ---------- 进入执行中（不 commit，保持 IMMEDIATE 写锁直到扣款完成） ----------
    transition(db, order, EXECUTING, actor=actor, reason="开始执行资金操作", trace_id=trace_id, commit=False)
    order.confirmed = True
    if order.confirmed_at is None:
        order.confirmed_at = utcnow()

    # ---------- 原子扣减余额（条件 UPDATE） ----------
    amount = order.amount_cents
    try:
        result = db.execute(
            update(Account)
            .where(Account.id == account.id, Account.balance_cents >= amount)
            .values(balance_cents=Account.balance_cents - amount)
        )
        if result.rowcount != 1:
            # 先回滚主事务（释放 IMMEDIATE 写锁），再用独立会话落 FAILED
            bal_now = account.balance_cents
            db.rollback()
            _fail_order_in_new_session(order_no, actor, trace_id, "账户可用余额不足")
            raise AppError(
                "账户可用余额不足，转账未执行",
                code="INSUFFICIENT_BALANCE",
                detail={
                    "balance": cents_to_yuan(bal_now),
                    "required": cents_to_yuan(amount),
                },
            )

        # 可用余额同步扣减（不可低于 0）
        db.execute(
            update(Account)
            .where(Account.id == account.id, Account.available_cents >= amount)
            .values(available_cents=Account.available_cents - amount)
        )
        db.expire(account)
        account = get_account(db, order.account_id)

        tx = Transaction(
            account_id=account.id,
            card_id=None,
            direction="expense",
            category="转账支出",
            amount_cents=amount,
            balance_after_cents=account.balance_cents,
            merchant=f"转账至 {order.payee_name or '外部账户'}",
            counterparty=order.payee_name,
            remark=f"[{order.order_no}] {order.remark}".strip(),
            status="success",
            channel="agent",
            is_simulated=True,
            occurred_at=utcnow(),
        )
        db.add(tx)
        db.flush()

        transition(db, order, SUCCEEDED, actor=actor, reason="资金操作完成", trace_id=trace_id, commit=False)
        order.risk_level = risk_level
        if idempotency_key:
            order.idempotency_key = idempotency_key
        # 统一提交：EXECUTING → 扣款 → 流水 → SUCCEEDED 在同一事务内原子完成
        db.commit()
        db.refresh(tx)
        db.refresh(account)
    except AppError:
        raise
    except Exception as exc:  # 任何未预期异常 → FAILED（独立事务落库）
        db.rollback()
        _fail_order_in_new_session(order_no, actor, trace_id, f"执行异常：{exc.__class__.__name__}")
        raise

    # 收款人使用统计
    if order.payee_id:
        payee = db.get(Payee, order.payee_id)
        if payee is not None:
            payee.total_count += 1
            payee.last_used_at = utcnow()
            if payee.total_count >= 3:
                payee.is_frequent = True
            db.commit()

    write_audit_log(
        db,
        action="transfer.executed",
        decision="allow",
        risk_level=risk_level,
        reason=decision.reason,
        actor=actor,
        target_type="transaction",
        target_id=str(tx.id),
        detail={
            "order_no": order.order_no,
            "amount": cents_to_yuan(order.amount_cents),
            "payee": order.payee_name,
            "balance_after": cents_to_yuan(account.balance_cents),
            "is_simulation": True,
            "rules": decision.rules,
        },
    )

    return {
        "order_no": order.order_no,
        "status": SUCCEEDED,
        "transaction_id": tx.id,
        "amount": cents_to_yuan(order.amount_cents),
        "payee_name": order.payee_name,
        "balance_after": cents_to_yuan(account.balance_cents),
        "is_simulated": True,
        "simulation_notice": f"{settings.simulation_tag} · 资金变动仅在本地数据库内模拟，未连接任何真实银行账户",
        "message": f"已{settings.simulation_tag}：向 {order.payee_name} 转账 {cents_to_yuan(order.amount_cents):.2f} 元",
    }


def _fail_order_in_new_session(order_no: str, actor: str, trace_id: str, reason: str) -> None:
    """用独立事务把工单标记为 FAILED，避免主事务回滚导致失败记录丢失。"""
    from app.core.database import SessionLocal

    from app.security.order_state import FAILED, is_terminal, transition

    s = SessionLocal()
    try:
        order = s.execute(
            select(TransferOrder).where(TransferOrder.order_no == order_no)
        ).scalar_one_or_none()
        if order is not None and not is_terminal(order.status):
            order.fail_reason = reason
            transition(s, order, FAILED, actor=actor, reason=reason, trace_id=trace_id, commit=True)
    finally:
        s.close()


def _begin_immediate(db: Session) -> None:
    """对 SQLite 显式开启 IMMEDIATE 事务，串行化并发写操作。

    SQLAlchemy 的 ORM session 默认 ``autobegin`` 会在第一次访问时自动开启
    ``BEGIN``（DEFERRED），手动执行 ``BEGIN IMMEDIATE`` 会被忽略。因此这里先
    回滚掉自动开启的事务，再在**底层连接**上显式 ``BEGIN IMMEDIATE``，让本事务
    从一开始就持有写锁，其他并发写事务会被阻塞，直到提交/回滚。
    """
    if not settings.database_url.startswith("sqlite"):
        return
    try:
        # 结束 autobegin 的隐式事务，避免嵌套
        if db.in_transaction():
            db.rollback()
        conn = db.connection()
        conn.exec_driver_sql("BEGIN IMMEDIATE")
    except Exception:
        # 已持有锁或驱动不支持时忽略，交由条件 UPDATE 兜底
        pass


def get_transfer_order(db: Session, order_no: str) -> TransferOrder:
    order = db.execute(
        select(TransferOrder).where(TransferOrder.order_no == order_no)
    ).scalar_one_or_none()
    if order is None:
        raise NotFoundError(f"转账工单 {order_no} 不存在")
    return order


def cancel_transfer(db: Session, order_no: str, *, actor: str = "system", trace_id: str = "") -> Dict[str, Any]:
    """用户主动取消转账工单。终态不可取消；取消后禁止执行。"""
    from app.security.order_state import CANCELLED, PENDING_CONFIRMATION, PENDING_MFA, is_terminal, transition

    order = db.execute(
        select(TransferOrder).where(TransferOrder.order_no == order_no)
    ).scalar_one_or_none()
    if order is None:
        raise NotFoundError(f"转账工单 {order_no} 不存在")

    if is_terminal(order.status):
        raise PolicyBlockedError(
            f"该转账工单当前状态为 {order.status}，无法取消",
            detail={"order_no": order.order_no, "status": order.status},
        )

    if order.status not in (PENDING_CONFIRMATION, PENDING_MFA):
        raise PolicyBlockedError(
            f"该转账工单当前状态为 {order.status}，仅待确认/待验证状态可取消",
            detail={"order_no": order.order_no, "status": order.status},
        )

    transition(db, order, CANCELLED, actor=actor, reason="用户主动取消", trace_id=trace_id, commit=True)
    write_audit_log(
        db,
        action="transfer.cancelled",
        decision="block",
        risk_level=order.risk_level,
        reason="用户主动取消转账",
        actor=actor,
        target_type="transfer_order",
        target_id=order.order_no,
        detail={"amount": cents_to_yuan(order.amount_cents), "payee": order.payee_name},
    )
    return {
        "order_no": order.order_no,
        "status": CANCELLED,
        "amount": cents_to_yuan(order.amount_cents),
        "payee_name": order.payee_name,
        "is_simulated": True,
        "message": "转账已取消",
    }


def expire_stale_orders(db: Session, *, actor: str = "system", trace_id: str = "") -> int:
    """批量过期清理（应用启动时调用）：把超过 expires_at 的待处理工单迁移为 EXPIRED。"""
    from app.security.order_state import EXPIRED, PENDING_CONFIRMATION, PENDING_MFA, transition

    now = utcnow()
    stale = db.execute(
        select(TransferOrder).where(
            TransferOrder.status.in_([PENDING_CONFIRMATION, PENDING_MFA]),
            TransferOrder.expires_at.isnot(None),
            TransferOrder.expires_at < now,
        )
    ).scalars().all()
    count = 0
    for order in stale:
        transition(db, order, EXPIRED, actor=actor, reason="工单超时自动过期", trace_id=trace_id, commit=False)
        count += 1
    if count:
        db.commit()
    return count


def policy_info() -> Dict[str, Any]:
    """向前端公开的三级权限策略说明（只读）。"""
    t = policy_engine.describe_thresholds()
    return {
        "yellow_single_max": t["yellow_single_max"],
        "red_single_min": t["red_single_min"],
        "red_daily_total": t["red_daily_total"],
        "yellow_daily_max": t["yellow_daily_max"],
        "red_daily_min": t["red_daily_min"],
        "levels": [
            {
                "level": "green",
                "label": "绿色 · 自动执行",
                "color": "emerald",
                "reason": "余额查询、交易查询、账单分析等纯只读操作，系统直接执行并记录审计日志。",
                "rules": [
                    "余额查询 / 交易记录查询 / 账单分析 / 理财收益查询等只读操作",
                    "任何资金写操作都不会获得绿色权限",
                ],
            },
            {
                "level": "yellow",
                "label": "黄色 · 需用户确认",
                "color": "amber",
                "reason": "写操作中的普通小额转账，执行后当日累计 ≤ 1000 元，须展示详情并取得明确确认。",
                "rules": [
                    f"执行后当日累计转账 ≤ {t['yellow_daily_max']:.2f} 元",
                    "虚拟卡申请、卡片冻结等写操作",
                ],
            },
            {
                "level": "red",
                "label": "红色 · 需多因子验证",
                "color": "rose",
                "reason": "执行后当日累计 > 1000 元，以及银行卡挂失、密码修改等敏感操作，必须通过模拟 MFA。",
                "rules": [
                    f"执行后当日累计转账 > {t['red_daily_min']:.2f} 元",
                    f"单笔 ≥ {t['red_single_min']:.2f} 元（辅助升红）",
                    "银行卡挂失、密码修改等敏感操作",
                    "备注命中敏感词",
                ],
            },
        ],
    }


__all__ = [
    "preview_transfer",
    "execute_transfer",
    "cancel_transfer",
    "expire_stale_orders",
    "daily_transfer_total",
    "resolve_payee",
    "get_transfer_order",
    "policy_info",
    "SENSITIVE_KEYWORDS",
]
