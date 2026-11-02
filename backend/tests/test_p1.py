"""P1 专项测试：交易状态机 / 身份认证 / MFA 持久化 / 密码修改。"""

from __future__ import annotations

from datetime import timedelta

from app.core.database import SessionLocal
from app.models import Account, Card, Payee, TransferOrder, utcnow
from app.services import auth_service


def _seed_account() -> int:
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
            db.commit()
        if db.query(Card).filter(Card.account_id == acc.id).count() == 0:
            db.add(
                Card(
                    account_id=acc.id,
                    card_no="6217000000000001",
                    card_type="debit",
                    card_name="测试卡",
                    network="银联",
                    status="active",
                    daily_limit_cents=500_000,
                    expire_month="2029/06",
                    is_virtual=False,
                    is_simulated=True,
                )
            )
            db.commit()
        auth_service.create_demo_user(db, "demo_user_1", "Demo1234!", acc.id)
        return acc.id
    finally:
        db.close()


def _reset_daily(account_id: int) -> None:
    from datetime import datetime

    from app.models import Transaction

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


# ======================================================================
# A. 交易状态机
# ======================================================================
def test_state_machine_seven_states_defined():
    from app.security.order_state import (
        CANCELLED,
        EXECUTING,
        EXPIRED,
        FAILED,
        PENDING_CONFIRMATION,
        PENDING_MFA,
        SUCCEEDED,
        TERMINAL_STATES,
    )

    assert {PENDING_CONFIRMATION, PENDING_MFA, EXECUTING, SUCCEEDED, FAILED, CANCELLED, EXPIRED}
    assert TERMINAL_STATES == {SUCCEEDED, FAILED, CANCELLED, EXPIRED}


def test_state_transition_legal_and_illegal():
    from app.security.order_state import (
        CANCELLED,
        EXECUTING,
        FAILED,
        PENDING_CONFIRMATION,
        PENDING_MFA,
        SUCCEEDED,
        allowed,
        is_terminal,
    )

    assert allowed(PENDING_CONFIRMATION, EXECUTING)
    assert allowed(PENDING_CONFIRMATION, PENDING_MFA)
    assert allowed(PENDING_CONFIRMATION, CANCELLED)
    assert allowed(PENDING_MFA, EXECUTING)
    assert allowed(EXECUTING, SUCCEEDED)
    assert allowed(EXECUTING, FAILED)
    # 非法迁移
    assert not allowed(SUCCEEDED, EXECUTING)
    assert not allowed(CANCELLED, SUCCEEDED)
    assert not allowed(FAILED, EXECUTING)
    # 终态
    assert is_terminal(SUCCEEDED) and is_terminal(FAILED) and is_terminal(CANCELLED)


def test_preview_creates_pending_confirmation(client, auth_headers):
    account_id = _seed_account()
    _reset_daily(account_id)
    res = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "常用收款人", "amount": 100},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["risk_level"] == "yellow"
    # 初始状态应为 PENDING_CONFIRMATION
    db = SessionLocal()
    try:
        order = db.query(TransferOrder).filter(TransferOrder.order_no == res.json()["order_no"]).first()
        assert order.status == "PENDING_CONFIRMATION"
        assert order.expires_at is not None
    finally:
        db.close()


def test_execute_success_sets_succeeded(client, auth_headers):
    account_id = _seed_account()
    _reset_daily(account_id)
    p = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "常用收款人", "amount": 100},
        headers=auth_headers,
    ).json()
    r = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p["order_no"], "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "sm-001"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "SUCCEEDED"
    db = SessionLocal()
    try:
        order = db.query(TransferOrder).filter(TransferOrder.order_no == p["order_no"]).first()
        assert order.status == "SUCCEEDED"
        assert order.executed_at is not None
    finally:
        db.close()


def test_cancel_transfer(client, auth_headers):
    account_id = _seed_account()
    _reset_daily(account_id)
    p = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "常用收款人", "amount": 100},
        headers=auth_headers,
    ).json()
    r = client.post(f"/api/v1/transfers/{p['order_no']}/cancel", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "CANCELLED"
    # 再次执行被拒绝
    r2 = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p["order_no"], "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "cancel-001"},
    )
    assert r2.status_code == 403


