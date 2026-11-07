# 系统架构说明

> 金枢 FinTrust Agent · 面向银行业务的可信 AI 智能体系统

---

## 1. 总体架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                          浏览器 (React 18 + TS + Vite)                │
│  账户总览 · AI 工作台 · 账单分析 · 智能转账 · 银行卡管理 · 安全审计    │
│         ↓  fetch('/api/v1/**')  [Vite Proxy]                          │
└──────────────────────────────────────────────────────────────────────┘
                                  │
┌──────────────────────────────────────────────────────────────────────┐
│                     FastAPI 应用层 (app/main.py)                       │
│  CORS · TraceId 中间件 · 统一异常处理 · 路由注册                       │
├──────────────────────────────────────────────────────────────────────┤
│  API 路由层 (app/api/routes)                                          │
│  system · accounts · cards · transactions · payees · transfers        │
│  agent · audit                                                         │
├──────────────────────────────────────────────────────────────────────┤
│  ★ Agent 引擎 (app/agent)                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐  │
│  │ nlu.py   │→ │planner.py│→ │tools.py  │→ │ orchestrator.py      │  │
│  │ 意图/参数 │  │ DAG 规划 │  │ 工具调用 │  │ 编排 + 轨迹 + 落库   │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────────┘  │
│       ↑              │                  │              │              │
│       │              │                  ▼              ▼              │
│       │              │          ┌────────────────┐  ┌──────────────┐   │
│       │              │          │ 业务服务层     │  │ security/    │   │
│       │              │          │ services/      │  │ ★ 权限引擎   │   │
│       │              │          └────────────────┘  │ policy.py    │   │
│       │              │                  │            │ mfa.py       │   │
│       │              │                  │            │ idempotency  │   │
│       │              │                  │            │ circuit_breaker│ │
│       │              │                  │            │ audit.py     │   │
│       │              │                  │            └──────────────┘   │
│  ┌──────────┐       │               │                                 │
│  │ llm.py   │───────┘               │                                 │
│  │ OpenAI兼容│  （未配置 Key 时降级）  │                                 │
│  └──────────┘                       ▼                                 │
├──────────────────────────────────────────────────────────────────────┤
│  数据层：SQLAlchemy 2.0  →  SQLite（WAL + 外键约束）                   │
│  accounts · cards · transactions · payees · audit_logs                │
│  agent_sessions · agent_messages · transfer_orders · idempotency_records│
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. 分层职责

| 层 | 目录 | 职责 | 明确**不**负责 |
| --- | --- | --- | --- |
| 接入层 | `app/api/routes` | 参数校验、HTTP 语义、序列化 | 业务逻辑、权限判定 |
| Agent 层 | `app/agent` | 意图识别、参数抽取、DAG 规划、工具编排、轨迹 | **权限判定**（由 `app/security/policy` 独立完成）；资金写操作不在工具内直接执行 |
| 业务层 | `app/services` | 真实业务规则与数据读写 | 权限判定（只调用策略引擎） |
| 安全层 | `app/security` | 权限策略、MFA、幂等、熔断、审计 | 业务逻辑 |
| 数据层 | `app/models` + `app/core/database` | ORM 映射、会话、事务 | — |

> **边界实况（2026-11-07 复核）**：Agent 工具通过注入的 `Session` 直接读取 ORM 来完成查询类任务，
> 例如 `app/agent/tools.py:_list_audit` 直接 `select(AuditLog)`。因此「Agent 不碰数据库」**不是**
> 当前实现的事实约束。真正被强制的边界是：工具注册表为服务端白名单，且所有资金写操作只生成
> 待确认工单，由 `app/services` 调用 `app/security` 策略引擎后在服务端执行。
> 该查询路径另有一条已记录的残余风险（`_list_audit` 未按当前 actor 过滤），
> 见 `FINAL_KNOWN_LIMITATIONS.md` 第十一节。

### 2.1 为什么权限引擎必须独立

产品要求「**禁止大模型直接决定自身权限**」。实现方式：

1. `security/policy.py` 的 `PolicyEngine.evaluate()` **只接受业务事实**：
   `amount_cents`、`daily_total_cents`、`is_frequent_payee`、`is_new_payee`、
   `target_is_self`、`remark_contains_sensitive`。
