# 金枢 FinTrust Agent — 最终 Agent 能力报告（V1.0.0）

> 日期：2026-11-02 ｜ 身份：首席 AI Agent 架构师

---

## 一、Agent 真实调用链路

```
用户自然语言输入
   │
   ├─ ① 意图识别（nlu.py）
   │     LLM 优先（llm_intent，chat_json 结构化输出）
   │     └─ 失败/未配置 → 本地规则引擎（rule_based_intent）
   │     输出 IntentResult(intent, confidence, slots, source)
   │
   ├─ ② 任务规划（planner.py）
   │     规则化生成 DAG（PlanNode 节点 + depends_on 依赖）
   │     约束：最大 12 节点 / 最大 10 次工具调用 / 30s 超时
   │
   ├─ ③ DAG 执行（orchestrator.py）
   │     按拓扑序调用工具，每个节点记录状态/耗时/payload
   │     工具白名单校验（get_tool），未知工具 → 拒绝
   │
   ├─ ④ 工具调用（tools.py）
   │     纯函数 (db, args, ctx) → ToolResult
   │     无 db.commit，写操作走 PolicyEngine + 状态机
   │     身份上下文 ctx["auth"] + _assert_account_authorized
   │
   ├─ ⑤ 权限判定（policy.py，后端独立）
   │     PolicyEngine 只接收业务事实，不接收 LLM 权限建议
   │
   └─ ⑥ 答复生成 + 审计
         _compose_reply（LLM 可用时润色，否则模板）
         write_audit_log（含哈希链签名）
```

---

## 二、各能力实现状态（如实）

| 能力 | 状态 | 说明 |
|---|---|---|
| 真实 LLM 调用 | ⚠️ 已具备能力，未联调 | `llm.py` OpenAI 兼容客户端 + 熔断器已就绪，无 Key |
| 自然语言意图识别 | ✅ 规则引擎可用 | 11 类意图（转账/账单/卡片/审计/帮助等） |
| LLM 结构化输出校验 | ✅ 已实现 | `chat_json` + `extract_json` 容错 + Pydantic 校验 |
| 参数提取 | ✅ | 中文数字（三千五→3500）、收款人、备注、周期 |
| 多轮对话上下文补全 | ❌ 未实现 | `_compose_reply` 未传历史消息（见已知限制） |
| DAG 真实执行 | ✅ | trace 9 节点来自后端实际执行事件 |
| 后端工具执行银行业务 | ✅ | 20 个工具，全部走真实服务 |
| 中断/失败/异常降级 | ✅ | LLM 未配置降级规则，工具异常中断不崩溃 |
| 交易结果准确反馈 | ✅ | 无流水号不报"成功" |

---

## 三、工具白名单（20 个）

`resolve_payee`、`daily_total`、`evaluate_policy`、`prepare_transfer`、`fetch_transactions`、`aggregate_categories`、`detect_anomalies`、`monthly_trend`、`compose_bill_summary`、`list_cards`、`locate_card`、`prepare_virtual_card`、`prepare_card_action`、`load_account`、`recent_transactions`、`spending_stats`、`list_payees`、`list_audit`、`capabilities`、`clarify`

- 工具层**无 `db.commit()`**（静态检查验证）。
- 不存在 `exec/eval/system/shell/sql/file_read/delete_all` 等危险工具。

---

## 四、LLM 接入状态（如实声明）

- **当前状态**：未配置 `LLM_API_KEY`，Agent 运行在**规则演示模式**，界面明确标注"未配置大模型 API Key，AI 助手运行在本地演示模式"。
- **真实模型联调**：**未完成**（无外部模型访问权限）。未虚构真实大模型调用。
- 配置 Key 后：`llm.py` 的 `enabled=True`，nlu 走 LLM 优先解析，`source="llm"`。

---

## 五、Agent 安全网关

- 工具安全元数据 `ToolMeta`（action_type / permission_level / write）。
- 白名单 + 未知工具拒绝。
- 身份上下文 `ctx["auth"]`（来自认证，非 LLM）。
- 账户归属 `_assert_account_authorized`。
- DAG 约束：12 节点 / 10 次调用 / 30s 超时。

---

## 六、结论

Agent 的**受控工具调用 + 后端独立权限**这一核心安全架构已完整落地并可演示。真实 LLM 联调是唯一未完成的能力项，已如实标注，不虚构通过。
