# `grill-me` 在本项目中的使用方式

> 复核日期：2026-11-07 ｜ 适用版本：金枢 FinTrust Agent V1.0.0
> 本文是**执行阶段的交付说明**，不是 `grill-me` skill 自身读写的文档（该 skill 的
> `allowed-tools` 仅为 `Read, Grep`，明确声明 *No documentation is read or updated*）。

---

## 一、结论先行

`grill-me` 是 WorkBuddy 的**用户级对话 skill**，用途是在动手前对方案做逐分支质询、暴露隐含假设。
它**不是库、不是 CLI、不是服务，也不该被「集成」进项目代码**。

因此「结合 grill-me 完成整体优化」的正确拆解是：

| 阶段 | 由谁负责 | 产物 |
| --- | --- | --- |
| 决策拷问（skill 作用域内） | `grill-me`：只 `Read` / `Grep`，逐题给推荐答案并等待回答 | 对齐后的方案口径 |
| 执行与落地（skill 作用域外） | 常规工程手段：编辑、测试、构建、打包、推送 | 代码改动 + 本文 + 验证记录 |

把两者混为一谈（例如试图给 `requirements.txt` 加依赖、给后端加调用入口、或在仓库里放一份 skill 副本）
都是对 skill 定位的误解，且会污染已经开源的项目。

---

## 二、调用入口

| 项 | 事实 |
| --- | --- |
| Skill 文件 | `~/.workbuddy/skills/grill-me/SKILL.md`（**用户级目录，不在本仓库内**；不写机器绝对路径） |
| 触发方式 | 对话中说「grill me」/「challenge my thinking」/「压力测试方案」，或直接加载该 skill |
| 触发前提 | 项目**尚未**建立 `CONTEXT.md` / ADR 领域模型 —— 本项目复核确认无此类文件，故适用 |
| 会话流程 | 列 3–6 个顶层决策分支 → 从最基础的一条开始 → 逐分支走完 → 每题**先给推荐答案、再提问、等回答** → 全部收敛后以一段话收尾 |
| 自查纪律 | 能从代码库查到的事实必须用 `Read`/`Grep` 自行查证，**不许拿去问用户** |
| 项目代码内入口 | **无，且不应有**。`git grep` 全库无 skill 相关引用 |
| 停止使用并切换的条件 | 一旦项目建立 `CONTEXT.md` / ADR 领域模型，应改用 `grill-with-docs`（质询会锚定术语表，并把结论实时写入决策文档）。**本文不是 ADR 库**，不构成该切换条件 |

---

## 三、需要调整的模块

### 3.1 业务代码模块：0 个

`backend/` 与 `frontend/` 不需要为 skill 增加任何代码、路由、依赖或配置。skill 在会话之外不产生运行时行为。

### 3.2 流程资产：2 处（本次实际落地）

| 文件 | 作用 |
| --- | --- |
| `docs/GRILL_ME_USAGE.md`（本文） | 固化 skill 定位、调用入口、配置与依赖边界、本次决策树结论，以及改动范围/影响/验证要点 |
| `docs/FINAL_KNOWN_LIMITATIONS.md` 第十一、十二节 | 承接拷问中「已知缺陷只如实记录、不改行为」的结论，把代码级残余边界与范围声明落到项目现有限制清单 |

明确**不**新建 `CONTEXT.md` / `ADR`：那会把项目推进 `grill-with-docs` 的适用范围，属于另一套工作流决策，
超出本轮「零行为变化的结构整理」口径。

---

## 四、配置与依赖边界

| 维度 | 边界 |
| --- | --- |
| 文件位置 | 用户级 `~/.workbuddy/skills/`，仓库内 `.gitignore` 的 `.workbuddy/` 规则已将其隔开 |
| Skill 元数据 | `version: 1.0.0`、`allowed-tools: Read,Grep`、`visibility: public`、`homepage: github.com/mattpocock/skills` |
| Python / Node 依赖 | **零**。不进入 `backend/requirements.txt`、`frontend/package.json`、源码 ZIP 的打包白名单 |
| 环境变量 / 密钥 | **零**。与 `Settings` 的 40 个字段无任何交集，不读取 `.env` |
| 网络 / 运行时 | **零**。不发起请求、不驻留进程、不占用端口，对 `/health`、限流、审计链均无影响 |
| 构建与测试 | **零影响**。不参与 `pytest`、`npm run build`、`submission/tools/*` 的生成链路 |
| 与项目唯一的连接 | 开发者约定：改动方案前先走一轮质询。该约定记录在本文中，靠流程遵守而非代码强制 |
| 越界风险 | 若把 skill 文件复制进仓库，会把个人用户级路径、本机用户名等带入公开仓库；本项目已开源（MIT），此风险需长期避免 |

---

## 五、本次决策树与逐分支结论

顶层分支共 6 条，按依赖顺序从最基础的 A 开始。A 由用户明确确认（「按这个口径走」），
其余 5 条均属「能从代码库/项目状态自行查证」，按 skill 纪律自行定案，未占用用户时间。

