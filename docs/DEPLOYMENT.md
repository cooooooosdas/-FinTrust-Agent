# 本地部署说明

> 金枢 FinTrust Agent · 从零到跑起来

---

## 1. 环境要求

| 组件 | 版本要求 | 本项目实测 |
| --- | --- | --- |
| Node.js | ≥ 18 | 22.22.2 |
| npm | ≥ 9 | 10.9.7 |
| Python | ≥ 3.11 | 3.13.14 |
| pip | ≥ 23 | 25.3 |

> **注意**：如果你的机器上装了多个 Python，请务必使用**虚拟环境**，
> 否则 `pip` 与 `python` 可能指向不同的解释器，导致"明明装好了却 import 不到"。

---

## 2. 目录准备

```bash
cd D:/jingshu
```

确认结构：

```
jingshu/
├── backend/
├── frontend/
├── docs/
└── README.md
```

---

## 3. 后端部署

### 3.1 创建虚拟环境

```bash
cd backend

# Windows
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3.2 配置环境变量（可选）

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

不配置也能运行 —— 此时 Agent 使用**本地演示模式**。

### 3.3 初始化数据库

```bash
.venv\Scripts\python.exe scripts/init_db.py --recreate
```

预期输出（「数据库路径」一行由 `init_db.py` 按本机实际位置打印，此处以占位符示意）：

```
数据库路径：sqlite:///<仓库所在路径>/backend/data/fintrust.db
→ 正在重建表结构…
  已删除全部旧表
  已按最新模型重建表结构
→ 正在建表…
  表结构已就绪
→ 正在写入演示种子数据…
  已写入 473 条模拟交易、3 张卡、5 位收款人
✅ 数据库初始化完成
```

### 3.4 启动

```bash
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
# 或
.venv\Scripts\python.exe run.py
```

验证：

```bash
curl http://127.0.0.1:8000/api/v1/health
```

```json
{"status":"ok","app":"金枢 FinTrust Agent","version":"1.0.0","environment":"development",
 "demo_mode":true,"database":"connected","time":"..."}
```

---

## 4. 前端部署

```bash
cd frontend
npm install
npm run dev
```

访问 <http://127.0.0.1:5173>

### 生产构建与本地预览

```bash
npm run build        # 产物在 dist/
npm run preview      # 本地预览构建产物
```

如需让生产产物直连后端，在 `frontend/.env.production` 中设置：

```
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

并确保后端 `CORS_ORIGINS` 包含前端来源。

---

## 5. 一键启动脚本

项目根目录已提供：

```bash
start_backend.bat     # 创建 venv（如缺）→ 装依赖 → 初始化库 → 启动 uvicorn
start_frontend.bat    # npm install（如缺）→ 启动 vite
```

两个窗口分别执行即可。

---

## 6. 完整演示脚本（5 分钟讲完）

### 第 1 幕 · 账户总览（30s）

打开 <http://127.0.0.1:5173/>

- 深色主卡显示账户总余额、可用余额、周期收支、卡片数量
- 右侧常用收款人列表
- 中部近 6 个月收支趋势（当月进行中 → 虚线 + "至今"）
- 右侧周期消费分类条形图
- 底部我的银行卡 + 近期交易流水

### 第 2 幕 · AI 工作台（90s）

切到「AI 工作台」，点击示例指令 **「给张明远转 800 元，备注项目结算款」**

- 观察 DAG 执行轨迹：意图识别 → 任务规划 → resolve_payee → check_daily_total
  → evaluate_policy → prepare_order → 答复生成
- 展开轨迹，每一步都有耗时与命中规则
- 强调：**权限由后端策略引擎判定，模型无法决定**

再试 **「本月餐饮消费统计」** —— 展示账单分析与异常识别能力。

### 第 3 幕 · 三级权限（120s）★ 核心

切到「智能转账」：

| 步骤 | 操作 | 预期 |
| --- | --- | --- |
| ① 绿色 | 收款人=李思远（常用），金额 300 | 提交 → 直接执行成功 |
| ② 黄色 | 收款人=赵启航（非常用），金额 400 | 提交 → 弹出明细 + 「我已核对，确认执行」；不确认直接调用 API 会 409 |
| ③ 红色 | 收款人=李思远，金额 60000 | 提交 → 弹出多因子验证 + 演示验证码；填错提示剩余次数；填对执行成功 |

