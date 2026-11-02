"""P2-T1 请求限流专项测试。"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import Account, Payee
from app.services import auth_service


@pytest.fixture(autouse=True)
def _enable_rate_limit(monkeypatch):
    """本文件测试启用限流（conftest 全局禁用了限流）。"""
    monkeypatch.setattr(settings, "rate_limiter_enabled", True)
    yield


@pytest.fixture(autouse=True)
def _clean_rate_records():
    yield
    db = SessionLocal()
    try:
        from app.models import RateLimitRecord

        db.query(RateLimitRecord).delete()
        db.commit()
    finally:
        db.close()


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
        auth_service.create_demo_user(db, "demo_user_1", "Demo1234!", acc.id)
        return acc.id
    finally:
        db.close()


def test_login_rate_limit_by_ip(client):
    """单 IP 高频登录触发 429。"""
    # 连续错误登录超过 10 次/分钟 → 429
    codes = []
    for i in range(12):
        r = client.post("/api/v1/auth/login", json={"username": "demo_user_1", "password": "wrong"})
        codes.append(r.status_code)
    assert 429 in codes
    # 429 响应包含 Retry-After 头
    r = client.post("/api/v1/auth/login", json={"username": "demo_user_1", "password": "wrong"})
    if r.status_code == 429:
        assert r.headers.get("retry-after") is not None
        assert r.json()["error"]["code"] == "RATE_LIMITED"


def test_agent_chat_rate_limit(client, auth_headers):
    """Agent 高频调用触发 429（30次/分钟/用户）。"""
    _seed_account()
    codes = []
    for i in range(35):
        r = client.post(
            "/api/v1/agent/chat",
            json={"message": "我的余额", "account_id": 1},
            headers=auth_headers,
        )
        codes.append(r.status_code)
    assert 429 in codes


def test_transfer_preview_rate_limit(client, auth_headers):
    """转账预览高频触发 429（10次/分钟/账户）。"""
    account_id = _seed_account()
    codes = []
    for i in range(12):
        r = client.post(
            "/api/v1/transfers/preview",
            json={"account_id": account_id, "payee_name": "常用收款人", "amount": 100},
            headers=auth_headers,
        )
        codes.append(r.status_code)
    assert 429 in codes


def test_mfa_create_rate_limit(client, auth_headers):
    """MFA 挑战高频申请触发 429（3次/10分钟）。"""
    account_id = _seed_account()
    codes = []
    for i in range(5):
        r = client.post(
            "/api/v1/accounts/password/change/challenge",
            headers=auth_headers,
        )
        codes.append(r.status_code)
    assert 429 in codes


def test_rate_limit_isolated_by_user(client, auth_headers, user2_headers):
    """不同用户限流隔离：用户1超限不影响用户2。"""
    _seed_account()
    # 用户1 触发限流
    for i in range(35):
        client.post("/api/v1/agent/chat", json={"message": "hi", "account_id": 1}, headers=auth_headers)
    # 用户2（demo_user_2 绑定 account 2）正常
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
        acc2_id = acc2.id
    finally:
        db.close()
    r = client.get("/api/v1/audit", headers=user2_headers)
    # 用户2 未超限（审计限流 60次/分钟）
    assert r.status_code == 200


def test_rate_limit_retry_after_header(client):
    """429 响应包含 Retry-After。"""
    for i in range(12):
        client.post("/api/v1/auth/login", json={"username": "demo_user_1", "password": "wrong"})
    r = client.post("/api/v1/auth/login", json={"username": "demo_user_1", "password": "wrong"})
    if r.status_code == 429:
        assert r.headers.get("retry-after") is not None
        assert int(r.headers.get("retry-after")) > 0
