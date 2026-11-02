# 金枢 FinTrust Agent — P1 安全报告

> 阶段：V0.3.0（身份认证、账户归属、会话管理、MFA 持久化、密码修改）

---

## 一、身份认证实现

| 项 | 实现 |
|---|---|
| 用户模型 | `User(username 唯一, password_hash, status)` |
| 密码哈希 | PBKDF2-HMAC-SHA256 + 随机盐（260,000 迭代），`hmac.compare_digest` 恒定时间比较 |
| 登录接口 | `POST /auth/login` → 校验密码 → 签发 Session Token |
| Token 生成 | `secrets.token_urlsafe(48)` 高强度随机 |
| Token 存储 | 服务端仅存 HMAC-SHA256 摘要（`Session.token_hash`），不存明文 |
| Token 有效期 | `session_ttl_minutes`（默认 12 小时），过期拒绝 |
| 登出/撤销 | `POST /auth/logout` + `revoke_all_sessions`（密码修改后） |
| 禁用用户 | `status != active` 拒绝登录 |

**禁止项落实**：不允许固定 demo-user 作为默认身份；不允许伪造 actor 绕过认证（actor 取自认证后的 `user.username`）；密码和 token 不写日志。

---

## 二、账户归属校验

- 每个受保护接口通过 `current_user` 解析用户，再经 `ensure_account_access` 校验账户归属。
- 非授权账户 → 403 `PERMISSION_DENIED`；无有效身份 → 401 `UNAUTHORIZED`。
- 覆盖全部业务路由：accounts / transactions / payees / cards / transfers / agent / audit。
- **Agent 工具层继承账户范围**：`agent/chat` 校验 account_id，会话列表按授权账户过滤，杜绝工具绕过账户权限。
- 健康检查 `/health`、`/meta/*`、登录 `/auth/login` 保持匿名。

---

## 三、会话管理

- Session 表存 token 哈希 + 有效期 + 撤销时间。
- 服务端撤销：登出即 revoke，密码修改撤销该用户全部会话。
- 过期 Session 在 `resolve_session` 时拒绝。
- 前端 `sessionStorage` 存 token（刷新恢复，不持久化密码），401 自动跳登录。

---

## 四、MFA 持久化

- `MfaChallenge` 表持久化挑战，服务器重启后仍可验证。
- 验证码 `secrets` 生成，**仅存 HMAC-SHA256 摘要**（`MFA_SECRET_KEY` 环境变量管理），不存明文、不写日志。
- 挑战绑定 `user_id / account_id / operation / target_id`，跨用户/账户/操作/目标复用一律拒绝。
- 默认有效期 300s，最多 5 次错误即锁定，成功后一次性消费。
- 演示模式向前端返回明文验证码并明确标注；正式模式不返回明文。

---

## 五、密码修改安全设计

流程：申请 challenge（PolicyEngine 判 PASSWORD_CHANGE 红色）→ MFA 挑战持久化 → 校验旧密码 + MFA + 新密码策略 → 更新哈希 → 撤销旧会话 → 审计。

| 校验 | 说明 |
|---|---|
| 旧密码 | `verify_password` 校验，错误返回 `OLD_PASSWORD_INVALID` |
| MFA | 绑定 user + operation + target，错误/缺失拒绝 |
| 新密码 ≠ 旧密码 | 相同返回 `PASSWORD_SAME` |
| 密码强度 | ≥8 位且含字母+数字，否则 `PASSWORD_WEAK` |
| 失败原子性 | 任何失败前不更新密码哈希 |

密码修改接口**不能绕过 PolicyEngine**（`request_password_change` 显式调用 `policy_engine.evaluate(PASSWORD_CHANGE)`）。

---

## 六、已知风险与限制

| 风险/限制 | 说明 |
|---|---|
| 演示密码默认值 | `demo_user_1/2` 密码默认 `Demo1234!`（仅演示，可通过环境变量覆盖；生产必须改） |
| Session token 无刷新机制 | 固定有效期，过期需重新登录（竞赛 MVP 可接受） |
| MFA 验证码演示明文回传 | 仅 `demo_mode` 下；正式模式返回 None |
| SQLite 单写者 | 并发写由 BEGIN IMMEDIATE 串行化，适合竞赛演示；生产需换行锁数据库 |
| 无请求限流 | 留待 P2（任务明确禁止本轮实现） |
| 无刷新 token / 记住登录 | sessionStorage 关闭即失效（安全优先） |

---

## 七、安全结论

本阶段完成后，金枢具备：
- **可验证**的身份认证（PBKDF2 + 服务端仅存 token 摘要）
- **不可绕过**的账户访问控制（后端强制，Agent 工具层同样受限）
- **可追踪**的交易生命周期（七状态机 + 只追加迁移审计）
- **可持久化**的 MFA（HMAC 摘要 + 跨重启验证 + 绑定校验）
- **不可伪造**的审计主体（真实会话用户名替代 demo-user）

核心目标「可验证、可追踪、不可随意绕过的身份与交易安全体系」已达成。
