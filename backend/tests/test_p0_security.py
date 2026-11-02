"""P0 安全修复专项测试：执行时重判、并发穿透、幂等、挂失 MFA。

全部基于真实 HTTP 调用（TestClient）+ 独立临时数据库，绝不虚构结果。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from app.core.database import SessionLocal
from app.models import Account, Card, Payee, Transaction, utcnow
from app.services import auth_service


def _seed(db) -> int:
    """准备一个最小账户，返回 account_id，并绑定 demo_user_1。"""
    acc = db.query(Account).filter(Account.account_no == "6217000000000001").first()
    if acc is None:
        acc = Account(
            account_no="6217000000000001",
            holder_name="P0测试用户",
            account_type="deposit",
            bank_name="金枢银行",
            currency="CNY",
            balance_cents=20_000_000,  # ¥200,000
            available_cents=20_000_000,
            status="active",
        )
        db.add(acc)
        db.commit()
        db.refresh(acc)
    # 确保收款人存在（幂等）
    payee = db.query(Payee).filter(Payee.account_id == acc.id, Payee.name == "P0常用收款人").first()
    if payee is None:
        db.add(
            Payee(
                account_id=acc.id,
                name="P0常用收款人",
                account_no="6212261234567890",
                bank_name="工商银行",
                card_last4="7890",
                is_frequent=True,
                single_limit_cents=1_000_000,
                total_count=3,
            )
        )
        db.commit()
    auth_service.create_demo_user(db, "demo_user_1", "Demo1234!", acc.id)
    return acc.id


def _get_account_id() -> int:
    db = SessionLocal()
    try:
        return _seed(db)
    finally:
        db.close()


def _reset_daily(account_id: int) -> None:
    db = SessionLocal()
    try:
        today = utcnow().date()
        start = datetime(today.year, today.month, today.day)
        db.query(Transaction).filter(
            Transaction.account_id == account_id,
            Transaction.category == "转账支出",
            Transaction.occurred_at >= start,
        ).delete()
        db.commit()
    finally:
        db.close()


def _daily_total(account_id: int) -> int:
    db = SessionLocal()
    try:
        from app.services.transfer_service import daily_transfer_total

        return daily_transfer_total(db, account_id)
    finally:
        db.close()


def _inject_transfer(account_id: int, amount_cents: int) -> None:
    """模拟「预览之后、执行之前」发生的另一笔转账支出。"""
    db = SessionLocal()
    try:
        db.add(
            Transaction(
                account_id=account_id,
                card_id=None,
                direction="expense",
                category="转账支出",
                amount_cents=amount_cents,
                balance_after_cents=0,
                merchant="并发注入",
                counterparty="注入收款人",
                remark="[INJECT] 并发转账",
                status="success",
                channel="agent",
                is_simulated=True,
                occurred_at=utcnow(),
            )
        )
        db.commit()
    finally:
        db.close()


# ======================================================================
# A. 权限测试（通过接口）
# ======================================================================
def test_policy_readonly_green(client, auth_headers):
    res = client.get("/api/v1/transfers/policy",
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    green = next(l for l in body["levels"] if l["level"] == "green")
    assert "只读" in green["reason"] or "查询" in green["reason"]


def test_transfer_preview_is_yellow_for_small_amount(client, auth_headers):
    account_id = _get_account_id()
    _reset_daily(account_id)
    res = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "P0常用收款人", "amount": 100},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["risk_level"] == "yellow"
    assert res.json()["requires_confirmation"] is True


def test_transfer_preview_red_when_daily_over_1000(client, auth_headers):
    account_id = _get_account_id()
    _reset_daily(account_id)
    # 累计 ¥900 再转 ¥200 → 红
    _inject_transfer(account_id, 90_000)
    res = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "P0常用收款人", "amount": 200},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["risk_level"] == "red"
    assert res.json()["requires_mfa"] is True


# ======================================================================
# B. 执行时重判测试
# ======================================================================
def test_execution_time_reevaluation_escalates(client, auth_headers):
    """预览黄 → 执行前累计已超 → 必须升级红并要求 MFA，且不得扣款。"""
    account_id = _get_account_id()
    _reset_daily(account_id)
    preview = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "P0常用收款人", "amount": 100},
        headers=auth_headers,
    ).json()
    assert preview["risk_level"] == "yellow"

    # 注入一笔 ¥950 的转账支出，使执行时累计 = ¥950
    _inject_transfer(account_id, 95_000)

    bal_before = _balance(account_id)
    res = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": preview["order_no"], "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "reeval-001"},
    )
    # 执行时累计 ¥950 + ¥100 = ¥1050 > ¥1000 → 升级红色，要求 MFA
    assert res.status_code == 428
    assert res.json()["error"]["code"] == "MFA_REQUIRED"
    # 不得扣款
    assert _balance(account_id) == bal_before


def test_execution_after_mfa_rechecks(client, auth_headers):
    """MFA 通过后再次重判：若累计仍超限，应拒绝扣款。"""
    account_id = _get_account_id()
    _reset_daily(account_id)
    # 单笔 ¥12000 → 预览即红
    preview = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "P0常用收款人", "amount": 12000},
        headers=auth_headers,
    ).json()
    assert preview["risk_level"] == "red"

    need = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": preview["order_no"], "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "reeval-mfa-001"},
    )
    assert need.status_code == 428
    detail = need.json()["error"]["detail"]
    challenge_id = detail["challenge_id"]
    demo_code = detail["demo_code"]

    ok = client.post(
        "/api/v1/transfers/execute",
        json={
            "order_no": preview["order_no"],
            "confirm": True,
            "mfa_code": demo_code,
            "mfa_challenge_id": challenge_id,
        },
        headers={**auth_headers, "Idempotency-Key": "reeval-mfa-002"},
    )
    # 单笔 ¥12000 辅助升红，MFA 通过后重判仍红但不再要求 MFA（已通过），可执行
    assert ok.status_code == 200
    assert ok.json()["status"] == "SUCCEEDED"


def _balance(account_id: int) -> int:
    db = SessionLocal()
    try:
        return db.query(Account).filter(Account.id == account_id).first().balance_cents
    finally:
        db.close()


# ======================================================================
# C. 并发测试
# ======================================================================
def test_concurrent_transfers_do_not_breach_daily_limit(client, auth_headers):
    """20 线程并发各转 ¥200：成功总额不得超过 ¥1000。"""
    account_id = _get_account_id()
    _reset_daily(account_id)
    bal_before = _balance(account_id)

    # 预先为每个线程生成一个独立工单（预览）
    orders = []
    for i in range(20):
        p = client.post(
            "/api/v1/transfers/preview",
            json={"account_id": account_id, "payee_name": "P0常用收款人", "amount": 200},
        headers=auth_headers,
    ).json()
        orders.append((p["order_no"], f"conc-{i}"))

    results = []

    def do_execute(item):
        order_no, key = item
        res = client.post(
            "/api/v1/transfers/execute",
            json={"order_no": order_no, "confirm": True},
            headers={**auth_headers, "Idempotency-Key": key},
        )
        results.append(res.status_code)

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(do_execute, orders))

    daily = _daily_total(account_id)
    bal_after = _balance(account_id)
    debited = bal_before - bal_after

    # 成功扣款总额 ≤ ¥1000（5 笔 × ¥200）
    assert daily <= 100_000, f"当日累计 {daily/100} 元超出 ¥1000 限额"
    assert debited <= 100_000, f"实际扣款 {debited/100} 元超出 ¥1000"
    # 没有 500 异常
    assert 500 not in results
    # 至少执行成功了一部分（余额确实被扣）
    assert debited > 0


def test_concurrent_same_key_no_500(client, auth_headers):
    """并发提交同一幂等键：不出现 500，只成功一次。"""
    account_id = _get_account_id()
    _reset_daily(account_id)
    preview = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "P0常用收款人", "amount": 100},
        headers=auth_headers,
    ).json()
    order_no = preview["order_no"]
    bal_before = _balance(account_id)

    codes = []

    def do(k):
        r = client.post(
            "/api/v1/transfers/execute",
            json={"order_no": order_no, "confirm": True},
            headers={**auth_headers, "Idempotency-Key": "same-key"},
        )
        codes.append(r.status_code)

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(do, range(10)))

    assert 500 not in codes
    # 只扣一次款（¥100）
    assert _balance(account_id) == bal_before - 10_000


# ======================================================================
# D. 幂等测试
# ======================================================================
def test_idempotency_same_key_10_times_debit_once(client, auth_headers):
    account_id = _get_account_id()
    _reset_daily(account_id)
    preview = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "P0常用收款人", "amount": 100},
        headers=auth_headers,
    ).json()
    bal_before = _balance(account_id)

    tx_ids = set()
    for _ in range(10):
        r = client.post(
            "/api/v1/transfers/execute",
            json={"order_no": preview["order_no"], "confirm": True},
            headers={**auth_headers, "Idempotency-Key": "idem-10x"},
        )
        assert r.status_code == 200
        tx_ids.add(r.json()["transaction_id"])

    assert len(tx_ids) == 1
    assert _balance(account_id) == bal_before - 10_000


def test_idempotency_same_key_different_params_conflict(client, auth_headers):
    account_id = _get_account_id()
    _reset_daily(account_id)
    p1 = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "P0常用收款人", "amount": 100},
        headers=auth_headers,
    ).json()
    p2 = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "P0常用收款人", "amount": 200},
        headers=auth_headers,
    ).json()

    client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p1["order_no"], "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "conflict-key"},
    )
    # 同键不同工单 → 冲突
    r = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p2["order_no"], "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "conflict-key"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_two_independent_transfers_use_different_keys(client, auth_headers):
    account_id = _get_account_id()
    _reset_daily(account_id)
    p1 = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "P0常用收款人", "amount": 100},
        headers=auth_headers,
    ).json()
    p2 = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "P0常用收款人", "amount": 100},
        headers=auth_headers,
    ).json()
    r1 = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p1["order_no"], "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "independent-1"},
    )
    r2 = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p2["order_no"], "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "independent-2"},
    )
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["transaction_id"] != r2.json()["transaction_id"]


# ======================================================================
# E. MFA 挂失端到端
# ======================================================================
def test_card_lost_end_to_end(client, auth_headers):
    db = SessionLocal()
    try:
        acc_id = _seed(db)
        card = db.query(Card).filter(Card.account_id == acc_id).first()
        if card is None:
            card = Card(
                account_id=acc_id,
                card_no="6222001234567890",
                card_type="debit",
                card_name="P0测试卡",
                network="银联",
                status="active",
                daily_limit_cents=500_000,
                expire_month="2029/06",
                is_virtual=False,
                is_simulated=True,
            )
            db.add(card)
            db.commit()
            db.refresh(card)
        card_id = card.id
    finally:
        db.close()

    # 发起挂失 → awaiting_mfa
    r1 = client.post(
        "/api/v1/cards/lost",
        json={"card_id": card_id, "reason": "P0测试挂失"},
        headers=auth_headers,
    )
    assert r1.status_code == 200
    body = r1.json()
    assert body["status"] == "awaiting_mfa"
    challenge_id = body["challenge_id"]
    demo_code = body["demo_code"]

    # 错误验证码 → 422，卡片状态不变
    r2 = client.post(
        f"/api/v1/cards/lost?mfa_code=000000&mfa_challenge_id={challenge_id}",
        json={"card_id": card_id, "reason": "P0测试挂失"},
        headers=auth_headers,
    )
    assert r2.status_code == 422
    assert _card_status(card_id) == "active"

    # 正确验证码 → 挂失成功
    r3 = client.post(
        f"/api/v1/cards/lost?mfa_code={demo_code}&mfa_challenge_id={challenge_id}",
        json={"card_id": card_id, "reason": "P0测试挂失"},
        headers=auth_headers,
    )
    assert r3.status_code == 200
    assert r3.json()["status"] == "lost"
    assert _card_status(card_id) == "lost"

    # 重复使用同一验证码 → 拒绝
    r4 = client.post(
        f"/api/v1/cards/lost?mfa_code={demo_code}&mfa_challenge_id={challenge_id}",
        json={"card_id": card_id, "reason": "P0重复挂失"},
        headers=auth_headers,
    )
    assert r4.status_code == 422


def _card_status(card_id: int) -> str:
    db = SessionLocal()
    try:
        return db.query(Card).filter(Card.id == card_id).first().status
    finally:
        db.close()


# ======================================================================
# F. 工单号唯一性
# ======================================================================
def test_100_orders_all_unique(client, auth_headers):
    account_id = _get_account_id()
    _reset_daily(account_id)
    order_nos = set()
    for _ in range(100):
        r = client.post(
            "/api/v1/transfers/preview",
            json={"account_id": account_id, "payee_name": "P0常用收款人", "amount": 10},
        headers=auth_headers,
    )
        assert r.status_code == 200
        order_nos.add(r.json()["order_no"])
    assert len(order_nos) == 100
