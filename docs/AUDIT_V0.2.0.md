# 金枢 FinTrust Agent — V0.2.0 代码审计报告

> 审计日期：2026-11-01
> 审计对象：`D:\jingshu`（V0.1.0 现状）
> 审计范围：后端 43 个 Python 文件 / 7718 行，前端 16 个 TS/TSX 文件 / 3722 行，9 张数据表，8 个 API 路由模块
> 审计方法：**逐文件读源码 + 隔离实例实测取证**，不使用「页面能显示」推断「后端已实现」
> 取证脚本：`backend/scripts/audit_probe.py`（可复现，本文所有实测结论均附原始输出）
> 取证环境：独立数据库 `backend/data/audit_probe.db` + 独立实例 `127.0.0.1:8010`（不污染演示库）

---

## 0. 审计结论摘要（一句话版）

> 骨架是真的、Agent 是真的、账是通的，但**权限引擎的判定轴与赛事要求错位**，且**执行阶段完全不重新判定风险**，导致「日累计 ¥1000 红线」在真实链路上**形同虚设**；同时发现 **1 个功能彻底不通**（银行卡挂失 MFA）、**1 个 8% 概率的测试随机失败**（工单号冲突）。
> 结论：**当前版本不能直接用于评审**，需先完成第 6 节的 P0 阶段（6 项任务）再进行演示。

| 维度 | 现状评分 | 说明 |
|---|---|---|
| 业务闭环完整性 | 70% | 8 步链路中前 4 步真实，后 4 步（重判/并发/状态机）存在硬伤 |
| 权限策略符合度 | 35% | 主判定轴错误（单笔驱动 vs 赛事日累计驱动） |
| 并发安全性 | 0% | 实测 6 笔并发全部突破日累计上限 |
| 状态机完备性 | 30% | 5 状态 / 目标 7 状态，缺 FAILED / CANCELLED / EXPIRED / EXECUTING |
| 身份认证 | 0% | 无任何认证与账户归属校验 |
| 前端真实性 | 95% | 无 mock、无静态数据，全部走真实 API（唯一例外见 2.2） |
| 可演示性 | 60% | 挂失场景演示必挂，需修复 |

---

## 1. 当前项目实现情况清单

分类口径：**A. 已真实实现** / **B. 仅有前端界面** / **C. 静态数据模拟** / **D. 已实现但有安全隐患** / **E. 完全未实现**

### 1.A 已真实实现（后端有真实逻辑，读取数据库、真实写入）

| # | 模块 | 实现位置 | 实证依据 |
|---|---|---|---|
| A1 | ORM 数据模型（9 张表） | `app/models/__init__.py` | Account / Card / Transaction / Payee / AuditLog / AgentSession / AgentMessage / TransferOrder / IdempotencyRecord，金额统一 `*_cents` 整数分存储 |
| A2 | 统一错误结构与链路追踪 | `app/core/errors.py`、`app/main.py` | 全部错误形如 `{error:{code,message,detail,trace_id}}`；`X-Trace-Id` 头贯穿中间件与日志 |
| A3 | 独立权限策略引擎 | `app/security/policy.py` | `PolicyEngine.evaluate()` 签名只接受业务事实（金额/日累计/收款人属性），**类型层面不存在「模型建议权限」入参**；`READ_ONLY_ACTIONS` 白名单只读动作返回绿色；每次判定返回可解释 `rules[]` |
| A4 | 按发生日的日累计计算 | `app/services/transfer_service.py:45` | 真实 SQL `SUM` + `occurred_at` 自然日窗口 + `category=='转账支出'` 过滤，**满足赛事要求 #1** |
| A5 | 转账预览与真实扣款 | `transfer_service.py` | 真实扣 `Account.balance_cents` / `available_cents`、真实写 `Transaction` 流水（`remark='[工单号] ...'`）、真实写审计 |
| A6 | 账单分析（真实聚合） | `app/services/analytics_service.py` | SQL `GROUP BY category` 分类汇总、逐月 `GROUP BY strftime` 趋势、3 条规则累加风险分的异常识别（非硬编码） |
| A7 | 审计日志（只追加） | `app/security/audit.py` | 覆盖 allow / confirm / mfa / block 四类处置，含 `actor / risk_level / decision / reason / detail_json / is_simulation` |
| A8 | 幂等控制（同键重放） | `app/security/idempotency.py` | `build_request_hash` 用 SHA256；同键同参返回首次结果；同键异参抛 `IDEMPOTENCY_CONFLICT`（**但存在竞态与兜底缺陷，见 D5/D6**） |
| A9 | 熔断降级 | `app/security/circuit_breaker.py` | closed/open/half_open 三态、线程安全、超时后半开探测；Agent 模型调用失败自动降级到本地规则引擎 |
| A10 | Agent 全链路 | `app/agent/{nlu,planner,tools,orchestrator}.py` | 意图识别（规则引擎 + LLM 融合）→ DAG 规划（Kahn 拓扑排序 + 环检测）→ 20 工具注册表 → 执行轨迹。实测 trace 节点：`intent_recognition → task_planning → fetch_transactions → aggregate_categories → detect_anomalies → monthly_trend → compose_summary → response_generation → pipeline_done` |
| A11 | Agent 不具备执行权 | `app/agent/tools.py` | 全文**无 `db.commit()`**，所有写类工具均为 `_prepare_transfer` / `_prepare_virtual_card` / `_prepare_card_action`（只生成方案，不落资金数据）→ 满足「未经确认不能执行」 |
| A12 | 模型不参与授权 | `app/agent/orchestrator.py:_compose_reply` | LLM 只对**工具已产出的事实数据**做措辞润色，prompt 内不含任何权限决策；`risk_level` 取自工具写入的 `ctx['policy']` |
| A13 | 模拟标识贯穿 | 全链路 | `Transaction.is_simulated` / `Card.is_simulated` / `AuditLog.is_simulation` / `TransferOrder.is_simulated`，前端全局「模拟交易」提示条与接口 `simulation_notice` |
| A14 | 统一设计系统 + 6 页面 | `frontend/src/components/ui/*`、`frontend/src/pages/*` | 深海军蓝 / 白 / 香槟金 token；手写 SVG 图表（TrendChart / CategoryBars / DonutChart / Sparkline）零第三方图表依赖 |
| A15 | 自动化测试 | `backend/tests/` | pytest **39 个用例**（当前 38 passed + 1 flaky，见 D9）；`scripts/smoke_api.py` **26/26 接口冒烟通过**（本次实测复跑确认） |

