@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo   金枢 FinTrust Agent - 后端启动
echo ============================================
cd /d "%~dp0backend"

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] 创建虚拟环境...
    python -m venv .venv
    if errorlevel 1 goto :error
) else (
    echo [1/3] 虚拟环境已存在，跳过
)

echo [2/3] 安装依赖...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo [3/3] 检查数据库...
if not exist "data\fintrust.db" (
    echo     未发现数据库，正在初始化...
    ".venv\Scripts\python.exe" scripts\init_db.py --recreate
)

echo.
echo 启动后端: http://127.0.0.1:8000
echo API 文档: http://127.0.0.1:8000/docs
echo 按 Ctrl+C 停止
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --reload --port 8000
goto :eof

:error
echo.
echo [错误] 启动失败，请检查 Python 是否已安装并加入 PATH。
pause