def test_expired_order_rejected(client, auth_headers):
    account_id = _seed_account()
    _reset_daily(account_id)
    p = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "常用收款人", "amount": 100},
        headers=auth_headers,
    ).json()
    # 手动把 expires_at 设为过去
    db = SessionLocal()
    try:
        order = db.query(TransferOrder).filter(TransferOrder.order_no == p["order_no"]).first()
        order.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()
    r = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p["order_no"], "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "expired-001"},
    )
    assert r.status_code == 403
    db = SessionLocal()
    try:
        order = db.query(TransferOrder).filter(TransferOrder.order_no == p["order_no"]).first()
        assert order.status == "EXPIRED"
    finally:
        db.close()


def test_state_transition_audit_records(client, auth_headers):
    account_id = _seed_account()
    _reset_daily(account_id)
    p = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "常用收款人", "amount": 100},
        headers=auth_headers,
    ).json()
    client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p["order_no"], "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "audit-001"},
    )
    r = client.get(f"/api/v1/transfers/{p['order_no']}/transitions", headers=auth_headers)
    assert r.status_code == 200
    transitions = r.json()["transitions"]
    assert len(transitions) >= 2  # PENDING_CONFIRMATION → EXECUTING → SUCCEEDED
    statuses = [t["to_status"] for t in transitions]
    assert "EXECUTING" in statuses and "SUCCEEDED" in statuses


# ======================================================================
# B. 身份认证
# ======================================================================
def test_login_success_and_me(client, demo_accounts):
    r = client.post("/api/v1/auth/login", json={"username": "demo_user_1", "password": "Demo1234!"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    assert token
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "demo_user_1"


def test_login_wrong_password(client):
    r = client.post("/api/v1/auth/login", json={"username": "demo_user_1", "password": "wrong"})
    assert r.status_code == 401


def test_logout_revokes_token(client, demo_accounts):
    token = client.post("/api/v1/auth/login", json={"username": "demo_user_1", "password": "Demo1234!"}).json()["access_token"]
    client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_unauthenticated_returns_401(client):
    r = client.get("/api/v1/accounts")
    assert r.status_code == 401


def test_cross_account_403(client, auth_headers, user2_headers, account_id_2):
    # demo_user_1 访问 demo_user_2 的账户 → 403
    r = client.get("/api/v1/accounts/overview", params={"account_id": account_id_2}, headers=auth_headers)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "PERMISSION_DENIED"


def test_user_data_isolation(client, auth_headers, user2_headers, account_id_1, account_id_2):
    # demo_user_1 只能看到 account_id_1
    r = client.get("/api/v1/accounts", headers=auth_headers)
    assert r.status_code == 200
    ids = {a["id"] for a in r.json()}
    assert account_id_1 in ids
    assert account_id_2 not in ids


def test_agent_chat_cross_account_blocked(client, auth_headers, account_id_2):
    # agent 对话指定其他账户 → 403
    r = client.post(
        "/api/v1/agent/chat",
        json={"message": "我的余额", "account_id": account_id_2},
        headers=auth_headers,
    )
    assert r.status_code == 403


# ======================================================================
# C. MFA 持久化
# ======================================================================
def test_mfa_challenge_persisted_and_consumed(client, auth_headers):
    """发起红色交易 → 验证码落库（摘要）→ 校验成功 → 一次性消费。"""
    from app.models import MfaChallenge

    account_id = _seed_account()
    _reset_daily(account_id)
    p = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "常用收款人", "amount": 12000},
        headers=auth_headers,
    ).json()
    need = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p["order_no"], "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "mfa-p-001"},
    )
    assert need.status_code == 428
    detail = need.json()["error"]["detail"]
    challenge_id = detail["challenge_id"]
    demo_code = detail["demo_code"]

    # 挑战已落库，且验证码不是明文
    db = SessionLocal()
    try:
        c = db.query(MfaChallenge).filter(MfaChallenge.challenge_id == challenge_id).first()
        assert c is not None
        assert c.code_hash != demo_code  # 存的是摘要不是明文
        assert c.status == "pending"
    finally:
        db.close()

    # 正确验证码 → 执行成功 + 挑战被消费
    ok = client.post(
        "/api/v1/transfers/execute",
        json={
            "order_no": p["order_no"],
            "confirm": True,
            "mfa_code": demo_code,
            "mfa_challenge_id": challenge_id,
        },
        headers={**auth_headers, "Idempotency-Key": "mfa-p-002"},
    )
    assert ok.status_code == 200
    db = SessionLocal()
    try:
        c = db.query(MfaChallenge).filter(MfaChallenge.challenge_id == challenge_id).first()
        assert c.status == "consumed"
        assert c.consumed_at is not None
    finally:
        db.close()


