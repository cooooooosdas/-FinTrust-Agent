"""ORM 数据模型。

金额统一使用 **整数分**（*_cents）存储与计算，杜绝浮点精度误差。
所有资金相关记录都带 `is_simulated` 标记，演示环境下的交易一律为 True。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    """统一使用 UTC naive 时间，SQLite 兼容性最好。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Account(Base):
    """银行账户。"""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    holder_name: Mapped[str] = mapped_column(String(64), index=True)
    account_type: Mapped[str] = mapped_column(String(16), default="deposit")  # deposit / credit
    bank_name: Mapped[str] = mapped_column(String(64), default="金枢银行")
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    balance_cents: Mapped[int] = mapped_column(Integer, default=0)
    available_cents: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active / frozen
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    cards: Mapped[list["Card"]] = relationship(back_populates="account", cascade="all, delete-orphan")
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )
    payees: Mapped[list["Payee"]] = relationship(back_populates="account", cascade="all, delete-orphan")


class Card(Base):
    """银行卡（含虚拟卡）。"""

    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    card_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    card_type: Mapped[str] = mapped_column(String(16), default="debit")  # debit / credit / virtual
    card_name: Mapped[str] = mapped_column(String(64), default="")
    network: Mapped[str] = mapped_column(String(16), default="银联")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active / frozen / lost
    daily_limit_cents: Mapped[int] = mapped_column(Integer, default=10000000)
    expire_month: Mapped[str] = mapped_column(String(8), default="")
    is_virtual: Mapped[bool] = mapped_column(Boolean, default=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    account: Mapped["Account"] = relationship(back_populates="cards")


class Transaction(Base):
    """交易流水。"""

    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_tx_account_time", "account_id", "occurred_at"),
        Index("ix_tx_category_time", "category", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    card_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("cards.id", ondelete="SET NULL"), nullable=True, index=True
    )
    direction: Mapped[str] = mapped_column(String(8), index=True)  # income / expense
    category: Mapped[str] = mapped_column(String(32), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    balance_after_cents: Mapped[int] = mapped_column(Integer, default=0)
    merchant: Mapped[str] = mapped_column(String(128), default="")
    counterparty: Mapped[str] = mapped_column(String(128), default="")
    remark: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(16), default="success")
    channel: Mapped[str] = mapped_column(String(16), default="mobile")
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    account: Mapped["Account"] = relationship(back_populates="transactions")


class Payee(Base):
    """收款人（常用联系人）。"""

    __tablename__ = "payees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    account_no: Mapped[str] = mapped_column(String(32), index=True)
    bank_name: Mapped[str] = mapped_column(String(64), default="")
    card_last4: Mapped[str] = mapped_column(String(8), default="")
    is_frequent: Mapped[bool] = mapped_column(Boolean, default=False)
    single_limit_cents: Mapped[int] = mapped_column(Integer, default=10000000)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    account: Mapped["Account"] = relationship(back_populates="payees")


class AuditLog(Base):
    """安全审计日志（只追加，不允许修改）。

    完整性哈希链（P2-T3）：
        event_hash = HMAC(密钥, previous_hash + 规范化内容)
    迁移前的历史记录 sequence_id 为 NULL（未签名）。
    """

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_time", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(64), default="demo-user")
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(32), default="")
    target_id: Mapped[str] = mapped_column(String(64), default="")
    risk_level: Mapped[str] = mapped_column(String(8), default="green")  # green / yellow / red
    decision: Mapped[str] = mapped_column(String(24), default="allow")  # allow / confirm / mfa / block
    reason: Mapped[str] = mapped_column(Text, default="")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    ip_address: Mapped[str] = mapped_column(String(64), default="127.0.0.1")
    is_simulation: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    # 完整性哈希链字段
    sequence_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, unique=True)
    previous_hash: Mapped[str] = mapped_column(String(64), default="")
    event_hash: Mapped[str] = mapped_column(String(64), default="")
    integrity_version: Mapped[int] = mapped_column(Integer, default=1)


