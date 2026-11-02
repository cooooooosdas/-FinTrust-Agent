"""Agent 工具注册表。

每个工具都是一个纯函数 `(db, args, ctx) -> ToolResult`，
负责调用真实的业务服务，绝不直接拼接 SQL 或伪造数据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.security.policy import ActionType, policy_engine
from app.services import analytics_service, card_service, transfer_service
from app.services.account_service import (
    cents_to_yuan,
    list_cards,
    list_payees,
    mask_card_no,
    recent_transactions,
)


@dataclass
class ToolResult:
    """工具执行结果。"""

    data: Dict[str, Any] = field(default_factory=dict)
    detail: str = ""
    actions: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class ToolMeta:
    """工具安全元数据。"""

    name: str
    description: str = ""
    action_type: str = ""  # 对应 ActionType；空表示只读查询
    permission_level: str = "green"  # green / yellow / red
    requires_confirmation: bool = False
    requires_mfa: bool = False
    write: bool = False


ToolFn = Callable[[Session, Dict[str, Any], Dict[str, Any]], ToolResult]
_REGISTRY: Dict[str, ToolFn] = {}
_TOOL_META: Dict[str, ToolMeta] = {}


def tool(name: str, *, meta: Optional[ToolMeta] = None) -> Callable[[ToolFn], ToolFn]:
    def decorator(fn: ToolFn) -> ToolFn:
        _REGISTRY[name] = fn
        _TOOL_META[name] = meta or ToolMeta(name=name)
        return fn

    return decorator


def get_tool(name: str) -> Optional[ToolFn]:
    return _REGISTRY.get(name)


def get_tool_meta(name: str) -> Optional[ToolMeta]:
    return _TOOL_META.get(name)


def list_tools() -> List[str]:
    return sorted(_REGISTRY.keys())


def _assert_account_authorized(ctx: Dict[str, Any], account_id: int) -> None:
    """工具层账户归属校验（纵深防御）：account_id 必须来自认证上下文授权集合。

    LLM 无法通过 slots 伪造 account_id，因为本校验以 ctx["auth"] 为准。
    """
    auth = ctx.get("auth", {})
    allowed = auth.get("authorized_account_ids") or []
    if allowed and account_id not in allowed:
        raise PermissionError(f"无权访问账户 {account_id}（工具层账户归属校验）")


# ======================================================================
# 转账链路
# ======================================================================
@tool("resolve_payee")
def _resolve_payee(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    slots = ctx.get("slots", {})
    try:
        payee, name, account_no = transfer_service.resolve_payee(
            db,
            args["account_id"],
            payee_id=slots.get("payee_id"),
            payee_name=slots.get("payee_name"),
            payee_account_no=slots.get("payee_account_no"),
        )
    except Exception as exc:
        return ToolResult(error=str(exc))

    ctx["payee"] = {
        "id": payee.id if payee else None,
        "name": name,
        "account_no": account_no,
        "is_frequent": bool(payee.is_frequent) if payee else False,
        "is_new": payee is None,
        "total_count": payee.total_count if payee else 0,
    }
    label = name or "未指定收款人"
    return ToolResult(
        data=ctx["payee"],
        detail=(
            f"匹配到收款人「{label}」"
            + (f"，历史转账 {payee.total_count} 次" if payee else "，未在常用收款人中找到（按新收款人处理）")
        ),
    )


@tool("daily_total")
def _daily_total(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    total = transfer_service.daily_transfer_total(db, args["account_id"])
    ctx["daily_total_cents"] = total
    limit = policy_engine.describe_thresholds()["red_daily_total"]
    return ToolResult(
        data={"daily_total": cents_to_yuan(total), "red_daily_total": limit},
        detail=f"当日已转出 {cents_to_yuan(total):.2f} 元，风控红线 {limit:.2f} 元",
    )


@tool("evaluate_policy")
def _evaluate_policy(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    slots = ctx.get("slots", {})
    action = ActionType(args.get("action") or "transfer")
    payee = ctx.get("payee", {})
    decision = policy_engine.evaluate(
        action,
        amount_cents=int(round(float(slots.get("amount") or 0) * 100)),
        daily_total_cents=ctx.get("daily_total_cents", 0),
        is_frequent_payee=bool(payee.get("is_frequent")),
        is_new_payee=bool(payee.get("is_new")),
        target_is_self=bool(payee.get("account_no") and payee.get("account_no") == ctx.get("self_account_no")),
        remark_contains_sensitive=transfer_service._remark_has_sensitive(slots.get("remark", "")),
    )
    ctx["policy"] = {
        "level": decision.level.value,
        "label": decision.level.label,
        "color": decision.level.color,
        "reason": decision.reason,
        "rules": decision.rules,
        "requires_confirmation": decision.requires_confirmation,
        "requires_mfa": decision.requires_mfa,
        "blocked": decision.blocked,
        "decision": decision.decision,
        "daily_total_before": decision.daily_total_before,
        "daily_total_after": decision.daily_total_after,
        "daily_limit_remaining": decision.daily_limit_remaining,
    }
    return ToolResult(
        data=ctx["policy"],
        detail=f"权限判定：{decision.level.label} —— {decision.reason}",
    )


@tool("prepare_transfer")
def _prepare_transfer(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    slots = ctx.get("slots", {})
    payee = ctx.get("payee", {})
    policy = ctx.get("policy", {})

    # 工具层账户归属校验（纵深防御）：不接受 LLM 伪造的 account_id
    _assert_account_authorized(ctx, args.get("account_id", 0))

    if not slots.get("amount"):
        return ToolResult(
            error="未识别到转账金额",
            detail="请在指令中说明金额，例如「给张三转 500 元，备注还房贷」",
        )
    if not payee.get("name") and not payee.get("account_no"):
        return ToolResult(
            error="未识别到收款人",
            detail="请在指令中说明收款人，例如「给张三转 500 元」",
        )

    amount = float(slots["amount"])
    preview = transfer_service.preview_transfer(
        db,
        account_id=args["account_id"],
        payee_id=payee.get("id"),
        payee_name=payee.get("name"),
        payee_account_no=payee.get("account_no"),
        amount=amount,
        remark=slots.get("remark", ""),
    )
    ctx["transfer_preview"] = preview

    actions: List[Dict[str, Any]] = [
        {
            "kind": "transfer_preview",
            "title": "转账方案",
            "fields": {
                "工单号": preview["order_no"],
                "收款人": preview["payee_name"],
                "收款账号": preview["masked_payee_account_no"],
                "金额": f"¥ {preview['amount']:.2f}",
                "备注": preview["remark"] or "无",
                "权限等级": preview["risk"]["label"],
                "当日累计": f"¥ {preview['daily_total_after']:.2f}",
            },
        }
    ]
    return ToolResult(
        data=preview,
        detail=(
            f"已生成转账工单 {preview['order_no']}：向 {preview['payee_name']} 转账 "
            f"{preview['amount']:.2f} 元，权限等级 {preview['risk']['label']}"
        ),
        actions=actions,
    )


# ======================================================================
# 账单分析链路
# ======================================================================
@tool("fetch_transactions")
def _fetch_transactions(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    slots = ctx.get("slots", {})
    period = slots.get("period")
    start = end = None
    if period == "last_month":
        start, end = analytics_service._month_range(
            analytics_service._month_shift(analytics_service.current_month_str(), -1)
        )
    elif period == "recent_7d":
        from datetime import timedelta

        from app.models import utcnow

        end = utcnow()
        start = end - timedelta(days=7)

    transactions = analytics_service.fetch_transactions(
        db,
        args["account_id"],
        start=start,
        end=end,
        category=slots.get("category"),
        direction=slots.get("direction"),
    )
    ctx["transactions"] = transactions
    total = sum(t.amount_cents for t in transactions if t.direction == "expense")
    return ToolResult(
        data={"count": len(transactions), "expense": cents_to_yuan(total)},
        detail=f"命中 {len(transactions)} 条流水，支出合计 {cents_to_yuan(total):.2f} 元",
    )


@tool("aggregate_categories")
def _aggregate_categories(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    transactions = ctx.get("transactions", [])
    breakdown = analytics_service.category_breakdown(transactions)
    ctx["categories"] = breakdown
    top = breakdown[0] if breakdown else None
    return ToolResult(
        data={"categories": breakdown},
        detail=(
            f"共 {len(breakdown)} 个消费分类"
            + (f"，最高「{top['category']}」{top['amount']:.2f} 元（占比 {top['ratio'] * 100:.1f}%）" if top else "")
        ),
    )


@tool("detect_anomalies")
def _detect_anomalies(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    transactions = ctx.get("transactions", [])
    anomalies = analytics_service.detect_anomalies(transactions)
    ctx["anomalies"] = anomalies
    return ToolResult(
        data={"anomalies": anomalies},
        detail=(
            f"识别到 {len(anomalies)} 笔可疑交易"
            if anomalies
            else "未发现显著异常交易"
        ),
    )


@tool("monthly_trend")
def _monthly_trend(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    trend = analytics_service.monthly_trend(db, args["account_id"], months=6)
    ctx["trend"] = trend
    latest = trend[-1] if trend else None
    return ToolResult(
        data={"trend": trend},
        detail=(
            f"近 {len(trend)} 个月趋势已生成"
            + (f"，本月支出 {latest['expense']:.2f} 元" if latest else "")
        ),
    )


@tool("compose_bill_summary")
def _compose_bill_summary(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    categories = ctx.get("categories", [])
    anomalies = ctx.get("anomalies", [])
    trend = ctx.get("trend", [])
    transactions = ctx.get("transactions", [])
    total = sum(t.amount_cents for t in transactions if t.direction == "expense")
    income = sum(t.amount_cents for t in transactions if t.direction == "income")

    ctx["bill_summary"] = {
        "total_expense": cents_to_yuan(total),
        "total_income": cents_to_yuan(income),
        "count": len(transactions),
        "categories": categories,
        "anomalies": anomalies,
        "trend": trend,
    }
    return ToolResult(
        data=ctx["bill_summary"],
        detail=(
            f"账单摘要已生成：支出 {cents_to_yuan(total):.2f} 元，"
            f"收入 {cents_to_yuan(income):.2f} 元，共 {len(transactions)} 笔"
        ),
    )


# ======================================================================
# 卡片链路
# ======================================================================
@tool("list_cards")
def _list_cards(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    cards = list_cards(db, args["account_id"])
    ctx["cards"] = cards
    active = sum(1 for c in cards if c.status == "active")
    return ToolResult(
        data={"count": len(cards), "active": active},
        detail=f"名下共 {len(cards)} 张卡，其中 {active} 张状态正常",
    )


@tool("locate_card")
def _locate_card(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    slots = ctx.get("slots", {})
    cards = list_cards(db, args["account_id"])
    last4 = slots.get("card_last4")
    account_no = slots.get("account_no")

    target = None
    if last4:
        target = next((c for c in cards if c.card_no.endswith(str(last4))), None)
    elif account_no:
        target = next((c for c in cards if account_no in c.card_no), None)
    elif len(cards) == 1:
        target = cards[0]
    elif cards:
        target = next((c for c in cards if c.status == "active"), cards[0])

    if target is None:
        return ToolResult(error="未能定位到目标卡片，请提供卡片尾号")

    ctx["target_card"] = {
        "id": target.id,
        "card_no": target.card_no,
        "masked_card_no": mask_card_no(target.card_no),
        "status": target.status,
        "card_name": target.card_name,
    }
    return ToolResult(
        data=ctx["target_card"],
        detail=f"已定位卡片 {mask_card_no(target.card_no)}（当前状态：{target.status}）",
    )


@tool("prepare_virtual_card")
def _prepare_virtual_card(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    slots = ctx.get("slots", {})
    card_name = slots.get("card_name") or "金枢虚拟卡"
    daily_limit = float(slots.get("daily_limit") or 5000)
    expire_month = slots.get("expire_month") or "2029/12"

    preview = card_service.apply_virtual_card(
        db,
        account_id=args["account_id"],
        card_name=card_name,
        daily_limit=daily_limit,
        expire_month=expire_month,
        confirm=False,
    )
    ctx["virtual_card_preview"] = preview
    actions = [
        {
            "kind": "virtual_card_preview",
            "title": "虚拟卡申请方案",
            "fields": {
                "卡片名称": card_name,
                "单日限额": f"¥ {daily_limit:.2f}",
                "有效期": expire_month,
                "权限等级": "黄色 · 需用户确认",
            },
        }
    ]
    return ToolResult(
        data=preview,
        detail=f"已生成虚拟卡申请方案：{card_name}，单日限额 {daily_limit:.2f} 元，等待用户确认",
        actions=actions,
    )


@tool("prepare_card_action")
def _prepare_card_action(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    slots = ctx.get("slots", {})
    intent = args.get("intent")
    target = ctx.get("target_card")
    policy = ctx.get("policy", {})
    if not target:
        return ToolResult(error="未定位到卡片")

    level = policy.get("level", "green")
    actions = [
        {
            "kind": "card_action_preview",
            "title": "卡片操作方案",
            "fields": {
                "目标卡片": target["masked_card_no"],
                "操作": "挂失" if intent == "card_lost" else "冻结/解冻",
                "权限等级": {"green": "绿色 · 自动执行", "yellow": "黄色 · 需用户确认", "red": "红色 · 需多因子验证"}.get(
                    level, level
                ),
            },
        }
    ]
    return ToolResult(
        data={"target": target, "policy": policy},
        detail=(
            f"已生成对 {target['masked_card_no']} 的操作方案，权限等级 "
            f"{ {'green': '绿色', 'yellow': '黄色', 'red': '红色'}.get(level, level) }"
        ),
        actions=actions,
    )


# ======================================================================
# 只读链路
# ======================================================================
@tool("load_account")
def _load_account(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    from app.services.account_service import get_account

    account = get_account(db, args["account_id"])
    ctx["account"] = account
    return ToolResult(
        data={
            "account_no": account.account_no,
            "holder": account.holder_name,
            "balance": cents_to_yuan(account.balance_cents),
        },
        detail=f"账户余额 {cents_to_yuan(account.balance_cents):.2f} 元",
    )


@tool("recent_transactions")
def _recent_transactions(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    txs = recent_transactions(db, args["account_id"], limit=8)
    ctx["recent_transactions"] = txs
    return ToolResult(data={"count": len(txs)}, detail=f"载入最近 {len(txs)} 笔交易")


@tool("spending_stats")
def _spending_stats(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    stats = analytics_service.spending_stats(db, args["account_id"])
    ctx["stats"] = stats
    return ToolResult(
        data={"month": stats["month"], "total_expense": stats["total_expense"]},
        detail=(
            f"{stats['month']} 支出合计 {stats['total_expense']:.2f} 元，"
            f"日均 {stats['daily_average']:.2f} 元"
        ),
    )


@tool("list_payees")
def _list_payees(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    payees = list_payees(db, args["account_id"])
    ctx["payees"] = payees
    return ToolResult(
        data={"count": len(payees)},
        detail=f"共 {len(payees)} 位收款人，其中 {sum(1 for p in payees if p.is_frequent)} 位为常用联系人",
    )


@tool("list_audit")
def _list_audit(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    from sqlalchemy import desc, select

    from app.models import AuditLog

    logs = list(
        db.execute(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(20)).scalars()
    )
    ctx["audit_logs"] = logs
    return ToolResult(data={"count": len(logs)}, detail=f"载入最近 {len(logs)} 条安全审计记录")


@tool("capabilities")
def _capabilities(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    return ToolResult(
        data={
            "capabilities": [
                "智能转账：自然语言理解收款人、金额与备注，自动判断权限等级",
                "智能账单分析：消费分类、月度统计、异常交易识别",
                "智能卡管理：卡片查询、虚拟卡申请、卡片挂失模拟",
                "安全审计：所有受控操作均写入审计日志",
            ]
        },
        detail="已输出系统能力清单",
    )


@tool("clarify")
def _clarify(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> ToolResult:
    return ToolResult(
        data={},
        detail="未能识别意图，已生成澄清问题",
    )


__all__ = ["ToolResult", "ToolMeta", "get_tool", "get_tool_meta", "list_tools", "tool"]
