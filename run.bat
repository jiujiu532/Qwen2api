@echo off
:: 使用 UTF-8 编码以防止中文乱码
chcp 65001 >nul
echo [QwenRegister] 正在启动项目...
echo [INFO] 使用 uv 环境运行 main.py

uv run main.py

if %ERRORLEVEL% neq 0 (
    echo [ERROR] 项目运行出错，请检查日志。
) else (
    echo [SUCCESS] 项目运行结束。
)

pause
