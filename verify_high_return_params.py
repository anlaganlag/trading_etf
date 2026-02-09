"""
验证《高收益参数.md》中的策略参数

文档声称的参数：
- Day 1, 2, 3: -0.019, -0.140, -0.243 (短期反转)
- Day 5, 7: -0.160, -0.689 (核心回调)
- Day 10, 14, 20: +0.761, +0.419, +0.530 (趋势驱动)

文档声称的表现：
- 累计收益：259.61%
- 年化收益：29.90%
- 最大回撤：-64.59%
- 实盘成交率：100% (过滤涨停板>9.5%)

验证内容：
1. 使用文档参数回测，验证收益是否匹配
2. 对比过滤/不过滤涨停板的差异
3. 与之前的{2: 30, 20: 70}参数对比
4. 验证实盘可行性
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
TOP_N = 4
HOLD_DAYS = 3

# 文档声称的参数
DOC_WEIGHTS = {
    1: -0.019,
    2: -0.140,
    3: -0.243,
    5: -0.160,
    7: -0.689,
    10: 0.761,
    14: 0.419,
    20: 0.530
}

# 之前的参数（用于对比）
OLD_WEIGHTS = {2: 0.3, 20: 0.7}

def backtest_strategy(stocks, weights, hold_days, top_n, filter_limit_up=False, filter_name=""):
    """
    回测策略

    Args:
        filter_limit_up: 是否过滤涨停板（>9.5%）
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

    # 过滤涨停板
    if filter_limit_up:
        daily_ret = stocks.pct_change()
        filtered_mask = pd.DataFrame(False, index=top_n_mask.index, columns=top_n_mask.columns)

        for date in top_n_mask.index[1:]:
            selected = top_n_mask.loc[date]
            ret_today = daily_ret.loc[date]

            # 过滤当日涨幅>9.5%的股票
            for stock in selected[selected].index:
                if pd.notna(ret_today[stock]) and ret_today[stock] <= 0.095:
                    filtered_mask.loc[date, stock] = True

        top_n_mask = filtered_mask

    # 计算收益
    market_ret = stocks.pct_change().fillna(0.0)
    port_daily = pd.Series(0.0, index=stocks.index)

    for lag in range(1, hold_days + 1):
        m = top_n_mask.shift(lag).fillna(False)
        # 统计每天实际选中的股票数
        daily_count = m.sum(axis=1)
        # 如果某天没有选中股票（全被过滤），避免除以0
        daily_count = daily_count.replace(0, np.nan)

        tranche_ret = (market_ret * m).sum(axis=1) / daily_count
        port_daily += tranche_ret.fillna(0)

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

    calmar = ann_ret / abs(max_dd) if max_dd < 0 else 0

    # 统计成交率（如果开启了过滤）
    if filter_limit_up:
        original_count = len(stocks.index) * top_n
        actual_count = top_n_mask.sum().sum()
        fill_rate = actual_count / original_count
    else:
        fill_rate = 1.0

    return {
        'name': filter_name,
        'weights': weights,
        'total_return': total_ret,
        'annual_return': ann_ret,
        'annual_vol': ann_vol,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'calmar': calmar,
        'daily_ret': port_daily,
        'cum_ret': cum_ret,
        'fill_rate': fill_rate,
    }

