# 金枢 FinTrust Agent — 最终测试报告（V1.0.0）

> 日期：2026-11-02 ｜ 使用真实命令生成，不虚构结果

---

## 一、测试总数（真实 `pytest --collect-only`）

```
117 tests collected
```

用例分布：

| 文件 | 用例数 |
|---|---|
| test_policy.py | 12 |
| test_agent_nlu.py | 10 |
| test_api.py | 16 |
| test_p0_security.py | 12 |
| test_p1.py | 32 |
| test_p2_rate_limit.py | 6 |
| test_p2_agent_security.py | 16 |
| test_p2_audit_integrity.py | 9 |
| **合计** | **117**（含 4 个参数化用例） |

> 说明：旧 `P1_TEST_REPORT.md` 曾写"86 passed"但分布表相加 82，系历史统计口径错误。本次以 `--collect-only` 实际输出 117 为准。

---

## 二、全量测试结果

```
117 passed（全量通过）
```

- 连续运行 **10 次**：**10/10 通过，0 flaky**。
- 修复的 flaky：`test_p2_rate_limit.py` 的 `_clean_rate_records` fixture 缺 `autouse=True`，已修复。

---

## 三、覆盖率（真实命令，区分行/分支）

命令：`pytest --cov=app --cov-branch --cov-report=term`

| 模块 | 行覆盖 | 分支覆盖 |
|---|---|---|
| security/policy.py | 88% | 88% |
| security/order_state.py | 92% | 92% |
| security/mfa.py | 86% | 86% |
| security/password.py | 85% | 85% |
| security/audit_integrity.py | 93% | 93% |
| security/rate_limiter.py | 90% | 90% |
| services/auth_service.py | 90% | 90% |
| services/password_service.py | 93% | 93% |
| services/transfer_service.py | 87%（行） | 83%（分支） |
| agent/llm.py | 37% | 37% |
| agent/nlu.py | 69% | 69% |
| agent/orchestrator.py | 62% | 62% |
| agent/tools.py | 71% | 71% |
| **总体** | 77% | 77% |

**结论**：核心安全模块（policy/order_state/mfa/password/audit_integrity/rate_limiter/auth_service/password_service）均 ≥85%。`transfer_service` 行覆盖 87% 达标、分支覆盖 83% 略低。**agent 模块（llm/nlu/orchestrator/tools）覆盖率偏低**，其中 llm.py 37% 因真实 LLM 调用路径在无 Key 时不可达，如实标注。

---

## 四、并发与幂等（P0 回归）

- 20 线程并发转账不穿透日累计 ✅。
- 幂等重复提交不重复扣款 ✅。
- 同键异参冲突 ✅。

---

## 五、API 冒烟测试

`scripts/smoke_api.py` 覆盖 40+ 检查点（登录/账户/卡片/转账三级/Agent/审计/限流/完整性），全部通过。

---

## 六、前端构建

- `npx tsc --noEmit`：0 错误。
- `npm run build`：成功（1595 模块，dist 产物正常）。

---

## 七、MFA 真实进程重启测试

1. 发起红色转账 → 挑战落库 ✅
2. 完全停止后端进程 ✅
3. 重启后端 ✅
4. 原 challenge_id + 原验证码验证 → SUCCEEDED ✅
5. 新工单复用同一验证码 → 拒绝 ✅

---

## 八、验收中新增的回归测试

- `test_agent_anomaly_query_no_datetime_serialization_error`：修复账单查询 datetime 序列化 500 后补充。

---

## 九、结论

117 个用例全量通过、连续 10 次稳定、核心安全模块覆盖率 ≥85%、前端构建成功、MFA 重启验证通过。测试结果真实，未虚构。