### 1.B 仅有前端界面（后端无对应可用实现）

| # | 界面 | 前端位置 | 后端现状 | 严重度 |
|---|---|---|---|---|
| B1 | **银行卡挂失（红色 · MFA 全流程）** | `pages/Cards.tsx:102-120, 292-352`（发起挂失 → 回显 demo_code → 输入 6 位验证码 → 验证并挂失，UI 完整） | `card_service.report_card_lost()` 校验阶段**重新 issue 了新验证码**，用户输入的有效码必然校验失败，HTTP 422 `MFA_INVALID`，卡片状态恒为 `active` | **P0 · 功能完全不通** |

> **实测原始输出**（演示实例 127.0.0.1:8000，复现于用户实际运行的系统）：
> ```
> 发起挂失 → {"status":"awaiting_mfa","risk_level":"red","challenge_id":"mfa_940886","demo_code":"135827"}
> 提交验证码 → {"error":{"code":"MFA_INVALID","message":"验证码错误，还可尝试 4 次"}}
> 卡片状态 → active
> ```
> **根因**：`card_service.py:213-217`
> ```python
> challenge_id = mfa_challenge_id or f"mfa_card_{card.id}"   # 首次下发的是随机 id（如 mfa_940886）
> challenge = mfa_service.get(challenge_id)                   # 取不到 → None
> if challenge is None:
>     challenge = mfa_service.issue(..., challenge_id=challenge_id)  # 又发了一个新码！
> ok, message = mfa_service.verify(challenge.challenge_id, mfa_code)  # 用户拿的是旧码 → 必然失败
> ```
> **对比**：转账的红色 MFA 链路是通的，因为 `TransferOrder` 落库了 `mfa_challenge_id` 并由 `transfers.py` 透传。挂失链路缺同样的字段与透传。

### 1.C 使用静态数据模拟（仅种子数据，全部带模拟标记）

| # | 内容 | 位置 | 说明 |
|---|---|---|---|
| C1 | 演示账户 2 个 | `scripts/init_db.py:ACCOUNTS` | 徐舒和 储蓄卡 ¥128,653.00 / 信用卡 -¥321.80，全部 `is_simulated` |
| C2 | 银行卡 3 张 | `init_db.py:CARDS` | 储蓄卡 / 信用卡 / 网购虚拟卡，`is_simulated=True` |
| C3 | 收款人 5 位 | `init_db.py:PAYEES` | 张明远、李思远等，含常用/非常用标记 |
| C4 | 交易流水 476 条 | `init_db.py:seed()` | 滚动 180 天窗口、按时间正序回填 `balance_after` 保证余额连续；另有 4 笔人为注入的异常样本供演示异常识别 |
| C5 | 审计日志 10 条 | `init_db.py:audit_seed` | 供「安全审计中心」开箱即有内容 |

> C 类**不是缺陷**：赛事要求「所有交易使用模拟银行业务系统」，这些种子数据正是模拟系统本体，且全部带 `is_simulated` 标记、前端显式声明「模拟交易 · 不连接任何真实银行账户」。
> **但**：种子里有 2 条 `transfer.executed` 审计记录声称「已执行」，而对应流水并不存在 —— 属于演示数据自洽性问题，建议在下一阶段清理（低优先级）。

### 1.D 已实现但存在安全隐患

| # | 问题 | 位置 | 严重度 | 实测证据 |
|---|---|---|---|---|
| **D1** | **执行阶段完全不重新判定风险**，直接复用预览快照 | `transfer_service.py:276` `policy = json.loads(order.policy_json)` | **严重** | 见下方 P3 取证 |
| **D2** | **并发可绕过日累计限制**（读余额→判断→扣款无行锁，执行路径不重算累计） | `transfer_service.py` 扣款段 | **严重** | 见下方 P4 取证 |
| **D3** | **幂等键退化为预览工单号** → 同一逻辑转账可重复扣款 | `transfers.py:82` `key = idempotency_key or payload.order_no` | **严重** | 见下方 P2 取证 |
| **D4** | **工单号基于内存地址生成** → UNIQUE 冲突 → 500 | `transfer_service.py:147` `id(decision) % 10000` | **严重** | 见下方测试不稳定证据 |
| **D5** | 幂等 `begin()` 为 SELECT-then-INSERT，未捕获并发插入的 `IntegrityError` → 500 | `idempotency.py:47-73` | 中 | 代码审阅 |
| **D6** | 前端 `newIdempotencyKey()` **每次调用生成新随机键** → 真实重试/双击永不被去重 | `frontend/src/api/client.ts:117`、`api/index.ts:102` | 中 | 代码审阅 |
| **D7** | **无任何身份认证与账户归属校验**，`actor` 硬编码 `demo-user`，`account_id` 由前端任意传 | `api/deps.py`、`AuditLog.actor` 默认值 | **严重** | 实测 `?account_id=2` 可直接读出他行信用卡余额 -321.80 |
| **D8** | 幂等记录无 TTL、无清理，`in_progress` 残留会永久阻塞该键 | `idempotency.py` | 中 | 代码审阅 |
| **D9** | **测试套件存在 ~8% 随机失败**（工单号冲突） | `backend/tests/test_api.py::test_insufficient_balance_is_rejected` | 中 | 连续 12 次运行：11 通过 / 1 失败 |
| **D10** | MFA 挑战仅存进程内存，重启即失效；`random.randint` 非密码学安全 | `app/security/mfa.py:51-52` | 中 | 代码审阅 |
| **D11** | 挂失/冻结接口硬编码 `account_id=1`，无视调用方上下文 | `api/routes/cards.py:61` | 低 | 代码审阅 |
| **D12** | 审计日志 `ip_address` 固定 `127.0.0.1`，未取真实客户端 IP | `models/__init__.py:141` | 低 | 代码审阅 |

