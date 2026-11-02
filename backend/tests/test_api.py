"""API 集成测试：覆盖健康检查、账户总览、账单统计、转账三级权限、认证与审计。"""

from __future__ import annotations

from datetime import datetime

from app.core.database import SessionLocal
from app.models import Account, Card, Payee, Transaction
from app.services import auth_service


def _seed() -> int:
    """准备一份最小可用的演示数据，并绑定 demo_user_1。返回 account_id。"""
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.account_no == "6217000000000001").first()
        if acc is None:
            acc = Account(
                account_no="6217000000000001",
                holder_name="测试用户",
                account_type="deposit",
                bank_name="金枢银行",
                currency="CNY",
                balance_cents=20_000_000,
                available_cents=20_000_000,
                status="active",
            )
            db.add(acc)
            db.commit()
            db.refresh(acc)
        # 幂等：确保卡与收款人存在
        if db.query(Card).filter(Card.account_id == acc.id).count() == 0:
            db.add(
                Card(
                    account_id=acc.id,
                    card_no="6217000000000001",
                    card_type="debit",
                    card_name="测试储蓄卡",
                    network="银联",
                    status="active",
                    daily_limit_cents=500_000,
                    expire_month="2029/06",
                    is_virtual=False,
                    is_simulated=True,
                )
            )
        if db.query(Payee).filter(Payee.account_id == acc.id, Payee.name == "常用收款人").first() is None:
            db.add(
                Payee(
                    account_id=acc.id,
                    name="常用收款人",
                    account_no="6212261234567890",
                    bank_name="工商银行",
                    card_last4="7890",
                    is_frequent=True,
                    single_limit_cents=1_000_000,
                    total_count=3,
                )
            )
        if db.query(Payee).filter(Payee.account_id == acc.id, Payee.name == "生僻收款人").first() is None:
            db.add(
                Payee(
                    account_id=acc.id,
                    name="生僻收款人",
                    account_no="6228480398765432",
                    bank_name="招商银行",
                    card_last4="5432",
                    is_frequent=False,
                    single_limit_cents=1_000_000,
                    total_count=0,
                )
            )
        if db.query(Transaction).filter(Transaction.account_id == acc.id).count() == 0:
            for i in range(12):
                db.add(
                    Transaction(
                        account_id=acc.id,
                        card_id=None,
                        direction="expense",
                        category="餐饮美食",
                        amount_cents=5_000 + i * 500,
                        balance_after_cents=5_000_000 - i * 5_000,
                        merchant=f"测试商户 {i}",
                        counterparty=f"测试商户 {i}",
                        remark="",
                        status="success",
                        channel="mobile",
                        is_simulated=True,
                    )
                )
        db.commit()
        # 绑定 demo_user_1
        auth_service.create_demo_user(db, "demo_user_1", "Demo1234!", acc.id)
        return acc.id
    finally:
        db.close()


# ----------------------------------------------------------------------
# 系统
# ----------------------------------------------------------------------
def test_health(client):
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"
    assert "demo_mode" in body


def test_unknown_route_returns_structured_error(client):
    res = client.get("/api/v1/definitely-not-a-route")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


def test_unauthenticated_access_returns_401(client):
    res = client.get("/api/v1/accounts/overview", params={"account_id": 1})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


# ----------------------------------------------------------------------
# 账户 / 账单
# ----------------------------------------------------------------------
def test_account_overview(client, auth_headers):
    account_id = _seed()
    res = client.get("/api/v1/accounts/overview", params={"account_id": account_id}, headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["account"]["holder_name"] == "测试用户"
    assert "cards" in body and "recent_transactions" in body
    assert body["simulation_notice"]


def test_transaction_stats(client, auth_headers):
    account_id = _seed()
    res = client.get(
        "/api/v1/transactions/stats", params={"account_id": account_id, "period": "last_30d"}, headers=auth_headers
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total_expense"] > 0
    assert body["transaction_count"] > 0
    assert len(body["trend"]) == 6


# ----------------------------------------------------------------------
# 三级权限
# ----------------------------------------------------------------------
def test_transfer_policy_endpoint(client, auth_headers):
    res = client.get("/api/v1/transfers/policy", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert len(body["levels"]) == 3
    assert {lvl["level"] for lvl in body["levels"]} == {"green", "yellow", "red"}


def test_green_transfer_executes_directly(client, auth_headers):
    """小额转账现在应判为黄色，需确认后执行（写操作不再绿色）。"""
    account_id = _seed()
    _reset_daily_total(account_id)
    preview = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "常用收款人", "amount": 200, "remark": "测试"},
        headers=auth_headers,
    )
    assert preview.status_code == 200
    p = preview.json()
    assert p["risk_level"] == "yellow"
    assert p["requires_confirmation"] is True

    execute = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p["order_no"], "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "test-green-001"},
    )
    assert execute.status_code == 200
    result = execute.json()
    assert result["status"] == "SUCCEEDED"
    assert result["is_simulated"] is True


