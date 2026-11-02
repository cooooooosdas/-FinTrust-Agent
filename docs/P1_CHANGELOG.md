# 金枢 FinTrust Agent — P1 变更记录（Changelog）

> 阶段：V0.3.0（身份认证、交易状态机、MFA 持久化、密码修改）

---

## 一、修改文件清单

### 后端新增
| 文件 | 说明 |
|---|---|
| `app/security/password.py` | PBKDF2-HMAC-SHA256 密码哈希 + token 哈希 |
| `app/security/order_state.py` | 七状态迁移引擎 + 只追加审计 |
| `app/services/auth_service.py` | 认证/会话/账户归属 |
| `app/services/password_service.py` | 密码修改 |
| `app/api/routes/auth.py` | 登录/登出/me |
| `scripts/migrate_v030.py` | 数据库迁移脚本 |
| `tests/test_p1.py` | P1 专项测试（32 用例） |

### 后端修改
| 文件 | 改动 |
|---|---|
| `app/models/__init__.py` | 新增 User/UserAccount/Session/MfaChallenge/OrderStatusTransition；TransferOrder 加 10 列 |
| `app/security/mfa.py` | 重写为持久化（HMAC 摘要存码，绑定 user/account/operation/target） |
| `app/services/transfer_service.py` | 七状态机 + 执行时重判 + 失败独立事务 + 并发修复 + cancel/expire |
| `app/services/card_service.py` | 挂失接入持久化 MFA + actor |
| `app/core/config.py` | 新增 session_ttl/order_ttl/mfa_ttl/mfa_secret/auth_secret/demo 密码等配置 |
| `app/core/database.py` | 连接池（P0 已有，沿用） |
| `app/core/errors.py` | 新增 UnauthorizedError |
| `app/api/deps.py` | 新增 current_user/ensure_account_access 等认证依赖 |
| `app/api/routes/{accounts,transactions,payees,cards,transfers,agent,audit}.py` | 全部挂认证 + 账户归属校验；transfers 加 cancel/transitions；accounts 加密码修改 |
| `app/main.py` | 注册 auth 路由 + 启动引导演示用户 + 过期工单清理 |
| `app/agent/orchestrator.py` | chat 接受 actor，审计写真实主体 |
| `app/schemas/__init__.py` | TransferPolicyInfo 加 red_daily_min |
| `scripts/smoke_api.py` | 支持登录 + 认证头 + 扩展至 41 检查点 + 业务时区 reset |

### 前端
| 文件 | 改动 |
|---|---|
| `src/pages/Login.tsx` | 新增登录页 |
| `src/App.tsx` | 认证门控 + 401 跳转 |
| `src/layouts/AppShell.tsx` | 登出按钮 + 用户徽标 |
| `src/api/client.ts` | token 管理 + 自动注入 Bearer + 401 处理 |
| `src/api/index.ts` | authApi + transferApi.execute 接受幂等键 |
| `src/types/index.ts` | LoginResponse/CurrentUser 类型 |
| `src/pages/Transfer.tsx` | 稳定幂等键（P0 已有） |

---

## 二、数据库迁移记录

- `scripts/migrate_v030.py`（幂等）：
  - `transfer_orders` 新增列：`fail_reason / version / expires_at / confirmed_at / mfa_verified_at / executing_at / executed_at / failed_at / cancelled_at / expired_at`
  - 旧状态映射：`ready/awaiting_confirm→PENDING_CONFIRMATION`、`awaiting_mfa→PENDING_MFA`、`executed→SUCCEEDED`、`rejected→FAILED`
  - 新建表：`users / user_accounts / sessions / mfa_challenges / order_status_transitions`
- 演示库迁移实测：新增 10 列 + 5 个旧工单状态映射，余额与流水未重置。

---

## 三、API 变化

### 新增
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/auth/login` | 登录，返回 access_token |
| POST | `/auth/logout` | 登出（撤销会话） |
| GET | `/auth/me` | 当前用户信息 |
| POST | `/transfers/{order_no}/cancel` | 取消工单 |
| GET | `/transfers/{order_no}/transitions` | 状态迁移审计记录 |
| POST | `/accounts/password/change/challenge` | 申请改密（下发 MFA） |
| POST | `/accounts/password/change` | 修改密码（校验旧密码+MFA） |

### 变更
- 所有业务接口需 `Authorization: Bearer <token>`，未认证 401，跨账户 403。
- `TransferResult.status` 由 `executed` 改为 `SUCCEEDED`（七状态机）。
- `/transfers/policy` 返回新增 `red_daily_min` 字段。

---

## 四、前端变化

- 新增登录页（金枢品牌 + 用户名/密码 + 演示账号说明）。
- 认证门控：未登录跳登录页；401 自动退出。
- token 存 sessionStorage，刷新恢复；登出按钮在顶栏。
- 请求自动附带 Bearer token。

---

## 五、兼容性说明

- 旧工单/旧交易数据可读（迁移脚本安全映射旧状态）。
- 演示库未重置，账户余额与流水保留。
- P0 的三级权限、执行时重判、幂等、并发安全机制全部保留并通过回归。
- 演示账号：`demo_user_1`（账户一）、`demo_user_2`（账户二），密码默认 `Demo1234!`（环境变量可覆盖）。
