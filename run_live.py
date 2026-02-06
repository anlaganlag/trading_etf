"""
工业级实盘启动器
带有环境安全互锁、账户校验、以及启动前冷静提示。
"""
import os
import sys
import time
from gm.api import run, MODE_LIVE
from config import config, logger

def main():
    logger.info("=" * 60)
    logger.info("🚀 ETF Rotation Strategy - LIVE TRADING")
    logger.info("=" * 60)
    
    # 1. 环境与强制 Token 校验
    if not config.validate_env(mode='LIVE'):
        logger.error("🛑 LIVE ADMISSION FAILED. Critical resources missing.")
        sys.exit(1)

    # 2. 核心参数确认
    logger.info(f"📋 Account ID: {config.ACCOUNT_ID}")
    logger.info(f"⏰ Execution: {config.EXEC_TIME}")
    logger.info(f"🛡️ StopLoss: {config.STOP_LOSS:.0%}")
    logger.info(f"🚦 Meta-Gate: {'ENABLED' if config.ENABLE_META_GATE else 'DISABLED'}")
    
    # 3. 冷静期确认
    logger.warning("⚠️  WARNING: You are about to start LIVE trading with REAL MONEY.")
    logger.warning("Starting in 3 seconds... Press Ctrl+C to abort.")
    try:
        for i in range(3, 0, -1):
            print(f"{i}...", end=' ', flush=True)
            time.sleep(1)
        print("GO!")
    except KeyboardInterrupt:
        print("\nAborted by user.")
        sys.exit(0)

    # 4. 安全运行
    os.environ['GM_MODE'] = 'LIVE'
    
    try:
        run(
            strategy_id=config.STRATEGY_ID,
            filename='main.py',
            mode=MODE_LIVE,
            token=config.GM_TOKEN
        )
    except Exception as e:
        logger.error(f"🔥 LIVE FATAL ERROR: {e}")
        # 这里以后可以扩展发送紧急短信/报警

if __name__ == '__main__':
    main()
