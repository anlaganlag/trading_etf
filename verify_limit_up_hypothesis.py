"""
验证"1165%收益策略原理解析.md"中的核心假设

假设1: 65.3%的买入点在涨停板上
假设2: 剔除涨停板后收益变成-99.20%
假设3: 收益100%来自涨停板溢价

验证方法：
1. 统计每次选中股票的当日涨幅分布
2. 回测剔除涨停板后的策略表现
3. 分层分析不同涨幅区间的收益贡献
4. 计算涨停板的收益占比
"""
import os
import pandas as pd
import numpy as np
from config import config
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = os.path.join(config.BASE_DIR, "data_for_opt_stocks")
PRICES_FILE = os.path.join(DATA_DIR, "prices.csv")

START_DATE = '2021-12-03'
END_DATE = '2026-01-23'
WEIGHTS = {2: 0.3, 20: 0.7}
TOP_N = 4
HOLD_DAYS = 3

def backtest_with_filter(stocks, weights, hold_days, top_n, filter_func=None, filter_name="No Filter"):
    """
    回测，支持过滤条件

    filter_func: 接收(prices, selected_mask, date)，返回过滤后的mask
    """
    # 计算分数
    score_df = pd.DataFrame(0.0, index=stocks.index, columns=stocks.columns)
    for p, w in weights.items():
        ret = stocks / stocks.shift(p) - 1
        rank = ret.rank(axis=1, pct=True).fillna(0.5)
        score_df += rank * w

    # 选Top N
    top_n_mask = pd.DataFrame(False, index=score_df.index, columns=score_df.columns)
    vals = score_df.values
    vals = np.nan_to_num(vals, nan=-np.inf)
    idx = np.argpartition(-vals, top_n, axis=1)[:, :top_n]
    rows = np.arange(len(score_df))[:, None]
    top_n_mask.values[rows, idx] = True

    # 应用过滤器
    if filter_func is not None:
        filtered_mask = pd.DataFrame(False, index=top_n_mask.index, columns=top_n_mask.columns)

        for i, date in enumerate(top_n_mask.index):
            if i == 0:
                continue  # 第一天没有前一天数据

            selected = top_n_mask.loc[date]
            filtered = filter_func(stocks, selected, date)
            filtered_mask.loc[date] = filtered

        top_n_mask = filtered_mask

    # 计算收益
    market_ret = stocks.pct_change().fillna(0.0)
    port_daily = pd.Series(0.0, index=stocks.index)

    for lag in range(1, hold_days + 1):
        m = top_n_mask.shift(lag).fillna(False)
        tranche_ret = (market_ret * m).sum(axis=1) / top_n
        port_daily += tranche_ret

    port_daily /= hold_days
    port_daily = port_daily.iloc[hold_days:]

    # 计算指标
    cum_ret = (1 + port_daily).cumprod()
    total_ret = cum_ret.iloc[-1] - 1

    n_days = len(port_daily)
    ann_ret = (1 + total_ret) ** (252 / n_days) - 1
    ann_vol = port_daily.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum_max = np.maximum.accumulate(cum_ret)
    drawdown = (cum_ret - cum_max) / cum_max
    max_dd = drawdown.min()

    return {
        'name': filter_name,
        'total_return': total_ret,
        'annual_return': ann_ret,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'daily_ret': port_daily,
        'selected_mask': top_n_mask,
    }

