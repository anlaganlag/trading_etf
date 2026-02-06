"""
实盘运行入口
用法: python run_live.py

注意: 运行前请确保:
1. 已配置环境变量 MY_QUANT_TGM_TOKEN
2. 已配置账户 ID (可通过 GM_ACCOUNT_ID 环境变量或 config.py)
3. 已启动掘金终端
"""
import os
from gm.api import run, MODE_LIVE
from config import config


def main():
    print("=" * 50)
    print("🚀 ETF Rotation Strategy - LIVE TRADING")
    print("=" * 50)
    print(f"📋 Account ID: {config.ACCOUNT_ID}")
    print(f"⏰ Execution Time: {config.EXEC_TIME}")
    print(f"📊 TOP_N: {config.TOP_N}")
    print(f"🛡️ Stop Loss: {config.STOP_LOSS:.0%}")
    print("=" * 50)
    print("⚠️  WARNING: This is LIVE trading with real money!")
    print("=" * 50)
    
    # 设置环境变量
    os.environ['GM_MODE'] = 'LIVE'
    
    run(
        strategy_id=config.STRATEGY_ID,
        filename='main.py',
        mode=MODE_LIVE,
        token=os.getenv('MY_QUANT_TGM_TOKEN')
    )


if __name__ == '__main__':
    main()
