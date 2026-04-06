@echo off
title WebP-Forge: 二次元插画高保真批量压缩工具
cd /d %~dp0

:: 检查并创建虚拟环境
if not exist "venv" (
    echo [INFO] 正在初始化环境，请稍候...
    python -m venv venv
    .\venv\Scripts\python.exe -m pip install tqdm rich --quiet
)

:: 启动程序
.\venv\Scripts\python.exe main.py

echo.
echo [OK] 任务结束，按任意键退出...
pause > nul