def analyze_selection_distribution(stocks, weights, top_n):
    """分析选中股票的涨幅分布"""

    # 计算分数
    score_df = pd.DataFrame(0.0, index=stocks.index, columns=stocks.columns)
    for p, w in weights.items():
        ret = stocks / stocks.shift(p) - 1
        rank = ret.rank(axis=1, pct=True).fillna(0.5)
        score_df += rank * w

    # 选Top N
    top_n_mask = pd.DataFrame(False, index=score_df.index, columns=score_df.columns)
    vals = score_df.values
    vals = np.nan_to_num(vals, nan=-np.inf)
    idx = np.argpartition(-vals, top_n, axis=1)[:, :top_n]
    rows = np.arange(len(score_df))[:, None]
    top_n_mask.values[rows, idx] = True

    # 计算当日涨幅
    daily_ret = stocks.pct_change()

    # 统计选中股票的当日涨幅
    selected_returns = []

    for date in top_n_mask.index[1:]:  # 跳过第一天
        selected = top_n_mask.loc[date]
        selected_stocks = selected[selected].index

        for stock in selected_stocks:
            ret = daily_ret.loc[date, stock]
            if pd.notna(ret):
                selected_returns.append(ret)

    selected_returns = pd.Series(selected_returns)

    return selected_returns

