# API 接口清单

> Base URL：`http://127.0.0.1:8000/api/v1`
> 交互式文档：<http://127.0.0.1:8000/docs>

## 通用约定

**成功响应**：直接返回业务对象。

**错误响应**（统一格式）：

```json
{
  "error": {
    "code": "CONFIRMATION_REQUIRED",
    "message": "该操作需要您确认后才会执行",
    "detail": { "order_no": "TR2026...", "summary": { "收款人": "赵启航", "金额": 400.0 } },
    "trace_id": "9f2c1a8b4d7e6035"
  }
}
```

| 状态码 | code | 含义 |
| --- | --- | --- |
| 400 | `INSUFFICIENT_BALANCE` | 余额不足 |
| 401 | `UNAUTHORIZED` | 未认证或会话失效 |
| 403 | `POLICY_BLOCKED` | 被安全策略拦截 |
| 403 | `PERMISSION_DENIED` | 无权访问该账户（跨账户） |
| 404 | `NOT_FOUND` | 资源不存在 |
| 409 | `CONFIRMATION_REQUIRED` | 黄色操作需用户确认 |
| 409 | `IDEMPOTENCY_CONFLICT` | 同幂等键不同参数 |
| 409 | `IDEMPOTENCY_IN_PROGRESS` | 同键请求处理中 |
| 422 | `VALIDATION_ERROR` | 参数校验失败 |
| 428 | `MFA_REQUIRED` | 红色操作需多因子验证 |
| 429 | `RATE_LIMITED` | 触发请求限流（响应含 `Retry-After` 头） |
| 503 | `CIRCUIT_OPEN` | 熔断中 |
| 503 | `LLM_UNAVAILABLE` | 模型服务不可用（已降级） |

**请求头**：`X-Trace-Id`（可选，前端自动生成）、`Idempotency-Key`（写操作必需）、`Authorization: Bearer <token>`（**除 `/health`、`/meta/*`、`/auth/login` 外的所有接口均需认证**）

---

## 认证

### `POST /auth/login`

body：`username`、`password`

```json
{
  "access_token": "5ch5y_UAF_LpC3WU...",
  "token_type": "bearer",
  "expires_in": 43200,
  "user": { "id": 1, "username": "demo_user_1", "account_ids": [1] }
}
```

> 演示账号：`demo_user_1` / `demo_user_2`，默认密码 `Demo1234!`（可用 `DEMO_USER_1_PASSWORD` / `DEMO_USER_2_PASSWORD` 覆盖）。
> 登录失败次数过多会触发限流（单 IP 10 次/分钟；用户名+IP 5 次/15 分钟），返回 429。

### `GET /auth/me`

Header：`Authorization: Bearer <token>`

```json
{ "id": 1, "username": "demo_user_1", "account_ids": [1] }
```

### `POST /auth/logout`

Header：`Authorization: Bearer <token>` —— 撤销当前会话（后续请求返回 401）。

---

## 系统

### `GET /health`

```json
{
  "status": "ok", "app": "金枢 FinTrust Agent", "version": "1.0.0",
  "environment": "development", "demo_mode": true,
  "demo_mode_notice": "当前未配置大模型 API Key……", "llm_configured": false,
  "database": "connected", "time": "2026-11-01T13:43:54.261735"
}
```

### `GET /meta/simulation-notice`

返回全局模拟交易声明。

---

## 账户

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/accounts` | 账户列表 |
| `GET` | `/accounts/overview?account_id=1` | 账户总览（余额 + 卡 + 近期流水 + 消费统计 + 收款人） |

`overview` 响应结构：

```json
{
  "account": { "id": 1, "account_no": "6217001234567890", "holder_name": "徐舒和",
               "balance": 128653.0, "available": 128153.0, "card_count": 2, ... },
  "cards": [ ... ],
  "recent_transactions": [ ... ],
  "stats": { "month": "近 30 天", "total_expense": 39318.92, "categories": [...],
             "trend": [...], "anomalies": [...] },
  "payees": [ ... ],
  "simulation_notice": "模拟交易：……"
}
```

---

## 银行卡

| 方法 | 路径 | 参数 | 权限 |
| --- | --- | --- | --- |
| `GET` | `/cards?account_id=1` | — | 🟢 |
| `GET` | `/cards/{card_id}` | — | 🟢 |
| `POST` | `/cards/virtual` | body: `card_name` `daily_limit` `expire_month`；query: `confirm` | 🟡 |
| `POST` | `/cards/freeze` | query: `card_id` `confirm` | 🟡 |
| `POST` | `/cards/lost` | body: `card_id` `reason`；query: `mfa_code` | 🔴 |

`POST /cards/virtual` 未确认时返回：

```json
{ "status": "awaiting_confirm", "risk_level": "yellow",
  "summary": { "卡片名称": "网购虚拟卡", "单日限额": 5000, "有效期": "2029/12" },
  "next_action": "confirm" }
