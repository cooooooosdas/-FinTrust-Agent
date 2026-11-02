# 金枢 FinTrust Agent — P1 系统架构报告

> 阶段：V0.3.0（第三阶段：身份认证、交易状态机、MFA 持久化、密码修改）

---

## 一、新系统架构图

```
┌────────────────────────────────────────────────────────────────────────────┐
│  前端 React 18 + TS 5 + Vite 6（新增认证层）                                 │
│                                                                             │
│  Login（登录页，独立路由）──成功──► AppShell（带登出按钮 + 用户徽标）          │
│       │                                                                       │
│       └── authApi.login → sessionStorage 存 token ──┐                        │
│                                                      ▼                        │
│  client.ts  request() 自动注入 Authorization: Bearer <token>                │
│              401 → onUnauthorized() → 清 token → 跳转登录                     │
│                                                                             │
│  pages/  Dashboard · AgentWorkbench · BillAnalysis · Transfer · Cards · Audit│
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │ HTTP（Bearer Token / Idempotency-Key / X-Trace-Id）
┌──────────────────────────────────▼───────────────────────────────────────────┐
│  后端 FastAPI                                                                │
│                                                                               │
│  api/deps.py                                                               │
│    current_user（认证依赖：解析 Session → User，未认证 401）                  │
│    ensure_account_access（账户归属：非授权账户 403）                          │
│                                                                               │
│  api/routes/                                                               │
│    auth.py    登录 / 登出 / me（匿名）                                        │
│    accounts · transactions · payees · transfers · cards · agent · audit      │
│    （全部挂 current_user 依赖 + 账户归属校验）                                │
│                                                                               │
│  services/                                                                  │
│    auth_service      认证 / 会话 / 账户归属                                  │
│    password_service  密码修改（PBKDF2 + MFA）                                │
│    transfer_service  转账（七状态机 + 执行时重判 + 条件UPDATE）              │
│    card_service      挂失（持久化 MFA）                                       │
│                                                                               │
│  security/                                                                  │
│    password.py   PBKDF2-HMAC-SHA256 密码哈希 + token 哈希                    │
│    mfa.py        持久化 MFA（HMAC 摘要存码）                                 │
│    order_state.py 七状态迁移引擎（只追加审计）                                │
│    policy.py     三级权限引擎（P0 保留）                                     │
│    idempotency.py 幂等（P0 保留）                                            │
│                                                                               │
│  models/  新增 User / UserAccount / Session / MfaChallenge /                │
│           OrderStatusTransition + TransferOrder 七状态字段                   │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │ SQLAlchemy 2.0 ORM
┌──────────────────────────────────▼───────────────────────────────────────────┐
│  SQLite（WAL · 外键约束 · BEGIN IMMEDIATE 串行化写）                          │
│  users · user_accounts · sessions · mfa_challenges · order_status_transitions│
│  accounts · cards · transactions · payees · audit_logs · transfer_orders     │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、用户认证架构

### 数据模型
- **User**：`id / username(唯一) / password_hash / status / created_at / updated_at`
- **Session**：`id / user_id / token_hash(唯一) / created_at / expires_at / revoked_at`
- **UserAccount**：`user_id + account_id（唯一约束）/ permission`

### 认证流程
1. `POST /auth/login` 接收用户名密码 → `auth_service.authenticate()` 用 `verify_password()` 校验。
2. `create_session()` 用 `secrets.token_urlsafe(48)` 生成高强度随机 token，**服务端仅存 HMAC 摘要**。
3. 返回 `access_token` + 有效期（`session_ttl_minutes`，默认 12h）。
4. 前端 `sessionStorage` 存 token，`client.ts` 自动注入 `Authorization: Bearer`。
5. 每个受保护接口经 `current_user` 依赖解析 Session → User，未认证 401。
6. 登出 / 密码修改 → `revoke_session()` 撤销。

### 密码哈希
- **PBKDF2-HMAC-SHA256** + 随机盐（`secrets.token_bytes(16)`），迭代 260,000 次。
- 格式 `pbkdf2_sha256$<iter>$<salt_hex>$<hash_hex>`，校验用 `hmac.compare_digest` 恒定时间比较。
- **禁止**普通 SHA256 直接存密码。

---

## 三、账户授权模型

- 一个用户通过 `UserAccount` 表绑定多个账户，`permission` 字段标记 owner/viewer。
- `ensure_account_access(db, user, account_id)` 校验请求账户是否在授权集合，否则 403。
- 所有业务路由（accounts/transactions/payees/cards/transfers/agent/audit）逐一挂账户归属校验。
- **Agent 工具层也继承账户范围**：`agent/chat` 校验 `account_id` 归属，会话列表按授权账户过滤。

---

## 四、七状态交易状态机

```
                 ┌──────────────► EXPIRED
                 │
