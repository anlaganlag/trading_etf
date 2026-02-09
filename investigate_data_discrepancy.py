"""
调查《高收益参数.md》收益差异的原因

文档声称：259.61%累计收益，29.90%年化
实际验证：54.51%累计收益，11.56%年化

可能原因：
1. 时间段不同（文档说2021-01-01，我们用2021-12-03）
2. 权重归一化问题
3. 计算方法不同
4. 数据集不同
5. 回测bug
"""
import os
import pandas as pd
import numpy as np
from config import config
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = os.path.join(config.BASE_DIR, "data_for_opt_stocks")
PRICES_FILE = os.path.join(DATA_DIR, "prices.csv")

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

TOP_N = 4
HOLD_DAYS = 3

def backtest(stocks, weights, hold_days, top_n, start_date, end_date, normalize_weights=False):
    """
    标准回测

    normalize_weights: 是否归一化权重
    """
    stocks = stocks.loc[start_date:end_date]

    # 权重归一化
    if normalize_weights:
        total_weight = sum(abs(w) for w in weights.values())
        weights = {k: v/total_weight for k, v in weights.items()}

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

    # 计算收益
    market_ret = stocks.pct_change().fillna(0.0)
    port_daily = pd.Series(0.0, index=stocks.index)

    for lag in range(1, hold_days + 1):
        m = top_n_mask.shift(lag).fillna(False)
        tranche_ret = (market_ret * m).sum(axis=1) / top_n
        port_daily += tranche_ret

    port_daily /= hold_days
    port_daily = port_daily.iloc[hold_days:]

    cum_ret = (1 + port_daily).cumprod()
    total_ret = cum_ret.iloc[-1] - 1
    n_days = len(port_daily)
    ann_ret = (1 + total_ret) ** (252 / n_days) - 1

    cum_max = np.maximum.accumulate(cum_ret)
    drawdown = (cum_ret - cum_max) / cum_max
    max_dd = drawdown.min()

    return {
        'total_return': total_ret,
        'annual_return': ann_ret,
        'max_dd': max_dd,
        'n_days': n_days,
        'cum_ret': cum_ret,
        'daily_ret': port_daily,
    }