def main():
    print("="*80)
    print("验证《1165%收益策略原理解析.md》中的核心假设")
    print("="*80)

    # 加载数据
    if not os.path.exists(PRICES_FILE):
        print(f"❌ 数据文件不存在: {PRICES_FILE}")
        return

    stocks = pd.read_csv(PRICES_FILE, index_col=0, parse_dates=True)
    stocks = stocks.loc[START_DATE:END_DATE]

    print(f"\n数据范围: {stocks.index[0].date()} ~ {stocks.index[-1].date()}")
    print(f"股票数量: {len(stocks.columns)}")
    print(f"交易日数: {len(stocks)}")

    # ================================================================
    # 验证假设1: 65.3%的买入点在涨停板上
    # ================================================================
    print("\n" + "="*80)
    print("验证假设1: 选中股票的涨幅分布")
    print("="*80)

    selected_returns = analyze_selection_distribution(stocks, WEIGHTS, TOP_N)

    # 统计涨幅区间
    limit_up_10 = (selected_returns > 0.095).sum()  # 10%涨停
    limit_up_20 = (selected_returns > 0.195).sum()  # 20%涨停
    strong_up = ((selected_returns > 0.05) & (selected_returns <= 0.095)).sum()  # 5-10%强势
    medium_up = ((selected_returns > 0.0) & (selected_returns <= 0.05)).sum()  # 0-5%
    flat_down = (selected_returns <= 0.0).sum()  # 下跌或平盘

    total = len(selected_returns)

    print(f"\n总样本数: {total}次选股")
    print(f"\n涨幅分布:")
    print(f"  >19.5% (20cm涨停):  {limit_up_20:>6} ({limit_up_20/total:>6.2%})")
    print(f"  9.5%-19.5% (10%涨停): {limit_up_10-limit_up_20:>6} ({(limit_up_10-limit_up_20)/total:>6.2%})")
    print(f"  5%-9.5% (强势):     {strong_up:>6} ({strong_up/total:>6.2%})")
    print(f"  0%-5% (普涨):       {medium_up:>6} ({medium_up/total:>6.2%})")
    print(f"  ≤0% (下跌):         {flat_down:>6} ({flat_down/total:>6.2%})")

    print(f"\n涨停板占比 (>9.5%):   {limit_up_10/total:.2%}")
    print(f"文档声称:            65.3%")
    print(f"差异:                {abs(limit_up_10/total - 0.653):.2%}")

    # 统计数据
    print(f"\n涨幅统计:")
    print(f"  均值:     {selected_returns.mean():.2%}")
    print(f"  中位数:   {selected_returns.median():.2%}")
    print(f"  标准差:   {selected_returns.std():.2%}")
    print(f"  最大值:   {selected_returns.max():.2%}")
    print(f"  最小值:   {selected_returns.min():.2%}")

    # ================================================================
    # 验证假设2: 剔除涨停板后收益-99%
    # ================================================================
    print("\n" + "="*80)
    print("验证假设2: 剔除涨停板后的策略表现")
    print("="*80)

    # 基准策略（无过滤）
    baseline = backtest_with_filter(stocks, WEIGHTS, HOLD_DAYS, TOP_N,
                                     filter_func=None, filter_name="基准策略（无过滤）")

    # 剔除涨停板策略
    def filter_no_limit_up(prices, selected_mask, date):
        """剔除当日涨幅>9.5%的股票"""
        daily_ret = prices.pct_change().loc[date]

        # 在选中的股票中，过滤掉涨停的
        filtered = selected_mask.copy()
        for stock in selected_mask[selected_mask].index:
            if daily_ret[stock] > 0.095:  # 涨幅>9.5%
                filtered[stock] = False

        return filtered

    no_limit_up = backtest_with_filter(stocks, WEIGHTS, HOLD_DAYS, TOP_N,
                                        filter_func=filter_no_limit_up,
                                        filter_name="剔除涨停板（>9.5%）")

    # 只保留涨停板策略
    def filter_only_limit_up(prices, selected_mask, date):
        """只保留当日涨幅>9.5%的股票"""
        daily_ret = prices.pct_change().loc[date]

        filtered = selected_mask.copy()
        for stock in selected_mask[selected_mask].index:
            if daily_ret[stock] <= 0.095:  # 涨幅≤9.5%
                filtered[stock] = False

        return filtered

    only_limit_up = backtest_with_filter(stocks, WEIGHTS, HOLD_DAYS, TOP_N,
                                          filter_func=filter_only_limit_up,
                                          filter_name="只买涨停板（>9.5%）")

    # 对比表
    results = [baseline, no_limit_up, only_limit_up]

    print("\n策略对比:")
    print("-"*80)
    print(f"{'策略':<30} {'总收益':>12} {'年化':>10} {'夏普':>8} {'最大回撤':>10}")
    print("-"*80)

    for r in results:
        print(f"{r['name']:<30} {r['total_return']:>11.2%} {r['annual_return']:>9.2%} "
              f"{r['sharpe']:>7.2f} {r['max_dd']:>9.2%}")

    print("-"*80)

    # 验证文档声称
    print(f"\n验证结果:")
    print(f"  文档声称（剔除涨停板）: -99.20%")
    print(f"  实际测试（剔除涨停板）: {no_limit_up['total_return']:.2%}")
    print(f"  差异: {abs(no_limit_up['total_return'] - (-0.992)):.2%}")

    if abs(no_limit_up['total_return'] - (-0.992)) < 0.05:
        print(f"\n✅ 假设2基本正确：剔除涨停板后收益接近-99%")
    else:
        print(f"\n⚠️ 假设2存在偏差")

    # ================================================================
    # 验证假设3: 收益100%来自涨停板
    # ================================================================
    print("\n" + "="*80)
    print("验证假设3: 涨停板的收益贡献")
    print("="*80)

    baseline_ret = baseline['total_return']
    only_limit_ret = only_limit_up['total_return']
    no_limit_ret = no_limit_up['total_return']

    # 计算涨停板贡献
    if baseline_ret != 0:
        limit_up_contribution = (only_limit_ret - no_limit_ret) / baseline_ret
        print(f"\n基准策略总收益: {baseline_ret:.2%}")
        print(f"只买涨停板收益: {only_limit_ret:.2%}")
        print(f"剔除涨停板收益: {no_limit_ret:.2%}")
        print(f"\n涨停板净贡献: {only_limit_ret - no_limit_ret:.2%}")
        print(f"涨停板贡献占比: {limit_up_contribution:.2%}")

        if limit_up_contribution > 0.8:
            print(f"\n✅ 假设3基本正确：涨停板贡献了{limit_up_contribution:.0%}的收益")
        else:
            print(f"\n⚠️ 假设3存在偏差：涨停板贡献仅{limit_up_contribution:.0%}")

    # ================================================================
    # 分层分析：不同涨幅区间的收益贡献
    # ================================================================
    print("\n" + "="*80)
    print("深度分析: 不同涨幅区间的收益贡献")
    print("="*80)

    # 定义多个过滤器
    filters = [
        ("全部", None),
        ("只买>19.5%涨停", lambda p, m, d: filter_by_return_range(p, m, d, 0.195, 1.0)),
        ("只买9.5%-19.5%", lambda p, m, d: filter_by_return_range(p, m, d, 0.095, 0.195)),
        ("只买5%-9.5%", lambda p, m, d: filter_by_return_range(p, m, d, 0.05, 0.095)),
        ("只买0%-5%", lambda p, m, d: filter_by_return_range(p, m, d, 0.0, 0.05)),
        ("只买下跌股", lambda p, m, d: filter_by_return_range(p, m, d, -1.0, 0.0)),
    ]

    print("\n各涨幅区间的策略表现:")
    print("-"*80)
    print(f"{'涨幅区间':<20} {'总收益':>12} {'年化':>10} {'夏普':>8} {'样本占比':>10}")
    print("-"*80)

    for name, filter_func in filters:
        if filter_func is None:
            result = baseline
            pct = 100.0
        else:
            result = backtest_with_filter(stocks, WEIGHTS, HOLD_DAYS, TOP_N,
                                           filter_func=filter_func, filter_name=name)

            # 计算样本占比
            selected_count = result['selected_mask'].sum().sum()
            total_count = baseline['selected_mask'].sum().sum()
            pct = selected_count / total_count * 100 if total_count > 0 else 0

        print(f"{name:<20} {result['total_return']:>11.2%} {result['annual_return']:>9.2%} "
              f"{result['sharpe']:>7.2f} {pct:>9.1f}%")

    print("-"*80)

    # ================================================================
    # 最终结论
    # ================================================================
    print("\n" + "="*80)
    print("📋 验证总结")
    print("="*80)

    print(f"\n1. 涨停板占比:")
    print(f"   文档声称: 65.3%")
    print(f"   实际测试: {limit_up_10/total:.2%}")
    print(f"   结论: {'✅ 基本一致' if abs(limit_up_10/total - 0.653) < 0.05 else '⚠️ 有偏差'}")

    print(f"\n2. 剔除涨停板收益:")
    print(f"   文档声称: -99.20%")
    print(f"   实际测试: {no_limit_up['total_return']:.2%}")
    print(f"   结论: {'✅ 基本一致' if abs(no_limit_up['total_return'] - (-0.992)) < 0.1 else '⚠️ 有偏差'}")

    print(f"\n3. 涨停板收益贡献:")
    print(f"   文档声称: 100%")
    print(f"   实际测试: {limit_up_contribution:.0%}")
    print(f"   结论: {'✅ 基本一致' if limit_up_contribution > 0.8 else '⚠️ 有偏差'}")

    print(f"\n" + "="*80)
    print("🎯 核心结论")
    print("="*80)

    if limit_up_10/total > 0.5 and abs(no_limit_up['total_return']) > 0.5:
        print(f"\n✅ 文档《1165%收益策略原理解析.md》的核心论断基本正确！")
        print(f"\n关键事实:")
        print(f"  • {limit_up_10/total:.0%}的买入点确实在涨停板上")
        print(f"  • 如果不能买入涨停板，策略收益会崩溃至{no_limit_up['total_return']:.0%}")
        print(f"  • 这个策略本质上是'打板策略'，实盘可行性极低")
        print(f"\n⚠️ 实盘警告:")
        print(f"  • 普通散户无法抢到涨停板")
        print(f"  • 买不到涨停板 = 买到炸板股/弱势股 = 巨亏")
        print(f"  • 除非你是职业打板客，否则不要尝试！")
    else:
        print(f"\n⚠️ 文档的论断存在一定偏差，需要进一步调查")

    print("="*80)

def filter_by_return_range(prices, selected_mask, date, min_ret, max_ret):
    """按涨幅区间过滤"""
    daily_ret = prices.pct_change().loc[date]

    filtered = selected_mask.copy()
    for stock in selected_mask[selected_mask].index:
        ret = daily_ret[stock]
        if pd.notna(ret):
            if not (min_ret <= ret < max_ret):
                filtered[stock] = False
        else:
            filtered[stock] = False

    return filtered

if __name__ == "__main__":
    main()