def test_mfa_reuse_rejected(client, auth_headers):
    account_id = _seed_account()
    _reset_daily(account_id)
    p = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "常用收款人", "amount": 12000},
        headers=auth_headers,
    ).json()
    need = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p["order_no"], "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "mfa-r-001"},
    )
    detail = need.json()["error"]["detail"]
    challenge_id = detail["challenge_id"]
    demo_code = detail["demo_code"]
    client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p["order_no"], "confirm": True, "mfa_code": demo_code, "mfa_challenge_id": challenge_id},
        headers={**auth_headers, "Idempotency-Key": "mfa-r-002"},
    )
    # 同一验证码再用于另一笔 → 拒绝
    p2 = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "常用收款人", "amount": 12000},
        headers=auth_headers,
    ).json()
    r = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p2["order_no"], "confirm": True, "mfa_code": demo_code, "mfa_challenge_id": challenge_id},
        headers={**auth_headers, "Idempotency-Key": "mfa-r-003"},
    )
    # 挑战绑定 target_id（order_no），跨工单复用被拒绝
    assert r.status_code == 428


def test_mfa_wrong_code_and_lockout(client, auth_headers):
    from app.models import MfaChallenge

    account_id = _seed_account()
    _reset_daily(account_id)
    p = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "常用收款人", "amount": 12000},
        headers=auth_headers,
    ).json()
    need = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p["order_no"], "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "mfa-l-001"},
    )
    detail = need.json()["error"]["detail"]
    challenge_id = detail["challenge_id"]

    # 连续 5 次错误 → 锁定
    for i in range(5):
        client.post(
            "/api/v1/transfers/execute",
            json={"order_no": p["order_no"], "confirm": True, "mfa_code": "000000", "mfa_challenge_id": challenge_id},
            headers={**auth_headers, "Idempotency-Key": f"mfa-l-w{i}"},
        )
    db = SessionLocal()
    try:
        c = db.query(MfaChallenge).filter(MfaChallenge.challenge_id == challenge_id).first()
        assert c.status == "locked" or c.attempts_remaining == 0
    finally:
        db.close()


# ======================================================================
# D. 密码修改（使用独立用户，避免影响 demo_user_1 的 session 级 token）
# ======================================================================
def _make_pw_user() -> tuple[str, str]:
    """创建一个独立的密码测试用户，返回 (token, headers)。"""
    from app.models import User
    from app.security.password import hash_password

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == "pw_test_user").first()
        if u is None:
            u = User(username="pw_test_user", password_hash=hash_password("OldPass123!"), status="active")
            db.add(u)
            db.commit()
            db.refresh(u)
        # 重置密码为已知值（幂等）
        u.password_hash = hash_password("OldPass123!")
        db.commit()
        return u.id
    finally:
        db.close()


