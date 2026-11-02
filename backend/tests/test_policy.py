"""安全策略引擎单元测试 —— 覆盖三级权限的核心判定规则（P0 日累计主轴）。"""

from __future__ import annotations

from app.security.policy import ActionType, GREEN, RED, YELLOW, policy_engine


def test_read_only_actions_are_green():
    for action in (
        ActionType.QUERY,
        ActionType.CARD_QUERY,
        ActionType.PAYEE_QUERY,
        ActionType.ANALYTICS,
        ActionType.AUDIT_QUERY,
    ):
        decision = policy_engine.evaluate(action)
        assert decision.level == GREEN
        assert decision.decision == "allow"
        assert decision.requires_confirmation is False
        assert decision.requires_mfa is False


def test_any_transfer_is_at_least_yellow():
    """资金写操作绝不能获得绿色权限。"""
    decision = policy_engine.evaluate(
        ActionType.TRANSFER,
        amount_cents=10_000,  # ¥100
        daily_total_cents=0,
        is_frequent_payee=True,
    )
    assert decision.level == YELLOW
    assert decision.requires_confirmation is True
    assert decision.requires_mfa is False
    assert decision.next_action == "confirm"


def test_transfer_exactly_at_daily_limit_is_yellow():
    """累计 ¥900 再转 ¥100 → 执行后恰好 ¥1000，仍属黄色。"""
    decision = policy_engine.evaluate(
        ActionType.TRANSFER,
        amount_cents=10_000,  # ¥100
        daily_total_cents=90_000,  # ¥900
        is_frequent_payee=True,
    )
    assert decision.level == YELLOW
    assert decision.daily_total_after == 1000.0


def test_transfer_over_daily_limit_is_red():
    """累计 ¥900 再转 ¥200 → 执行后 ¥1100 > ¥1000，升级红色并要求 MFA。"""
    decision = policy_engine.evaluate(
        ActionType.TRANSFER,
        amount_cents=20_000,  # ¥200
        daily_total_cents=90_000,  # ¥900
        is_frequent_payee=True,
    )
    assert decision.level == RED
    assert decision.requires_mfa is True
    assert decision.requires_confirmation is True


def test_single_amount_auxiliary_escalation():
    """单笔金额可辅助升红（≥ ¥10000），但不替代日累计判断。"""
    decision = policy_engine.evaluate(
        ActionType.TRANSFER,
        amount_cents=1_000_000,  # ¥10000
        daily_total_cents=0,
        is_frequent_payee=True,
    )
    assert decision.level == RED
    assert decision.requires_mfa is True


def test_new_payee_stays_yellow():
    decision = policy_engine.evaluate(
        ActionType.TRANSFER,
        amount_cents=10_000,  # ¥100
        daily_total_cents=0,
        is_new_payee=True,
    )
    assert decision.level == YELLOW
    assert decision.requires_confirmation is True


def test_card_lost_always_requires_mfa():
    decision = policy_engine.evaluate(ActionType.CARD_LOST)
    assert decision.level == RED
    assert decision.requires_mfa is True


def test_password_change_requires_mfa():
    decision = policy_engine.evaluate(ActionType.PASSWORD_CHANGE)
    assert decision.level == RED
    assert decision.requires_mfa is True
    assert decision.decision == "mfa"


def test_sensitive_remark_escalates_to_red():
    decision = policy_engine.evaluate(
        ActionType.TRANSFER,
        amount_cents=10_000,
        daily_total_cents=0,
        is_frequent_payee=True,
        remark_contains_sensitive=True,
    )
    assert decision.level == RED
    assert decision.requires_mfa is True


def test_daily_red_line_blocks():
    decision = policy_engine.evaluate(
        ActionType.TRANSFER,
        amount_cents=1_000_000,  # ¥10000
        daily_total_cents=99_000_000,  # ¥990000，加上本笔超过红线 ¥1000000
        is_frequent_payee=True,
    )
    assert decision.blocked is True
    assert decision.decision == "block"
    assert decision.next_action == "blocked"


def test_action_outside_whitelist_is_blocked():
    decision = policy_engine.evaluate("unregistered_action")
    assert decision.blocked is True
    assert decision.decision == "block"


def test_decision_always_explains_rules():
    decision = policy_engine.evaluate(
        ActionType.TRANSFER,
        amount_cents=10_000,
        daily_total_cents=0,
        is_frequent_payee=True,
    )
    assert len(decision.rules) > 0
    assert decision.reason
    for rule in decision.rules:
        assert isinstance(rule, str) and rule.strip()
