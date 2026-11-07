# 金枢 FinTrust Agent — 已知限制清单（V1.0.0）

> 日期：2026-11-02 ｜ 如实声明，不掩盖、不虚构
> 最近复核：2026-11-07（仓库状态、版本元数据、代码级残余边界；本轮只记录不改行为）

---

## 一、真实 LLM 联调未完成

- **状态**：未配置 `LLM_API_KEY`，Agent 运行在**规则演示模式**。
- **影响**：意图识别、答复润色由本地规则引擎完成，未经过真实大模型实测。
- **如实声明**：**不宣称真实模型接入已通过**。配置 Key 后 `llm.py`/`nlu.py` 已具备真实调用能力，但联调、成功率统计、10 条真实模型测试均未执行。

---

## 二、多轮对话上下文未实现

- `_compose_reply` 只传当前 `message`，**未把历史消息传给 LLM**。
- 影响：无法支持"给刚才那个人再转 200 元"这类指代消解，以及跨轮参数补全。
- 会话存储本身存在（AgentSession/AgentMessage），但上下文利用不完整。

---

## 三、NLU 澄清字段缺失

- `IntentResult` 无 `missing_parameters` / `clarification_required` / `entities` 字段。
- 参数缺失时未主动追问，而是由规则引擎返回"未识别金额"等错误提示。

---

## 四、SQLite 单写者 + 进程内限流

- 请求限流基于 SQLite 原子更新 + 进程内状态，**仅适用于单进程竞赛演示**。
- **不宣称**具备分布式/多实例生产级防护能力。

---

## 五、Agent 模块覆盖率偏低

- `llm.py` 37%、`nlu.py` 69%、`orchestrator.py` 62%、`tools.py` 71%。
- 原因：真实 LLM 调用路径在无 Key 时不可达，且 Agent 链路测试尚未补足。

---

## 六、Git 仓库状态（2026-11-07 更新）

- ✅ 本地 Git 仓库已初始化并完成 V1.0.0 首次提交（2026-11-02）。
- ✅ 已推送至公开仓库 `https://github.com/cooooooosdas/-FinTrust-Agent`（默认分支 `main`）。
- ✅ 已采用 **MIT License** 开源，仓库侧栏许可证识别为 `MIT`。
- ✅ 干净克隆复核通过：无 API Key / Token / `.env` / 数据库文件 / `node_modules` / `.venv` 泄漏。
- 说明：`FINAL_RELEASE_REPORT.md` 中「远程地址待补、未推送」是 **2026-11-02 交付时点**的历史记录，不代表当前状态。

---

## 七、审计完整性信任边界

- 哈希链 + HMAC 可检测篡改/删除/重排，但**不能**声称在数据库管理员与密钥同时被攻破时仍绝对不可篡改。

---

## 八、演示数据账号余额

- 演示库中账户 2（信用卡）余额为负数（欠款），属信用卡业务语义，非 bug。

---

## 九、未完成功能汇总（不影响核心演示）

| 项 | 状态 |
|---|---|
| 真实 LLM 联调 + 10 条实测 | 未做（无 API Key） |
| 多轮上下文补全 | 未做 |
| NLU 澄清字段 | 未做 |
| Agent 模块覆盖率补足 | 未做 |
| Git 远程仓库配置 + 推送 | ✅ 已完成（2026-11-07：公开仓库 + MIT 开源） |
| 70 条安全基准测试集（当前 15 条红队） | 未做 |
| 演示视频录制 | 未做 |

---

## 十、其余运行期说明

| 项 | 说明 |
|---|---|
| 演示库当日累计 | 演示前必须运行 `scripts/prepare_demo.py --reset-daily`，否则 800 元场景会直接触发红色 |
| 演示库与开发库 | `data/demo_v100.db`（演示，可重置）/ `data/fintrust.db`（开发，**不可重置**） |

---

## 十一、代码级残余边界（2026-11-07 源码复核，本轮只记录不修行为）

以下为**当前代码中确实存在**的边界与缺陷，按「零行为变化的结构整理」口径如实登记，
本轮不修改其运行时行为，也不宣称已修复。

| 项 | 代码位置 | 实况 | 影响 |
| --- | --- | --- | --- |
| 熔断半开恢复 | `app/security/circuit_breaker.py:47` `is_open` | `is_open` 把 `OPEN` 与 `HALF_OPEN` 一并判为打开，`call()` 在半开时直接抛 `CircuitOpenError` | 恢复探测无法真正放行，`record_success()` 在该路径不可达 |
| 幂等覆盖范围 | `app/services/transfer_service.py` | `IdempotencyStore` 仅接入 `POST /api/v1/transfers/execute` | 其余写接口重复提交不享有幂等去重 |
| Agent 审计查询过滤 | `app/agent/tools.py:494-500` `_list_audit` | 直接 `select(AuditLog).order_by(...).limit(20)`，未按当前 actor 过滤 | 同一会话内可读取非本用户的最近审计记录 |
| 会话复用归属核对 | `app/services/auth_service.py:ensure_session()` | 复用已有会话时未充分核对账户归属 | 账户隔离存在边界（沿用上一轮审计记录） |
| 红色 MFA 并发 | 转账执行路径 | 写锁释放存在边界 | 极端并发下可能出现重复推进（沿用上一轮审计记录） |
| 可信代理配置死分支 | `app/api/deps.py:client_ip()` | 读取 `settings.trusted_proxy`，但 `Settings` 未定义该字段，`getattr` 恒为 `""` | `X-Forwarded-For` 分支不可达；当前只信任直连 IP，符合单机演示定位，但配置代理后不会自动生效 |
| 限流依赖工厂未接入 | `app/api/deps.py:rate_limit` / `rate_limit_by_ip` | 两个工厂零调用；8 处限流由各路由直接调用 `check_and_increment` | 读代码时易误判请求链路上已生效统一限流依赖 |

> 说明：`docs/FINAL_SECURITY_AUDIT.md` 的结论已于 2026-11-07 加上范围限定，明确不覆盖上表各项。

---

## 十二、本轮结构整理的范围声明（2026-11-07）

本轮按「零行为变化」口径完成：后端版本收敛到 `app/__init__.py:__version__` 单一真源、
`Settings` 40 字段与 `.env.example` 完全对齐、`HMAC-SHA256` 纯算法收口到 `app/security/crypto.py`
（各模块密钥来源与回退链保持原样，改前改后 9 项摘要逐字节一致）、清理 `deps.py` 的动态
`__import__` 写法、文档与代码偏差对齐。**未修**上表任何缺陷，**未改**任何业务判定、状态迁移、
权限阈值或 API 语义。完整改动范围、潜在影响与验证要点见 `docs/GRILL_ME_USAGE.md`。
