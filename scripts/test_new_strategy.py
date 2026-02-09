"""
测试新的反转策略参数

对比：
- 原策略：{1: 30, 3: -70, 20: 150}（追涨）
- 新策略：{20: -100}（反转）

使用方法：
    python scripts/test_new_strategy.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from scipy import stats

def backtest_strategy(periods_dict, prices, benchmark, name="Strategy"):
    """
    回测策略

    Args:
        periods_dict: 权重字典
        prices: 价格数据
        benchmark: 基准指数
        name: 策略名称

    Returns:
        metrics字典
    """
    print(f"\n{'='*70}")
    print(f"回测策略: {name}")
    print(f"参数: {periods_dict}")
    print(f"{'='*70}")

    # 计算收益
    hist = prices
    last = hist.iloc[-1]

    # 计算各周期收益
    rets = {}
    for p in periods_dict.keys():
        rets[f'r{p}'] = (hist / hist.shift(p)) - 1

    # 计算评分（按原有逻辑）
    all_scores = []
    all_dates = hist.index[251:]  # 需要至少251天历史

    for current_dt in all_dates:
        hist_slice = hist[:current_dt]
        if len(hist_slice) < 251:
            continue

        last_prices = hist_slice.iloc[-1]
        scores = pd.Series(0.0, index=hist.columns)

        # 计算当日各周期收益
        for p in periods_dict.keys():
            if len(hist_slice) > p:
                period_ret = (hist_slice.iloc[-1] / hist_slice.iloc[-(p+1)]) - 1
                # 排名评分
                weight = periods_dict[p]
                # 反转策略(负权重)：跌幅大的排名高
                if weight < 0:
                    ranks = period_ret.rank(ascending=True, method='min')  # 收益低的排名靠前
                    score_component = ((30 - ranks) / 30).clip(lower=0) * abs(weight)
                else:
                    ranks = period_ret.rank(ascending=False, method='min')  # 收益高的排名靠前
                    score_component = ((30 - ranks) / 30).clip(lower=0) * weight
                scores += score_component

        all_scores.append((current_dt, scores))

    print(f"计算了 {len(all_scores)} 个交易日的评分")

    # 未来20日收益
    forward_p = 20
    future_rets = prices.shift(-forward_p) / prices - 1
    future_bm = benchmark.shift(-forward_p) / benchmark - 1

    # 模拟交易
    portfolio_returns = []
    benchmark_returns = []
    win_count = 0
    selected_stocks_history = []

    for date, scores in all_scores:
        if date not in future_rets.index:
            continue

        # 选择Top 4
        valid_scores = scores.dropna()
        if len(valid_scores) < 4:
            continue

        top4 = valid_scores.nlargest(4)
        selected = top4.index.tolist()
        selected_stocks_history.append((date, selected, top4.values))

        # 未来收益
        stock_rets = future_rets.loc[date, selected]
        valid_rets = stock_rets.dropna()

        if len(valid_rets) > 0:
            port_ret = valid_rets.mean()
            portfolio_returns.append(port_ret)

            if date in future_bm.index:
                bm_ret = future_bm.loc[date]
                if not np.isnan(bm_ret):
                    benchmark_returns.append(bm_ret)
                    if port_ret > bm_ret:
                        win_count += 1

    # 计算指标
    portfolio_returns = np.array(portfolio_returns)
    benchmark_returns = np.array(benchmark_returns[:len(portfolio_returns)])

    if len(portfolio_returns) == 0:
        print("❌ 没有交易数据！")
        return None

    metrics = {
        'n_trades': len(portfolio_returns),
        'mean_return': portfolio_returns.mean(),
        'std_return': portfolio_returns.std(),
        'total_return': (1 + portfolio_returns).prod() - 1,
        'win_rate': win_count / len(benchmark_returns) if len(benchmark_returns) > 0 else 0,
        'sharpe_ratio': 0,
        'max_drawdown': 0,
        'excess_return': 0,
        't_stat': 0,
        'p_value': 1.0
    }

    # 超额收益
    if len(benchmark_returns) > 0:
        excess = portfolio_returns - benchmark_returns
        metrics['excess_return'] = excess.mean()
        metrics['benchmark_return'] = benchmark_returns.mean()

        # t检验
        if len(excess) > 1:
            t_stat, p_value = stats.ttest_1samp(excess, 0)
            metrics['t_stat'] = t_stat
            metrics['p_value'] = p_value

    # 夏普比率
    if portfolio_returns.std() > 0:
        metrics['sharpe_ratio'] = portfolio_returns.mean() / portfolio_returns.std() * np.sqrt(252 / 20)

    # 最大回撤
    cumulative = (1 + portfolio_returns).cumprod()
    running_max = np.maximum.accumulate(cumulative)
    drawdown = (cumulative - running_max) / running_max
    metrics['max_drawdown'] = drawdown.min()

    # 年化收益
    n_years = len(portfolio_returns) * 20 / 252
    if n_years > 0:
        metrics['annualized_return'] = (1 + metrics['total_return']) ** (1 / n_years) - 1

    # 打印结果
    print(f"\n📊 回测结果:")
    print(f"{'='*70}")
    print(f"  交易次数:     {metrics['n_trades']}")
    print(f"  胜率:         {metrics['win_rate']:.2%}")
    print(f"  平均收益:     {metrics['mean_return']:.2%} (每20天)")
    print(f"  基准收益:     {metrics.get('benchmark_return', 0):.2%}")
    print(f"  超额收益:     {metrics['excess_return']:.2%}")
    print(f"  总收益:       {metrics['total_return']:.2%}")
    print(f"  年化收益:     {metrics.get('annualized_return', 0):.2%}")
    print(f"  夏普比率:     {metrics['sharpe_ratio']:.2f}")
    print(f"  最大回撤:     {metrics['max_drawdown']:.2%}")
    print(f"  t统计量:      {metrics['t_stat']:.2f}")
    print(f"  p值:          {metrics['p_value']:.4f}", end="")

    # 显著性判断
    if metrics['p_value'] < 0.01:
        print(" ✅✅ 高度显著")
    elif metrics['p_value'] < 0.05:
        print(" ✅ 显著")
    elif metrics['p_value'] < 0.10:
        print(" ⚠️ 边缘显著")
    else:
        print(" ❌ 不显著")

    # 最近5次选股
    print(f"\n最近5次选股示例:")
    for date, stocks, scores in selected_stocks_history[-5:]:
        print(f"  {date.date()}: {stocks[:2]}... (分数: {scores[0]:.1f}, {scores[1]:.1f})")

    return metrics


def main():
    """主测试函数"""
    print("=" * 70)
    print("反转策略回测对比")
    print("=" * 70)

    # 加载数据
    data_dir = 'data_for_opt_stocks'
    prices_file = os.path.join(data_dir, 'prices.csv')
    benchmark_file = os.path.join(data_dir, 'benchmark.csv')

    if not os.path.exists(prices_file):
        print(f"❌ 数据文件不存在: {prices_file}")
        print("\n请确保已经运行了数据准备脚本")
        return

    prices = pd.read_csv(prices_file, index_col=0, parse_dates=True)
    prices = prices.apply(pd.to_numeric, errors='coerce')

    benchmark = pd.read_csv(benchmark_file, index_col=0, parse_dates=True)
    if isinstance(benchmark, pd.DataFrame):
        benchmark = benchmark.iloc[:, 0]
    benchmark = pd.to_numeric(benchmark, errors='coerce')

    print(f"\n数据加载:")
    print(f"  价格数据: {prices.shape}")
    print(f"  时间范围: {prices.index[0].date()} ~ {prices.index[-1].date()}")
    print(f"  总交易日: {len(prices)}")

    # 定义策略
    strategies = {
        '原策略（混合）': {1: 30, 3: -70, 20: 150},
        '方案1（IC top3）': {20: -34, 19: -33, 18: -33},
        '方案2（纯20日）': {20: -100},
        '方案3（长期反转）': {15: -29, 18: -35, 20: -36}
    }

    results = {}

    # 回测各策略
    for name, params in strategies.items():
        metrics = backtest_strategy(params, prices, benchmark, name)
        if metrics:
            results[name] = metrics

    # 对比分析
    if len(results) >= 2:
        print("\n" + "=" * 70)
        print("📊 策略对比汇总")
        print("=" * 70)

        # 打印对比表格
        print(f"\n{'策略':<20} {'胜率':>8} {'超额收益':>10} {'年化':>8} {'夏普':>6} {'P值':>8}")
        print("-" * 70)
        for name, metrics in results.items():
            print(f"{name:<20} {metrics['win_rate']:>7.2%} {metrics['excess_return']:>9.2%} "
                  f"{metrics.get('annualized_return', 0):>7.2%} {metrics['sharpe_ratio']:>6.2f} "
                  f"{metrics['p_value']:>8.4f}")

        # 找出最佳策略
        print("\n" + "=" * 70)
        print("🏆 最佳策略排名")
        print("=" * 70)

        sorted_by_excess = sorted(results.items(), key=lambda x: x[1]['excess_return'], reverse=True)
        for i, (name, metrics) in enumerate(sorted_by_excess[:3], 1):
            star = "⭐" * (4 - i)
            print(f"{i}. {name:<20} 超额收益: {metrics['excess_return']:>7.2%}  "
                  f"胜率: {metrics['win_rate']:>6.2%}  P值: {metrics['p_value']:.4f} {star}")

        # 详细对比原策略vs最佳新策略
        old = results.get('原策略（混合）') or results.get('原策略（追涨）')
        best_new_name = [n for n, _ in sorted_by_excess if '原策略' not in n][0]
        new = results[best_new_name]

        print("\n" + "=" * 70)
        print(f"📊 详细对比: 原策略 vs {best_new_name}")
        print("=" * 70)

        print(f"\n{'指标':<15} {'原策略':>12} {'最佳新策略':>12} {'改进':>12}")
        print("-" * 70)

        comparisons = [
            ('胜率', 'win_rate', '%'),
            ('平均收益/20天', 'mean_return', '%'),
            ('超额收益', 'excess_return', '%'),
            ('年化收益', 'annualized_return', '%'),
            ('夏普比率', 'sharpe_ratio', ''),
            ('最大回撤', 'max_drawdown', '%'),
            ('P值', 'p_value', '')
        ]

        for label, key, fmt in comparisons:
            old_val = old.get(key, 0)
            new_val = new.get(key, 0)

            if fmt == '%':
                old_str = f"{old_val:>10.2%}"
                new_str = f"{new_val:>10.2%}"
                diff = new_val - old_val
                diff_str = f"{diff:>+10.2%}"
            else:
                old_str = f"{old_val:>10.2f}"
                new_str = f"{new_val:>10.2f}"
                diff = new_val - old_val
                diff_str = f"{diff:>+10.2f}"

            # 判断好坏
            if key in ['win_rate', 'mean_return', 'excess_return', 'annualized_return', 'sharpe_ratio']:
                emoji = "📈" if diff > 0 else "📉"
            elif key in ['max_drawdown', 'p_value']:
                emoji = "📈" if diff < 0 else "📉"
            else:
                emoji = ""

            print(f"{label:<15} {old_str} {new_str} {diff_str} {emoji}")

        # 结论
        print("\n" + "=" * 70)
        print("🎯 结论")
        print("=" * 70)

        # 判断是否值得采用
        improvements = []
        concerns = []

        if new['win_rate'] > old['win_rate'] + 0.03:
            improvements.append(f"胜率提升 {(new['win_rate'] - old['win_rate']):.2%}")
        elif new['win_rate'] < old['win_rate'] - 0.03:
            concerns.append(f"胜率下降 {(new['win_rate'] - old['win_rate']):.2%}")

        if new['excess_return'] > old['excess_return'] + 0.01:
            improvements.append(f"超额收益提升 {(new['excess_return'] - old['excess_return']):.2%}")
        elif new['excess_return'] < old['excess_return'] - 0.01:
            concerns.append(f"超额收益下降 {(new['excess_return'] - old['excess_return']):.2%}")

        if new['p_value'] < 0.05 and old['p_value'] >= 0.05:
            improvements.append("达到统计显著性")

        if improvements:
            print(f"\n✅ 新策略优势:")
            for imp in improvements:
                print(f"  • {imp}")

        if concerns:
            print(f"\n⚠️ 新策略劣势:")
            for con in concerns:
                print(f"  • {con}")

        # 最终建议
        print(f"\n📋 最终建议:")

        if new['excess_return'] > old['excess_return'] + 0.02 and new['win_rate'] > 0.50:
            print(f"  ✅ {best_new_name} 表现优于原策略！")
            print(f"\n  参数: {strategies[best_new_name]}")
            print(f"\n  下一步:")
            print(f"    1. 更新 core/signal.py 第65行使用该参数")
            print(f"    2. 小资金实盘测试（5-10万元）")
            print(f"    3. 观察期：2周（至少5个交易日）")
        elif new['excess_return'] > old['excess_return']:
            print(f"  ⚠️ {best_new_name} 略有改进，但不够显著")
            print(f"\n  建议:")
            print(f"    1. 扩展数据到3-5年重新验证")
            print(f"    2. 或谨慎小仓位测试")
        else:
            print(f"  ❌ 所有反转策略表现都不如原策略")
            print(f"\n  建议:")
            print(f"    1. 保持原策略 {strategies.get('原策略（混合）') or strategies.get('原策略（追涨）')}")
            print(f"    2. IC分析虽显示反转效应，但实际效果不佳")
            print(f"    3. 可能原因：IC太弱(-0.028)、数据周期短、原策略混合逻辑更优")


if __name__ == '__main__':
    main()
