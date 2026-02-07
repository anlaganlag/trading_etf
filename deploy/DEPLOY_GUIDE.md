# 远程部署指南

本文档说明如何在远程 Windows 机器上部署并运行 ETF 量化交易策略。

---

## 📋 前置条件

- Windows 10/11 或 Windows Server 2016+
- Python 3.8+ (推荐 3.10+)
- 稳定的网络连接（需要连接掘金量化服务器）
- 掘金量化账号和 Token

---

## 🚀 快速部署（推荐）

### 步骤 1: 拉取代码

```powershell
git clone <your-repo-url> C:\trading\etf-strategy
cd C:\trading\etf-strategy
```

### 步骤 2: 运行部署脚本

双击运行 `deploy\setup_remote.bat`，或在命令行执行：

```powershell
.\deploy\setup_remote.bat
```

脚本会自动：
- ✅ 检查 Python 环境
- ✅ 安装依赖包
- ✅ 创建必要目录
- ✅ 引导你配置 `.env` 文件

### 步骤 3: 配置环境变量

编辑 `.env` 文件，填入你的凭证：

```ini
MY_QUANT_TGM_TOKEN=你的掘金Token
GM_ACCOUNT_ID=你的账号ID
```

### 步骤 4: 启动策略

**方式 A - 直接运行（测试用）**

```powershell
python main.py
```

**方式 B - 守护进程运行（推荐）**

双击 `run_forever.bat`

---

## 🔧 高级部署：安装为 Windows 服务

将策略安装为 Windows 服务可以实现：
- ✅ 开机自动启动
- ✅ 无需登录即可运行
- ✅ 系统级别的进程保护

### 准备工作

1. 下载 NSSM (Non-Sucking Service Manager)
   - 官网: https://nssm.cc/download
   - 解压后将 `nssm.exe` 放到 `deploy\` 目录

2. 以管理员身份运行 PowerShell

### 安装服务

```powershell
# 安装服务
.\deploy\install_service.ps1

# 卸载服务
.\deploy\install_service.ps1 -Uninstall
```

### 服务管理命令

```powershell
# 查看状态
Get-Service ETFTradingStrategy

# 启动服务
Start-Service ETFTradingStrategy

# 停止服务
Stop-Service ETFTradingStrategy

# 重启服务
Restart-Service ETFTradingStrategy

# 查看日志
Get-Content .\logs\service_stdout.log -Tail 100
```

---

## 📁 目录结构

```
project/
├── main.py              # 主入口（实盘运行）
├── config.py            # 配置文件
├── .env                 # 环境变量（需要自己创建/配置）
├── requirements.txt     # 依赖列表
├── run_forever.bat      # 守护进程启动脚本
├── deploy/              # 部署相关文件
│   ├── setup_remote.bat    # 一键部署脚本
│   ├── install_service.ps1 # Windows 服务安装脚本
│   ├── .env.template       # 环境变量模板
│   └── nssm.exe            # (需要手动下载)
├── core/                # 核心逻辑模块
├── logs/                # 日志目录
└── data_cache/          # 数据缓存目录
```

---

## 🔔 通知机制

策略运行时会通过以下方式发送通知：

| 事件 | 微信 | 邮件 |
|------|------|------|
| 策略启动 | ✅ | ❌ |
| 每日调仓 | ✅ | ✅ |
| 心跳报告 (每4小时) | ✅ | ❌ |
| 异常崩溃 | ✅ | ❌ |

### 配置通知

在 `.env` 文件中配置：

```ini
# 企业微信
WECHAT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your_key

# 邮件
EMAIL_HOST=smtp.163.com
EMAIL_PORT=465
EMAIL_USER=your_email@163.com
EMAIL_PASS=your_email_password
EMAIL_TO=your_email@163.com
```

---

## 🛡️ 安全建议

1. **不要将 `.env` 提交到 Git**
   - `.env` 已在 `.gitignore` 中排除
   
2. **定期检查日志**
   - 日志位于 `logs/` 目录
   - 自动保留最近 7 天的日志

3. **使用 Windows 防火墙**
   - 仅开放必要的端口
   
4. **设置远程桌面的自动断开**
   - 断开远程桌面不会影响服务运行

---

## ❓ 常见问题

### Q: 断开远程桌面后策略会停止吗？

**A:** 取决于运行方式：
- `python main.py` → ⚠️ 会停止
- `run_forever.bat` → ⚠️ 会停止
- Windows 服务 → ✅ 不会停止

建议使用 Windows 服务方式运行。

### Q: 如何查看策略是否在运行？

```powershell
# 方式1: 查看进程
Get-Process python

# 方式2: 查看服务状态
Get-Service ETFTradingStrategy

# 方式3: 查看最新日志
Get-Content .\logs\strategy_*.log -Tail 20
```

### Q: 策略崩溃后会自动恢复吗？

**A:** 是的，策略内置了多重保护：
1. `main.py` 内部有自动重连机制（最多 999 次）
2. `run_forever.bat` 会在脚本退出后自动重启
3. Windows 服务由 NSSM 管理，也会自动重启

### Q: 每天什么时候执行交易？

**A:** 默认是 14:55:00，可以在 `.env` 中修改：

```ini
OPT_EXEC_TIME=14:55:00
```

---

## 📞 联系支持

如有问题，请查看日志文件或联系开发者。