class AgentSession(Base):
    """AI 会话。"""

    __tablename__ = "agent_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(128), default="新的对话")
    account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    messages: Mapped[list["AgentMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class AgentMessage(Base):
    """AI 消息（含意图、风险等级与执行轨迹）。"""

    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user / assistant / system
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(48), default="")
    confidence: Mapped[float] = mapped_column(default=0.0)
    risk_level: Mapped[str] = mapped_column(String(8), default="green")
    trace_json: Mapped[str] = mapped_column(Text, default="[]")
    demo_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    session: Mapped["AgentSession"] = relationship(back_populates="messages")


class IdempotencyRecord(Base):
    """幂等控制记录。"""

    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("key", "endpoint", name="uq_idem_key_endpoint"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), index=True)
    endpoint: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(16), default="in_progress")  # in_progress / done
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TransferOrder(Base):
    """转账工单（七状态生命周期）。

    状态机（P1-T1）：
        PENDING_CONFIRMATION / PENDING_MFA / EXECUTING /
        SUCCEEDED / FAILED / CANCELLED / EXPIRED
    终态：SUCCEEDED / FAILED / CANCELLED / EXPIRED
    """

    __tablename__ = "transfer_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    payee_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("payees.id", ondelete="SET NULL"), nullable=True
    )
    payee_name: Mapped[str] = mapped_column(String(64), default="")
    payee_account_no: Mapped[str] = mapped_column(String(32), default="")
    amount_cents: Mapped[int] = mapped_column(Integer)
    remark: Mapped[str] = mapped_column(String(256), default="")
    risk_level: Mapped[str] = mapped_column(String(8), default="green")
    status: Mapped[str] = mapped_column(String(24), default="PENDING_CONFIRMATION", index=True)
    policy_json: Mapped[str] = mapped_column(Text, default="{}")
    mfa_code: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    mfa_challenge_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    fail_reason: Mapped[str] = mapped_column(String(256), default="")
    version: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    mfa_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    executing_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expired_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class OrderStatusTransition(Base):
    """交易状态迁移审计（只追加，不可覆盖历史）。"""

    __tablename__ = "order_status_transitions"
    __table_args__ = (Index("ix_ost_order", "order_no", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_no: Mapped[str] = mapped_column(String(64), index=True)
    from_status: Mapped[str] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24))
    actor: Mapped[str] = mapped_column(String(64), default="system")
    reason: Mapped[str] = mapped_column(String(256), default="")
    trace_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class User(Base):
    """认证用户。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16), default="active")  # active / disabled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class UserAccount(Base):
    """用户与账户的授权关系（一个用户只能访问被授权的账户）。"""

    __tablename__ = "user_accounts"
    __table_args__ = (UniqueConstraint("user_id", "account_id", name="uq_user_account"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    permission: Mapped[str] = mapped_column(String(16), default="owner")  # owner / viewer
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Session(Base):
    """认证会话（服务端仅存 Token 哈希）。"""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class MfaChallenge(Base):
    """持久化 MFA 挑战（验证码仅存 HMAC 摘要，不存明文）。"""

    __tablename__ = "mfa_challenges"
    __table_args__ = (Index("ix_mfa_challenge_id", "challenge_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    challenge_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True
    )
    operation: Mapped[str] = mapped_column(String(48), index=True)
    target_id: Mapped[str] = mapped_column(String(64), default="")
    code_hash: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    attempts_remaining: Mapped[int] = mapped_column(Integer, default=5)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending / consumed / expired / locked


class RateLimitRecord(Base):
    """请求限流计数（窗口计数器，键 HMAC 脱敏）。"""

    __tablename__ = "rate_limit_records"
    __table_args__ = (
        UniqueConstraint("key", "window_start", name="uq_rate_limit_key_window"),
        Index("ix_rate_limit_key", "key", "window_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128))  # HMAC 脱敏后的限流键
    window_start: Mapped[int] = mapped_column(Integer)  # 窗口起始（Unix 秒）
    count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


__all__ = [
    "Account",
    "Card",
    "Transaction",
    "Payee",
    "AuditLog",
    "AgentSession",
    "AgentMessage",
    "IdempotencyRecord",
    "TransferOrder",
    "OrderStatusTransition",
    "User",
    "UserAccount",
    "Session",
    "MfaChallenge",
    "RateLimitRecord",
    "utcnow",
]
