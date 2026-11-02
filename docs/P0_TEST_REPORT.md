# 金枢 FinTrust Agent — P0 测试报告

> 阶段：V0.2.0 第二阶段（P0 安全修复）
> 测试环境：独立临时数据库（不污染演示库）+ FastAPI TestClient + 真实 HTTP 并发
> 原则：**如实报告，不虚构结果**

---

## 一、测试概览

| 项目 | 结果 |
|---|---|
| pytest 用例总数 | **52 个** |
| pytest 通过 | **52 passed** |
| pytest 失败 | 0 |
| flaky 率（连续 10 次运行） | **0%（10/10 全绿）** |
| smoke_api 接口冒烟 | **26/26 通过** |
| 前端 `tsc --noEmit` | **0 错误** |
| 前端 `npm run build` | **成功** |

---

## 二、pytest 用例分布

| 文件 | 用例数 | 覆盖内容 |
|---|---|---|
| `test_policy.py` | 12 | 三级权限判定（绿/黄/红/阻断/敏感操作/解释性） |
| `test_api.py` | 14 | 健康检查、账户、账单、转账三级权限、幂等、agent、审计 |
| `test_agent_nlu.py` | 10 | NLU 意图识别与参数抽取 |
| `test_p0_security.py` | 12 | **本轮新增**：执行时重判/并发/幂等/挂失 MFA/工单唯一 |
| `conftest.py` | — | 独立临时库夹具 |

---

## 三、P0 专项测试明细（`test_p0_security.py`）

### A. 权限测试
- `test_policy_readonly_green` — 策略面板绿色含「只读」语义
- `test_transfer_preview_is_yellow_for_small_amount` — ¥100 转账 → 黄色 + 需确认
- `test_transfer_preview_red_when_daily_over_1000` — 累计 ¥900 再转 ¥200 → 红色 + 需 MFA

### B. 执行时重判测试
- `test_execution_time_reevaluation_escalates` — 预览黄，执行前累计超限 → 428 MFA_REQUIRED，**余额不变**
- `test_execution_after_mfa_rechecks` — MFA 通过后再次重判

### C. 并发测试
- `test_concurrent_transfers_do_not_breach_daily_limit` — 20 线程各 ¥200，成功总额 ≤ ¥1000，无 500
- `test_concurrent_same_key_no_500` — 10 线程同键并发，只扣一次，无 500

### D. 幂等测试
- `test_idempotency_same_key_10_times_debit_once` — 同键 10 次 → 只扣一次、同一 transaction_id
- `test_idempotency_same_key_different_params_conflict` — 同键异参 → 409 IDEMPOTENCY_CONFLICT
- `test_two_independent_transfers_use_different_keys` — 不同键 → 两笔独立交易

### E. MFA 挂失测试
- `test_card_lost_end_to_end` — 发起→错误码 422→正确码 lost→重复码拒绝（4 步断言）

### F. 工单唯一性
- `test_100_orders_all_unique` — 连续 100 个工单号全部唯一

---

## 四、稳定性验证（flaky 消除）

修复前（审计轮实测）：连续 12 次运行，`test_insufficient_balance_is_rejected` 因工单号冲突随机失败，flaky ≈ 8.3%。

修复后实测：

```
$ 完整套件连续 10 次：通过 10 / 失败 0
$ 并发专项连续 10 次：通过 10 / 失败 0
```

工单号已改为 `uuid4`，UNIQUE 冲突根因消除。

---

## 五、smoke_api 冒烟结果

对独立库（`smoke_p0.db`）+ 独立实例（8001）运行，结果 26/26：

```
✓ GET /health
✓ GET /accounts/overview
✓ GET /cards / GET /cards/{id}
✓ POST /cards/virtual（需确认/确认后）
✓ POST /cards/freeze
✓ POST /cards/lost（需 MFA）
✓ GET /transactions（分页/筛选）
✓ GET /transactions/stats / anomalies
✓ GET /payees
✓ GET /transfers/policy / daily-total
✓ POST /transfers（小额→黄色确认后执行）
✓ POST /transfers（黄色需确认：409→执行）
✓ POST /transfers（红色需 MFA：428→执行）
✓ POST /transfers（幂等控制：重复提交不重复扣款）
✓ POST /agent/chat（转账/账单/卡片）
✓ GET /agent/sessions / capabilities
✓ GET /audit（全量/按等级筛选）
```

唯一调整：原「绿色直接执行」用例改为「小额转账→黄色确认后执行」，符合 P0 新口径。

---

## 六、前端检查结果

| 检查项 | 结果 |
|---|---|
| `npx tsc --noEmit` | 0 错误 |
| `npm run build` | ✓ built in 36.69s（1594 模块） |
| 转账页渲染（无头 Chrome 截图） | 正常，三级策略面板显示新阈值（黄 ≤¥1000 / 红 >¥1000） |
| 挂失 MFA 端到端（演示实例实测） | 正确验证码 → 卡片状态 lost |

---

## 七、遗留问题（如实声明）

1. **认证/授权未做**（P1-T2 范围）：`account_id` 仍可由调用方任意指定。
2. **状态机未落地 7 态**（P1-T1）：失败交易仍以抛异常方式处理，未持久化 FAILED 状态。
3. **密码修改仅完成策略判定**，接口未实现（P1-T3）。
4. **MFA 挑战仍存进程内**，重启丢失（已改 CSPRNG，未做持久化）。
5. 并发测试在 SQLite 单写者模型下通过，但在真实多连接生产数据库上仍需以行锁/事务隔离复核（当前为竞赛演示环境，SQLite 方案已满足「不穿透」要求）。