| 分支 | 结论 | 依据 |
| --- | --- | --- |
| **A 目标与验收口径** | **只做零行为变化的结构整理**；已知缺陷只如实记录、不改行为 | 项目已推送公开仓库，117 个测试、四份交付物与 `FINAL_*` 报告都与当前行为对齐；修缺陷等于改变验收基线，须另起一轮 |
| **B 交付材料边界** | 改代码后同步重建源码 ZIP 与两份 PDF 的相关语句；PPT 不含版本字面量，不重建 | 源码包含 `backend/`，不重建会与仓库脱节；`build_pdfs.py` 里两处「待统一」自认必须作废 |
| **C 决策沉淀形式** | 新建本文，**不建** `CONTEXT.md`/ADR | 满足「梳理使用方式」的交付要求，同时不触发 skill 切换规则 |
| **D 工程化设施** | 本轮**不引入** CI / lint / `pyproject.toml` | 新增流程资产会改变贡献流程，超出「结构整理」口径 |
| **E 模块边界收口力度** | 只抽**纯算法**重复实现、保留各自密钥回退链；清理动态 `__import__`；零调用工厂保留为扩展点并如实标注 | 统一密钥会改变 HMAC 摘要，直接破坏既有审计链与 MFA 摘要 |
| **F 验证标准** | 现有 117 测试 + 前端生产构建 + 交付物一致性复核，**不新增回归用例** | 零行为变化下新增用例等于改动验收基线 |

---

## 六、改动范围

| # | 文件 | 改动 | 性质 |
| --- | --- | --- | --- |
| 1 | `backend/app/__init__.py` | `__version__` 由 `0.1.0` → `1.0.0`，写明「唯一真源」 | 元数据 |
| 2 | `backend/app/main.py` | FastAPI `version` 与根路由 `version` 改为引用 `__version__` | 元数据 |
| 3 | `backend/app/api/routes/system.py` | `/health` 的 `version` 改为引用 `__version__` | 元数据 |
| 4 | `frontend/package-lock.json` | 根版本 2 处 `0.1.0` → `1.0.0`，与 `package.json` 对齐 | 元数据 |
| 5 | `frontend/src/layouts/AppShell.tsx` | 版本号兜底值 `0.1.0` → `1.0.0` | 元数据 |
| 6 | `docs/API.md`、`docs/DEPLOYMENT.md` | `/health` 示例响应版本值同步 | 文档 |
| 7 | `submission/tools/build_pdfs.py` | 两处「版本待统一」自认改写为「已统一」 | 文档生成脚本 |
| 8 | `backend/.env.example` | 补齐 13 个 `Settings` 字段（限流 9、Agent 3、`AUDIT_HMAC_KEY` 1） | 配置样例 |
| 9 | `backend/app/security/crypto.py` | **新增**：`hmac_sha256_hex()` 纯算法封装 | 结构整理 |
| 10 | `backend/app/security/{audit_integrity,mfa,rate_limiter,password}.py` | 4 份 `hmac.new(...).hexdigest()` 改为调用共享函数；删冗余 `hashlib`/`hmac` import | 结构整理 |
| 11 | `backend/app/api/deps.py` | `getattr(__import__(...).settings, ...)` → 顶部导入的 `settings`；为两个未接入工厂与 `trusted_proxy` 死分支加如实注释 | 结构整理 |
| 12 | `docs/ARCHITECTURE.md` | Kahn 拓扑排序 → DFS 三色实况；Agent 层「不碰数据库」→ 真实边界说明 | 文档对齐 |
| 13 | `docs/FINAL_SECURITY_AUDIT.md` | 「未发现可绕过授权」加范围限定，指向残余边界 | 文档如实化 |
| 14 | `docs/FINAL_KNOWN_LIMITATIONS.md` | 仓库状态更新为已推送 + MIT；新增第十一节代码级残余边界、第十二节范围声明 | 文档如实化 |
| 15 | `docs/FINAL_RELEASE_REPORT.md` | 「未推送」标注为交付时点历史记录并补注后续状态 | 文档如实化 |
| 16 | `docs/GRILL_ME_USAGE.md` | 新增本文 | 流程资产 |

**未改**：`backend/app/security/policy.py`（三级权限）、`order_state.py`（状态机）、
`transfer_service.py`（业务闭环）、`idempotency.py`、`agent/*`（意图/DAG/工具）、
所有 `backend/tests/`、`frontend` 组件与样式、四份交付物中的 PPT。

---

## 七、潜在影响

