# ============================================
# ETF 交易策略 - Windows 服务安装脚本
# ============================================
# 用法: 以管理员权限运行此脚本
# PowerShell -ExecutionPolicy Bypass -File .\deploy\install_service.ps1
# ============================================

param(
    [string]$ServiceName = "ETFTradingStrategy",
    [string]$PythonPath = "",  # 留空则自动检测
    [switch]$Uninstall = $false
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$NssmPath = Join-Path $ProjectDir "deploy\nssm.exe"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  ETF 交易策略 - Windows 服务安装器" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# 检查管理员权限
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "❌ 请以管理员身份运行此脚本！" -ForegroundColor Red
    Write-Host "   右键点击 PowerShell -> 以管理员身份运行" -ForegroundColor Yellow
    exit 1
}

# 卸载模式
if ($Uninstall) {
    Write-Host "🗑️  正在卸载服务: $ServiceName ..." -ForegroundColor Yellow
    
    # 停止服务
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($service) {
        if ($service.Status -eq "Running") {
            Stop-Service -Name $ServiceName -Force
            Write-Host "   ⏹️  服务已停止" -ForegroundColor Green
        }
        
        # 使用 sc.exe 删除服务
        sc.exe delete $ServiceName | Out-Null
        Write-Host "   ✅ 服务已删除" -ForegroundColor Green
    } else {
        Write-Host "   ⚠️  服务不存在" -ForegroundColor Yellow
    }
    exit 0
}

# 检查 Python
if ([string]::IsNullOrEmpty($PythonPath)) {
    $PythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
    if ([string]::IsNullOrEmpty($PythonPath)) {
        Write-Host "❌ 未找到 Python! 请安装 Python 或指定 -PythonPath 参数" -ForegroundColor Red
        exit 1
    }
}
Write-Host "🐍 Python: $PythonPath" -ForegroundColor Green

# 检查项目目录
$MainScript = Join-Path $ProjectDir "main.py"
if (-not (Test-Path $MainScript)) {
    Write-Host "❌ 未找到 main.py: $MainScript" -ForegroundColor Red
    exit 1
}
Write-Host "📂 项目目录: $ProjectDir" -ForegroundColor Green

# 检查 NSSM（如果不存在则提示下载）
if (-not (Test-Path $NssmPath)) {
    Write-Host ""
    Write-Host "⚠️  未找到 NSSM (Non-Sucking Service Manager)" -ForegroundColor Yellow
    Write-Host "   请下载 NSSM: https://nssm.cc/download" -ForegroundColor Yellow
    Write-Host "   将 nssm.exe 放到: $NssmPath" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "   或者使用内置的 run_forever.bat 方式运行（详见 README）" -ForegroundColor Cyan
    exit 1
}

# 检查服务是否已存在
$existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Host ""
    Write-Host "⚠️  服务 '$ServiceName' 已存在！" -ForegroundColor Yellow
    $confirm = Read-Host "   是否删除并重新安装? (y/N)"
    if ($confirm -ne "y" -and $confirm -ne "Y") {
        Write-Host "   已取消" -ForegroundColor Cyan
        exit 0
    }
    
    # 停止并删除现有服务
    if ($existingService.Status -eq "Running") {
        Stop-Service -Name $ServiceName -Force
    }
    sc.exe delete $ServiceName | Out-Null
    Start-Sleep -Seconds 2
}

Write-Host ""
Write-Host "📦 正在安装 Windows 服务..." -ForegroundColor Cyan

# 使用 NSSM 安装服务
& $NssmPath install $ServiceName $PythonPath $MainScript
& $NssmPath set $ServiceName AppDirectory $ProjectDir
& $NssmPath set $ServiceName DisplayName "ETF Trading Strategy"
& $NssmPath set $ServiceName Description "ETF 量化交易策略 - 自动运行版"
& $NssmPath set $ServiceName Start SERVICE_AUTO_START
& $NssmPath set $ServiceName AppStdout (Join-Path $ProjectDir "logs\service_stdout.log")
& $NssmPath set $ServiceName AppStderr (Join-Path $ProjectDir "logs\service_stderr.log")
& $NssmPath set $ServiceName AppRotateFiles 1
& $NssmPath set $ServiceName AppRotateBytes 10485760  # 10MB

Write-Host ""
Write-Host "✅ 服务安装成功！" -ForegroundColor Green
Write-Host ""
Write-Host "📌 常用命令:" -ForegroundColor Cyan
Write-Host "   启动服务:  Start-Service $ServiceName"
Write-Host "   停止服务:  Stop-Service $ServiceName"
Write-Host "   查看状态:  Get-Service $ServiceName"
Write-Host "   查看日志:  Get-Content $ProjectDir\logs\service_*.log -Tail 50"
Write-Host "   卸载服务:  .\deploy\install_service.ps1 -Uninstall"
Write-Host ""

# 询问是否立即启动
$startNow = Read-Host "是否立即启动服务? (Y/n)"
if ($startNow -ne "n" -and $startNow -ne "N") {
    Start-Service $ServiceName
    Write-Host "🚀 服务已启动！" -ForegroundColor Green
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  安装完成!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