补充：点「银行卡管理」→ 对任意卡点「挂失」→ 同样触发红色 MFA。

### 第 4 幕 · 安全审计（60s）

切到「安全审计」

- 四个统计卡：总数 / 绿 / 黄 / 红
- 表格逐条展示：时间、操作、权限等级、处置、判定说明、操作对象
- 右上角按绿/黄/红筛选
- 底部「安全设计要点」六张卡

### 第 5 幕 · 账单分析（60s）

切到「账单分析」

- 顶部周期切换（近30天 / 本月 / 上月 / 近90天 / 近180天）
- 四个指标卡、月度趋势、环形图、分类明细
- 异常交易识别：重点讲「境外博彩平台 · 风险分 100」的判定原因
- 底部流水明细支持分类筛选、关键词搜索、分页

---

## 7. 常见问题排查

### Q1：`ModuleNotFoundError: No module named 'fastapi'`

**原因**：`pip` 与 `python` 指向不同的解释器。

**解决**：始终使用虚拟环境里的解释器执行一切：

```bash
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pytest tests/ -q
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

### Q2：`requirements.txt` 固定版本装不上

**原因**：部分镜像源只提供有限版本。

**解决**：项目已改用兼容区间（`>=`）。若仍失败：

```bash
.venv\Scripts\python.exe -m pip install -U pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Q3：前端显示「无法连接到后端服务」

依次检查：

```bash
curl http://127.0.0.1:8000/api/v1/health      # 后端是否活着
curl http://127.0.0.1:5173/api/v1/health      # Vite 代理是否通
```

- 后端不通 → 查看后端终端报错
- 代理不通 → 确认 `vite.config.ts` 中 `target: 'http://127.0.0.1:8000'`
- 端口被占 → `netstat -ano | findstr :8000` 查看占用进程

### Q4：转账一直返回 `428 MFA_REQUIRED`

**原因**：当日累计已超过 ¥20,000，策略自动升级为红色。这是**设计行为**，不是 Bug。

解决：重置演示数据

```bash
.venv\Scripts\python.exe scripts/init_db.py --reset
```

或直接在「智能转账」页查看「当日已转出」与各级阈值。

### Q5：改了后端代码但接口行为没变

`--reload` 有时在 Windows 上文件监听不可靠。重启进程即可：

```bash
# Ctrl+C 停掉后重新启动
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

### Q6：数据库表结构变了之后报错 `no such column`

`create_all()` 不会修改已存在的表。重建：

```bash
.venv\Scripts\python.exe scripts/init_db.py --recreate
```

### Q7：端口被占用

```bash
# 后端
netstat -ano | findstr :8000
taskkill /PID <PID> /F
# 前端（Vite 会自动递增到 5174）
```

---

## 8. 常用命令速查

```bash
# ---------- 后端 ----------
cd backend
.venv\Scripts\python.exe scripts\init_db.py --recreate      # 重建数据库
.venv\Scripts\python.exe scripts\init_db.py --reset         # 重置数据
.venv\Scripts\python.exe scripts\smoke_api.py               # 26 项接口冒烟
.venv\Scripts\python.exe -m pytest tests\ -q                # 39 个用例
.venv\Scripts\python.exe -m uvicorn app.main:app --reload   # 启动

# ---------- 前端 ----------
cd frontend
npm run dev        # 开发服务器
npm run build      # 生产构建
npm run preview    # 预览构建产物
npx tsc --noEmit   # 类型检查

# ---------- 接口文档 ----------
# http://127.0.0.1:8000/docs
```

---

## 9. 目录权限与数据位置

| 路径 | 内容 | 是否需要提交到 Git |
| --- | --- | --- |
| `backend/.env` | 本地环境变量（含密钥） | ❌ **绝对不要** |
| `backend/.env.example` | 环境变量模板 | ✅ |
| `backend/data/*.db` | SQLite 数据库 | ❌ |
| `backend/.venv/` | Python 虚拟环境 | ❌ |
| `frontend/node_modules/` | npm 依赖 | ❌ |
| `frontend/dist/` | 构建产物 | ❌ |

`.gitignore` 已默认排除以上全部内容。
