"""
测试推荐的反转策略参数

快速验证方案1、2、3的回测表现

使用方法：
    python scripts/test_reversion_params.py
"""
import os
import pandas as pd
import numpy as np
from scipy import stats

def backtest_simple(periods_dict, prices, benchmark, start_date=None, end_date=None):
    """
    简单回测函数

    Args:
        periods_dict: 权重字典，如 {20: -100}
        prices: 价格DataFrame
        benchmark: 基准Series
        start_date: 起始日期
        end_date: 结束日期

    Returns:
        performance字典
    """
    # 计算各周期收益
    features = {}
    for period in periods_dict.keys():
        rets = prices.pct_change(period)
        features[period] = rets

    # 计算综合评分（反转：跌幅大的分数高）
    scores = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)

    for period, weight in periods_dict.items():
        rets = features[period]
        # 负权重：跌幅大的排名高
        ranks = (-rets).rank(axis=1, ascending=False)
        # 归一化
        normalized = (ranks.max(axis=1) - ranks + 1) / ranks.max(axis=1)
        scores += normalized * abs(weight)

    # 未来20日收益
    forward_p = 20
    future_rets = prices.shift(-forward_p) / prices - 1
    future_bm = benchmark.shift(-forward_p) / benchmark - 1

    # 筛选日期
    dates = prices.index
    if start_date:
        dates = dates[dates >= start_date]
    if end_date:
        dates = dates[dates <= end_date]

    # 有未来收益的日期
    valid_dates = [d for d in dates if d in future_rets.index and future_rets.loc[d].notna().sum() > 4]

    # 模拟交易
    portfolio_returns = []
    benchmark_returns = []

    for date in valid_dates:
        # 选择Top 4
        day_scores = scores.loc[date].dropna()
        if len(day_scores) < 4:
            continue

        selected = day_scores.nlargest(4).index

        # 收益
        stock_rets = future_rets.loc[date, selected]
        valid_rets = stock_rets.dropna()

        if len(valid_rets) > 0:
            port_ret = valid_rets.mean()
            portfolio_returns.append(port_ret)

            if date in future_bm.index:
                bm_ret = future_bm.loc[date]
                if not np.isnan(bm_ret):
                    benchmark_returns.append(bm_ret)

    # 计算指标
    portfolio_returns = np.array(portfolio_returns)
    benchmark_returns = np.array(benchmark_returns[:len(portfolio_returns)])

    if len(portfolio_returns) == 0:
        return None

    metrics = {
        'n_trades': len(portfolio_returns),
        'mean_return': portfolio_returns.mean(),
        'std_return': portfolio_returns.std(),
        'total_return': (1 + portfolio_returns).prod() - 1,
        'win_rate': 0,
        'excess_return': 0,
        'sharpe_ratio': 0,
        't_stat': 0,
        'p_value': 1.0
    }

    if len(benchmark_returns) > 0:
        metrics['win_rate'] = (portfolio_returns > benchmark_returns).mean()
        excess = portfolio_returns - benchmark_returns
        metrics['excess_return'] = excess.mean()

        if len(excess) > 1:
            t_stat, p_value = stats.ttest_1samp(excess, 0)
            metrics['t_stat'] = t_stat
            metrics['p_value'] = p_value

    if portfolio_returns.std() > 0:
        metrics['sharpe_ratio'] = portfolio_returns.mean() / portfolio_returns.std() * np.sqrt(252 / 20)

    return metrics