| 影响面 | 评估 |
| --- | --- |
| API 响应体 | `/health`、`/`、OpenAPI `version` 由 `0.1.0` 变为 `1.0.0`。**唯一一处运行时可见变化**，属元数据，不影响任何业务判定、状态迁移、权限阈值或鉴权 |
| 既有数据兼容性 | **零风险**。`crypto.py` 只替换算法调用，4 条链路各自的密钥来源与回退链逐字保留；改前改后 9 项摘要基准逐字节一致（含 `compute_event_hash`、MFA 摘要、限流键、会话 token 摘要） |
| 审计哈希链 | 不受影响，既有 `sequence_id` / `previous_hash` / `event_hash` 校验逻辑未动 |
| 配置默认值 | `.env.example` 新增键的值全部照抄 `Settings` 内置默认值；未改 `config.py`，未设置环境变量时行为完全不变 |
| `client_ip()` | 从动态 `__import__` 改为模块级 `settings`。`Settings` 未定义 `trusted_proxy`，`getattr` 依旧恒返回 `""`，XFF 分支仍不可达，行为一致 |
| 文档与交付物一致性 | 版本统一后 `build_pdfs.py` 两处自认已作废，需重建两份 PDF 与源码 ZIP；源码包文件数会因新增 `crypto.py` 与本文而变化 |
| 开源仓库 | 改动需重新提交推送；`docs/` 内新增内容不含任何密钥、本机绝对路径或个人数据 |

---

## 八、验证要点与实测结果

| 验证项 | 方法 | 结果 |
| --- | --- | --- |
| HMAC 逐字节不变 | 改前固化 9 项基准（`.workbuddy/qa/hmac_baseline.json`），改后同输入重算比对 | ✅ 9/9 完全一致，无差异 |
| 后端回归 | `cd backend && .venv/Scripts/python.exe -m pytest -q` | ✅ **117 passed**（40s，exit 0） |
| 前端生产构建 | `cd frontend && npm run build` | ✅ 1597 modules transformed，50.64s，exit 0 |
| 配置覆盖 | 脚本比对 `Settings.model_fields` 与 `.env.example` 键集 | ✅ 40 / 40，缺失 `[]`、多余 `[]`、完全覆盖 `True` |
| 版本真源 | `git grep 0.1.0` 复核剩余命中 | 仅应剩历史快照（`AUDIT_V0.2.0.md`）、历史迁移注释（`order_state.py`）与发布报告里的历史描述 |
| 交付物一致性 | 重建两份 PDF + 源码 ZIP，`zip_validation.json` 全项通过 | ✅ 源码包 134 文件 / 27 目录，`zip_test PASS`，三项校验数组均为空 |
| 敏感信息 | 源码包扫描 + 新增文档路径检查 | ✅ 无 API Key / Token / 本机绝对路径 / 个人用户名 |

---

## 九、评估后**未采纳**的候选项（附理由）

| 候选 | 未采纳理由 |
| --- | --- |
| 状态字符串全面收敛到常量 | 复核发现 `transfer_service.py` 已大量引用 `order_state` 常量；剩余字面量在 SQLAlchemy 列默认值与 `__all__` 导出列表中，强行替换会引入 `security → models` 循环依赖。此项属「扫描结论过度概括」，不做 |
| 删除 `deps.py` 两个零调用限流工厂 | 删除虽零行为变化，但会丢失一份语义完整的统一接入扩展点；且 `__all__` 已导出，删除属内部 API 破坏。改为**保留 + 明确标注未接入**，更符合「如实记录」口径 |
| 把 8 处路由改为使用限流依赖工厂 | 工厂以 `user:` 为 identifier 且强制依赖 `current_user`，与现行各路由的 scope/identifier/window 口径不同，会改变限流键 → **行为变化**，A 口径下排除 |
| 给 `Settings` 补 `trusted_proxy` 字段 | 会启用 XFF 信任分支，改变 `client_ip()` 行为 → **行为变化**，排除；只如实记录为死分支 |
| 抽取 `backend/scripts/_bootstrap.py` 消除 7 处 `sys.path.insert` | 7 个脚本均为 `python scripts/xxx.py` 直接执行的独立入口，`sys.path.insert` 是其启动契约；抽取会引入「以模块方式调用」的兼容风险，收益不足以覆盖改动面，本轮不做，列为可选后续 |
| 修复熔断半开 / 扩大幂等覆盖 / 给 `_list_audit` 加 actor 过滤 | 均改变运行时行为，属于功能目标变更，按 A 口径明确排除；已如实登记在 `FINAL_KNOWN_LIMITATIONS.md` 第十一节 |

---

## 十、收尾摘要（skill 要求的 closing paragraph）

本轮以 `grill-me` 的决策拷问作为前置关卡，先把「优化」钉死为**零行为变化的结构整理**，
再由代码库自查确定其余五个分支的默认答案，避免了对已推送、已交付、已开源的 V1.0.0
做高风险的隐式行为变更。实际落地的是版本单一真源、配置样例全覆盖、密码学原语收口、
动态导入清理与文档如实化；所有已知缺陷一律只记录不修复，全部归入现有限制清单。
`grill-me` 自始至终停留在会话层 —— 项目代码零依赖、零调用入口、零运行时影响，
它与项目之间唯一的连接是本文所固化的这条流程约定。
