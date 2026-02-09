"""
工业级回测入口
支持命令行参数、环境自动化校验、黄金基准比对。
"""
import os
import argparse
import sys
from gm.api import run, MODE_BACKTEST, ADJUST_PREV
from config import config, logger

def main():
    parser = argparse.ArgumentParser(description='ETF Rotation Strategy Backtest')
    parser.add_argument('--start', type=str, default=config.START_DATE, help='Start Date')
    parser.add_argument('--end', type=str, default=config.END_DATE, help='End Date')
    parser.add_argument('--cash', type=float, default=1000000, help='Initial Cash')
    args = parser.parse_args()
    
    # 1. 环境校验
    if not config.validate_env(mode='BACKTEST'):
        logger.error("❌ Environment check failed. Aborting.")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("📉 ETF Rotation Strategy - BACKTEST MODE")
    logger.info(f"📅 Period: {args.start} -> {args.end}")
    logger.info(f"💰 Cash: ¥{args.cash:,.0f}")
    logger.info("=" * 60)
    
    # 设置环境变量供 main.py 识别
    os.environ['GM_MODE'] = 'BACKTEST'
    
    try:
        run(
            strategy_id=config.STRATEGY_ID,
            filename='main.py',
            mode=MODE_BACKTEST,
            token=config.GM_TOKEN,
            backtest_start_time=args.start,
            backtest_end_time=args.end,
            backtest_adjust=ADJUST_PREV,
            backtest_initial_cash=args.cash,
            backtest_commission_ratio=0.0001,
            backtest_match_mode=1  # <--- 添加这一行，实现收盘价撮合

        )
    except Exception as e:
        logger.error(f"💥 Backtest crashed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