```

`POST /cards/lost` 未验证时返回：

```json
{ "status": "awaiting_mfa", "risk_level": "red",
  "challenge_id": "mfa_486055", "demo_code": "269688", "expires_in": 300 }
```

---

## 交易与账单

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/transactions` | 分页查询。参数：`account_id` `start_date` `end_date` `category` `direction` `keyword` `min_amount` `max_amount` `page` `page_size` |
| `GET` | `/transactions/stats` | 账单统计。参数：`account_id` `month` 或 `period` |
| `GET` | `/transactions/categories` | 分类汇总 |
| `GET` | `/transactions/anomalies` | 异常交易列表 |

`period` 可选值：`current_month`（本月）、`last_month`（上月）、`last_30d`（近30天）、`last_90d`、`last_180d`，或直接传 `month=YYYY-MM`。

---

## 收款人

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/payees?account_id=1` | 收款人列表 |
| `POST` | `/payees` | 新增收款人。body: `account_id` `name` `account_no` `bank_name` `card_last4` |

---

## 转账

### `GET /transfers/policy`

返回三级权限阈值与规则说明。

### `GET /transfers/daily-total?account_id=1`

返回当日累计与三级权限阈值。

```json
{ "daily_total": 0.0, "yellow_daily_max": 1000.0, "red_daily_min": 1000.0,
  "red_single_min": 10000.0, "red_daily_total": 100000.0 }
```

> **阈值口径（V1.0.0 现行）**：日累计为唯一主判定轴 —— 写操作执行后当日累计 ≤ ¥1,000 → 黄色（需用户确认）；> ¥1,000 → 红色（强制 MFA）；> ¥100,000 → 直接阻断。单笔 ≥ ¥10,000 为辅助升红因子。只读操作保持绿色。

### `POST /transfers/preview`

body：`account_id`、`payee_id` / `payee_name` / `payee_account_no`（三者之一）、`amount`、`remark`

响应：

```json
{
  "order_no": "TR202611011351331392",
  "risk_level": "red",
  "risk": { "level": "red", "label": "红色 · 需多因子验证", "color": "rose",
            "reason": "执行后当日累计 2300.00 元超过 1000.00 元红线。",
            "rules": ["执行后当日累计 > 1000.00 元 → 红色"] },
  "daily_total_before": 800.0, "daily_total_after": 2300.0, "daily_limit_remaining": 0.0,
  "payee_name": "张明远", "masked_payee_account_no": "6212****7890",
  "amount": 1500.0, "remark": "项目尾款",
  "next_action": "mfa", "requires_confirmation": true, "requires_mfa": true,
  "is_simulated": true, "simulation_notice": "模拟交易 · ……"
}
```

### `POST /transfers/execute`

Header：`Idempotency-Key: <uuid>`（必填）
body：`order_no`、`confirm`、`mfa_code`、`mfa_challenge_id`

| 等级 | 请求 | 结果 |
| --- | --- | --- |
| 🟢 | `{"order_no":"...","confirm":true}` | `200` 执行成功 |
| 🟡 | 不带 confirm | `409 CONFIRMATION_REQUIRED` |
| 🟡 | 带 confirm | `200` 执行成功 |
| 🔴 | 不带 mfa_code | `428 MFA_REQUIRED` + `demo_code` |
| 🔴 | 错误验证码 | `428 MFA_REQUIRED`（提示剩余次数） |
| 🔴 | 正确验证码 | `200` 执行成功 |

成功响应：

```json
{ "order_no": "TR2026...", "status": "SUCCEEDED", "transaction_id": 474,
  "amount": 1500.0, "payee_name": "李思远", "balance_after": 126853.0,
  "is_simulated": true, "simulation_notice": "模拟交易 · ……",
  "message": "已模拟交易：向 李思远 转账 1500.00 元" }
