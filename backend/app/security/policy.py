"""独立权限策略引擎（后端强制执行）。

三级权限定义（赛事口径）
------------------------
- **绿色 GREEN**：纯查询类操作（余额查询、交易查询、账单分析、理财收益查询等），自动执行。
- **黄色 YELLOW**：写操作中的普通小额转账，且**执行后当日累计转账金额 ≤ 1000 元**，
  必须展示完整交易信息并取得用户明确确认。
- **红色 RED**：**执行后当日累计转账金额 > 1000 元**，以及银行卡挂失、密码修改等
  敏感操作，必须通过模拟多因子身份验证 (MFA)。

关键约束
--------
1. **任何资金写操作绝不能获得绿色权限**（写操作最低黄色）。
2. **日累计金额是主要判定依据**；单笔金额可作为额外升红条件，但**不替代**日累计判断。
3. 当日累计恰好等于 1000 元时仍属黄色；**超过 1000 元立即进入红色**。
4. 以交易发生日为准，业务时区默认 Asia/Shanghai（由 settings.business_timezone 配置）。
5. 所有金额使用整数分计算。
6. 本模块不接受任何来自大模型或前端的"权限建议 / 风险等级"入参，只接受业务事实。
7. 每次判定都返回可解释的 `rules` 列表，用于前端展示与写入审计日志。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List

from app.core.config import settings


class RiskLevel(str, Enum):
    """三级权限枚举。"""

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"

    @property
    def label(self) -> str:
        return {"green": "绿色 · 自动执行", "yellow": "黄色 · 需确认", "red": "红色 · 需多因子验证"}[self.value]

    @property
    def color(self) -> str:
        return {"green": "emerald", "yellow": "amber", "red": "rose"}[self.value]


GREEN = RiskLevel.GREEN
YELLOW = RiskLevel.YELLOW
RED = RiskLevel.RED


class ActionType(str, Enum):
    """受控动作类型。策略引擎仅对白名单内的动作类型授权。"""

    QUERY = "query"
    TRANSFER = "transfer"
    CARD_QUERY = "card_query"
    CARD_APPLY_VIRTUAL = "card_apply_virtual"
    CARD_FREEZE = "card_freeze"
    CARD_LOST = "card_lost"
    PAYEE_QUERY = "payee_query"
    ANALYTICS = "analytics"
    AUDIT_QUERY = "audit_query"
    PASSWORD_CHANGE = "password_change"


#: 允许「用户明确确认」后执行的动作（黄色）。
CONFIRMABLE_ACTIONS = {
    ActionType.TRANSFER,
    ActionType.CARD_APPLY_VIRTUAL,
    ActionType.CARD_FREEZE,
}

#: 强制要求 MFA 的动作（红色，不可降级）。
MFA_REQUIRED_ACTIONS = {
    ActionType.CARD_LOST,
    ActionType.PASSWORD_CHANGE,
}

#: 纯只读动作（绿色，自动执行）。
READ_ONLY_ACTIONS = {
    ActionType.QUERY,
    ActionType.CARD_QUERY,
    ActionType.PAYEE_QUERY,
    ActionType.ANALYTICS,
    ActionType.AUDIT_QUERY,
}


@dataclass
class PolicyDecision:
    """一次权限判定的完整结果。"""

    level: RiskLevel
    decision: str  # allow / confirm / mfa / block
    reason: str
    rules: List[str] = field(default_factory=list)
    requires_confirmation: bool = False
    requires_mfa: bool = False
    blocked: bool = False
    daily_total_before: float = 0.0
    daily_total_after: float = 0.0
    daily_limit_remaining: float = 0.0

    @property
    def next_action(self) -> str:
        if self.blocked:
            return "blocked"
        if self.requires_mfa:
            return "mfa"
        if self.requires_confirmation:
            return "confirm"
        return "execute"


class PolicyEngine:
    """规则化的权限策略引擎（日累计主轴）。"""

    def __init__(self) -> None:
        # 黄色 / 红色日累计阈值（赛事要求：≤1000 黄，>1000 红）
        self.yellow_daily_max_cents = int(settings.policy_yellow_daily_max * 100)
        self.red_daily_min_cents = int(settings.policy_red_daily_min * 100)
        # 单笔辅助升红阈值（不替代日累计判断）
        self.red_single_min_cents = int(settings.policy_red_single_min * 100)
        # 风控硬红线（超出直接阻断）
        self.red_daily_total_cents = int(settings.policy_red_daily_total * 100)

    # ------------------------------------------------------------------
    # 通用入口
    # ------------------------------------------------------------------
    def evaluate(
        self,
        action: ActionType | str,
        *,
        amount_cents: int = 0,
        daily_total_cents: int = 0,
        is_frequent_payee: bool = False,
        is_new_payee: bool = False,
        target_is_self: bool = False,
        remark_contains_sensitive: bool = False,
    ) -> PolicyDecision:
        """对一次操作执行权限判定。

        参数全部是业务事实，不包含任何模型或前端给出的权限意见。
        """
        raw_action = action
        resolved = action if isinstance(action, ActionType) else None
        if resolved is None:
            try:
                resolved = ActionType(str(raw_action))
            except ValueError:
                return PolicyDecision(
                    level=RED,
                    decision="block",
                    reason="该操作类型未被安全策略引擎授权。",
                    rules=["动作类型不在受控白名单内，禁止执行"],
                    blocked=True,
                )

        rules: List[str] = []

        # ---------- 规则 0：只读白名单 → 绿色自动执行 ----------
        if resolved in READ_ONLY_ACTIONS:
            rules.append("只读查询类操作，默认绿色，自动执行")
            return PolicyDecision(
                level=GREEN,
                decision="allow",
                reason="只读查询类操作，风险可控，自动执行。",
                rules=rules,
            )

        # 不在受控白名单内 → 阻断
        if resolved not in CONFIRMABLE_ACTIONS and resolved not in MFA_REQUIRED_ACTIONS:
            rules.append("动作类型不在受控白名单内，禁止执行")
            return PolicyDecision(
                level=RED,
                decision="block",
                reason="该操作类型未被安全策略引擎授权。",
                rules=rules,
                blocked=True,
            )

        # ---------- 规则 1：强制 MFA 的敏感动作 ----------
        if resolved in MFA_REQUIRED_ACTIONS:
            label = "银行卡挂失" if resolved == ActionType.CARD_LOST else "密码修改"
            rules.append(f"{resolved.value} 属于敏感操作，强制要求多因子身份验证")
            return PolicyDecision(
                level=RED,
                decision="mfa",
                reason=f"敏感操作（{label}）必须通过模拟多因子身份验证。",
                rules=rules,
                requires_mfa=True,
                daily_total_before=daily_total_cents / 100,
                daily_total_after=(daily_total_cents + amount_cents) / 100,
                daily_limit_remaining=max(0, self.red_daily_total_cents - daily_total_cents - amount_cents) / 100,
            )

        # ---------- 规则 2：转账（日累计主轴） ----------
        if resolved == ActionType.TRANSFER:
            return self._evaluate_transfer(
                amount_cents=amount_cents,
                daily_total_cents=daily_total_cents,
                is_frequent_payee=is_frequent_payee,
                is_new_payee=is_new_payee,
                target_is_self=target_is_self,
                remark_contains_sensitive=remark_contains_sensitive,
                rules=rules,
            )

        # ---------- 规则 3：非转账写操作（虚拟卡申请 / 冻结）→ 最低黄色 ----------
        rules.append(f"{resolved.value} 为写操作，最低按黄色处理")
        return PolicyDecision(
            level=YELLOW,
            decision="confirm",
            reason="写操作需用户明确确认后执行。",
            rules=rules,
            requires_confirmation=True,
            daily_total_before=daily_total_cents / 100,
            daily_total_after=daily_total_cents / 100,
        )

    # ------------------------------------------------------------------
    # 转账专用规则（日累计主轴）
    # ------------------------------------------------------------------
    def _evaluate_transfer(
        self,
        *,
        amount_cents: int,
        daily_total_cents: int,
        is_frequent_payee: bool,
        is_new_payee: bool,
        target_is_self: bool,
        remark_contains_sensitive: bool,
        rules: List[str],
    ) -> PolicyDecision:
        after_cents = daily_total_cents + amount_cents
        daily_total_before = daily_total_cents / 100
        daily_total_after = after_cents / 100

        # --- 硬阻断：日累计超出风控红线 ---
        if after_cents > self.red_daily_total_cents:
            rules.append(
                f"执行后当日累计 {daily_total_after:.2f} 元超过风控红线 "
                f"{self.red_daily_total_cents / 100:.2f} 元，直接阻断"
            )
            return PolicyDecision(
                level=RED,
                decision="block",
                reason="单日累计转账金额超过银行风控红线，操作已被拦截。",
                rules=rules,
                blocked=True,
                daily_total_before=daily_total_before,
                daily_total_after=daily_total_after,
                daily_limit_remaining=0.0,
            )

        # 资金写操作**绝不能是绿色**，最低黄色。
        level = YELLOW
        reason = ""
        requires_confirmation = True
        requires_mfa = False

        rules.append("转账为资金写操作，最低按黄色处理，必须展示详情并取得用户确认")

        # --- 主轴：执行后日累计是否超过 1000 元 ---
        if after_cents > self.red_daily_min_cents:
            rules.append(
                f"执行后当日累计 {daily_total_after:.2f} 元超过 {self.red_daily_min_cents / 100:.2f} 元 → 红色"
            )
            level = RED
            requires_mfa = True
            requires_confirmation = True
            reason = f"执行后当日累计转账 {daily_total_after:.2f} 元已超过 {self.red_daily_min_cents / 100:.2f} 元。"
        elif after_cents > self.yellow_daily_max_cents:
            # after > yellow_max 但 <= red_daily_min（两者通常相等，此处为容错）
            rules.append(
                f"执行后当日累计 {daily_total_after:.2f} 元超过 {self.yellow_daily_max_cents / 100:.2f} 元 → 红色"
            )
            level = RED
            requires_mfa = True
            requires_confirmation = True
            reason = f"执行后当日累计转账 {daily_total_after:.2f} 元已超过 {self.yellow_daily_max_cents / 100:.2f} 元。"
        else:
            rules.append(
                f"执行后当日累计 {daily_total_after:.2f} 元 ≤ {self.yellow_daily_max_cents / 100:.2f} 元 → 黄色"
            )
            reason = f"执行后当日累计转账 {daily_total_after:.2f} 元，未超过 {self.yellow_daily_max_cents / 100:.2f} 元，需人工确认。"

        # --- 单笔辅助升红（不替代日累计判断）---
        if amount_cents >= self.red_single_min_cents:
            rules.append(f"单笔金额 {amount_cents / 100:.2f} 元达到辅助升红阈值 {self.red_single_min_cents / 100:.2f} 元 → 红色")
            level = RED
            requires_mfa = True
            requires_confirmation = True
            reason = f"单笔金额 {amount_cents / 100:.2f} 元达到辅助升红阈值。"

        # --- 收款人风险（仅可升黄，不改变已有的红）---
        if is_new_payee:
            rules.append("收款人为首次转账对象 → 至少黄色")
            if level == YELLOW:
                reason = "首次向该收款人转账，需人工确认。"
        if not is_frequent_payee and not is_new_payee:
            rules.append("收款人非常用联系人 → 至少黄色")
            if level == YELLOW:
                reason = "向非常用联系人转账，需人工确认。"

        # --- 自转账（仅可升黄）---
        if target_is_self:
            rules.append("目标为本行本人账户 → 至少黄色")
            if level == YELLOW:
                reason = "向本人账户划转，需人工确认。"

        # --- 备注敏感词 → 升红 ---
        if remark_contains_sensitive:
            rules.append("备注命中敏感词 → 升级为红色")
            level = RED
            requires_mfa = True
            requires_confirmation = True
            reason = "转账备注命中风险敏感词，需多因子验证。"

        if level == YELLOW:
            reason = reason or "小额转账需展示详情并取得用户明确确认。"
            rules.append("综合判定 → 黄色，需用户明确确认")

        decision_str = "mfa" if requires_mfa else ("confirm" if requires_confirmation else "allow")

        return PolicyDecision(
            level=level,
            decision=decision_str,
            reason=reason,
            rules=rules,
            requires_confirmation=requires_confirmation,
            requires_mfa=requires_mfa,
            daily_total_before=daily_total_before,
            daily_total_after=daily_total_after,
            daily_limit_remaining=max(0, self.red_daily_total_cents - after_cents) / 100,
        )

    # ------------------------------------------------------------------
    def describe_thresholds(self) -> dict:
        return {
            "yellow_single_max": self.yellow_daily_max_cents / 100,
            "red_single_min": self.red_single_min_cents / 100,
            "red_daily_total": self.red_daily_total_cents / 100,
            "yellow_daily_max": self.yellow_daily_max_cents / 100,
            "red_daily_min": self.red_daily_min_cents / 100,
        }


policy_engine = PolicyEngine()

__all__ = [
    "RiskLevel",
    "GREEN",
    "YELLOW",
    "RED",
    "ActionType",
    "CONFIRMABLE_ACTIONS",
    "MFA_REQUIRED_ACTIONS",
    "READ_ONLY_ACTIONS",
    "PolicyDecision",
    "PolicyEngine",
    "policy_engine",
]
