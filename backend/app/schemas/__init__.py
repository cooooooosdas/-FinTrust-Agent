"""Pydantic 请求 / 响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ============================ 账户 ============================
class AccountSummary(ApiModel):
    id: int
    account_no: str
    holder_name: str
    account_type: str
    bank_name: str
    currency: str
    balance: float
    available: float
    status: str
    card_count: int = 0
    created_at: datetime


class OverviewResponse(ApiModel):
    account: AccountSummary
    cards: List["CardOut"]
    recent_transactions: List["TransactionOut"]
    stats: "SpendingStats"
    payees: List["PayeeOut"]
    simulation_notice: str


# ============================ 银行卡 ============================
class CardOut(ApiModel):
    id: int
    account_id: int
    card_no: str
    masked_card_no: str
    card_type: str
    card_name: str
    network: str
    status: str
    daily_limit: float
    expire_month: str
    is_virtual: bool
    is_simulated: bool
    created_at: datetime


class VirtualCardApplyRequest(ApiModel):
    card_name: str = Field(..., min_length=1, max_length=32, description="虚拟卡用途名称")
    daily_limit: float = Field(default=5000.0, ge=100.0, le=100000.0, description="单日限额(元)")
    expire_month: str = Field(default="2029/12", description="有效期")


class CardLossRequest(ApiModel):
    card_id: int
    reason: str = Field(default="", max_length=200)


# ============================ 交易 ============================
class TransactionOut(ApiModel):
    id: int
    account_id: int
    card_id: Optional[int]
    direction: str
    category: str
    amount: float
    balance_after: float
    merchant: str
    counterparty: str
    remark: str
    status: str
    channel: str
    is_simulated: bool
    occurred_at: datetime


class TransactionQuery(ApiModel):
    account_id: int
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    category: Optional[str] = None
    direction: Optional[str] = None
    keyword: Optional[str] = None
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None
    page: int = 1
    page_size: int = 20


class TransactionPage(ApiModel):
    items: List[TransactionOut]
    total: int
    page: int
    page_size: int
    total_amount: float


class CategoryBreakdown(ApiModel):
    category: str
    amount: float
    count: int
    ratio: float


class SpendingStats(ApiModel):
    month: str
    total_expense: float
    total_income: float
    transaction_count: int
    daily_average: float
    max_single: float
    categories: List[CategoryBreakdown]
    trend: List["MonthlyTrend"]
    anomalies: List["AnomalyItem"]


class MonthlyTrend(ApiModel):
    month: str
    expense: float
    income: float


class AnomalyItem(ApiModel):
    transaction_id: int
    occurred_at: datetime
    merchant: str
    category: str
    amount: float
    direction: str
    score: float
    reason: str


# ============================ 收款人 ============================
class PayeeOut(ApiModel):
    id: int
    account_id: int
    name: str
    account_no: str
    masked_account_no: str
    bank_name: str
    card_last4: str
    is_frequent: bool
    single_limit: float
    total_count: int
    last_used_at: Optional[datetime]
    created_at: datetime


class PayeeCreateRequest(ApiModel):
    account_id: int
    name: str = Field(..., min_length=1, max_length=32)
    account_no: str = Field(..., min_length=8, max_length=32)
    bank_name: str = Field(default="金枢银行", max_length=32)
    card_last4: str = Field(default="", max_length=4)


# ============================ 转账 ============================
class TransferRequest(ApiModel):
    account_id: int
    payee_id: Optional[int] = None
    payee_name: Optional[str] = None
    payee_account_no: Optional[str] = None
    amount: float = Field(..., gt=0, le=10000000)
    remark: str = Field(default="", max_length=100)
    idempotency_key: Optional[str] = Field(default=None, max_length=128)


class TransferPreviewRequest(ApiModel):
    account_id: int
    payee_id: Optional[int] = None
    payee_name: Optional[str] = None
    payee_account_no: Optional[str] = None
    amount: float = Field(..., gt=0, le=10000000)
    remark: str = Field(default="", max_length=100)


class RiskLevelInfo(ApiModel):
    level: str
    label: str
    color: str
    reason: str
    rules: List[str]


class TransferPreview(ApiModel):
    order_no: str
    risk_level: str
    risk: RiskLevelInfo
    daily_total_before: float
    daily_total_after: float
    daily_limit_remaining: float
    payee_name: str
    payee_account_no: str
    masked_payee_account_no: str
    amount: float
    remark: str
    next_action: str
    requires_confirmation: bool
    requires_mfa: bool
    is_simulated: bool
    simulation_notice: str


class TransferExecuteRequest(ApiModel):
    order_no: str
    confirm: bool = False
    mfa_code: Optional[str] = None
    mfa_challenge_id: Optional[str] = None


class TransferResult(ApiModel):
    order_no: str
    status: str
    transaction_id: Optional[int]
    amount: float
    payee_name: str
    balance_after: float
    is_simulated: bool
    simulation_notice: str
    message: str


class TransferPolicyInfo(ApiModel):
    yellow_single_max: float
    red_single_min: float
    red_daily_total: float
    yellow_daily_max: float
    red_daily_min: float = 0.0
    levels: List[RiskLevelInfo]


# ============================ 审计 ============================
class AuditLogOut(ApiModel):
    id: int
    actor: str
    action: str
    target_type: str
    target_id: str
    risk_level: str
    decision: str
    reason: str
    detail: Dict[str, Any]
    ip_address: str
    is_simulation: bool
    created_at: datetime


class AuditQuery(ApiModel):
    risk_level: Optional[str] = None
    action: Optional[str] = None
    page: int = 1
    page_size: int = 20


class AuditPage(ApiModel):
    items: List[AuditLogOut]
    total: int
    page: int
    page_size: int
    summary: Dict[str, Any]


# ============================ Agent ============================
class AgentChatRequest(ApiModel):
    session_id: Optional[str] = None
    message: str = Field(..., min_length=1, max_length=1000)
    account_id: int = 1


class TraceStep(ApiModel):
    step: int
    node: str
    title: str
    status: str
    detail: str = ""
    duration_ms: int = 0
    payload: Dict[str, Any] = Field(default_factory=dict)


class AgentActionCard(ApiModel):
    kind: str
    title: str
    fields: Dict[str, Any] = Field(default_factory=dict)


class AgentResponse(ApiModel):
    session_id: str
    message_id: int
    reply: str
    intent: str
    intent_label: str
    confidence: float
    risk_level: str
    demo_mode: bool
    demo_mode_notice: str
    trace: List[TraceStep]
    actions: List[AgentActionCard]
    data: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AgentSessionOut(ApiModel):
    session_id: str
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class AgentMessageOut(ApiModel):
    id: int
    role: str
    content: str
    intent: str
    risk_level: str
    demo_mode: bool
    trace: List[TraceStep]
    created_at: datetime


class AgentSessionDetail(ApiModel):
    session: AgentSessionOut
    messages: List[AgentMessageOut]


# ============================ 系统 ============================
class HealthResponse(ApiModel):
    status: str
    app: str
    version: str
    environment: str
    demo_mode: bool
    demo_mode_notice: str
    llm_configured: bool
    database: str
    time: datetime


OverviewResponse.model_rebuild()
SpendingStats.model_rebuild()