```

> `status` 取七状态之一：`PENDING_CONFIRMATION` / `PENDING_MFA` / `EXECUTING` / `SUCCEEDED` / `FAILED` / `CANCELLED` / `EXPIRED`。

### `POST /transfers/{order_no}/cancel`

取消待确认 / 待验证的工单。终态（`SUCCEEDED`/`FAILED`/`CANCELLED`/`EXPIRED`）不可取消，返回 403。

```json
{ "order_no": "TR2026...", "status": "CANCELLED", "message": "工单已取消" }
```

### `GET /transfers/{order_no}/transitions`

返回该工单的完整状态迁移轨迹（只追加审计）。

```json
{ "order_no": "TR2026...", "transitions": [
    { "from_status": "PENDING_CONFIRMATION", "to_status": "EXECUTING",
      "actor": "demo_user_1", "reason": "开始执行资金操作", "created_at": "..." }
] }
```

---

## AI 助手

### `POST /agent/chat`

body：`message`、`session_id`（可选）、`account_id`

```json
{
  "session_id": "sess_3a2b...", "message_id": 12,
  "reply": "已为你生成转账方案（黄色 · 需确认）：\n- 收款人：张明远（6212****7890）……",
  "intent": "transfer", "intent_label": "智能转账", "confidence": 0.92,
  "risk_level": "yellow", "demo_mode": true,
  "demo_mode_notice": "当前未配置大模型 API Key……",
  "trace": [
    { "step": 1, "node": "intent_recognition", "title": "意图识别与参数抽取",
      "status": "success", "detail": "智能转账（置信度 0.92）— 命中「转账/汇款」关键词",
      "duration_ms": 1, "payload": { "intent": "transfer", "slots": {...} } },
    { "step": 2, "node": "task_planning", "title": "任务规划（生成 DAG）", ... }
  ],
  "actions": [ { "kind": "transfer_preview", "title": "转账方案", "fields": {...} } ],
  "data": { "transfer": { ... } }
}
```

支持意图：`transfer` `bill_analysis` `card_query` `card_virtual_apply` `card_lost`
`card_freeze` `account_overview` `payee_query` `audit_query` `help` `unknown`

### `GET /agent/sessions` / `GET /agent/sessions/{session_id}`

### `GET /agent/capabilities`

```json
{
  "demo_mode": true, "demo_mode_notice": "……", "llm_model": "本地规则引擎",
  "llm_base_url": null,
  "tools": ["capabilities", "evaluate_policy", "fetch_transactions", ...],
  "circuit_breaker": { "name": "llm", "state": "closed", "failures": 0, "threshold": 5 },
  "intents": ["transfer", "bill_analysis", ...]
}
```

---

## 安全审计

### `GET /audit`

参数：`risk_level`（`green`/`yellow`/`red`）、`action`（模糊匹配）、`page`、`page_size`

```json
{
  "items": [
    { "id": 1, "actor": "demo-user", "action": "transfer.executed",
      "target_type": "transaction", "target_id": "8802",
      "risk_level": "green", "decision": "allow",
      "reason": "金额与收款人均在常规区间，自动执行。",
      "detail": { "order_no": "TR2026...", "amount": 300.0, "is_simulation": true },
      "ip_address": "127.0.0.1", "is_simulation": true,
      "created_at": "2026-11-01T13:02:00" }
  ],
  "total": 34, "page": 1, "page_size": 20,
  "summary": { "by_risk_level": { "green": 10, "yellow": 8, "red": 16 },
               "by_decision": { "allow": 20, "confirm": 6, "mfa": 5, "block": 3 },
               "total": 34 }
}
```

### `GET /audit/integrity`

验证审计哈希链完整性（只读，不修改任何数据）。返回 `PASS` / `FAILED` 及首个异常记录定位。

```json
{
  "status": "AUDIT INTEGRITY: PASS",
  "passed": true,
  "detail": { "total": 42, "checked": 42 },
  "verified_at": "2026-11-02T17:30:00"
}
```

检测到篡改时：

```json
{
  "status": "AUDIT INTEGRITY: FAILED",
  "passed": false,
  "detail": { "sequence_id": 17, "audit_id": 42, "reason": "event_hash 校验失败（记录被修改或密钥不一致）" },
  "verified_at": "2026-11-02T17:30:00"
}
```

> 哈希链 + HMAC 可**检测**记录篡改 / 删除 / 重排，但不能声称在数据库管理员与密钥同时被攻破时仍绝对不可篡改。

---

## 密码修改

### `POST /accounts/password/change/challenge`

Header：`Authorization: Bearer <token>` —— 申请修改密码的 MFA 挑战（红色操作）。

```json
{
  "status": "awaiting_mfa",
  "challenge_id": "mfa_72c22d9e...",
  "demo_code": "836276",
  "expires_in": 300
}
```

> 演示模式直接返回明文验证码；正式模式 `demo_code` 为 `null`。

### `POST /accounts/password/change`

Header：`Authorization: Bearer <token>`

body：`old_password`、`new_password`、`mfa_code`、`mfa_challenge_id`

```json
{ "status": "changed", "message": "密码已修改，请重新登录" }
```

校验项：旧密码正确 + MFA 有效 + 新密码 ≥8 位含字母数字 + 新旧不同。成功后**撤销该用户全部会话**（旧 token 立即失效，需重新登录）。