### 1.E 完全尚未实现

| # | 需求项 | 赛事对应条款 | 现状 |
|---|---|---|---|
| **E1** | **7 状态交易状态机** | 第四步 PENDING_CONFIRMATION / PENDING_MFA / EXECUTING / SUCCEEDED / FAILED / CANCELLED / EXPIRED | 只有 5 态：`ready / awaiting_confirm / awaiting_mfa / executed / rejected`（`transfer_service._order_status()`）。**缺 EXECUTING / FAILED / CANCELLED / EXPIRED**，且失败场景只抛异常、不落状态 |
| **E2** | **密码修改等红色高风险动作** | 第三步「银行卡挂失、密码修改等高风险操作必须通过模拟 MFA」 | `ActionType` 枚举无 `PASSWORD_CHANGE`；`MFA_REQUIRED_ACTIONS` 仅含 `CARD_LOST`；无密码修改接口 |
| **E3** | **身份认证 / 会话 / 账户归属** | 安全通则 | `deps.py` 无任何 auth 依赖；`actor` 硬编码 |
| **E4** | 失败交易的落库与可查询 | 「失败交易不能被报告为成功」 | 余额不足/MFA 失败仅抛 `AppError`，`TransferOrder.status` 不变，事后无法在库中查到「这笔失败了」 |
| **E5** | MFA 挑战持久化 + CSPRNG | 安全通则 | 进程内 dict + `random.randint` |
| **E6** | 请求限流 / 防刷 | 安全通则 | 无 |
| **E7** | 转账工单过期机制（EXPIRED） | 第四步 | 无，工单永不失效 |

> **说明**：`E2`（密码修改）在赛事的表述里属于红色动作的**举例**（「银行卡挂失、密码修改等高风险操作」）。若评审严格按字面核对，此项需补齐；若按「等高风险操作」理解，核心是**红色动作集合必须可扩展**，当前引擎的 `MFA_REQUIRED_ACTIONS` 是可扩展集合，扩展成本仅 1 行 + 1 个接口。

---

## 2. 前后端模块依赖图

### 2.1 整体分层与依赖流向

```
┌───────────────────────────────────────────────────────────────────────────────┐
│  前端 React 18 + TS 5 + Vite 6 + Tailwind 3 + React Router 6 + Lucide         │
│                                                                               │
│  pages/            Dashboard  AgentWorkbench  BillAnalysis  Transfer  Cards  Audit │
│      │                                                                              │
│      ▼                                                                              │
│  hooks/            useAsync（统一 loading/error/data）  useOverview（总览聚合）    │
│      │                                                                              │
│      ▼                                                                              │
│  api/index.ts      六大业务 API 封装（accountApi transactionApi cardApi         │
│      │             transferApi agentApi auditApi）                                │
│      ▼                                                                              │
│  api/client.ts     request<T>()：超时 / AbortController / ApiError / X-Trace-Id    │
│      │             newIdempotencyKey()  ← ⚠ 每次调用随机（D6）                    │
│      ▼                                                                              │
│  Vite Proxy  /api  →  http://127.0.0.1:8000/api/v1                               │
└──────────────────────────────────┬────────────────────────────────────────────────┘
                                   │  HTTP（JSON / Idempotency-Key / X-Trace-Id）
┌──────────────────────────────────▼────────────────────────────────────────────────┐
│  后端 FastAPI                                                                │
│                                                                               │
│  api/routes/  accounts  transactions  cards  payees  transfers  agent  audit   │
│      │                    ▲                                                      │
│      │                    └── api/deps.py：db_session（⚠ 无 auth，D7）            │
│      ▼                                                                          │
│  ┌──────────────────── services/ ────────────────────┐                          │
│  │ account_service   账户/卡/收款人读取 + 脱敏掩码     │                          │
│  │ analytics_service 分类/趋势/异常识别（真实 SQL）    │                          │
│  │ card_service      虚拟卡 / 冻结 / 挂失  ⚠ B1 缺陷   │                          │
│  │ transfer_service  预览 / 日累计 / 执行扣款 ⚠ D1-D4  │                          │
│  └───────────────┬──────────────────────────────┘    │                          │
│                  │                                    │                          │
│  ┌───────────────▼──────────┐   ┌──────────────────┐  │                          │
│  │  security/               │   │  agent/          │  │                          │
│  │  policy.py  ★ 策略引擎    │◄──┤ nlu / planner    │  │                          │
│  │   （唯一授权来源）        │   │ tools / orch     │  │                          │
│  │  mfa.py     ⚠ D10        │   │ llm.py（可降级）  │  │                          │
│  │  idempotency.py ⚠ D5/D8  │   └──────────────────┘  │                          │
│  │  circuit_breaker.py      │                         │                          │
│  │  audit.py（只追加）       │                         │                          │
│  └───────────────┬──────────┘                         │                          │
│                  │                                    │                          │
│  core/  config.py（阈值/密钥）  database.py（WAL+外键）  errors.py（统一异常）      │
│  models/__init__.py  ← 9 张表，★ 本轮策略引擎与工单状态机均需在此扩展           │
└──────────────────────────────────┬────────────────────────────────────────────────┘
                                   │  SQLAlchemy 2.0 ORM
┌──────────────────────────────────▼────────────────────────────────────────────────┐
│  SQLite  backend/data/fintrust.db  （WAL · PRAGMA foreign_keys=ON）           │
│  accounts · cards · transactions · payees · audit_logs                          │
│  agent_sessions · agent_messages · transfer_orders · idempotency_records        │
└───────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 关键依赖事实（审计要点）

| 事实 | 结论 |
|---|---|
| 前端是否存在 mock / 假数据 | **无**。对 `frontend/src` 全量 grep `(mock\|fake\|dummy\|hardcod\|placeholder data\|TODO\|FIXME\|假数据\|静态数据)` → **No matches found**。六个页面全部通过 `api/index.ts` 拉真实数据 |
| 前端是否把权限等级回传给后端 | **否**。grep `risk_level` 命中 17 处，**全部为展示用途**（RiskBadge 渲染、Audit 页筛选参数）；`TransferPreviewRequest` / `TransferExecuteRequest` 均未声明该字段，多余字段被 Pydantic 忽略 → **满足赛事要求 #4（实测 P5 验证）** |
| Agent 是否能直接执行资金操作 | **否**。`agent/tools.py` 全文无 `db.commit()`，写类工具只产出方案 |
| 大模型是否参与授权 | **否**。`PolicyEngine.evaluate()` 只接受 7 个业务事实参数，模型输出无法进入该函数 |
| 是否连接真实银行账户 | **否**。全库无任何外部支付/银行 SDK 依赖，金额字段全为本地整数分 |

---

## 3. 当前安全问题清单（按严重度排序，含实测证据）

### 🔴 P0-1｜执行阶段不重新判定风险，日累计红线完全失效

**位置**：`backend/app/services/transfer_service.py:276`

```python
policy = json.loads(order.policy_json)   # ← 预览时的快照，直接复用
```

执行阶段既不重读当日累计，也不重新调用 `policy_engine.evaluate()`。

**实测（P3）**：
```
步骤1 预览 ¥4000 → order_no=TR202611012352113728 risk=green daily_after=4200.0
步骤2 注入 ¥300000.00 转账支出 → 当日累计变为 300200.0 元
       （yellow_daily_max=¥20000、red_daily_total=¥100000 均已远超）