2. 函数签名中**不存在**任何"模型建议的权限等级"参数 —— 模型想传也传不进来。
3. Agent 的执行链路是 `tools.py → policy_engine.evaluate()`，
   中间不存在任何"模型可以覆盖策略"的分支。
4. 前端隐藏按钮**不是**安全手段：即使绕过 UI 直接 `POST /api/v1/transfers/execute`，
   服务端依然会返回 `409` / `428` / `403`。

### 2.2 双通道模型调用

```
parse_intent(text)
   │
   ├─ rule_based_intent(text)        ← 永远先跑，保证可用性
   │
   ├─ if llm_client.enabled:
   │     llm_intent(text)            ← 配置了 API Key 才走
   │     └ 失败 / 超时 → 熔断器记录 → 自动回退 rule 结果
   │
   └─ 融合：意图一致 → 采信模型并合并参数
             不一致 → 模型置信度高出 0.15 以上才纠正，否则保留规则结果
```

未配置 `LLM_API_KEY` 时 `llm_client.enabled == False`，
响应体中的 `demo_mode=true` 与 `demo_mode_notice` 会明确告知当前处于本地演示模式。

---

## 3. Agent DAG 执行模型

### 3.1 节点定义

`planner.py` 为每种意图生成一张有向无环图：

```python
PlanNode(
    id="evaluate_policy",
    title="安全策略引擎定级",
    tool="evaluate_policy",
    args={"account_id": account_id},
    depends_on=["resolve_payee", "check_daily_total"],
)
```

`Plan.topological_order()`（`app/agent/planner.py:57`）采用 **DFS 三色标记**（未访问 / 访问中 / 已完成）做依赖优先输出：先递归访问 `depends_on`，再把当前节点追加到结果，因此依赖节点必排在被依赖节点之前。遇到「访问中」节点（即存在环）时**跳过该依赖**以避免死循环，不抛异常。它不是基于入度队列的 Kahn 算法；由于当前 DAG 由固定意图模板生成且不含环，两种算法的输出顺序一致。

### 3.2 转账链路示例

```
resolve_payee ──┬──> check_daily_total ──┬──> evaluate_policy ──> prepare_order
                └─────────────────────────┘
```

### 3.3 账单链路示例

```
fetch_transactions ──┬──> aggregate_categories ──┐
                      ├──> detect_anomalies ──────┼──> compose_bill_summary
                      └──> monthly_trend ─────────┘
```

### 3.4 执行轨迹

每个节点执行后写入 `TraceBuilder`：

```json
{
  "step": 4,
  "node": "evaluate_policy",
  "title": "安全策略引擎定级",
  "status": "success",
  "detail": "权限判定：黄色 · 需确认 —— 向非常用联系人转账，需人工确认。",
  "duration_ms": 3,
  "payload": { "level": "yellow", "rules": [...] }
}
```

轨迹最终以 JSON 存入 `agent_messages.trace_json`，前端「DAG 执行轨迹」面板可展开查看。

---

## 4. 转账执行链路（核心业务闭环）

```
POST /transfers/preview
   ├─ 解析收款人（payee_id / name / account_no 三选一）
   ├─ 查询当日累计转出金额（category = '转账支出'，自然日窗口）
   ├─ policy_engine.evaluate()  ──→  绿 / 黄 / 红 / 阻断
   ├─ 落库 transfer_orders（保存权限判定快照 policy_json）
   └─ 写审计日志 transfer.preview

POST /transfers/execute
   ├─ 幂等检查（idempotency_records，同键异参 → 409 IDEMPOTENCY_CONFLICT）
   ├─ 取回工单
   ├─ 黄色 → 无 confirm 则 409 CONFIRMATION_REQUIRED
   ├─ 红色 → 无 mfa_code 则 428 MFA_REQUIRED（并持久化 challenge_id）
   │         验证码错误 → 428 MFA_REQUIRED（剩余次数递减）
   ├─ 余额校验 → 不足则 400 INSUFFICIENT_BALANCE（并写审计）
   ├─ 扣款：balance_cents -= amount, available_cents -= amount
   ├─ 生成 transactions 流水（remark 以 [工单号] 开头，便于反查）
   ├─ 工单状态 → executed，更新收款人使用统计
   └─ 写审计日志 transfer.executed
```

