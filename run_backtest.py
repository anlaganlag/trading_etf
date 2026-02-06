"""
独立回测入口
用法: python run_backtest.py [--start START_DATE] [--end END_DATE] [--cash INITIAL_CASH]

示例:
  python run_backtest.py
  python run_backtest.py --start "2022-01-01 09:00:00" --end "2024-12-31 16:00:00"
  python run_backtest.py --cash 2000000
"""
import os
import argparse
from gm.api import run, MODE_BACKTEST, ADJUST_PREV
from config import config


def main():
    parser = argparse.ArgumentParser(description='ETF Rotation Strategy Backtest')
    parser.add_argument('--start', type=str, default=config.START_DATE,
                        help='Backtest start date (default: config.START_DATE)')
    parser.add_argument('--end', type=str, default=config.END_DATE,
                        help='Backtest end date (default: config.END_DATE)')
    parser.add_argument('--cash', type=float, default=1000000,
                        help='Initial cash (default: 1000000)')
    parser.add_argument('--commission', type=float, default=0.0001,
                        help='Commission ratio (default: 0.0001)')
    args = parser.parse_args()
    
    print("=" * 50)
    print("📉 ETF Rotation Strategy Backtest")
    print("=" * 50)
    print(f"📅 Period: {args.start} → {args.end}")
    print(f"💰 Initial Cash: ¥{args.cash:,.0f}")
    print(f"📊 Commission: {args.commission:.4%}")
    print("=" * 50)
    
    # 设置环境变量确保是回测模式
    os.environ['GM_MODE'] = 'BACKTEST'
    
    run(
        strategy_id=config.STRATEGY_ID,
        filename='main.py',
        mode=MODE_BACKTEST,
        token=os.getenv('MY_QUANT_TGM_TOKEN'),
        backtest_start_time=args.start,
        backtest_end_time=args.end,
        backtest_adjust=ADJUST_PREV,
        backtest_initial_cash=args.cash,
        backtest_commission_ratio=args.commission
    )


if __name__ == '__main__':
    main()