def _login_pw_user(client) -> str:
    _make_pw_user()
    r = client.post("/api/v1/auth/login", json={"username": "pw_test_user", "password": "OldPass123!"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_password_change_full_flow(client):
    token = _login_pw_user(client)
    h = {"Authorization": f"Bearer {token}"}

    r = client.post("/api/v1/accounts/password/change/challenge", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "awaiting_mfa"
    challenge_id = body["challenge_id"]
    demo_code = body["demo_code"]

    r2 = client.post(
        "/api/v1/accounts/password/change",
        json={
            "old_password": "OldPass123!",
            "new_password": "NewPass123!",
            "mfa_code": demo_code,
            "mfa_challenge_id": challenge_id,
        },
        headers=h,
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "changed"

    # 旧 token 失效
    r3 = client.get("/api/v1/auth/me", headers=h)
    assert r3.status_code == 401

    # 新密码可登录
    r4 = client.post("/api/v1/auth/login", json={"username": "pw_test_user", "password": "NewPass123!"})
    assert r4.status_code == 200


def test_password_change_wrong_old_password(client):
    token = _login_pw_user(client)
    h = {"Authorization": f"Bearer {token}"}
    challenge = client.post("/api/v1/accounts/password/change/challenge", headers=h).json()
    r = client.post(
        "/api/v1/accounts/password/change",
        json={
            "old_password": "WrongPass",
            "new_password": "NewPass123!",
            "mfa_code": challenge["demo_code"],
            "mfa_challenge_id": challenge["challenge_id"],
        },
        headers=h,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "OLD_PASSWORD_INVALID"


def test_password_change_no_mfa(client):
    token = _login_pw_user(client)
    h = {"Authorization": f"Bearer {token}"}
    r = client.post(
        "/api/v1/accounts/password/change",
        json={"old_password": "OldPass123!", "new_password": "NewPass123!", "mfa_code": "000000", "mfa_challenge_id": "mfa_nonexistent"},
        headers=h,
    )
    assert r.status_code == 422


def test_password_change_weak_password(client):
    token = _login_pw_user(client)
    h = {"Authorization": f"Bearer {token}"}
    challenge = client.post("/api/v1/accounts/password/change/challenge", headers=h).json()
    r = client.post(
        "/api/v1/accounts/password/change",
        json={
            "old_password": "OldPass123!",
            "new_password": "abc",
            "mfa_code": challenge["demo_code"],
            "mfa_challenge_id": challenge["challenge_id"],
        },
        headers=h,
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "PASSWORD_WEAK"


# ======================================================================
# E. 原有功能回归（带认证）
# ======================================================================
def test_regression_account_overview(client, auth_headers):
    account_id = _seed_account()
    r = client.get("/api/v1/accounts/overview", params={"account_id": account_id}, headers=auth_headers)
    assert r.status_code == 200


def test_regression_agent_chat(client, auth_headers):
    account_id = _seed_account()
    r = client.post(
        "/api/v1/agent/chat",
        json={"message": "我的余额", "account_id": account_id},
        headers=auth_headers,
    )
    assert r.status_code == 200


def test_regression_cards_list(client, auth_headers):
    account_id = _seed_account()
    r = client.get("/api/v1/cards", params={"account_id": account_id}, headers=auth_headers)
    assert r.status_code == 200


def test_regression_audit_list(client, auth_headers):
    _seed_account()
    r = client.get("/api/v1/audit", headers=auth_headers)
    assert r.status_code == 200


# ======================================================================
# 补充：提升 coverage 的边界测试
# ======================================================================
def test_insufficient_balance_marks_failed(client, auth_headers):
    """余额不足时工单应标记 FAILED 并记录 fail_reason。"""
    from app.models import Transaction

    account_id = _seed_account()
    _reset_daily(account_id)
    # 把余额调低到 ¥100，转账 ¥12000（红色+余额不足）
    db = SessionLocal()
    try:
        from app.models import Account

        acc = db.query(Account).filter(Account.id == account_id).first()
        acc.balance_cents = 100_00
        acc.available_cents = 100_00
        db.commit()
    finally:
        db.close()

    p = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "常用收款人", "amount": 12000},
        headers=auth_headers,
    ).json()
    need = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p["order_no"], "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "fail-001"},
    )
    # 红色先要求 MFA
    assert need.status_code == 428
    detail = need.json()["error"]["detail"]
    # 通过 MFA 后执行 → 余额不足 → FAILED
    r = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p["order_no"], "confirm": True, "mfa_code": detail["demo_code"], "mfa_challenge_id": detail["challenge_id"]},
        headers={**auth_headers, "Idempotency-Key": "fail-002"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INSUFFICIENT_BALANCE"
    db = SessionLocal()
    try:
        order = db.query(TransferOrder).filter(TransferOrder.order_no == p["order_no"]).first()
        assert order.status == "FAILED"
        assert "余额不足" in order.fail_reason
    finally:
        db.close()


def test_mfa_expired_rejected(client, auth_headers):
    from app.models import MfaChallenge

    account_id = _seed_account()
    _reset_daily(account_id)
    p = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "常用收款人", "amount": 12000},
        headers=auth_headers,
    ).json()
    need = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p["order_no"], "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "mfa-exp-001"},
    )
    detail = need.json()["error"]["detail"]
    challenge_id = detail["challenge_id"]
    # 把挑战改为已过期
    db = SessionLocal()
    try:
        c = db.query(MfaChallenge).filter(MfaChallenge.challenge_id == challenge_id).first()
        c.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    r = client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p["order_no"], "confirm": True, "mfa_code": "123456", "mfa_challenge_id": challenge_id},
        headers={**auth_headers, "Idempotency-Key": "mfa-exp-002"},
    )
    assert r.status_code == 428


