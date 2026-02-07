@echo off
chcp 65001 >nul
title ETF Strategy - Equal Weight Version (等权版)
color 0B

:: ============================================
::   ETF 量化交易策略 - 等权版本启动脚本
:: ============================================
:: 本脚本设置环境变量后启动策略，使用:
::   - 权重方案: EQUAL (1:1:1:1 等权)
::   - 状态文件: rolling_state_main_equal.json
::   - 日志文件: strategy_YYYYMMDD_equal.log
::   - 账户 ID: 通过环境变量指定
:: ============================================

:: 获取脚本所在目录
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

:: === 等权版本专用配置 ===
set WEIGHT_SCHEME=EQUAL
set VERSION_SUFFIX=_equal

:: === 账户配置 (请修改为你的等权版账户ID) ===
:: 如果需要使用不同账户，请取消下面这行的注释并填入账户ID
:: set GM_ACCOUNT_ID=你的等权版账户ID

echo ============================================
echo   ETF 交易策略 - 等权版本 (1:1:1:1)
echo ============================================
echo   启动时间: %date% %time%
echo   权重方案: %WEIGHT_SCHEME%
echo   状态文件: rolling_state_main%VERSION_SUFFIX%.json
echo   工作目录: %SCRIPT_DIR%
echo ============================================
echo.
echo [提示] 按 Ctrl+C 可停止策略
echo.

:: 无限循环运行
:loop
echo.
echo [%date% %time%] ========================================
echo [%date% %time%] 正在启动等权版策略...
echo.

python main.py

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