def main():
    """测试所有推荐方案"""
    print("=" * 80)
    print("反转策略参数回测验证")
    print("=" * 80)

    # 加载数据
    data_dir = 'data_for_opt_stocks'
    prices = pd.read_csv(os.path.join(data_dir, 'prices.csv'), index_col=0, parse_dates=True)
    prices = prices.apply(pd.to_numeric, errors='coerce')

    benchmark = pd.read_csv(os.path.join(data_dir, 'benchmark.csv'), index_col=0, parse_dates=True)
    if isinstance(benchmark, pd.DataFrame):
        benchmark = benchmark.iloc[:, 0]
    benchmark = pd.to_numeric(benchmark, errors='coerce')

    print(f"\n数据: {prices.shape}")
    print(f"时间范围: {prices.index[0].date()} ~ {prices.index[-1].date()}")

    # 定义要测试的方案
    strategies = {
        '当前策略': {1: 30, 3: -70, 20: 150},
        '方案1（推荐）': {20: -34, 19: -33, 18: -33},
        '方案2（最简）': {20: -100},
        '方案3（长期）': {15: -29, 18: -35, 20: -36}
    }

    # 分两个时期测试
    periods = [
        ('全部数据', None, None),
        ('近期（2025-）', '2025-01-01', None)
    ]

    results = []

    for period_name, start, end in periods:
        print(f"\n" + "=" * 80)
        print(f"回测期: {period_name}")
        print("=" * 80)

        for name, params in strategies.items():
            print(f"\n{name}: {params}")

            metrics = backtest_simple(params, prices, benchmark, start, end)

            if metrics:
                print(f"  交易次数: {metrics['n_trades']}")
                print(f"  胜率:     {metrics['win_rate']:.2%}")
                print(f"  平均收益: {metrics['mean_return']:.2%} (每20天)")
                print(f"  超额收益: {metrics['excess_return']:.2%}")
                print(f"  总收益:   {metrics['total_return']:.2%}")
                print(f"  夏普比率: {metrics['sharpe_ratio']:.2f}")
                print(f"  P值:      {metrics['p_value']:.4f}", end="")

                if metrics['p_value'] < 0.05:
                    print(" ✅ 显著")
                elif metrics['p_value'] < 0.10:
                    print(" ⚠️ 边缘")
                else:
                    print(" ❌ 不显著")

                results.append({
                    'period': period_name,
                    'strategy': name,
                    **metrics
                })

    # 汇总对比
    print("\n" + "=" * 80)
    print("汇总对比（全部数据）")
    print("=" * 80)

    df_results = pd.DataFrame(results)
    df_full = df_results[df_results['period'] == '全部数据']

    print(f"\n{'策略':<15} {'胜率':<10} {'超额收益':<10} {'夏普':<8} {'P值':<10} {'评价'}")
    print("-" * 80)

    for _, row in df_full.iterrows():
        status = ""
        if row['p_value'] < 0.05 and row['win_rate'] > 0.55:
            status = "✅ 优秀"
        elif row['p_value'] < 0.10 and row['win_rate'] > 0.52:
            status = "⚠️ 可用"
        else:
            status = "❌ 不佳"

        print(f"{row['strategy']:<15} {row['win_rate']:>8.2%} {row['excess_return']:>9.2%} {row['sharpe_ratio']:>6.2f} {row['p_value']:>8.4f} {status}")

    # 推荐
    print("\n" + "=" * 80)
    print("结论与建议")
    print("=" * 80)

    # 找出表现最好的方案（排除当前策略）
    df_new = df_full[df_full['strategy'] != '当前策略']

    if len(df_new) > 0:
        best = df_new.loc[df_new['excess_return'].idxmax()]

        print(f"\n📊 回测表现最佳: {best['strategy']}")
        print(f"   胜率: {best['win_rate']:.2%}")
        print(f"   超额收益: {best['excess_return']:.2%}")
        print(f"   P值: {best['p_value']:.4f}")

        # 与当前策略对比
        current = df_full[df_full['strategy'] == '当前策略'].iloc[0]

        print(f"\n📈 vs 当前策略:")
        print(f"   胜率提升:     {(best['win_rate'] - current['win_rate']):.2%}")
        print(f"   超额收益提升: {(best['excess_return'] - current['excess_return']):.2%}")

        if best['win_rate'] > current['win_rate'] + 0.05:
            print(f"\n✅ 建议采用: {best['strategy']}")

            # 给出参数
            params = strategies[best['strategy']]
            print(f"\n在 core/signal.py 中使用:")
            print(f"periods = {params}")
        else:
            print(f"\n⚠️ 改进不明显，建议:")
            print(f"   1. 扩展数据到3-5年")
            print(f"   2. 或使用方案2（最简单），先小资金测试")


if __name__ == '__main__':
    main()