**不伪造成功**：余额不足、累计超限、验证码错误、未确认，全部返回明确的失败码与原因。

---

## 5. 数据模型

```
Account 1 ──┬──< Card
            ├──< Transaction >── Card (可空)
            └──< Payee

AgentSession 1 ──< AgentMessage
TransferOrder ──> Payee (可空)
IdempotencyRecord (key + endpoint 唯一)
AuditLog (只追加)
```

### 5.1 金额存储规范

**所有金额一律使用整数分（`*_cents`）存储与计算**，只在 API 边界换算为元。
这样彻底避免浮点数在累加与比较时的精度误差 —— 这是金融系统的基本要求。

```python
balance_cents: Mapped[int]     # 12_865_300 → ¥128,653.00
amount_cents:  Mapped[int]
```

### 5.2 关键索引

```python
__table_args__ = (
    Index("ix_tx_account_time", "account_id", "occurred_at"),   # 账户流水时间序
    Index("ix_tx_category_time", "category", "occurred_at"),    # 分类聚合
    Index("ix_audit_time", "created_at"),                       # 审计时间序
)
```

---

## 6. 异常交易识别规则

`analytics_service.detect_anomalies()` 采用三条可解释规则，累加风险分：

| 规则 | 加分 | 说明 |
| --- | --- | --- |
| 单笔金额 ≥ 分类基线 × 3 且 ≥ ¥1,000 | +55 | 各分类有 `CATEGORY_BASELINE_CENTS` 参考月均 |
| 交易发生在 00:00–05:00 | +25 | 非常规消费时段 |
| 夜间（00:00–05:00）且单笔 ≥ ¥8,000 | +25 | 夜间高额直接判高风险 |
| 交易状态非 success | +20 | 异常状态 |

风险分 ≥ 50 记为可疑交易，按分值降序返回，并附中文 `reason` 字段供前端展示。

---

## 7. 熔断与降级

```
llm_client.chat()
   └─ circuit_breaker.call(_do_request)
        ├─ 连续失败 < 阈值 → 正常放行
        ├─ 连续失败 ≥ 阈值 → state = OPEN，熔断
        │     └─ 熔断期间：抛 CircuitOpenError → Agent 自动降级到本地规则引擎
        └─ 超过 reset_timeout → HALF_OPEN，允许一次探测
```

熔断状态通过 `GET /api/v1/agent/capabilities` 的 `circuit_breaker` 字段对外暴露，
前端「AI 工作台 → Agent 执行链路」可实时查看。

---

## 8. 前后端通信

| 方面 | 方案 |
| --- | --- |
| 协议 | REST / JSON，统一前缀 `/api/v1` |
| 开发期 | Vite Proxy：`/api` → `http://127.0.0.1:8000`（免跨域配置） |
| 错误格式 | `{ "error": { "code", "message", "detail", "trace_id" } }` |
| 超时 | 前端 30s AbortController；后端 httpx 30s |
| 链路追踪 | 前端生成 `X-Trace-Id` → 后端中间件透传并回写响应头 |
| 幂等 | 写操作请求头 `Idempotency-Key` |
| 类型同步 | `frontend/src/types/index.ts` 与后端 Pydantic schema 一一对应 |

---

## 9. 设计系统

- **主色**：深海军蓝 `#0a1c34` / `#0f2745` —— 侧边栏、主余额卡，建立金融级可信感
- **强调色**：香槟金 `#c1903f` / `#dfbf78` —— 只用于关键动作与强调，数量克制
- **中性**：纯净白卡片 + `#f6f7f9` 画布 + `#e3e8ef` 分隔线
- **风险色**：绿 `#10b981` / 琥珀 `#f59e0b` / 玫瑰 `#e11d48`（仅用于权限等级）

刻意避免：廉价渐变、过度发光、密集小卡片、模板式后台栅格。
信息密度按「一屏一个主题」组织，重要数字使用 `tabular-nums` 等宽数字保证纵向对齐。

图表全部为**手写 SVG**（`components/ui/charts.tsx`），无第三方图表依赖，
保证离线环境可构建，且视觉完全融入设计系统。
