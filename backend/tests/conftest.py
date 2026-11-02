"""pytest 公共夹具：独立临时数据库 + 认证演示用户。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

# 必须在导入 app 之前设置，强制使用临时 SQLite
TEST_DB = BACKEND_ROOT / "data" / "test_fintrust.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ["FORCE_DEMO_MODE"] = "true"
os.environ["AUTH_SESSION_SECRET"] = "test-session-secret"
os.environ["MFA_SECRET_KEY"] = "test-mfa-secret"
os.environ["DEMO_USER_1_PASSWORD"] = "Demo1234!"
os.environ["DEMO_USER_2_PASSWORD"] = "Demo1234!"
os.environ["RATE_LIMITER_ENABLED"] = "false"  # 常规测试禁用限流，限流专项测试单独启用

from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Account, User  # noqa: E402
from app.services import auth_service  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _prepare_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def _ensure_demo_users(db) -> tuple[int, int]:
    """创建两个演示用户并分别绑定账户，返回 (account_id_1, account_id_2)。"""
    accounts = db.query(Account).order_by(Account.id).all()
    if not accounts:
        # 无账户则先建两个
        a1 = Account(
            account_no="6217000000000001",
            holder_name="测试用户",
            account_type="deposit",
            bank_name="金枢银行",
            currency="CNY",
            balance_cents=20_000_000,
            available_cents=20_000_000,
            status="active",
        )
        a2 = Account(
            account_no="6217000000000002",
            holder_name="测试用户二",
            account_type="deposit",
            bank_name="金枢银行",
            currency="CNY",
            balance_cents=10_000_000,
            available_cents=10_000_000,
            status="active",
        )
        db.add_all([a1, a2])
        db.commit()
        accounts = [a1, a2]

    auth_service.create_demo_user(db, "demo_user_1", "Demo1234!", accounts[0].id)
    if len(accounts) >= 2:
        auth_service.create_demo_user(db, "demo_user_2", "Demo1234!", accounts[1].id)
    return accounts[0].id, (accounts[1].id if len(accounts) >= 2 else accounts[0].id)


@pytest.fixture(scope="session")
def demo_accounts(client) -> tuple[int, int]:
    db = SessionLocal()
    try:
        return _ensure_demo_users(db)
    finally:
        db.close()


def _login(client, username: str, password: str) -> str:
    res = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


@pytest.fixture(scope="session")
def user1_token(client, demo_accounts) -> str:
    return _login(client, "demo_user_1", "Demo1234!")


@pytest.fixture(scope="session")
def user2_token(client, demo_accounts) -> str:
    return _login(client, "demo_user_2", "Demo1234!")


@pytest.fixture(scope="session")
def auth_headers(user1_token) -> dict:
    return {"Authorization": f"Bearer {user1_token}"}


@pytest.fixture(scope="session")
def user2_headers(user2_token) -> dict:
    return {"Authorization": f"Bearer {user2_token}"}


@pytest.fixture(scope="session")
def account_id_1(demo_accounts) -> int:
    return demo_accounts[0]


@pytest.fixture(scope="session")
def account_id_2(demo_accounts) -> int:
    return demo_accounts[1]
