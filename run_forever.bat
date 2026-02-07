@echo off
chcp 65001 >nul
title ETF Strategy Guardian - 24/7
color 0A

:: 获取脚本所在目录
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

echo ============================================
echo   ETF 交易策略 - 冠军加权版 (3:1:1:1)
echo ============================================
echo   启动时间: %date% %time%
echo   权重方案: CHAMPION
echo   状态文件: rolling_state_main.json
echo   工作目录: %SCRIPT_DIR%
echo ============================================
echo.
echo [提示] 按 Ctrl+C 可停止策略
echo [提示] 请勿关闭此窗口，否则策略将停止运行
echo.

:: 无限循环运行
:loop
echo.
echo [%date% %time%] ========================================
echo [%date% %time%] 正在启动冠军加权版策略...
echo.

:: 运行 Python 脚本
python main.py

:: 检查退出码
if %errorlevel% equ 0 (
    echo.
    echo [%date% %time%] 策略正常退出
    echo [%date% %time%] 如需重新启动，请按任意键...
    pause
    goto loop
) else (
    echo.
    echo [%date% %time%] ⚠️ 策略异常退出! 错误码: %errorlevel%
    echo [%date% %time%] 将在 10 秒后自动重启...
    timeout /t 10 /nobreak
    goto loop
)