def main():
    print("="*80)
    print("调查《高收益参数.md》数据差异原因")
    print("="*80)

    stocks = pd.read_csv(PRICES_FILE, index_col=0, parse_dates=True)

    print(f"\n可用数据范围: {stocks.index[0].date()} ~ {stocks.index[-1].date()}")

    # ================================================================
    # 假设1: 时间段不同
    # ================================================================
    print("\n" + "="*80)
    print("假设1: 时间段差异")
    print("="*80)

    # 文档声称的时间段
    doc_start = '2021-01-01'
    doc_end = '2026-02-07'

    # 我们使用的时间段
    our_start = '2021-12-03'
    our_end = '2026-01-23'

    print(f"\n文档声称时间: {doc_start} ~ {doc_end}")
    print(f"我们的时间:   {our_start} ~ {our_end}")

    # 检查数据覆盖
    if stocks.index[0] > pd.to_datetime(doc_start):
        print(f"\n⚠️ 数据起始晚于文档声称的起始日期")
        print(f"   数据起始: {stocks.index[0].date()}")
        print(f"   文档起始: {doc_start}")

    # 测试文档时间段（如果数据允许）
    try:
        result_doc_period = backtest(stocks, DOC_WEIGHTS, HOLD_DAYS, TOP_N, doc_start, doc_end)
        print(f"\n使用文档时间段的结果:")
        print(f"  累计收益: {result_doc_period['total_return']:.2%}")
        print(f"  年化收益: {result_doc_period['annual_return']:.2%}")
        print(f"  最大回撤: {result_doc_period['max_dd']:.2%}")
    except:
        print(f"\n⚠️ 数据不包含文档声称的时间段")

    # 我们的时间段
    result_our_period = backtest(stocks, DOC_WEIGHTS, HOLD_DAYS, TOP_N, our_start, our_end)
    print(f"\n使用我们时间段的结果:")
    print(f"  累计收益: {result_our_period['total_return']:.2%}")
    print(f"  年化收益: {result_our_period['annual_return']:.2%}")
    print(f"  最大回撤: {result_our_period['max_dd']:.2%}")

    # ================================================================
    # 假设2: 权重归一化问题
    # ================================================================
    print("\n" + "="*80)
    print("假设2: 权重归一化")
    print("="*80)

    print(f"\n原始权重:")
    for p, w in DOC_WEIGHTS.items():
        print(f"  Day {p:>2}: {w:>7.3f}")

    print(f"\n权重总和: {sum(DOC_WEIGHTS.values()):.3f}")
    print(f"权重绝对值总和: {sum(abs(w) for w in DOC_WEIGHTS.values()):.3f}")

    # 测试归一化权重
    result_normalized = backtest(stocks, DOC_WEIGHTS, HOLD_DAYS, TOP_N, our_start, our_end,
                                 normalize_weights=True)

    print(f"\n归一化权重后的结果:")
    print(f"  累计收益: {result_normalized['total_return']:.2%}")
    print(f"  年化收益: {result_normalized['annual_return']:.2%}")

    # ================================================================
    # 假设3: 不同换仓周期
    # ================================================================
    print("\n" + "="*80)
    print("假设3: 不同换仓周期")
    print("="*80)

    for hold in [1, 3, 5, 10, 20]:
        result = backtest(stocks, DOC_WEIGHTS, hold, TOP_N, our_start, our_end)
        print(f"\n{hold}日换仓:")
        print(f"  累计收益: {result['total_return']:>7.2%}")
        print(f"  年化收益: {result['annual_return']:>7.2%}")

    # ================================================================
    # 假设4: 不同选股数量
    # ================================================================
    print("\n" + "="*80)
    print("假设4: 不同选股数量")
    print("="*80)

    for n in [2, 4, 6, 10]:
        result = backtest(stocks, DOC_WEIGHTS, HOLD_DAYS, n, our_start, our_end)
        print(f"\nTop {n}选股:")
        print(f"  累计收益: {result['total_return']:>7.2%}")
        print(f"  年化收益: {result['annual_return']:>7.2%}")

    # ================================================================
    # 假设5: 权重符号反转
    # ================================================================
    print("\n" + "="*80)
    print("假设5: 权重符号可能理解错误")
    print("="*80)

    # 测试所有权重取反
    reversed_weights = {k: -v for k, v in DOC_WEIGHTS.items()}
    result_reversed = backtest(stocks, reversed_weights, HOLD_DAYS, TOP_N, our_start, our_end)

    print(f"\n权重全部取反后:")
    print(f"  累计收益: {result_reversed['total_return']:.2%}")
    print(f"  年化收益: {result_reversed['annual_return']:.2%}")

    # 测试只反转负权重部分
    partial_reversed = {}
    for k, v in DOC_WEIGHTS.items():
        if v < 0:
            partial_reversed[k] = -v
        else:
            partial_reversed[k] = v

    result_partial = backtest(stocks, partial_reversed, HOLD_DAYS, TOP_N, our_start, our_end)

    print(f"\n只反转负权重:")
    print(f"  累计收益: {result_partial['total_return']:.2%}")
    print(f"  年化收益: {result_partial['annual_return']:.2%}")

    # ================================================================
    # 假设6: 不过滤vs过滤涨停板
    # ================================================================
    print("\n" + "="*80)
    print("假设6: 文档可能未过滤涨停板")
    print("="*80)

    # 不过滤涨停板的版本
    print(f"\n不过滤涨停板（已测试）:")
    print(f"  累计收益: {result_our_period['total_return']:.2%}")

    # 如果文档真的获得259%，可能的参数组合
    print(f"\n文档声称: 259.61%")
    print(f"实际测试: {result_our_period['total_return']:.2%}")
    print(f"倍数差异: {2.5961 / (result_our_period['total_return'] + 1):.2f}x")

    # ================================================================
    # 假设7: 滚动窗口vs固定周期
    # ================================================================
    print("\n" + "="*80)
    print("假设7: 计算收益率的方法可能不同")
    print("="*80)

    # 测试：使用shift(-p)而不是shift(p)（未来数据泄露）
    def backtest_lookahead(stocks, weights, hold_days, top_n, start_date, end_date):
        """使用未来数据的回测（错误方法）"""
        stocks = stocks.loc[start_date:end_date]

        score_df = pd.DataFrame(0.0, index=stocks.index, columns=stocks.columns)
        for p, w in weights.items():
            # 错误：使用未来数据
            ret = stocks.shift(-p) / stocks - 1
            rank = ret.rank(axis=1, pct=True).fillna(0.5)
            score_df += rank * w

        top_n_mask = pd.DataFrame(False, index=score_df.index, columns=score_df.columns)
        vals = score_df.values
        vals = np.nan_to_num(vals, nan=-np.inf)
        idx = np.argpartition(-vals, top_n, axis=1)[:, :top_n]
        rows = np.arange(len(score_df))[:, None]
        top_n_mask.values[rows, idx] = True

        market_ret = stocks.pct_change().fillna(0.0)
        port_daily = pd.Series(0.0, index=stocks.index)

        for lag in range(1, hold_days + 1):
            m = top_n_mask.shift(lag).fillna(False)
            tranche_ret = (market_ret * m).sum(axis=1) / top_n
            port_daily += tranche_ret

        port_daily /= hold_days
        port_daily = port_daily.iloc[hold_days:]

        cum_ret = (1 + port_daily).cumprod()
        total_ret = cum_ret.iloc[-1] - 1
        n_days = len(port_daily)
        ann_ret = (1 + total_ret) ** (252 / n_days) - 1

        return total_ret, ann_ret

    try:
        total_lookahead, ann_lookahead = backtest_lookahead(stocks, DOC_WEIGHTS, HOLD_DAYS, TOP_N,
                                                            our_start, our_end)
        print(f"\n如果使用未来数据（错误）:")
        print(f"  累计收益: {total_lookahead:.2%}")
        print(f"  年化收益: {ann_lookahead:.2%}")

        if abs(total_lookahead - 2.5961) < 0.5:
            print(f"\n⚠️ 警告：使用未来数据能达到文档声称的收益！")
            print(f"   这可能是文档的bug来源")
    except:
        print(f"\n无法测试未来数据场景")

    # ================================================================
    # 总结
    # ================================================================
    print("\n" + "="*80)
    print("📋 调查总结")
    print("="*80)

    print(f"\n测试的各种情况:")
    print(f"1. 原始参数（我们的时间段）: {result_our_period['total_return']:.2%}")
    print(f"2. 归一化权重:               {result_normalized['total_return']:.2%}")
    print(f"3. 权重全部取反:             {result_reversed['total_return']:.2%}")
    print(f"4. 只反转负权重:             {result_partial['total_return']:.2%}")

    print(f"\n文档声称:                    259.61%")
    print(f"差距最小的方案:              {max(result_our_period['total_return'], result_normalized['total_return'], result_reversed['total_return'], result_partial['total_return']):.2%}")

    print(f"\n🎯 可能的原因:")
    print(f"1. 时间段不同（我们的数据可能不包含2021年初的数据）")
    print(f"2. 数据集不同（文档可能用了不同的股票池）")
    print(f"3. 计算方法不同（可能有bug或特殊处理）")
    print(f"4. 文档数据可能有误或夸大")

    # 检查数据起始
    if stocks.index[0] > pd.to_datetime('2021-01-01'):
        print(f"\n⚠️ 重要发现：我们的数据从{stocks.index[0].date()}开始")
        print(f"   文档声称从2021-01-01开始，缺少了{(stocks.index[0] - pd.to_datetime('2021-01-01')).days}天的数据")
        print(f"   如果2021年初表现特别好，这可能是差异的主要原因")

    print("="*80)

if __name__ == "__main__":
    main()
