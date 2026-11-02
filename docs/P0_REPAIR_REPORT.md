# 金枢 FinTrust Agent — P0 核心安全修复报告

> 阶段：V0.2.0 第二阶段（P0 安全修复与业务闭环加固）
> 依据：`docs/AUDIT_V0.2.0.md` 实测确认的问题清单
> 原则：不推翻架构、不重写业务、不改 UI、大模型不参与授权、全部模拟银行系统

---

## 一、修改文件清单

### 后端（10 个文件）

| 文件 | 改动 |
|---|---|
| `app/security/policy.py` | 重写策略引擎：日累计主轴、绿色仅限只读、新增 `ActionType.PASSWORD_CHANGE`、`red_daily_min` 阈值 |
| `app/core/config.py` | 阈值改为赛事口径（黄 ¥1000 / 红 ¥1000 / 单笔辅助升红 ¥10000 / 硬红线 ¥100000）；新增 `business_timezone=Asia/Shanghai` |
| `app/services/transfer_service.py` | 工单号改 uuid4；`daily_transfer_total` 用业务时区窗口；`execute_transfer` 执行时重判 + 条件 UPDATE 原子扣款 + `BEGIN IMMEDIATE` 串行化 + MFA 挑战持久化不重发 |
| `app/services/card_service.py` | 挂失 MFA 修复：challenge_id 持久化复用，校验不重新发码 |
| `app/security/mfa.py` | `random` → `secrets`（CSPRNG）；新增 `get_active_by_operation`（不重发码） |
| `app/security/idempotency.py` | `begin()` 捕获 IntegrityError 并发竞态；新增 TTL 清理 |
| `app/core/database.py` | SQLite 连接池扩容（size 30 / overflow 30）+ `timeout=30` + `check_same_thread=False` |
| `app/api/routes/cards.py` | 挂失路由透传 `mfa_challenge_id` |
| `scripts/smoke_api.py` | 支持 `SMOKE_BASE` 环境变量；「绿色转账」用例改为「小额转账→黄色」口径 |

### 前端（4 个文件）

| 文件 | 改动 |
|---|---|
| `src/api/client.ts` | 新增 `createIntentIdempotencyKey()`（用户意图级稳定 UUID） |
| `src/api/index.ts` | `transferApi.execute` 接受显式幂等键；`cardApi.reportLost` 透传 `mfa_challenge_id` |
| `src/pages/Transfer.tsx` | 一次意图持有稳定幂等键（预览/执行/重试复用），reset 时重新生成 |
| `src/pages/Cards.tsx` | 挂失记录 `challenge_id` 并透传给后端 |

### 测试（2 个文件）

| 文件 | 改动 |
|---|---|
| `tests/test_policy.py` | 重写为日累计主轴口径（12 用例） |
| `tests/test_api.py` | 更新转账三级权限用例 + agent 用例补 `_seed` 消除顺序依赖 |
| `tests/test_p0_security.py` | **新增** 12 个 P0 专项测试（执行时重判/并发/幂等/挂失 MFA/工单唯一） |

---

## 二、每个漏洞的原始根因与修复方案

### 漏洞 1：策略判定轴与赛事口径错位

**根因**：`policy.py` 的 `_evaluate_transfer` 以**单笔金额**为主轴（¥5000/¥50000），
`yellow_single_max` 被同时复用为单笔黄线和日累计黄线；小额转账落到 `GREEN` 分支自动执行，
违反「任何资金写操作绝不能绿色」；且无「密码修改」动作类型。

**修复**：改为**日累计单轴**判定——
- 绿色：仅 `READ_ONLY_ACTIONS`（查询/账单/分析/审计）。
- 黄色：写操作且 `执行后日累计 ≤ ¥1000`（含恰好 1000）。
- 红色：`执行后日累计 > ¥1000`，或挂失/密码修改等 `MFA_REQUIRED_ACTIONS`。
- 单笔金额作为**辅助升红**（≥ ¥10000），不替代日累计判断。
- 新增 `ActionType.PASSWORD_CHANGE` → `MFA_REQUIRED_ACTIONS`。

### 漏洞 2：执行阶段不重新判定风险

**根因**：`execute_transfer()` 直接 `json.loads(order.policy_json)` 复用预览快照，
既不重读当日累计，也不重调 `policy_engine.evaluate()`。

**修复**：执行时在同一 `BEGIN IMMEDIATE` 事务内——
1. 重读账户；2. 重算 `daily_transfer_total`；3. 重新 `policy_engine.evaluate()`；
4. 按最新判定走确认/MFA/阻断；5. 权限升级（预览黄→执行红）时不得扣款、持久化 MFA 挑战、返回 428；
6. **反向不降级**：预览为红，执行时即使累计下降仍要求 MFA；
7. MFA 通过后再完整重判一次，防止验证窗口内累计又变化。

### 漏洞 3：并发绕过日累计限制

**根因**：余额读改写无行锁；执行路径不重算累计；SQLAlchemy 默认 autobegin 让手写
`BEGIN IMMEDIATE` 失效，6 笔并发各自基于同一份陈旧累计值通过校验。

**修复**：
- `_begin_immediate()` 先回滚 autobegin 隐式事务，再在底层连接执行 `BEGIN IMMEDIATE`，
  让事务从一开始持有写锁，串行化并发写（SQLite 单写者模型）。
- 余额扣减改为**条件 UPDATE**：`UPDATE accounts SET balance_cents = balance_cents - :amt WHERE id=:id AND balance_cents >= :amt`，按受影响行数判断。
- 连接池扩容 + `timeout=30`，避免并发线程连接池耗尽导致 500。

