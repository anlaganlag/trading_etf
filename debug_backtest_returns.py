"""
调试回测收益率计算
检查为什么简化回测显示50000%+的收益
"""
import os
import pandas as pd
import numpy as np
from config import config

DATA_DIR = os.path.join(config.BASE_DIR, "data_for_opt_stocks")
PRICES_FILE = os.path.join(DATA_DIR, "prices.csv")

START_DATE = '2021-12-03'
END_DATE = '2026-01-23'
WEIGHTS = {2: 0.3, 20: 0.7}
TOP_N = 4

def debug_returns():
    """逐步调试收益率计算"""

    stocks = pd.read_csv(PRICES_FILE, index_col=0, parse_dates=True)
    stocks = stocks.loc[START_DATE:END_DATE]

    print("="*60)
    print("数据基本信息")
    print("="*60)
    print(f"股票数: {len(stocks.columns)}")
    print(f"交易日: {len(stocks)}")
    print(f"日期范围: {stocks.index[0]} 到 {stocks.index[-1]}")

    # 计算分数
    score_df = pd.DataFrame(0.0, index=stocks.index, columns=stocks.columns)
    for p, w in WEIGHTS.items():
        ret = stocks / stocks.shift(p) - 1
        rank = ret.rank(axis=1, pct=True).fillna(0.5)
        score_df += rank * w

    # 选Top N
    top_n_mask = pd.DataFrame(False, index=score_df.index, columns=score_df.columns)
    vals = score_df.values
    vals = np.nan_to_num(vals, nan=-np.inf)
    idx = np.argpartition(-vals, TOP_N, axis=1)[:, :TOP_N]
    rows = np.arange(len(score_df))[:, None]
    top_n_mask.values[rows, idx] = True

    # 计算市场收益
    market_ret = stocks.pct_change().fillna(0.0)

    # 方法1: 简单的T+1持仓
    print("\n" + "="*60)
    print("方法1: 简单T+1持仓 (每天换仓)")
    print("="*60)

    # T日收盘选股，T+1日持有
    port_ret_simple = (market_ret * top_n_mask.shift(1)).sum(axis=1) / TOP_N
    port_ret_simple = port_ret_simple.iloc[1:]  # 去掉第一天

    cum_simple = (1 + port_ret_simple).cumprod()

    print(f"起始净值: 1.0")
    print(f"结束净值: {cum_simple.iloc[-1]:.2f}")
    print(f"总收益: {(cum_simple.iloc[-1] - 1):.2%}")

    # 检查前10天收益
    print("\n前10天净值走势:")
    print(cum_simple.head(10))

    # 检查是否有异常收益日
    print("\n最大单日收益Top 10:")
    top_days = port_ret_simple.nlargest(10)
    for date, ret in top_days.items():
        print(f"  {date.date()}: {ret:.2%}")

    print("\n最大单日亏损Top 10:")
    worst_days = port_ret_simple.nsmallest(10)
    for date, ret in worst_days.items():
        print(f"  {date.date()}: {ret:.2%}")

    # 方法2: 3分仓滚动
    print("\n" + "="*60)
    print("方法2: 3分仓滚动 (文档中的方法)")
    print("="*60)

    HOLD_DAYS = 3
    port_daily = pd.Series(0.0, index=stocks.index)

    for lag in range(1, HOLD_DAYS + 1):
        m = top_n_mask.shift(lag).fillna(False)
        tranche_ret = (market_ret * m).sum(axis=1) / TOP_N
        port_daily += tranche_ret

    port_daily /= HOLD_DAYS
    port_daily = port_daily.iloc[HOLD_DAYS:]

    cum_rolling = (1 + port_daily).cumprod()

    print(f"起始净值: 1.0")
    print(f"结束净值: {cum_rolling.iloc[-1]:.2f}")
    print(f"总收益: {(cum_rolling.iloc[-1] - 1):.2%}")

    # 检查前10天
    print("\n前10天净值走势:")
    print(cum_rolling.head(10))

    # 检查最大单日收益
    print("\n最大单日收益Top 10:")
    top_days = port_daily.nlargest(10)
    for date, ret in top_days.items():
        print(f"  {date.date()}: {ret:.2%}")

    # 统计分析
    print("\n" + "="*60)
    print("收益率统计")
    print("="*60)

    print("\n方法1 (每天换仓):")
    print(f"  平均日收益: {port_ret_simple.mean():.4%}")
    print(f"  收益标准差: {port_ret_simple.std():.4%}")
    print(f"  夏普比率: {port_ret_simple.mean() / port_ret_simple.std() * np.sqrt(252):.2f}")
    print(f"  胜率: {(port_ret_simple > 0).mean():.2%}")

    print("\n方法2 (3分仓):")
    print(f"  平均日收益: {port_daily.mean():.4%}")
    print(f"  收益标准差: {port_daily.std():.4%}")
    print(f"  夏普比率: {port_daily.mean() / port_daily.std() * np.sqrt(252):.2f}")
    print(f"  胜率: {(port_daily > 0).mean():.2%}")

    # 检查是否有数据异常
    print("\n" + "="*60)
    print("数据质量检查")
    print("="*60)

    # 检查是否有涨跌停异常
    daily_changes = stocks.pct_change()

    extreme_up = (daily_changes > 0.2).sum().sum()  # 单日涨超20%
    extreme_down = (daily_changes < -0.2).sum().sum()  # 单日跌超20%

    print(f"单日涨幅>20%次数: {extreme_up}")
    print(f"单日跌幅>20%次数: {extreme_down}")

    # 检查是否有停牌恢复后的巨大跳空
    gaps = daily_changes[daily_changes.abs() > 0.5].stack()
    if len(gaps) > 0:
        print(f"\n发现{len(gaps)}个巨大跳空(>50%):")
        print(gaps.head(20))

    # 检查选中的股票是否都是妖股
    print("\n" + "="*60)
    print("选股特征分析")
    print("="*60)

    # 统计每只股票被选中的次数
    selection_count = top_n_mask.sum(axis=0).sort_values(ascending=False)

    print(f"\n被选次数Top 20:")
    for stock, count in selection_count.head(20).items():
        total_ret = (stocks[stock].iloc[-1] / stocks[stock].iloc[0] - 1)
        print(f"  {stock}: {count}次 (总涨幅: {total_ret:.2%})")

    # 分析这些股票的特征
    top_20_stocks = selection_count.head(20).index
    top_20_returns = stocks[top_20_stocks].pct_change().mean()

    print(f"\nTop 20常选股的平均日收益: {top_20_returns.mean():.4%}")

if __name__ == "__main__":
    debug_returns()