步骤3 执行 → HTTP 200  status=executed  tx_id=480
```
→ 累计已超**红线** ¥100,000，执行阶段仍按绿色快照直接放行扣款。

**影响**：赛事要求 #2「使用交易执行时的最新累计金额重新判断风险」**完全不成立**。红线只是展示用的数字。

**修复方向**：`execute_transfer()` 内重新读取 `daily_transfer_total()` 并调用 `policy_engine.evaluate()`，用新判定覆盖快照判定；若新判定严于快照，按新判定走（MFA / 阻断）。

---

### 🔴 P0-2｜并发可绕过日累计限制

**位置**：`backend/app/services/transfer_service.py` 扣款段（读余额 → 判断 → 扣款）

无 `SELECT ... FOR UPDATE` 行锁（SQLite 需用 `BEGIN IMMEDIATE` 或条件更新替代），且执行路径不重算日累计，导致 N 个并发请求各自基于**同一份陈旧累计值**通过校验。

**实测（P4）**：
```
并发计划：6 笔并发转账，每笔 ¥5000，合计 ¥30000（单笔未超黄线 ¥5000）
线程0~5: HTTP 200 status=executed  （6 笔全部成功）
并发后：余额 124453.0 → 104453.0（扣款 ¥20000.0）
并发后：当日累计 = ¥30000.0（黄线 ¥20000，红线 ¥100000）
```
→ **超出黄色日累计上限 ¥20,000 达 ¥10,000**。

**影响**：赛事要求 #3「多笔交易并发时不能绕过日累计限制」**不成立**。

**修复方向**：以数据库为唯一真源做**原子条件更新**——在一条 `UPDATE accounts SET balance_cents = balance_cents - :amt WHERE id=:id AND balance_cents >= :amt` 上判断受影响行数；日累计判定移到同一事务内，用 `BEGIN IMMEDIATE` 串行化写事务（SQLite 单写者模型天然串行）。

---

### 🔴 P0-3｜幂等键兜底策略导致重复扣款

**位置**：`backend/app/api/routes/transfers.py:82`

```python
key = idempotency_key or payload.order_no   # ← 退化为「每次预览新生成的工单号」
```

`order_no` 每次预览都不同 ⇒ 两次预览同一逻辑转账 ⇒ 两个不同幂等键 ⇒ 两次都执行 ⇒ **扣款两次**。服务端没有任何按业务语义的去重。

**实测（P2）**：
```
执行前：余额=128653.0 元，转账支出流水数=1
步骤1.1 预览 → order_no=TR202611012352114592 risk=green
步骤1.2 预览 → order_no=TR202611012352117936 risk=green
步骤2.1 执行（未带 Idempotency-Key 头）→ status=executed tx_id=477
步骤2.2 执行（未带 Idempotency-Key 头）→ status=executed tx_id=478
执行后：余额=128453.0 元（扣款 ¥200.0），转账支出流水数=3（新增 2 条）
```
→ 同一笔 ¥100 转账被扣了 ¥200、写了 2 条流水。

**叠加问题**：前端 `newIdempotencyKey()` 在 `api/index.ts:102` 每次请求现生成随机键，所以**即使前端主动带 header，重试/双击也永不被去重**（D6）。

**修复方向**：`order_no` 由服务端生成唯一值；幂等键必须来自**客户端在用户意图产生时固定的稳定值**（前端在用户点击「确认转账」时生成一次并随工单生命周期复用）；服务端对「同账户 + 同收款人 + 同金额 + 同备注 + 同一自然日」增加业务级去重兜底。

---

### 🔴 P0-4｜无身份认证与账户归属校验

**位置**：`backend/app/api/deps.py`（无 auth 依赖）、`AuditLog.actor` 默认 `demo-user`、`app/api/routes/cards.py:61`（硬编码 `account_id=1`）

**实测**：
```
GET /api/v1/accounts/overview?account_id=2
→ account_id=2 可读取 → 徐舒和 6222029876543210 余额 -321.8
```
任意调用方可遍历 `account_id` 读取全部账户的余额、流水、卡片、收款人、审计日志。

**影响**：与「可信 AI 智能体」定位冲突；审计日志中的 `actor` 字段无实际归因价值。

**修复方向**：引入最小可用会话（如 `X-Session-Token` → 服务端映射到 `actor` + 可访问账户集合）；所有 `account_id` 必须落在该集合内，否则 403。

---

### 🟠 P1-1｜策略判定轴与赛事口径错位（绿色允许写操作）

**位置**：`backend/app/security/policy.py`

| 维度 | 赛事要求 | 当前实现 | 差距 |
|---|---|---|---|
| 绿色 | **仅限**余额查询、交易查询、账单分析等**只读**操作 | `READ_ONLY_ACTIONS` 白名单正确，但 `_evaluate_transfer` 对「小额 + 常用收款人 + 低累计」返回 **GREEN**（实测 P2 两笔 ¥100 转账均为 `risk=green` 并直接执行） | **转账可以是绿色** → 直接违反 |
| 黄色 | 小额转账，**日累计 ≤ ¥1000**，须展示完整信息并获用户明确确认 | 黄色触发条件是「单笔 > ¥5000」或「日累计 > ¥5000」 | 阈值口径、数量级全错 |
| 红色 | **日累计 > ¥1000** 的交易，以及挂失、密码修改等高风险操作，必须模拟 MFA | 红色触发条件是「单笔 ≥ ¥50000」或「日累计 > ¥20000」 | 阈值高 50 倍，且主轴错误 |

**额外错位**：`yellow_single_max_cents`（¥5000）被**同时复用**为「单笔黄线」与「日累计黄线」（`policy.py:273`），导致「日累计超 ¥5000 升黄」与「单笔超 ¥5000 升黄」无法独立配置。

**修复方向**：改为**日累计单轴**判定 —— `after_daily <= 1000 元` → 黄色（写操作一律至少黄色）；`after_daily > 1000 元` → 红色（强制 MFA）；只读操作保持绿色；单笔金额作为**辅助升红因子**（如单笔 ≥ ¥10000 独立升红），不再作为主轴。

---

### 🟠 P1-2｜交易状态机缺失 4 个状态，失败交易不落库

**位置**：`backend/app/services/transfer_service.py:_order_status()`、`TransferOrder.status`

现状 5 态：`ready / awaiting_confirm / awaiting_mfa / executed / rejected`。
目标 7 态：`PENDING_CONFIRMATION / PENDING_MFA / EXECUTING / SUCCEEDED / FAILED / CANCELLED / EXPIRED`。

| 赛事要求 | 现状 | 缺口 |
|---|---|---|
| 未经确认不能执行 | ✅ 已有（黄色缺 `confirm` → 409） | — |
| 未经 MFA 不能执行红色交易 | ⚠️ 逻辑存在但**挂失场景恒失败**（B1）；转账场景通过 | 挂失链路不可用 |
| 失败交易不能被报告为成功 | ⚠️ 失败时抛异常不落库，**库中查不到「这笔失败了」** | 缺 FAILED 状态与落库 |
| 幂等键避免重复交易 | ❌ 见 P0-3 | 键策略错误 |

**修复方向**：`TransferOrder.status` 迁移到 7 态枚举；执行入口先落 `EXECUTING`，成功落 `SUCCEEDED`，任何异常落 `FAILED`（含 `fail_reason`），用户主动放弃落 `CANCELLED`，超 TTL 落 `EXPIRED`。

---

### 🟠 P1-3｜工单号基于内存地址，随机失败率约 8%

**位置**：`backend/app/services/transfer_service.py:147`

```python
order_no = f"TR{utcnow().strftime('%Y%m%d%H%M%S')}{id(decision) % 10000:04d}"
```

`id()` 是 CPython 对象内存地址，分配器复用后可能与历史值相同；`order_no` 有 `unique=True` 约束 ⇒ `IntegrityError` ⇒ HTTP 500。

**实测（连续 12 次运行 pytest）**：
```
连续运行 12 次：通过 11 次 / 失败 1 次
FAILED tests/test_api.py::test_insufficient_balance_is_rejected
  sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) UNIQUE constraint failed: transfer_orders.order_no
