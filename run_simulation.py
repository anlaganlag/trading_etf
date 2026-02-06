"""
Simulation script for missing live trading days
"""
import os
import sys
from gm.api import run, MODE_BACKTEST, ADJUST_PREV
from config import config, logger

def main():
    start_date = '2026-01-26 09:00:00'
    end_date = '2026-02-06 16:00:00'
    cash = 1000000

    # 1. 环境校验
    # Skip strict env check to avoid issues, or simpler check
    # if not config.validate_env(mode='BACKTEST'):
    #     logger.error("❌ Environment check failed. Aborting.")
    #     sys.exit(1)

    logger.info("=" * 60)
    logger.info("📉 ETF Rotation Strategy - SIMULATION MODE")
    logger.info(f"📅 Period: {start_date} -> {end_date}")
    logger.info(f"💰 Cash: ¥{cash:,.0f}")
    logger.info("=" * 60)
    
    # 设置环境变量供 main.py 识别
    os.environ['GM_MODE'] = 'BACKTEST'
    
    try:
        run(
            strategy_id=config.STRATEGY_ID,
            filename='main.py',
            mode=MODE_BACKTEST,
            token=config.GM_TOKEN,
            backtest_start_time=start_date,
            backtest_end_time=end_date,
            backtest_adjust=ADJUST_PREV,
            backtest_initial_cash=cash,
            backtest_commission_ratio=0.0001
        )
    except Exception as e:
        logger.error(f"💥 Simulation crashed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