### 漏洞 4：幂等键兜底导致重复扣款 / 幂等 begin 竞态

**根因**：`key = idempotency_key or payload.order_no`，而 order_no 每次预览都不同 →
两次预览同一逻辑转账 → 两个键 → 扣两次；`begin()` 的 SELECT-then-INSERT 未捕获并发
IntegrityError；前端每次调用现生成随机键。

**修复**：
- 前端一次意图生成**一个稳定 UUID**（`createIntentIdempotencyKey`），预览/执行/重试复用。
- `begin()` 捕获 `IntegrityError` 后重查，返回已有记录而非 500。
- 幂等记录新增 TTL 清理，避免 `in_progress` 残留永久阻塞。
- 服务端 `execute_transfer` 内「已 executed 幂等返回首次结果」兜底，同一工单仅一次成功扣款。

### 漏洞 5：工单号冲突（flaky 8.3%）

**根因**：`order_no = f"TR...{id(decision) % 10000:04d}"`，`id()` 是 CPython 内存地址，
GC 复用后同秒两笔可能生成相同 order_no，命中 UNIQUE 约束 → 500。

**修复**：`order_no = f"TR{utcnow():%Y%m%d%H%M%S}{uuid.uuid4().hex[:8].upper()}"`。

### 漏洞 6：银行卡挂失 MFA 链路不通

**根因**：`report_card_lost()` 校验阶段用 `mfa_card_{id}` 去取首次下发的随机 challenge_id，
取不到 → 又 `issue()` 一个新码 → 用户输入的有效码必然 422。

**修复**：发起时下发并透传唯一 `challenge_id`；校验阶段**复用同一 challenge_id**，绝不重新
发码；`mfa.py` 改用 `secrets`（CSPRNG）；验证码一次性消费。

---

## 三、关键代码实现说明

### 1. 日累计主轴（policy.py 核心片段）

```python
# 资金写操作绝不能是绿色，最低黄色
level = YELLOW
requires_confirmation = True
# 主轴：执行后日累计是否超过 1000 元
if after_cents > self.red_daily_min_cents:   # > ¥1000 → 红
    level = RED; requires_mfa = True
else:                                        # ≤ ¥1000（含恰好）→ 黄
    level = YELLOW
# 单笔辅助升红（不替代日累计）
if amount_cents >= self.red_single_min_cents:  # ≥ ¥10000
    level = RED; requires_mfa = True
```

### 2. 执行时重判 + 原子扣款（transfer_service.py 核心片段）

```python
_begin_immediate(db)                    # 写锁串行化
daily_before = daily_transfer_total(db, order.account_id)
decision = policy_engine.evaluate(...)  # 重新判定，不信任快照
...
result = db.execute(                    # 条件 UPDATE 原子扣款
    update(Account)
    .where(Account.id == account.id, Account.balance_cents >= amount)
    .values(balance_cents=Account.balance_cents - amount)
)
if result.rowcount != 1:                # 余额不足 → 拒绝
    raise AppError(...INSUFFICIENT_BALANCE...)
```

### 3. BEGIN IMMEDIATE 串行化

```python
def _begin_immediate(db):
    if not settings.database_url.startswith("sqlite"): return
    if db.in_transaction(): db.rollback()   # 结束 autobegin 隐式事务
    conn = db.connection()
    conn.exec_driver_sql("BEGIN IMMEDIATE") # 从一开始持有写锁
```

### 4. 挂失 MFA 复用挑战（card_service.py 核心片段）

```python
challenge = mfa_service.get(mfa_challenge_id) if mfa_challenge_id else None
if challenge is None:
    challenge = mfa_service.issue(operation=f"card_lost:{card.id}")  # 仅首次生成
# 校验阶段直接 verify(challenge.challenge_id, code)，绝不重新发码
```

---

## 四、验证结果摘要（详见 P0_TEST_REPORT.md）

- pytest：**52 passed**（连续 10 次运行 0 flaky）
- smoke_api：**26/26 通过**
- 前端 `tsc --noEmit`：**0 错误**
- 前端 `npm run build`：**成功**
- 挂失 MFA 端到端：演示实例实测通过（正确码 → lost）
- 并发 20 线程：成功总额 ≤ ¥1000，无 500

---

## 五、尚未修复的问题（本轮范围之外，如实列出）

| 问题 | 归属 | 说明 |
|---|---|---|
| 无身份认证与账户归属校验 | P1-T2 | `account_id` 仍可由前端任意传；本轮按要求未做认证 |
| 7 状态交易状态机 | P1-T1 | 本轮仅确保「失败不报告成功」，未落地 FAILED/CANCELLED/EXPIRED 落库 |
| 密码修改接口 | P1-T3 | 已新增 `ActionType.PASSWORD_CHANGE` 策略判定，但**尚未**实现对应接口 |
| MFA 挑战进程内存储 | P1-T3 | 已改 CSPRNG，但重启仍丢挑战 |
| 请求限流 | P2-T2 | 未实现 |
| 前端策略面板 `red_daily_min` 字段 | 小问题 | `policy_info()` 顶层未返回该 key（前端未引用，无影响） |

---

## 六、下一阶段建议

按 `AUDIT_V0.2.0.md` 第 6 节继续：P1-T1（状态机）→ P1-T2（认证归属）→ P1-T3（密码修改/MFA 持久化）→ P1-T4（回归补测）→ P2（前端口径/限流/文档）。