```
→ **约 8.3% 的随机失败率**。V0.1.0 交付时声称的「39 passed」是**不稳定**的。

**修复方向**：`order_no = f"TR{utcnow():%Y%m%d%H%M%S}{uuid.uuid4().hex[:8].upper()}"`。

---

### 🟡 P2 级

| # | 问题 | 位置 | 说明 |
|---|---|---|---|
| P2-1 | 幂等 `begin()` 并发竞态 → 500 | `idempotency.py:47-73` | SELECT-then-INSERT 未捕获 `IntegrityError`；应改为 `INSERT OR IGNORE` / 捕获后重查 |
| P2-2 | 幂等记录无 TTL，`in_progress` 残留永久阻塞 | `idempotency.py` | 进程崩溃后该键永远返回 `IDEMPOTENCY_IN_PROGRESS` |
| P2-3 | 前端幂等键每次随机 | `api/client.ts:117` | 重试/双击永不去重 |
| P2-4 | MFA 挑战存内存 + `random.randint` 非 CSPRNG | `security/mfa.py` | 重启失效；应改 `secrets` + 落库 |
| P2-5 | 挂失/冻结硬编码 `account_id=1` | `api/routes/cards.py:61` | 忽略调用方上下文 |
| P2-6 | 审计 `ip_address` 固定 `127.0.0.1` | `models/__init__.py:141` | 应取 `request.client.host` |
| P2-7 | 无请求限流 | 全局 | 防刷保护缺失 |
| P2-8 | 种子审计含 2 条与流水不自洽的 `transfer.executed` | `init_db.py:341-342` | 演示数据自洽性 |

### ✅ 已验证合格的安全设计（保留，不要动）

| # | 设计 | 验证方式 |
|---|---|---|
| S1 | 权限判定完全在后端独立策略引擎 | `PolicyEngine.evaluate()` 签名无「模型建议」入参；实测 P5：请求体伪造 `risk_level:'green'` 被忽略 |
| S2 | 大模型不能决定自身权限 | `_compose_reply` 只做措辞润色，facts 全部来自工具层 |
| S3 | Agent 无资金执行权 | `agent/tools.py` 全文无 `db.commit()` |
| S4 | 前端隐藏按钮 ≠ 权限控制 | 所有写接口均在服务端独立判定并返回 409 / 428 |
| S5 | 金额全程整数分运算 | `*_cents` 存储与计算，仅 API 边界换算 |
| S6 | 审计只追加且覆盖四类处置 | allow / confirm / mfa / block 全覆盖 |
| S7 | 熔断降级保证核心业务可用 | 模型故障自动回落规则引擎 |
| S8 | 不连接任何真实银行账户 | 全库无外部支付 SDK |

---

## 4. 与竞赛要求的不一致之处（逐条对照）

### 4.1 第三步「修正权限策略」逐条对照

| # | 赛事原文要求 | 现状 | 结论 |
|---|---|---|---|
| 1 | 按**交易发生日**计算累计转账金额 | `daily_transfer_total()` 用 `occurred_at` 自然日窗口 + SQL `SUM` | ✅ **符合** |
| 2 | 使用**交易执行时的最新累计金额**重新判断风险 | 执行阶段复用预览快照 | ❌ **不符合**（P0-1） |
| 3 | 多笔交易**并发时不能绕过**日累计限制 | 实测 6 笔并发突破上限 | ❌ **不符合**（P0-2） |
| 4 | 不能信任前端传来的权限等级 | Pydantic 未声明该字段 + 实测伪造被忽略 | ✅ **符合** |
| 5 | 不能由大模型自行决定是否有权限 | 引擎签名不含模型意见；Agent 无 `db.commit()` | ✅ **符合** |
| 6 | 所有权限判定必须由后端独立策略引擎完成 | 全部 8 个路由的写接口均走 `policy_engine` | ✅ **符合** |
| 7 | 绿色：仅限余额查询、交易查询、账单分析等**只读**操作 | 小额转账被判为绿色并自动执行 | ❌ **不符合**（P1-1） |
| 8 | 黄色：小额转账，**日累计 ≤ ¥1000**，展示完整信息 + 明确确认 | 阈值口径与数量级全错（¥5000 / ¥20000） | ❌ **不符合**（P1-1） |
| 9 | 红色：**日累计 > ¥1000**，以及挂失、**密码修改**等高风险操作，必须模拟 MFA | 阈值 ¥20000 / ¥50000；无密码修改动作 | ❌ **不符合**（P1-1 / E2） |

**小计：9 条中 4 条符合、5 条不符合。**

### 4.2 第四步「建立交易状态机」逐条对照

| 赛事要求的状态 | 现状 | 结论 |
|---|---|---|
| PENDING_CONFIRMATION | `awaiting_confirm` | ⚠️ 语义等价，命名未对齐 |
| PENDING_MFA | `awaiting_mfa` | ⚠️ 语义等价，挂失场景恒失败 |
| EXECUTING | — | ❌ 缺失 |
| SUCCEEDED | `executed` | ⚠️ 语义等价 |
| FAILED | — | ❌ **缺失**（失败不落库） |
| CANCELLED | — | ❌ **缺失**（用户放弃无入口） |
| EXPIRED | — | ❌ **缺失**（工单永不过期） |

**小计：7 个状态中 2 个语义等价、5 个缺失或行为不符。**

### 4.3 其他

| 赛事通则 | 现状 | 结论 |
|---|---|---|
| 不得连接真实银行账户 | 无外部支付依赖 | ✅ 符合 |
| 所有模拟交易明确标注 | `is_simulated` 全链路 + 前端声明 | ✅ 符合 |
| 不得伪造交易成功结果 | 失败时抛异常不落「成功」 | ⚠️ 形式上符合，但因缺 FAILED 状态，**事后无法证明**某笔失败（应补状态机） |
| API Key 不得写入前端 | 仅 `backend/.env`（当前无 .env 文件，仅 `.env.example`） | ✅ 符合 |
| 不允许前端隐藏按钮实现权限控制 | 后端独立判定 | ✅ 符合 |

---

## 5. 银行业务闭环链路核查（第二步）

标准链路：账户查询 → 转账预览 → 风险判断 → 用户确认或 MFA → 交易执行 → 余额更新 → 流水写入 → 审计日志生成

| 步骤 | 后端实现 | 数据来源 | 真实度 | 缺口 |
|---|---|---|---|---|
| ① 账户查询 | `accounts.py` / `account_service.py` | `accounts` 表 | ✅ 真实 | 缺归属校验（D7） |
| ② 转账预览 | `transfer_service.preview_transfer()` | `payees` + `transactions` 聚合 | ✅ 真实 | 工单号冲突（D4） |
| ③ 风险判断 | `policy_engine.evaluate()` | 当日累计实时 SQL | ✅ 真实（预览阶段） | **判定轴错位**（P1-1） |
| ④ 用户确认 / MFA | `transfers.py` 409 / 428 | 工单 `confirmed` / `mfa_challenge_id` | ⚠️ 转账可用、**挂失恒失败** | B1 |
| ⑤ 交易执行 | `transfer_service.execute_transfer()` | 工单快照 | ❌ **不重新判定** | P0-1 |
| ⑥ 余额更新 | `account.balance_cents -= amount` | `accounts` 表 | ✅ 真实 | **无行锁**（P0-2） |
| ⑦ 流水写入 | `Transaction(remark='[工单号]…')` | `transactions` 表 | ✅ 真实 | 缺 FAILED 流水 |
| ⑧ 审计日志 | `write_audit_log()` | `audit_logs` 表 | ✅ 真实 | `actor` 硬编码、IP 固定 |

**闭环完整度：8 步中 5 步完全真实，2 步有缺陷（⑤⑥），1 步功能不通（④ 挂失分支）。**
**所有数据均来自后端数据库，无静态数据参与闭环** —— 这一点是达标的。

---

## 6. 下一阶段开发任务及顺序

> 原则：**先堵资金安全窟窿，再补功能完整性，最后做体验与文档**。
> P0 未完成前不建议对外演示（挂失场景会当场翻车）。

### 阶段 P0 —— 资金安全闭环（预计 5 个任务，必须全部完成）

| 序 | 任务 | 涉及文件 | 依赖 |
|---|---|---|---|
| **P0-T1** | **策略引擎改轴**：日累计 ¥1000 单轴判定；绿色仅限只读（写操作一律至少黄色）；补 `PASSWORD_CHANGE` 等红色动作；阈值改由 `.env` 配置（`policy_yellow_daily_max=1000`、`policy_red_daily_min=1000`） | `security/policy.py`、`core/config.py` | — |
| **P0-T2** | **执行时重新判定**：在 `execute_transfer()` 事务内重读当日累计并重新调用 `policy_engine.evaluate()`；新判定严于快照时按新判定走（要求 MFA / 阻断） | `services/transfer_service.py` | T1 |
| **P0-T3** | **并发安全**：扣款改为原子条件更新 `UPDATE … WHERE balance_cents >= :amt`，按受影响行数判定；写事务用 `BEGIN IMMEDIATE` 串行化；日累计与扣款置于同一事务 | `services/transfer_service.py`、`core/database.py` | T1 |
| **P0-T4** | **幂等键修正**：服务端以 `order_no` 为幂等键（唯一且服务端生成）；请求头幂等键改为「用户意图级稳定键」；`begin()` 捕获 `IntegrityError` 后重查；加 TTL 清理 | `api/routes/transfers.py`、`security/idempotency.py`、`frontend/src/api/client.ts` | T2 |
| **P0-T5** | **工单号唯一化**：`uuid4` 替代 `id(decision)`；顺带修复挂失 MFA 挑战 ID 不匹配（工单化或透传 challenge_id） | `services/transfer_service.py`、`services/card_service.py`、`api/routes/cards.py` | T4 |

### 阶段 P1 —— 功能完整性（预计 4 个任务）

| 序 | 任务 | 涉及文件 | 依赖 |
|---|---|---|---|
| **P1-T1** | **7 状态交易状态机**：`TransferOrder.status` 迁移枚举；执行入口落 `EXECUTING` → `SUCCEEDED`/`FAILED`；新增用户取消（`CANCELLED`）与超时自动过期（`EXPIRED`）；失败原因落库 | `models/__init__.py`、`services/transfer_service.py`、`schemas/__init__.py` | P0 全部 |
| **P1-T2** | **认证与账户归属**：最小可用会话（token → actor + 可访问账户集合）；所有 `account_id` 校验归属；审计 `actor` 取真实会话主体、`ip_address` 取真实客户端 IP；去掉 `cards.py` 硬编码 `account_id=1` | `api/deps.py`、`api/routes/*`、`security/audit.py` | P0 全部 |
| **P1-T3** | **密码修改等红色动作**：新增 `ActionType.PASSWORD_CHANGE`（红色 · 强制 MFA）、接口、审计；MFA 挑战改 `secrets` + 落库 + TTL 清理 | `security/policy.py`、`security/mfa.py`、`models/__init__.py`、`api/routes/*` | P1-T1 |
| **P1-T4** | **并发与幂等回归测试**：补充并发穿透测试、重复提交测试、状态机迁移测试 | `backend/tests/` | P1-T1~T3 |

### 阶段 P2 —— 体验与交付（预计 3 个任务）

| 序 | 任务 | 涉及文件 | 依赖 |
|---|---|---|---|
| **P2-T1** | 阈值与策略文案同步前端：风险徽标、策略说明页、审计中心文案改为新口径（¥1000） | `frontend/src/pages/*`、`frontend/src/components/ui/*` | P0-T1 |
| **P2-T2** | 补充限流、请求体大小限制、统一安全响应头 | `app/main.py` | P1 |
| **P2-T3** | 文档同步：README / SECURITY.md / ARCHITECTURE.md / API.md 反映 7 态状态机与新阈值；清理种子里不自洽的审计记录 | `docs/`、`README.md`、`scripts/init_db.py` | 全部 |

---

## 7. 每项任务的验收标准

### P0 阶段

| 任务 | 验收标准（可执行、可观测） |
|---|---|
| **P0-T1** 策略改轴 | ① `GET /transfers/policy` 返回黄色日累计上限 = `1000.0`、红色日累计下限 = `1000.0`；② 预览 ¥300 给常用收款人 → `risk_level=yellow`（不再出现 green 的转账）；③ 预览只读类（余额/流水/账单）→ `green`；④ 当日累计 ¥900 时预览 ¥200 → `yellow`；⑤ 当日累计 ¥900 时预览 ¥200 且合计 ¥1100 → `red` 且 `requires_mfa=true`；⑥ 挂失 → `red` + `requires_mfa=true`；⑦ 新增 `PASSWORD_CHANGE` → `red` + `requires_mfa=true`；⑧ `evaluate()` 签名仍不含任何模型/客户端等级入参 |
| **P0-T2** 执行时重判 | ① 预览 ¥300（当日累计 ¥0，判黄）→ 在预览与执行之间注入一笔 ¥900 转账支出 → 执行 → 返回 **428 MFA_REQUIRED**（而非 200）；② 反向：预览时判红 → 执行时若累计下降 → 仍按红色要求 MFA（不降级）；③ 每次执行在审计中留下**执行时判定**的 risk_level / rules，与预览快照不一致时以执行时为准记录 |
| **P0-T3** 并发安全 | ① 20 线程并发执行 20 笔 ¥200，当日累计从 ¥0 起 → **成功金额总和 ≤ ¥1000**（或超限的笔数被拒绝并返回明确的「超出当日限额」错误）；② 并发后 `transactions` 中当日「转账支出」合计 **≤ ¥1000**；③ 并发场景下 `balance_cents` 与流水 `balance_after` 序列**完全自洽**（无丢失更新）；④ 余额不足的并发请求返回 `INSUFFICIENT_BALANCE` 而非 500 |
| **P0-T4** 幂等键 | ① 同一 `Idempotency-Key` 连续提交 10 次 → **只扣款一次**、只写 1 条流水，返回同一 `transaction_id`；② 同一 key 不同参数 → `IDEMPOTENCY_CONFLICT`；③ **两次预览同一逻辑转账 → 最多扣款一次**（业务级去重生效）；④ 前端双击「确认转账」按钮只产生 1 笔交易（幂等键在用户意图产生时固定）；⑤ 并发提交同一 key → 无 500，返回 `IDEMPOTENCY_IN_PROGRESS` 或首次结果 |
| **P0-T5** 唯一号与挂失修复 | ① 连续 100 次预览 → `order_no` 100 个互不相同；② 连续运行 pytest **20 次全部通过**（0 flaky）；③ **挂失链路端到端可用**：发起 → 输入回显验证码 → 卡片状态变为 `lost` → 审计记录 `card.reported_lost`；④ 错误验证码 → 422 且卡片仍为 `active`；⑤ 同一挑战重复使用 → 拒绝（一次性消费） |

### P1 阶段

| 任务 | 验收标准 |
|---|---|
| **P1-T1** 状态机 | ① `TransferOrder.status` 取值集合 ⊇ {PENDING_CONFIRMATION, PENDING_MFA, EXECUTING, SUCCEEDED, FAILED, CANCELLED, EXPIRED}；② 未确认时 `status=PENDING_CONFIRMATION` 且执行被拒；③ 未 MFA 时 `status=PENDING_MFA` 且执行被拒；④ 成功后 `status=SUCCEEDED`；⑤ 余额不足 / MFA 错误 → `status=FAILED` 且 `fail_reason` 落库，**审计与接口响应均不报告成功**；⑥ 用户放弃 → `CANCELLED`；⑦ 超过 TTL 的工单 → `EXPIRED` 且执行被拒；⑧ 每次状态迁移写审计日志 |
| **P1-T2** 认证归属 | ① 无 token 访问受保护接口 → 401；② token 对应主体访问**不属于**自己的 `account_id` → 403；③ 审计日志 `actor` = 会话主体、`ip_address` = 真实客户端 IP；④ `cards.py` 不再硬编码 `account_id=1`；⑤ 现有六页面在带 token 下功能不回退 |
| **P1-T3** 密码修改/MFA | ① `POST /accounts/password/change` 无 MFA → 428；② 正确 MFA → 成功且旧密码失效；③ 错误 MFA → 422 且密码不变；④ MFA 验证码用 `secrets` 生成且重启后未过期挑战仍可校验；⑤ 同一挑战第二次使用被拒；⑥ 5 次错误后锁定 |
| **P1-T4** 回归测试 | ① 新增 ≥ 20 个用例，覆盖并发、幂等、状态机、权限边界；② pytest **连续 10 次全绿**；③ `smoke_api.py` 扩展到 ≥ 40 项且全通过；④ 覆盖率报告中 `security/` 与 `services/transfer_service.py` 分支覆盖 ≥ 85% |

### P2 阶段

| 任务 | 验收标准 |
|---|---|
| **P2-T1** 前端口径同步 | ① 全站文案不再出现「¥5000 / ¥20000 / ¥100000 旧阈值」；② 策略说明页展示新阈值与状态机说明；③ 风险徽标在新判定下颜色正确 |
| **P2-T2** 加固 | ① 同一 IP 超阈值请求返回 429；② 超过体积限制的请求体被拒；③ 响应含 `X-Content-Type-Options` 等安全头 |
| **P2-T3** 文档同步 | ① README 反映 7 态状态机与新阈值；② SECURITY.md 补并发/幂等/认证章节；③ ARCHITECTURE.md 模块图与实际一致；④ API.md 覆盖新增接口；⑤ 种子数据审计记录与流水自洽；⑥ 演示环境 `pytest` + `smoke` + 前端 `tsc --noEmit` + `npm run build` 四项全绿（**如实记录，不得虚构**） |

---

## 8. 附录：取证复现方式

### 8.1 取证脚本

```bash
cd backend
# 1) 建隔离库并灌种子
DATABASE_URL="sqlite:///D:/jingshu/backend/data/audit_probe.db" .venv/Scripts/python.exe scripts/init_db.py --recreate
# 2) 起隔离实例（8000 是演示实例，不要动）
DATABASE_URL="sqlite:///D:/jingshu/backend/data/audit_probe.db" .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --log-level warning
# 3) 跑取证
.venv/Scripts/python.exe scripts/audit_probe.py
```

输出落盘：`backend/data/audit_probe_report.txt`

### 8.2 探针清单与结果

| 探针 | 检验目标 | 结果 |
|---|---|---|
| P1 | 挂失红色 MFA 链路端到端 | ❌ 恒 422，卡片状态不变 |
| P2 | 幂等兜底是否导致重复扣款 | ❌ ¥100 转账被扣 ¥200、写 2 条流水 |
| P3 | 执行阶段是否用最新日累计重判 | ❌ 累计 ¥300,200（超红线）仍放行 |
| P4 | 并发能否绕过日累计 | ❌ 6 笔并发全成功，超黄线 ¥10,000 |
| P5 | 后端是否信任前端权限等级 | ✅ 伪造 `risk_level` 被忽略 |

### 8.3 本次审计执行的其他验证

```
pytest                      → 38 passed / 1 failed（flaky，见 P1-3）
pytest 连续 12 次           → 11 通过 / 1 失败（失败率 ≈ 8.3%）
scripts/smoke_api.py        → 26/26 通过
GET /accounts/overview?account_id=2 → 成功读出他人信用卡余额 -321.80
POST /agent/chat            → intent=bill_analysis，9 个 trace 节点全 success
代码规模                     → 后端 43 文件 7718 行；前端 16 文件 3722 行
```

### 8.4 审计方法声明

- 全部 A/B/C/D/E 分类**基于逐文件读源码**得出；页面「看起来能用」不作为实现依据（B1 正是「界面完整但后端不通」的反例）。
- 所有 ❌ 结论均有**可复现的实测输出**；所有 ✅ 结论均有源码位置或实测佐证。
- **未对任何业务代码做修改**（本轮仅新增 `backend/scripts/audit_probe.py` 取证脚本与本报告）。