def main():
    print("="*80)
    print("验证《高收益参数.md》中的策略参数")
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
    # 验证1: 文档参数的实际表现
    # ================================================================
    print("\n" + "="*80)
    print("验证1: 文档参数表现（过滤涨停板）")
    print("="*80)

    print("\n文档声称的参数:")
    for period, weight in DOC_WEIGHTS.items():
        print(f"  Day {period:>2}: {weight:>7.3f}")

    doc_result_filtered = backtest_strategy(stocks, DOC_WEIGHTS, HOLD_DAYS, TOP_N,
                                           filter_limit_up=True,
                                           filter_name="文档参数（过滤涨停）")

    print("\n回测结果:")
    print(f"  累计收益:   {doc_result_filtered['total_return']:>7.2%}")
    print(f"  年化收益:   {doc_result_filtered['annual_return']:>7.2%}")
    print(f"  最大回撤:   {doc_result_filtered['max_dd']:>7.2%}")
    print(f"  夏普比率:   {doc_result_filtered['sharpe']:>7.2f}")
    print(f"  成交率:     {doc_result_filtered['fill_rate']:>7.2%}")

    print("\n文档声称:")
    print(f"  累计收益:   259.61%")
    print(f"  年化收益:    29.90%")
    print(f"  最大回撤:   -64.59%")
    print(f"  成交率:     100.00%")

    print("\n差异:")
    print(f"  累计收益差: {abs(doc_result_filtered['total_return'] - 2.5961):.2%}")
    print(f"  年化收益差: {abs(doc_result_filtered['annual_return'] - 0.2990):.2%}")
    print(f"  最大回撤差: {abs(doc_result_filtered['max_dd'] - (-0.6459)):.2%}")

    # 判断是否匹配
    total_ret_match = abs(doc_result_filtered['total_return'] - 2.5961) < 0.1
    ann_ret_match = abs(doc_result_filtered['annual_return'] - 0.2990) < 0.05
    dd_match = abs(doc_result_filtered['max_dd'] - (-0.6459)) < 0.1

    if total_ret_match and ann_ret_match and dd_match:
        print("\n✅ 验证通过：文档声称的数据基本匹配！")
    else:
        print("\n⚠️ 验证失败：文档数据与实际回测存在偏差")

    # ================================================================
    # 验证2: 过滤 vs 不过滤涨停板的差异
    # ================================================================
    print("\n" + "="*80)
    print("验证2: 过滤涨停板的影响")
    print("="*80)

    doc_result_no_filter = backtest_strategy(stocks, DOC_WEIGHTS, HOLD_DAYS, TOP_N,
                                            filter_limit_up=False,
                                            filter_name="文档参数（不过滤）")

    print("\n对比:")
    print("-"*80)
    print(f"{'策略':<30} {'累计收益':>12} {'年化':>10} {'夏普':>8} {'回撤':>10} {'成交率':>10}")
    print("-"*80)

    for result in [doc_result_no_filter, doc_result_filtered]:
        print(f"{result['name']:<30} {result['total_return']:>11.2%} {result['annual_return']:>9.2%} "
              f"{result['sharpe']:>7.2f} {result['max_dd']:>9.2%} {result['fill_rate']:>9.2%}")

    print("-"*80)

    # 计算过滤的影响
    ret_loss = doc_result_no_filter['total_return'] - doc_result_filtered['total_return']
    print(f"\n过滤涨停板的代价:")
    print(f"  收益损失: {ret_loss:.2%}")
    print(f"  年化损失: {doc_result_no_filter['annual_return'] - doc_result_filtered['annual_return']:.2%}")

    if ret_loss < 0.5:  # 损失<50%
        print(f"\n✅ 过滤涨停板的代价较小，策略具备实盘可行性")
    else:
        print(f"\n⚠️ 过滤涨停板损失较大，策略可能仍依赖涨停板")

    # ================================================================
    # 验证3: 与旧参数{2: 30, 20: 70}对比
    # ================================================================
    print("\n" + "="*80)
    print("验证3: 与旧参数 {2: 30, 20: 70} 对比")
    print("="*80)

    old_result_filtered = backtest_strategy(stocks, OLD_WEIGHTS, HOLD_DAYS, TOP_N,
                                           filter_limit_up=True,
                                           filter_name="旧参数（过滤涨停）")

    old_result_no_filter = backtest_strategy(stocks, OLD_WEIGHTS, HOLD_DAYS, TOP_N,
                                            filter_limit_up=False,
                                            filter_name="旧参数（不过滤）")

    print("\n全面对比（过滤涨停板后）:")
    print("-"*80)
    print(f"{'策略':<30} {'累计收益':>12} {'年化':>10} {'夏普':>8} {'回撤':>10}")
    print("-"*80)
    print(f"{'文档参数（新）':<30} {doc_result_filtered['total_return']:>11.2%} "
          f"{doc_result_filtered['annual_return']:>9.2%} "
          f"{doc_result_filtered['sharpe']:>7.2f} {doc_result_filtered['max_dd']:>9.2%}")
    print(f"{'旧参数 {2:30, 20:70}':<30} {old_result_filtered['total_return']:>11.2%} "
          f"{old_result_filtered['annual_return']:>9.2%} "
          f"{old_result_filtered['sharpe']:>7.2f} {old_result_filtered['max_dd']:>9.2%}")
    print("-"*80)

    improvement = doc_result_filtered['total_return'] - old_result_filtered['total_return']
    print(f"\n文档参数相比旧参数:")
    print(f"  收益改进: {improvement:>+7.2%}")
    print(f"  年化改进: {doc_result_filtered['annual_return'] - old_result_filtered['annual_return']:>+7.2%}")
    print(f"  夏普改进: {doc_result_filtered['sharpe'] - old_result_filtered['sharpe']:>+7.2f}")

    if improvement > 0.5:
        print(f"\n✅ 文档参数在过滤涨停板后表现显著优于旧参数")
    elif improvement > 0:
        print(f"\n⚠️ 文档参数略优于旧参数，但改进有限")
    else:
        print(f"\n❌ 文档参数不如旧参数")

    # ================================================================
    # 验证4: 实盘可行性评估
    # ================================================================
    print("\n" + "="*80)
    print("验证4: 实盘可行性评估")
    print("="*80)

    # 统计被过滤的股票占比
    daily_ret = stocks.pct_change()

    # 计算文档参数选出的股票
    score_df = pd.DataFrame(0.0, index=stocks.index, columns=stocks.columns)
    for p, w in DOC_WEIGHTS.items():
        ret = stocks / stocks.shift(p) - 1
        rank = ret.rank(axis=1, pct=True).fillna(0.5)
        score_df += rank * w

    top_n_mask = pd.DataFrame(False, index=score_df.index, columns=score_df.columns)
    vals = score_df.values
    vals = np.nan_to_num(vals, nan=-np.inf)
    idx = np.argpartition(-vals, TOP_N, axis=1)[:, :TOP_N]
    rows = np.arange(len(score_df))[:, None]
    top_n_mask.values[rows, idx] = True

    # 统计选中股票的涨幅分布
    selected_returns = []
    for date in top_n_mask.index[1:]:
        selected = top_n_mask.loc[date]
        ret_today = daily_ret.loc[date]

        for stock in selected[selected].index:
            ret = ret_today[stock]
            if pd.notna(ret):
                selected_returns.append(ret)

    selected_returns = pd.Series(selected_returns)

    # 统计涨停板占比
    limit_up_count = (selected_returns > 0.095).sum()
    total_count = len(selected_returns)
    limit_up_pct = limit_up_count / total_count if total_count > 0 else 0

    print(f"\n选中股票的涨幅分布:")
    print(f"  总样本数:     {total_count}")
    print(f"  涨停板数:     {limit_up_count}")
    print(f"  涨停板占比:   {limit_up_pct:.2%}")
    print(f"\n  均值涨幅:     {selected_returns.mean():.2%}")
    print(f"  中位数涨幅:   {selected_returns.median():.2%}")

    print(f"\n实盘可行性评估:")
    if limit_up_pct < 0.2:
        print(f"  ✅ 优秀：涨停板占比<20%，散户可轻松成交")
    elif limit_up_pct < 0.4:
        print(f"  ⭐ 良好：涨停板占比<40%，大部分情况可成交")
    elif limit_up_pct < 0.6:
        print(f"  ⚠️ 一般：涨停板占比较高，成交有困难")
    else:
        print(f"  ❌ 困难：涨停板占比>60%，散户难以操作")

    # ================================================================
    # 总结报告
    # ================================================================
    print("\n" + "="*80)
    print("📋 综合验证报告")
    print("="*80)

    print(f"\n1. 文档数据准确性:")
    if total_ret_match and ann_ret_match:
        print(f"   ✅ 文档声称的收益数据基本准确")
        print(f"   - 实测累计收益: {doc_result_filtered['total_return']:.2%} vs 声称259.61%")
        print(f"   - 实测年化收益: {doc_result_filtered['annual_return']:.2%} vs 声称29.90%")
    else:
        print(f"   ⚠️ 文档数据与实测存在偏差")
        print(f"   - 实测累计收益: {doc_result_filtered['total_return']:.2%} vs 声称259.61%")
        print(f"   - 实测年化收益: {doc_result_filtered['annual_return']:.2%} vs 声称29.90%")

    print(f"\n2. 实盘可行性:")
    print(f"   - 涨停板占比: {limit_up_pct:.2%} (旧参数65%)")
    print(f"   - 成交率: {doc_result_filtered['fill_rate']:.2%}")
    print(f"   - 过滤涨停板后收益: {doc_result_filtered['total_return']:.2%}")

    if limit_up_pct < 0.3:
        print(f"   ✅ 实盘可行性高，涨停板依赖低")
    else:
        print(f"   ⚠️ 仍有一定涨停板依赖")

    print(f"\n3. 相比旧参数的优势:")
    print(f"   - 过滤涨停后收益差: {improvement:+.2%}")
    print(f"   - 年化收益差: {doc_result_filtered['annual_return'] - old_result_filtered['annual_return']:+.2%}")

    if improvement > 0.5:
        print(f"   ✅ 新参数显著优于旧参数（过滤涨停板场景）")
    elif improvement > 0:
        print(f"   ⚠️ 新参数略优于旧参数")
    else:
        print(f"   ❌ 新参数不如旧参数")

    print("\n" + "="*80)
    print("🎯 最终结论")
    print("="*80)

    if total_ret_match and limit_up_pct < 0.3 and improvement > 0:
        print(f"\n✅ 文档《高收益参数.md》的参数经验证基本可信！")
        print(f"\n关键优势:")
        print(f"  • 涨停板占比{limit_up_pct:.0%}，远低于旧参数的65%")
        print(f"  • 过滤涨停板后仍有{doc_result_filtered['annual_return']:.1%}年化收益")
        print(f"  • 实盘可行性显著提升")
        print(f"\n⚠️ 但需注意:")
        print(f"  • 最大回撤{doc_result_filtered['max_dd']:.1%}仍然较大")
        print(f"  • 收益显著低于不过滤版本（这是可操作性的代价）")
    else:
        print(f"\n⚠️ 文档参数存在以下问题:")
        if not total_ret_match:
            print(f"  • 声称的收益数据与实测有偏差")
        if limit_up_pct >= 0.3:
            print(f"  • 涨停板占比仍然较高（{limit_up_pct:.0%}）")
        if improvement <= 0:
            print(f"  • 过滤涨停板后不如旧参数")

    print("="*80)

if __name__ == "__main__":
    main()