def test_yellow_transfer_requires_confirmation(client, auth_headers):
    account_id = _seed()
    _reset_daily_total(account_id)
    preview = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "生僻收款人", "amount": 300, "remark": "测试"},
        headers=auth_headers,
    )
    assert preview.status_code == 200
    p = preview.json()
    assert p["risk_level"] == "yellow"
    assert p["requires_confirmation"] is True

    blocked = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p["order_no"], "confirm": False},
        headers={**auth_headers, "Idempotency-Key": "test-yellow-001"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "CONFIRMATION_REQUIRED"

    ok = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p["order_no"], "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "test-yellow-002"},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "SUCCEEDED"


def test_red_transfer_requires_mfa(client, auth_headers):
    account_id = _seed()
    _reset_daily_total(account_id)
    preview = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "常用收款人", "amount": 12000, "remark": "大额"},
        headers=auth_headers,
    )
    assert preview.status_code == 200
    p = preview.json()
    assert p["risk_level"] == "red"
    assert p["requires_mfa"] is True

    need_mfa = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p["order_no"], "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "test-red-001"},
    )
    assert need_mfa.status_code == 428
    detail = need_mfa.json()["error"]["detail"]
    assert detail["challenge_id"]
    assert detail["demo_code"]

    wrong = client.post(
        "/api/v1/transfers/execute",
        json={
            "order_no": p["order_no"],
            "confirm": True,
            "mfa_code": "000000",
            "mfa_challenge_id": detail["challenge_id"],
        },
        headers={**auth_headers, "Idempotency-Key": "test-red-002"},
    )
    assert wrong.status_code == 428

    ok = client.post(
        "/api/v1/transfers/execute",
        json={
            "order_no": p["order_no"],
            "confirm": True,
            "mfa_code": detail["demo_code"],
            "mfa_challenge_id": detail["challenge_id"],
        },
        headers={**auth_headers, "Idempotency-Key": "test-red-003"},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "SUCCEEDED"


def _reset_daily_total(account_id: int = 1) -> None:
    """清空当日累计，保证各用例之间互不干扰。"""
    from app.models import utcnow

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


def test_idempotency_returns_first_result(client, auth_headers):
    account_id = _seed()
    _reset_daily_total(account_id)
    preview = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "常用收款人", "amount": 150, "remark": "幂等"},
        headers=auth_headers,
    )
    order_no = preview.json()["order_no"]
    headers = {**auth_headers, "Idempotency-Key": "test-idem-001"}

    first = client.post(
        "/api/v1/transfers/execute", json={"order_no": order_no, "confirm": True}, headers=headers
    )
    second = client.post(
        "/api/v1/transfers/execute", json={"order_no": order_no, "confirm": True}, headers=headers
    )
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["balance_after"] == second.json()["balance_after"]
    assert first.json()["transaction_id"] == second.json()["transaction_id"]


def test_insufficient_balance_is_rejected(client, auth_headers):
    account_id = _seed()
    _reset_daily_total(account_id)
    preview = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "常用收款人", "amount": 250000, "remark": "超额"},
        headers=auth_headers,
    )
    assert preview.status_code == 200
    order_no = preview.json()["order_no"]
    res = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": order_no, "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "test-balance-001"},
    )
    assert res.status_code in (428, 400, 403)
    assert res.json()["error"]["code"] in (
        "MFA_REQUIRED",
        "INSUFFICIENT_BALANCE",
        "POLICY_BLOCKED",
    )


def test_daily_red_line_blocks_transfer(client, auth_headers):
    account_id = _seed()
    _reset_daily_total(account_id)
    preview = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "常用收款人", "amount": 900000, "remark": "超额"},
        headers=auth_headers,
    )
    assert preview.status_code == 200
    p = preview.json()
    assert p["risk_level"] == "red"
    assert p["requires_mfa"] is True or p["next_action"] == "blocked"


# ----------------------------------------------------------------------
# 认证 / 越权
# ----------------------------------------------------------------------
def test_cross_account_access_returns_403(client, auth_headers, user2_headers):
    account_id_1 = _seed()
    # demo_user_2 绑定的是另一个账户（conftest 里的 6217000000000002）
    db = SessionLocal()
    try:
        acc2 = db.query(Account).filter(Account.account_no == "6217000000000002").first()
        if acc2 is None:
            acc2 = Account(
                account_no="6217000000000002",
                holder_name="测试用户二",
                account_type="deposit",
                bank_name="金枢银行",
                currency="CNY",
                balance_cents=10_000_000,
                available_cents=10_000_000,
                status="active",
            )
            db.add(acc2)
            db.commit()
        auth_service.create_demo_user(db, "demo_user_2", "Demo1234!", acc2.id)
        account_id_2 = acc2.id
    finally:
        db.close()

    # demo_user_1 访问账户2 → 403
    res = client.get("/api/v1/accounts/overview", params={"account_id": account_id_2}, headers=auth_headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "PERMISSION_DENIED"


# ----------------------------------------------------------------------
# Agent / 审计
# ----------------------------------------------------------------------
def test_agent_chat_returns_trace(client, auth_headers):
    _seed()
    res = client.post(
        "/api/v1/agent/chat",
        json={"message": "本月餐饮消费统计", "account_id": 1},
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["intent"] == "bill_analysis"
    assert len(body["trace"]) >= 3
    assert body["demo_mode"] is True
    nodes = [s["node"] for s in body["trace"]]
    assert "intent_recognition" in nodes
    assert "task_planning" in nodes


def test_agent_chat_transfer_flow(client, auth_headers):
    _seed()
    res = client.post(
        "/api/v1/agent/chat",
        json={"message": "给常用收款人转 800 元，备注项目结算款", "account_id": 1},
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["intent"] == "transfer"
    assert body["data"].get("transfer")


def test_audit_log_records_operations(client, auth_headers):
    _seed()
    res = client.get("/api/v1/audit", params={"page_size": 50}, headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] > 0
    actions = {item["action"] for item in body["items"]}
    assert "transfer.preview" in actions or "agent.chat" in actions
    assert "by_risk_level" in body["summary"]
