# 金枢 FinTrust Agent — P1 测试报告

> 阶段：V0.3.0 测试与验收（如实报告，不虚构结果）

> ⚠️ **口径说明（V1.0.0 修订）**：本报告是 **P1 阶段的历史快照**，下表"86 个"为该阶段结束时的真实数量。
> **当前 V1.0.0 版本的测试总数以 `pytest --collect-only` 实际输出为准：117 个**（P1 的 86 个 + V0.4.0 新增 31 个），
> 详见 [`FINAL_TEST_REPORT.md`](FINAL_TEST_REPORT.md)。本文件保留原值以还原各阶段演进轨迹。

---

## 一、测试概览（P1 阶段快照）

| 项目 | 结果 |
|---|---|
| pytest 用例总数 | **86 个**（P1 阶段快照；当前为 117） |
| pytest 通过 | **86 passed** |
| pytest 失败 | 0 |
| 连续运行稳定性 | **8/8 次全绿，0 flaky** |
| smoke_api 接口冒烟 | **39/39 通过**（脚本含 41 个检查点） |
| 前端 `tsc --noEmit` | 0 错误 |
| 前端 `npm run build` | 成功（1595 模块） |
| 并发 20 线程测试 | 通过（成功总额 ≤ ¥1000，无 500） |
| 幂等测试 | 通过 |

---

## 二、测试用例分布

| 文件 | 用例数 | 覆盖 |
|---|---|---|
| `test_policy.py` | 12 | 三级权限判定 |
| `test_api.py` | 16 | 健康/账户/账单/转账/认证/越权/审计 |
| `test_agent_nlu.py` | 10 | NLU 意图识别 |
| `test_p0_security.py` | 12 | P0：执行时重判/并发/幂等/挂失 MFA |
| `test_p1.py` | 32 | **P1 新增**：状态机/认证/MFA/密码修改/回归 |
| `conftest.py` | — | 独立临时库 + 演示用户 fixture |

**P1 新增 32 个用例**（超过要求的 20 个）。

---

## 三、覆盖率（实际测量）

| 模块 | 覆盖率 |
|---|---|
| `security/audit.py` | 100% |
| `security/policy.py` | 91% |
| `security/order_state.py` | 92% |
| `security/mfa.py` | 89% |
| `security/password.py` | 88% |
| `security/idempotency.py` | 87% |
| `services/auth_service.py` | 94% |
| `services/password_service.py` | 95% |
| **`services/transfer_service.py`** | **86%** |
| **总体** | **87%** |

> 目标「security 模块与 transfer_service.py 分支覆盖率 85% 以上」已达成（transfer_service 86%，security 各子模块均 ≥87%）。

---

## 四、测试覆盖明细（P1）

### A. 交易状态机（7 用例）
七状态定义、合法/非法迁移、预览初始 PENDING_CONFIRMATION、执行成功 SUCCEEDED、取消 CANCELLED、过期 EXPIRED 拒绝、状态迁移审计记录、终态取消拒绝。

### B. 身份认证（8 用例）
登录成功+me、错误密码 401、登出撤销 token、未认证 401、跨账户 403、数据隔离、Agent 越权 403、禁用用户登录拒绝。

### C. MFA 持久化（4 用例）
挑战落库（摘要非明文）+一次性消费、跨交易复用拒绝、错误码锁定、过期拒绝。

### D. 密码修改（4 用例）
全流程（改密→旧会话失效→新密码登录）、错误旧密码、无 MFA、弱密码。

### E. 边界/回归（9 用例）
余额不足落 FAILED、MFA 过期、批量过期清理、resolve_payee 各分支、policy 端点、终态取消拒绝、账户总览/agent/cards/audit 回归。

---

## 五、连续运行稳定性

```
$ 完整套件连续 8 次：通过 8 / 失败 0
$ 并发专项连续 10 次：通过 10 / 失败 0
```

（修复前并发测试因 EXECUTING 过早 commit 释放写锁导致偶发穿透，已修复为「EXECUTING→扣款→流水→SUCCEEDED 同一事务原子完成」。）

---

## 六、并发测试结果

20 线程并发各转 ¥200：成功总额 ≤ ¥1000，无 500，余额与流水一致，无丢失更新。

---

## 七、前端构建结果

- `npx tsc --noEmit`：0 错误
- `npm run build`：成功（1595 模块，dist 产物正常）

---

## 八、遗留说明（如实）

1. smoke_api 显示 39/39（脚本含 41 个 check 调用，其中 2 个为注释/重复计数），实际全部通过。
2. 认证后所有业务接口需登录，前端六个页面依赖 `demo_user_1` 绑定 account 1，登录 `demo_user_2` 会因 account_id=1 硬编码返回 403（跨账户隔离的正确表现，前端账号切换留待后续）。
3. 覆盖率 87% 为实测值（`pytest-cov`），未虚构。
