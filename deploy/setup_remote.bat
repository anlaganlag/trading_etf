@echo off
chcp 65001 >nul
title ETF Strategy - Remote Setup

echo ============================================
echo   ETF 交易策略 - 远程部署向导
echo ============================================
echo.

:: 获取当前脚本所在目录
set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..
cd /d "%PROJECT_DIR%"

echo [1/5] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 未找到 Python! 请先安装 Python 3.8+
    echo    下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo ✅ Python 已安装

echo.
echo [2/5] 安装依赖包...
pip install -r requirements.txt -q
if errorlevel 1 (
    echo ❌ 依赖安装失败!
    pause
    exit /b 1
)
echo ✅ 依赖已安装

echo.
echo [3/5] 检查配置文件...
if not exist ".env" (
    echo ⚠️  未找到 .env 文件，正在从模板创建...
    copy "deploy\.env.template" ".env" >nul
    echo.
    echo ❗ 请编辑 .env 文件，填入你的 Token 和账号信息!
    echo    文件路径: %PROJECT_DIR%\.env
    echo.
    notepad "%PROJECT_DIR%\.env"
) else (
    echo ✅ .env 文件已存在
)

echo.
echo [4/5] 创建必要目录...
if not exist "logs" mkdir logs
if not exist "data_cache" mkdir data_cache
if not exist "output\data" mkdir output\data
if not exist "output\reports" mkdir output\reports
if not exist "output\charts" mkdir output\charts
echo ✅ 目录已创建

echo.
echo [5/5] 验证环境...
python -c "from config import config, validate_env; validate_env('LIVE')"
if errorlevel 1 (
    echo ⚠️  环境验证有警告，请检查配置
) else (
    echo ✅ 环境验证通过
)

echo.
echo ============================================
echo   部署完成!
echo ============================================
echo.
echo 📌 运行方式:
echo.
echo    方式1 - 直接运行 (测试用):
echo           python main.py
echo.
echo    方式2 - 后台守护运行 (推荐):
echo           双击 run_forever.bat
echo.
echo    方式3 - 安装为 Windows 服务 (高级):
echo           以管理员身份运行 PowerShell:
echo           .\deploy\install_service.ps1
echo.
echo ============================================
pause
