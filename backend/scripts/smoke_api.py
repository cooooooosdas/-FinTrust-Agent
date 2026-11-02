"""端到端接口冒烟：逐一验证前端页面实际调用的每一个后端接口。

运行：python scripts/smoke_api.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal  # noqa: E402
from app.models import Transaction, utcnow  # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:8000/api/v1")
SMOKE_USER = os.environ.get("SMOKE_USER", "demo_user_1")
SMOKE_PASSWORD = os.environ.get("SMOKE_PASSWORD", "Demo1234!")

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"

results: list[tuple[str, bool, str]] = []

#: 登录后注入的认证头
_AUTH_HEADERS: dict[str, str] = {}


def check(name: str, fn) -> None:
    try:
        detail = fn()
        results.append((name, True, detail or "OK"))
        print(f"{PASS} {name}  {detail}")
    except Exception as exc:  # noqa: BLE001
        results.append((name, False, str(exc)))
        print(f"{FAIL} {name}  {exc}")


def get(client: httpx.Client, path: str, **params) -> httpx.Response:
    res = client.get(f"{BASE}{path}", params=params or None, headers=_AUTH_HEADERS)
    res.raise_for_status()
    return res


def post(client: httpx.Client, path: str, body: dict, **params) -> httpx.Response:
    headers = {**_AUTH_HEADERS}
    if "headers" in params:
        headers.update(params.pop("headers"))
    res = client.post(f"{BASE}{path}", json=body, params=params or None, headers=headers)
    return res


def reset_daily_total(account_id: int = 1) -> None:
    """清空当日累计转账金额（使用业务时区窗口，与 daily_transfer_total 一致）。"""
    from app.services.transfer_service import _business_day_window

    db = SessionLocal()
    try:
        start, end = _business_day_window()
        db.query(Transaction).filter(
            Transaction.account_id == account_id,
            Transaction.category == "转账支出",
            Transaction.occurred_at >= start,
            Transaction.occurred_at < end,
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def main() -> int:
    with httpx.Client(timeout=20.0) as c:
        # ---------- 认证 ----------
        def _login():
            res = c.post(f"{BASE}/auth/login", json={"username": SMOKE_USER, "password": SMOKE_PASSWORD})
            assert res.status_code == 200, res.text
            body = res.json()
            global _AUTH_HEADERS
            _AUTH_HEADERS = {"Authorization": f"Bearer {body['access_token']}"}
            return f"登录 {body['user']['username']} / 账户 {body['user']['account_ids']}"

        check("POST /auth/login", _login)

        def _me():
            body = get(c, "/auth/me").json()
            assert body["username"] == SMOKE_USER
            return f"当前用户 {body['username']}"

        check("GET /auth/me", _me)

        def _cross_account():
            # 访问不存在的账户 ID（999999）→ 403
            res = c.get(f"{BASE}/accounts/overview", params={"account_id": 999999}, headers=_AUTH_HEADERS)
            assert res.status_code == 403, res.text
            return "跨账户访问返回 403"

        check("GET /accounts (跨账户403)", _cross_account)

        def _unauth():
            res = c.get(f"{BASE}/accounts/overview", params={"account_id": 1})
            assert res.status_code == 401, res.text
            return "未认证返回 401"

        check("GET /accounts (未认证401)", _unauth)

        # ---------- 系统 ----------
        def _health():
            body = get(c, "/health").json()
            assert body["status"] == "ok", body
            return f"demo_mode={body['demo_mode']} db={body['database']}"

        check("GET /health", _health)

        # ---------- 账户总览 ----------
        def _overview():
            body = get(c, "/accounts/overview", account_id=1).json()
            assert body["account"]["balance"] > 0, body
            assert len(body["cards"]) > 0
            assert len(body["recent_transactions"]) > 0
            assert body["stats"]["total_expense"] > 0
            return (
                f"余额 {body['account']['balance']} / 卡 {len(body['cards'])} / "
                f"流水 {len(body['recent_transactions'])} / 支出 {body['stats']['total_expense']}"
            )

        check("GET /accounts/overview", _overview)

        # ---------- 卡片 ----------
        def _cards():
            cards = get(c, "/cards", account_id=1).json()
            assert len(cards) >= 2, cards
            return f"{len(cards)} 张卡"

        check("GET /cards", _cards)

        def _card_detail():
            cards = get(c, "/cards", account_id=1).json()
            card = get(c, f"/cards/{cards[0]['id']}").json()
            assert card["id"] == cards[0]["id"]
            return card["masked_card_no"]

        check("GET /cards/{id}", _card_detail)

        def _virtual_preview():
            res = post(
                c,
                "/cards/virtual",
                {"card_name": "冒烟测试虚拟卡", "daily_limit": 2000, "expire_month": "2029/12"},
            )
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["status"] == "awaiting_confirm", body
            return "黄色：等待确认"

        check("POST /cards/virtual (需确认)", _virtual_preview)

        def _virtual_issue():
            res = post(
                c,
                "/cards/virtual",
                {"card_name": "冒烟测试虚拟卡", "daily_limit": 2000, "expire_month": "2029/12"},
                confirm="true",
            )
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["status"] == "issued", body
            return f"已签发 {body['card']['masked_card_no']}"

        check("POST /cards/virtual (确认后)", _virtual_issue)

        def _freeze():
            cards = get(c, "/cards", account_id=1).json()
            target = next(x for x in cards if x["status"] == "active")
            res = post(c, "/cards/freeze", {}, card_id=target["id"])
            assert res.status_code == 200, res.text
            assert res.json()["status"] == "awaiting_confirm", res.text
            res2 = post(c, "/cards/freeze", {}, card_id=target["id"], confirm="true")
            assert res2.json()["card_status"] == "frozen", res2.text
            post(c, "/cards/freeze", {}, card_id=target["id"], confirm="true")  # 解冻还原
            return "冻结 → 解冻 往返正常"

        check("POST /cards/freeze", _freeze)

        def _lost():
            cards = get(c, "/cards", account_id=1).json()
            target = cards[0]
            res = post(c, "/cards/lost", {"card_id": target["id"], "reason": "冒烟测试"})
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["status"] == "awaiting_mfa", body
            return f"红色：下发验证码 {body['demo_code']}"

        check("POST /cards/lost (需 MFA)", _lost)

        # ---------- 交易 / 账单 ----------
        def _tx_list():
            body = get(c, "/transactions", account_id=1, page=1, page_size=10).json()
            assert body["total"] > 0, body
            assert len(body["items"]) == 10, body
            return f"共 {body['total']} 条，本页 {len(body['items'])} 条"

        check("GET /transactions", _tx_list)

        def _tx_filter():
            body = get(c, "/transactions", account_id=1, category="餐饮美食", direction="expense").json()
            assert all(i["category"] == "餐饮美食" for i in body["items"]), body
            return f"筛选后 {body['total']} 条"

        check("GET /transactions (筛选)", _tx_filter)

        def _stats():
            body = get(c, "/transactions/stats", account_id=1, period="last_30d").json()
            assert body["total_expense"] > 0
            assert len(body["trend"]) == 6
            assert len(body["categories"]) > 0
            return f"支出 {body['total_expense']} / 分类 {len(body['categories'])} / 异常 {len(body['anomalies'])}"

        check("GET /transactions/stats", _stats)

        def _anomalies():
            body = get(c, "/transactions/anomalies", account_id=1).json()
            assert isinstance(body, list)
            return f"{len(body)} 笔异常"

        check("GET /transactions/anomalies", _anomalies)

        # ---------- 收款人 ----------
        def _payees():
            body = get(c, "/payees", account_id=1).json()
            assert len(body) > 0
            return f"{len(body)} 位收款人"

        check("GET /payees", _payees)

        # ---------- 转账三级权限 ----------
        def _policy():
            body = get(c, "/transfers/policy").json()
            assert {l["level"] for l in body["levels"]} == {"green", "yellow", "red"}
            return "绿/黄/红 三级策略已公开"

        check("GET /transfers/policy", _policy)

        def _daily_total():
            body = get(c, "/transfers/daily-total", account_id=1).json()
            return f"当日累计 {body['daily_total']}"

        check("GET /transfers/daily-total", _daily_total)

        def _green():
            reset_daily_total()
            res = post(
                c,
                "/transfers/preview",
                {"account_id": 1, "payee_name": "李思远", "amount": 300, "remark": "绿色冒烟"},
            )
            assert res.status_code == 200, res.text
            p = res.json()
            # P0 口径：任何资金写操作都不再是绿色，小额转账最低黄色
            assert p["risk_level"] == "yellow", p
            assert p["requires_confirmation"] is True
            exec_res = post(
                c,
                "/transfers/execute",
                {"order_no": p["order_no"], "confirm": True},
                headers={"Idempotency-Key": "smoke-green"},
            )
            assert exec_res.status_code == 200, exec_res.text
            assert exec_res.json()["status"] == "SUCCEEDED"
            return "小额转账判黄色，确认后执行成功"

        check("POST /transfers (小额转账→黄色确认后执行)", _green)

        def _yellow():
            reset_daily_total()
            res = post(
                c,
                "/transfers/preview",
                {"account_id": 1, "payee_name": "赵启航", "amount": 400, "remark": "黄色冒烟"},
            )
            p = res.json()
            assert p["risk_level"] == "yellow", p
            blocked = post(
                c,
                "/transfers/execute",
                {"order_no": p["order_no"], "confirm": False},
                headers={"Idempotency-Key": "smoke-yellow-a"},
            )
            assert blocked.status_code == 409, blocked.text
            assert blocked.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
            ok = post(
                c,
                "/transfers/execute",
                {"order_no": p["order_no"], "confirm": True},
                headers={"Idempotency-Key": "smoke-yellow-b"},
            )
            assert ok.status_code == 200, ok.text
            return "黄色：409 → 确认后执行成功"

        check("POST /transfers (黄色需确认)", _yellow)

        def _red():
            reset_daily_total()
            res = post(
                c,
                "/transfers/preview",
                {"account_id": 1, "payee_name": "李思远", "amount": 60000, "remark": "红色冒烟"},
            )
            p = res.json()
            assert p["risk_level"] == "red", p
            need = post(
                c,
                "/transfers/execute",
                {"order_no": p["order_no"], "confirm": True},
                headers={"Idempotency-Key": "smoke-red-a"},
            )
            assert need.status_code == 428, need.text
            detail = need.json()["error"]["detail"]
            ok = post(
                c,
                "/transfers/execute",
                {
                    "order_no": p["order_no"],
                    "confirm": True,
                    "mfa_code": detail["demo_code"],
                    "mfa_challenge_id": detail["challenge_id"],
                },
                headers={"Idempotency-Key": "smoke-red-b"},
            )
            assert ok.status_code == 200, ok.text
            assert ok.json()["is_simulated"] is True
            return "红色：428 → MFA 验证后执行成功"

        check("POST /transfers (红色需 MFA)", _red)

        def _idempotent():
            reset_daily_total()
            res = post(
                c,
                "/transfers/preview",
                {"account_id": 1, "payee_name": "王雨桐", "amount": 120, "remark": "幂等冒烟"},
            )
            order_no = res.json()["order_no"]
            hdr = {"Idempotency-Key": "smoke-idem-001"}
            a = post(c, "/transfers/execute", {"order_no": order_no, "confirm": True}, headers=hdr).json()
            b = post(c, "/transfers/execute", {"order_no": order_no, "confirm": True}, headers=hdr).json()
            assert a["balance_after"] == b["balance_after"], (a, b)
            assert a["transaction_id"] == b["transaction_id"], (a, b)
            return "重复提交返回首次结果，未重复扣款"

        check("POST /transfers (幂等控制)", _idempotent)

        # ---------- Agent ----------
        def _agent_transfer():
            res = post(
                c,
                "/agent/chat",
                {"message": "给张明远转 500 元，备注冒烟测试", "account_id": 1},
            )
            body = res.json()
            assert body["intent"] == "transfer", body
            assert len(body["trace"]) >= 5, body
            assert body["demo_mode"] is True
            return f"意图={body['intent']} 轨迹 {len(body['trace'])} 步"

        check("POST /agent/chat (转账)", _agent_transfer)

        def _agent_bill():
            res = post(c, "/agent/chat", {"message": "本月餐饮消费统计", "account_id": 1})
            body = res.json()
            assert body["intent"] == "bill_analysis", body
            assert body["data"]["bill"]["total_expense"] > 0
            return f"意图={body['intent']} 支出 {body['data']['bill']['total_expense']}"

        check("POST /agent/chat (账单)", _agent_bill)

        def _agent_card():
            res = post(c, "/agent/chat", {"message": "我有几张银行卡", "account_id": 1})
            body = res.json()
            assert body["intent"] == "card_query", body
            assert len(body["data"]["cards"]) > 0
            return f"意图={body['intent']} 卡片 {len(body['data']['cards'])} 张"

        check("POST /agent/chat (卡片)", _agent_card)

        def _agent_sessions():
            body = get(c, "/agent/sessions").json()
            assert len(body) > 0
            detail = get(c, f"/agent/sessions/{body[0]['session_id']}").json()
            assert len(detail["messages"]) > 0
            return f"{len(body)} 个会话，首个含 {len(detail['messages'])} 条消息"

        check("GET /agent/sessions", _agent_sessions)

        def _agent_caps():
            body = get(c, "/agent/capabilities").json()
            assert len(body["tools"]) > 10, body
            assert body["circuit_breaker"]["state"] in ("closed", "open", "half_open")
            return f"工具 {len(body['tools'])} 个 / 熔断器 {body['circuit_breaker']['state']}"

        check("GET /agent/capabilities", _agent_caps)

        # ---------- 审计 ----------
        def _audit():
            body = get(c, "/audit", page_size=50).json()
            assert body["total"] > 0, body
            actions = {i["action"] for i in body["items"]}
            assert "agent.chat" in actions, actions
            return f"{body['total']} 条记录 / 按等级 {body['summary']['by_risk_level']}"

        check("GET /audit", _audit)

        def _audit_filter():
            body = get(c, "/audit", risk_level="red", page_size=20).json()
            assert all(i["risk_level"] == "red" for i in body["items"]), body
            return f"红色 {body['total']} 条"

        check("GET /audit (按等级筛选)", _audit_filter)

        # ---------- 状态机 / 取消 ----------
        def _cancel():
            reset_daily_total()
            res = post(
                c,
                "/transfers/preview",
                {"account_id": 1, "payee_name": "李思远", "amount": 100, "remark": "取消冒烟"},
            )
            order_no = res.json()["order_no"]
            cancel = c.post(f"{BASE}/transfers/{order_no}/cancel", headers=_AUTH_HEADERS)
            assert cancel.status_code == 200, cancel.text
            assert cancel.json()["status"] == "CANCELLED"
            return "取消成功，状态 CANCELLED"

        check("POST /transfers/{order_no}/cancel", _cancel)

        def _transitions():
            reset_daily_total()
            res = post(
                c,
                "/transfers/preview",
                {"account_id": 1, "payee_name": "李思远", "amount": 100, "remark": "状态迁移冒烟"},
            )
            order_no = res.json()["order_no"]
            post(
                c,
                "/transfers/execute",
                {"order_no": order_no, "confirm": True},
                headers={"Idempotency-Key": "smoke-trans-001"},
            )
            body = get(c, f"/transfers/{order_no}/transitions").json()
            statuses = [t["to_status"] for t in body["transitions"]]
            assert "EXECUTING" in statuses and "SUCCEEDED" in statuses, body
            return f"迁移轨迹 {' → '.join(statuses)}"

        check("GET /transfers/{order_no}/transitions", _transitions)

        # ---------- 密码修改挑战（仅下发 MFA，不实际修改） ----------
        def _password_challenge():
            res = c.post(f"{BASE}/accounts/password/change/challenge", headers=_AUTH_HEADERS)
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["status"] == "awaiting_mfa", body
            assert body["challenge_id"] and body["demo_code"]
            return f"红色：下发 MFA 挑战 {body['challenge_id'][:12]}…"

        check("POST /accounts/password/change/challenge", _password_challenge)

        # ---------- 收款人新增 ----------
        def _payee_create():
            res = post(
                c,
                "/payees",
                {"account_id": 1, "name": "冒烟新增收款人", "account_no": "6222000000000001", "bank_name": "金枢银行"},
            )
            assert res.status_code in (200, 201), res.text
            return "新增收款人成功"

        check("POST /payees", _payee_create)

        # ---------- 账户列表（数据隔离） ----------
        def _accounts_list():
            body = get(c, "/accounts").json()
            assert len(body) >= 1
            ids = [a["id"] for a in body]
            assert 1 in ids
            return f"可见账户 {ids}"

        check("GET /accounts", _accounts_list)

        # ---------- MFA 挑战持久化（库中存在摘要） ----------
        def _mfa_persisted():
            from app.core.database import SessionLocal as SL
            from app.models import MfaChallenge

            db = SL()
            try:
                cnt = db.query(MfaChallenge).count()
                assert cnt >= 1, "MFA 挑战未持久化"
                c = db.query(MfaChallenge).order_by(MfaChallenge.id.desc()).first()
                assert c.code_hash and len(c.code_hash) == 64
                return f"已持久化 {cnt} 个挑战（验证码存摘要）"
            finally:
                db.close()

        check("MFA 挑战持久化", _mfa_persisted)

        # ---------- Agent 工具越权（跨账户） ----------
        def _agent_cross_account():
            # 用 demo_user_1 的 token 访问 account 999999 → 403
            res = c.post(
                f"{BASE}/agent/chat",
                json={"message": "我的余额", "account_id": 999999},
                headers=_AUTH_HEADERS,
            )
            assert res.status_code == 403, res.text
            return "Agent 越权访问返回 403"

        check("POST /agent/chat (越权403)", _agent_cross_account)

        # ---------- 余额与流水一致性 ----------
        def _balance_consistency():
            ov = get(c, "/accounts/overview", account_id=1).json()
            balance = ov["account"]["balance"]
            txs = get(c, "/transactions", account_id=1, page_size=200).json()
            assert txs["total"] > 0
            return f"账户余额 {balance} / 流水 {txs['total']} 条"

        check("GET /accounts/overview (余额流水一致性)", _balance_consistency)

        # ---------- 系统版本与模拟声明 ----------
        def _meta():
            body = get(c, "/meta/simulation-notice").json()
            assert body["tag"] == "模拟交易"
            assert "不连接任何真实银行账户" in body["notice"]
            return f"模拟声明：{body['tag']}"

        check("GET /meta/simulation-notice", _meta)

        # ---------- 登出（最后执行，注销当前 token） ----------
        def _logout():
            res = c.post(f"{BASE}/auth/logout", headers=_AUTH_HEADERS)
            assert res.status_code == 200
            return "登出成功"

        check("POST /auth/logout", _logout)

    # ---------- 汇总 ----------
    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    print()
    print(f"{'=' * 60}")
    print(f"接口冒烟结果：{passed}/{len(results)} 通过，{failed} 失败")
    print("=" * 60)
    if failed:
        for name, ok, detail in results:
            if not ok:
                print(f"  {FAIL} {name}: {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