def test_expire_stale_orders_batch(client, auth_headers):
    from app.services.transfer_service import expire_stale_orders

    account_id = _seed_account()
    _reset_daily(account_id)
    p = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "常用收款人", "amount": 100},
        headers=auth_headers,
    ).json()
    db = SessionLocal()
    try:
        order = db.query(TransferOrder).filter(TransferOrder.order_no == p["order_no"]).first()
        order.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
        n = expire_stale_orders(db)
        assert n >= 1
        db.refresh(order)
        assert order.status == "EXPIRED"
    finally:
        db.close()


def test_login_disabled_user(client):
    from app.models import User

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == "disabled_user").first()
        if u is None:
            from app.security.password import hash_password

            u = User(username="disabled_user", password_hash=hash_password("Pass1234!"), status="disabled")
            db.add(u)
            db.commit()
    finally:
        db.close()
    r = client.post("/api/v1/auth/login", json={"username": "disabled_user", "password": "Pass1234!"})
    assert r.status_code == 401


def test_resolve_payee_branches(client, auth_headers):
    """覆盖 resolve_payee 的各分支（按账号/姓名/ID 解析）。"""
    from app.core.database import SessionLocal
    from app.services.transfer_service import resolve_payee

    account_id = _seed_account()
    db = SessionLocal()
    try:
        # 按姓名
        payee, name, no = resolve_payee(db, account_id, payee_id=None, payee_name="常用收款人", payee_account_no=None)
        assert name == "常用收款人"
        # 按账号
        payee2, name2, no2 = resolve_payee(db, account_id, payee_id=None, payee_name=None, payee_account_no="6212261234567890")
        assert name2 == "常用收款人"
        # 按 ID
        payee3, name3, no3 = resolve_payee(db, account_id, payee_id=payee.id, payee_name=None, payee_account_no=None)
        assert name3 == "常用收款人"
    finally:
        db.close()


def test_policy_info_endpoint(client, auth_headers):
    r = client.get("/api/v1/transfers/policy", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["yellow_daily_max"] == 1000.0
    assert body["red_daily_min"] == 1000.0


def test_cancel_terminal_order_rejected(client, auth_headers):
    account_id = _seed_account()
    _reset_daily(account_id)
    p = client.post(
        "/api/v1/transfers/preview",
        json={"account_id": account_id, "payee_name": "常用收款人", "amount": 100},
        headers=auth_headers,
    ).json()
    client.post(
        "/api/v1/transfers/execute",
        json={"order_no": p["order_no"], "confirm": True},
        headers={**auth_headers, "Idempotency-Key": "cancel-term-001"},
    )
    r = client.post(f"/api/v1/transfers/{p['order_no']}/cancel", headers=auth_headers)
    assert r.status_code == 403  # SUCCEEDED 终态不可取消
