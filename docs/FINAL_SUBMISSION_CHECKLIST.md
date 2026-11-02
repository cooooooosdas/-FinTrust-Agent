# 金枢 FinTrust Agent — 提交清单（V1.0.0）

> 日期：2026-11-02 ｜ 逐项核对，明确"已备 / 待补 / 草稿"
> **原则**：草稿与最终交付物严格区分；不夸大未完成能力。

---

## 一、交付物状态总览

| 交付物 | 状态 | 位置 |
|---|---|---|
| 源代码 | ✅ **最终交付物** | `backend/` `frontend/` |
| README | ✅ **最终交付物** | `README.md` |
| 环境配置示例 | ✅ **最终交付物** | `backend/.env.example`、`frontend/.env.example` |
| 数据库初始化脚本 | ✅ **最终交付物** | `backend/scripts/init_db.py` |
| 数据库迁移脚本 | ✅ **最终交付物** | `backend/scripts/migrate_v030.py`、`migrate_v040.py` |
| 演示准备脚本 | ✅ **最终交付物** | `backend/scripts/prepare_demo.py` |
| 测试用例 | ✅ **最终交付物** | `backend/tests/`（117 个） |
| 系统架构图 | ✅ **最终交付物**（图待绘制/截图） | `docs/ARCHITECTURE.md` + PPT P3 配图建议 |
| 安全自评报告 | ✅ **最终交付物** | `docs/FINAL_SECURITY_AUDIT.md` |
| 作品简介（200 字） | ✅ **最终交付物**（199 字） | `docs/PROJECT_INTRO_200.md` |
| 答辩 PPT 提纲 | ✅ **最终交付物**（10 页逐页 + 讲解稿） | `docs/PPT_OUTLINE_10MIN.md` |
| 五分钟演示脚本 | ✅ **最终交付物** | `docs/FINAL_DEMO_SCRIPT_5MIN.md` |
| 最终发布报告 | ✅ **最终交付物** | `docs/FINAL_RELEASE_REPORT.md` |
| **演示视频** | ❌ **待录制** | 现场录制 60 秒核心动线 |

---

## 二、源代码与配置

| 项 | 状态 |
|---|---|
| 后端 `backend/`（58 个 .py：应用 + 脚本 + 测试） | ✅ 已备 |
| 前端 `frontend/`（19 个 .ts/.tsx 源文件） | ✅ 已备 |
| `backend/requirements.txt`（含 pytest-cov） | ✅ 已备 |
| `frontend/package.json`（version 1.0.0） | ✅ 已备 |
| `.gitignore`（已排除 .env / *.db / node_modules / .venv / .workbuddy） | ✅ 已备 |
| `start_backend.bat` / `start_frontend.bat` | ✅ 已备 |
| 部署说明 `docs/DEPLOYMENT.md` | ✅ 已备 |

---

## 三、文档清单

| 文档 | 性质 |
|---|---|
| `README.md` | 最终交付物 |
| `docs/PROJECT_INTRO_200.md` | **最终交付物**（作品简介） |
| `docs/PPT_OUTLINE_10MIN.md` | **最终交付物**（PPT 逐页内容 + 讲解稿） |
| `docs/FINAL_DEMO_SCRIPT_5MIN.md` | **最终交付物**（演示动线） |
| `docs/FINAL_RELEASE_REPORT.md` | **最终交付物**（发布报告） |
| `docs/FINAL_ACCEPTANCE_REPORT.md` | 最终交付物（验收） |
| `docs/FINAL_SECURITY_AUDIT.md` | 最终交付物（安全自评） |
| `docs/FINAL_AGENT_CAPABILITY_REPORT.md` | 最终交付物（Agent 能力） |
| `docs/FINAL_TEST_REPORT.md` | 最终交付物（测试） |
| `docs/FINAL_KNOWN_LIMITATIONS.md` | 最终交付物（已知限制） |
| `docs/AGENT_THREAT_MODEL.md` | 最终交付物（威胁模型） |
| `docs/API.md` | 最终交付物（接口清单，已补全 V0.3 / V0.4 接口） |
| `docs/ARCHITECTURE.md` / `SECURITY.md` / `DEPLOYMENT.md` | 最终交付物 |
| `docs/P0_*.md` / `P1_*.md` / `AUDIT_V0.2.0.md` | **历史归档**（各阶段真实快照，保留以还原演进轨迹，顶部已加口径说明） |

---

## 四、Git 仓库

| 项 | 状态 |
|---|---|
| 本地仓库已初始化（`git init`） | ✅ 已建立 |
| V1.0.0 首次提交 | ✅ 已完成 |
| 远程仓库地址 | ❌ **待补**（需项目负责人提供） |
| 推送到公开仓库 | ⛔ **未执行**（未经确认不推送） |

---

## 五、敏感信息检查（提交前已执行）

| 检查项 | 结果 |
|---|---|
| API Key（`sk-` 模式） | ✅ 无 |
| 硬编码密钥 / Token / Password | ✅ 无 |
| `.env` 文件 | ✅ 不存在（仅 `.env.example`） |
| 数据库文件（`*.db` / wal / shm） | ✅ 已被 `.gitignore` 排除 |
| `node_modules/` / `.venv/` / `__pycache__/` | ✅ 已排除 |
| 工作区内部数据 `.workbuddy/` | ✅ 已排除 |

---

## 六、待办（提交前需项目负责人完成）

| # | 事项 | 说明 |
|---|---|---|
| 1 | 提供远程仓库地址并推送 | 我不擅自推送公开仓库 |
| 2 | 录制演示视频（60 秒核心动线 + 可选完整 5 分钟） | 按 `FINAL_DEMO_SCRIPT_5MIN.md` 录制 |
| 3 | 截取 7 张真实界面截图 + 绘制 2 张架构示意图 | 见 `PPT_OUTLINE_10MIN.md` 素材清单 |
| 4 | 按 PPT 内容制作正式 PPTX | 内容已就绪，可直接落地 |

---

## 七、如实声明（不可省略）

- 真实大模型**尚未联调**，当前为规则演示模式，界面已明确标注。
- **多轮对话上下文**尚未实现。
- 哈希链提供的是**篡改检测**能力，非绝对防篡改。
- 全部资金操作均为**本地模拟**，不连接任何真实银行账户。
