"""意图识别与参数抽取单元测试。"""

from __future__ import annotations

import pytest

from app.agent.nlu import (
    INTENT_ACCOUNT_OVERVIEW,
    INTENT_BILL_ANALYSIS,
    INTENT_CARD_LOST,
    INTENT_CARD_QUERY,
    INTENT_CARD_VIRTUAL_APPLY,
    INTENT_HELP,
    INTENT_TRANSFER,
    extract_amount,
    extract_remark,
    parse_intent,
)


@pytest.mark.parametrize(
    "text,amount",
    [
        ("给张明远转 800 元", 800.0),
        ("转 5000 元给李四", 5000.0),
        ("转账 1.5 万", 15000.0),
        ("给王五转三千元", 3000.0),
        ("转 1200 块", 1200.0),
    ],
)
def test_extract_amount(text: str, amount: float):
    assert extract_amount(text) == pytest.approx(amount)


def test_extract_amount_ignores_card_number():
    # 尾号不应被当作金额
    assert extract_amount("尾号 8888 的卡") is None


def test_extract_remark():
    assert extract_remark("备注项目结算款") == "项目结算款"
    assert extract_remark("给张三转 100 元，备注：房租") == "房租"
    # 没有可识别的备注关键字时返回空串
    assert extract_remark("今天天气不错") == ""


def test_intent_transfer():
    result = parse_intent("给张明远转 800 元，备注项目结算款", allow_llm=False)
    assert result.intent == INTENT_TRANSFER
    assert result.slots["amount"] == 800.0
    assert result.slots["payee_name"] == "张明远"
    assert result.slots["remark"] == "项目结算款"


def test_intent_bill_analysis():
    result = parse_intent("本月餐饮消费统计", allow_llm=False)
    assert result.intent == INTENT_BILL_ANALYSIS
    assert result.slots["category"] == "餐饮美食"
    assert result.slots["period"] == "current_month"


def test_intent_card_query():
    assert parse_intent("我有几张银行卡", allow_llm=False).intent == INTENT_CARD_QUERY


def test_intent_card_lost():
    result = parse_intent("把尾号 8899 的卡挂失", allow_llm=False)
    assert result.intent == INTENT_CARD_LOST
    assert result.slots["card_last4"] == "8899"


def test_intent_virtual_card():
    result = parse_intent("申请一张虚拟卡，单日限额 3000", allow_llm=False)
    assert result.intent == INTENT_CARD_VIRTUAL_APPLY
    assert result.slots["daily_limit"] == 3000.0


def test_intent_overview_and_help():
    assert parse_intent("看看我的账户余额", allow_llm=False).intent == INTENT_ACCOUNT_OVERVIEW
    assert parse_intent("你能做什么", allow_llm=False).intent == INTENT_HELP


def test_unknown_intent_is_low_confidence():
    result = parse_intent("今天天气怎么样", allow_llm=False)
    assert result.confidence < 0.5