PENDING_CONFIRMATION ────────────► EXECUTING ──► SUCCEEDED
    │   │   │                         │
    │   │   └────────► CANCELLED      └────► FAILED
    │   └────────────► PENDING_MFA ──► EXECUTING
    │                        │            │
    │                        ├────────────► FAILED
    │                        ├────────────► CANCELLED
    │                        └────────────► EXPIRED
    └────────────► EXPIRED

终态：SUCCEEDED / FAILED / CANCELLED / EXPIRED（不可再迁移）
```

### 迁移规则（`order_state.py`）
- 统一 `transition(db, order, to_status, ...)` 引擎，禁止路由直接改 status。
- 非法迁移抛 `InvalidTransitionError`；相同状态迁移幂等。
- 每次迁移**只追加**写入 `OrderStatusTransition`（order_no / from / to / actor / reason / trace_id / created_at）。
- 时间戳字段：`confirmed_at / mfa_verified_at / executing_at / executed_at / failed_at / cancelled_at / expired_at`。

### 关键安全保证
- 未确认不能执行；未过 MFA 的红色交易不能执行。
- EXECUTING 不重复执行；SUCCEEDED 不重复扣款；FAILED 不报告成功。
- 失败通过**独立事务**落 FAILED（`_fail_order_in_new_session`），主事务回滚不丢失败记录。
- EXECUTING → 扣款 → 流水 → SUCCEEDED 在**同一 IMMEDIATE 事务**内原子完成（修复 P0 并发穿透回归）。

---

## 五、MFA 数据流（持久化）

```
用户发起红色操作（转账/挂失/密码修改）
   │
   ▼
PolicyEngine.evaluate() → RED（需 MFA）
   │
   ▼
mfa_service.issue(db, operation, account_id, target_id)
   │  secrets 生成 6 位验证码
   │  code_hash = HMAC-SHA256(secret_key, code)   ← 只存摘要
   │  落库 MfaChallenge（绑定 user/account/operation/target）
   ▼
演示模式返回明文验证码（明确标注模拟 MFA）；正式模式不返回明文
   │
   ▼（服务器重启后）
mfa_service.verify(db, challenge_id, code, expected_*)
   │  校验：存在/未消费/未过期/次数/绑定（user/account/operation/target）
   │  恒定时间比较 code_hash
   │  成功后 status=consumed + consumed_at（一次性）
   ▼
验证通过 → 继续业务
```

- 验证码**不存明文**、**不写日志**；HMAC 密钥经环境变量 `MFA_SECRET_KEY` 管理。
- 有效期 `mfa_ttl_seconds`（默认 300s），最多 `mfa_max_attempts`（5 次）错误即锁定。
- 挑战绑定 `target_id`（工单号/卡片 ID），**跨交易验证码不可复用**。

---

## 六、前后端依赖关系

| 前端 | 后端 |
|---|---|
| `pages/Login.tsx` | `POST /auth/login` |
| `client.ts`（token 注入 + 401 处理） | `current_user` 依赖 |
| `AppShell`（登出/用户徽标） | `POST /auth/logout`、`GET /auth/me` |
| 六大业务页面（原有） | 各业务路由（新增认证 + 归属校验） |
| `Transfer.tsx`（状态徽标/取消入口） | `POST /transfers/{no}/cancel`、`GET /transfers/{no}/transitions` |
| 密码修改（未来 UI） | `POST /accounts/password/change/challenge` + `/change` |

---

## 七、数据库迁移

- 脚本：`scripts/migrate_v030.py`（幂等，不重置数据）。
- 为 `transfer_orders` 新增 10 列（fail_reason/version/expires_at/6 个时间戳/…）。
- 旧状态安全映射：`ready/awaiting_confirm→PENDING_CONFIRMATION`、`awaiting_mfa→PENDING_MFA`、`executed→SUCCEEDED`、`rejected→FAILED`。
- 新建 5 张表：users / user_accounts / sessions / mfa_challenges / order_status_transitions。
- 不删除任何旧表、不清空数据、不重置余额与流水。
