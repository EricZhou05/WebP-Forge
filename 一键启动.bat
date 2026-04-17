@echo off
title WebP-Forge
:: 强制使用 UTF-8 编码显示，解决 .bat 运行时的乱码
chcp 65001 > nul
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
echo [OK]任务完成，按任意键退出
pause > nul
