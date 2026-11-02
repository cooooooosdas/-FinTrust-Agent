@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo   金枢 FinTrust Agent - 前端启动
echo ============================================
cd /d "%~dp0frontend"

if not exist "node_modules" (
    echo [1/2] 安装依赖...
    call npm install
    if errorlevel 1 goto :error
) else (
    echo [1/2] 依赖已存在，跳过
)

echo [2/2] 启动开发服务器...
echo.
echo 前端地址: http://127.0.0.1:5173
echo 按 Ctrl+C 停止
echo.
call npm run dev
goto :eof

:error
echo.
echo [错误] 依赖安装失败，请检查 Node.js 是否已安装并加入 PATH。
pause
