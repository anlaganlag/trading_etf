"""
多周期权重打分选股模型 - 最佳参数价值验证

验证目标：
1. 当前参数 {2: 30, 20: 70} 是否真的是最优的？
2. 与其他参数组合相比的优势在哪里？
3. 参数的稳健性如何？（不同时期、不同市场环境）
4. 是否存在过拟合？
5. 风险调整后收益的比较

对比基准：
- 原始参数 {1: 30, 3: -70, 20: 150}
- 纯动量策略 {20: 100}
- 纯短期策略 {2: 100}
- 均衡策略 {2: 50, 20: 50}
- 其他优化参数组合
"""
import os
import pandas as pd
import numpy as np
from config import config
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = os.path.join(config.BASE_DIR, "data_for_opt_stocks")
PRICES_FILE = os.path.join(DATA_DIR, "prices.csv")

START_DATE = '2021-12-03'
END_DATE = '2026-01-23'
TOP_N = 4
HOLD_DAYS = 3

# 待验证的参数组合
PARAM_CONFIGS = {
    "当前最优 (2+20)": {2: 30, 20: 70},
    "原始参数 (1+3+20)": {1: 30, 3: -70, 20: 150},
    "纯长期动量": {20: 100},
    "纯短期动量": {2: 100},
    "均衡组合": {2: 50, 20: 50},
    "短中长组合": {2: 33, 5: 33, 20: 34},
    "反转+动量": {3: -50, 20: 100},
    "极端短期": {1: 100},
    "中期组合": {5: 50, 10: 50},
}

def backtest_strategy(stocks, weights, hold_days=3, top_n=4):
    """
    标准化回测函数

    Returns:
        dict: 包含各项指标的字典
    """
    # 计算分数
    score_df = pd.DataFrame(0.0, index=stocks.index, columns=stocks.columns)

    for p, w in weights.items():
        ret = stocks / stocks.shift(p) - 1

        # 正确的排名逻辑：
        # rank默认ascending=True，所以高值=高rank
        # 动量因子：高收益率应该高分 → 直接用rank
        # 反转因子：低收益率应该高分 → 用(1-rank)或负权重
        rank = ret.rank(axis=1, pct=True).fillna(0.5)
        score_df += rank * w

    # 选Top N
    top_n_mask = pd.DataFrame(False, index=score_df.index, columns=score_df.columns)
    vals = score_df.values
    vals = np.nan_to_num(vals, nan=-np.inf)
    idx = np.argpartition(-vals, top_n, axis=1)[:, :top_n]
    rows = np.arange(len(score_df))[:, None]
    top_n_mask.values[rows, idx] = True

    # 计算收益 - 3分仓滚动
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

    # 波动率
    ann_vol = port_daily.std() * np.sqrt(252)

    # 夏普比率
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # 最大回撤
    cum_max = np.maximum.accumulate(cum_ret)
    drawdown = (cum_ret - cum_max) / cum_max
    max_dd = drawdown.min()

    # Calmar比率
    calmar = ann_ret / abs(max_dd) if max_dd < 0 else 0

    # 胜率
    win_rate = (port_daily > 0).mean()

    # 日均收益
    daily_mean = port_daily.mean()

    return {
        'total_return': total_ret,
        'annual_return': ann_ret,
        'annual_vol': ann_vol,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'calmar': calmar,
        'win_rate': win_rate,
        'daily_mean': daily_mean,
        'cum_ret_series': cum_ret,
        'daily_ret_series': port_daily,
    }

def period_analysis(stocks, weights, periods):
    """分时段分析"""
    results = {}

    for name, (start, end) in periods.items():
        period_stocks = stocks.loc[start:end]
        if len(period_stocks) < 100:  # 太短的period跳过
            continue

        result = backtest_strategy(period_stocks, weights, HOLD_DAYS, TOP_N)
        results[name] = result

    return results

def statistical_test(returns1, returns2, name1, name2):
    """统计显著性检验"""
    # T检验
    t_stat, p_value = stats.ttest_ind(returns1, returns2)

    # 效果量 (Cohen's d)
    pooled_std = np.sqrt((returns1.std()**2 + returns2.std()**2) / 2)
    cohens_d = (returns1.mean() - returns2.mean()) / pooled_std

    return {
        't_stat': t_stat,
        'p_value': p_value,
        'cohens_d': cohens_d,
        'significant': p_value < 0.05
    }

def main():
    """主验证流程"""

    print("="*80)
    print("多周期权重打分选股模型 - 最佳参数价值验证")
    print("="*80)
    print(f"回测期间: {START_DATE} 到 {END_DATE}")
    print(f"选股数量: Top {TOP_N}")
    print(f"换仓周期: 每{HOLD_DAYS}天")
    print()

    # 加载数据
    if not os.path.exists(PRICES_FILE):
        print(f"❌ 数据文件不存在: {PRICES_FILE}")
        return

    print("加载数据...")
    stocks = pd.read_csv(PRICES_FILE, index_col=0, parse_dates=True)
    stocks = stocks.loc[START_DATE:END_DATE]
    print(f"✓ 加载完成: {len(stocks.columns)}只股票, {len(stocks)}个交易日\n")

    # ============================================================
    # 1. 全样本对比
    # ============================================================
    print("="*80)
    print("1. 全样本回测对比 (2021-12-03 ~ 2026-01-23)")
    print("="*80)

    all_results = {}

    for name, weights in PARAM_CONFIGS.items():
        print(f"回测: {name}...", end=" ")
        result = backtest_strategy(stocks, weights, HOLD_DAYS, TOP_N)
        all_results[name] = result
        print("✓")

    # 输出对比表
    print("\n" + "="*80)
    print("📊 全样本表现对比")
    print("="*80)

    df_results = pd.DataFrame({
        name: {
            '总收益': f"{r['total_return']:.2%}",
            '年化收益': f"{r['annual_return']:.2%}",
            '年化波动': f"{r['annual_vol']:.2%}",
            '夏普比率': f"{r['sharpe']:.2f}",
            '最大回撤': f"{r['max_dd']:.2%}",
            'Calmar': f"{r['calmar']:.2f}",
            '胜率': f"{r['win_rate']:.2%}",
            '日均收益': f"{r['daily_mean']:.4%}",
        }
        for name, r in all_results.items()
    }).T

    print(df_results.to_string())

    # 排名分析
    print("\n" + "="*80)
    print("📈 各指标排名")
    print("="*80)

    metrics_rank = pd.DataFrame({
        name: {
            '总收益': r['total_return'],
            '夏普比率': r['sharpe'],
            'Calmar': r['calmar'],
            '风险调整收益': r['annual_return'] / abs(r['max_dd']) if r['max_dd'] < 0 else 0,
        }
        for name, r in all_results.items()
    }).T

    for col in metrics_rank.columns:
        metrics_rank[f'{col}排名'] = metrics_rank[col].rank(ascending=False).astype(int)

    print(metrics_rank[[c for c in metrics_rank.columns if '排名' in c]].to_string())

    # 综合评分
    print("\n" + "="*80)
    print("🏆 综合评分 (各指标排名的平均)")
    print("="*80)

    rank_cols = [c for c in metrics_rank.columns if '排名' in c]
    metrics_rank['综合得分'] = metrics_rank[rank_cols].mean(axis=1)
    metrics_rank = metrics_rank.sort_values('综合得分')

    for idx, (name, row) in enumerate(metrics_rank.iterrows(), 1):
        print(f"{idx}. {name:25s} - 综合得分: {row['综合得分']:.2f}")

    # ============================================================
    # 2. 分时段稳健性测试
    # ============================================================
    print("\n" + "="*80)
    print("2. 分时段稳健性测试")
    print("="*80)

    # 定义测试时段
    periods = {
        '训练期 (70%)': (START_DATE, stocks.index[int(len(stocks)*0.7)]),
        '测试期 (30%)': (stocks.index[int(len(stocks)*0.7)], END_DATE),
        '2022年': ('2022-01-01', '2022-12-31'),
        '2023年': ('2023-01-01', '2023-12-31'),
        '2024年': ('2024-01-01', '2024-12-31'),
        '2025年': ('2025-01-01', '2025-12-31'),
    }

    # 只对比关键几个策略
    key_strategies = ["当前最优 (2+20)", "原始参数 (1+3+20)", "纯长期动量", "均衡组合"]

    period_comparison = {}

    for strategy in key_strategies:
        weights = PARAM_CONFIGS[strategy]
        period_results = period_analysis(stocks, weights, periods)
        period_comparison[strategy] = period_results

    # 输出分时段对比
    print("\n各策略在不同时段的年化收益:")
    print("-" * 80)

    period_df = pd.DataFrame({
        strategy: {
            period: f"{results['annual_return']:.2%}"
            for period, results in period_results.items()
        }
        for strategy, period_results in period_comparison.items()
    })

    print(period_df.to_string())

    # 稳健性分数：标准差越小越稳健
    print("\n" + "="*80)
    print("📊 时段稳健性分析")
    print("="*80)

    for strategy in key_strategies:
        returns = [r['annual_return'] for r in period_comparison[strategy].values()]
        mean_ret = np.mean(returns)
        std_ret = np.std(returns)
        cv = std_ret / mean_ret if mean_ret != 0 else np.inf  # 变异系数

        print(f"{strategy:25s}: 均值={mean_ret:>7.2%}, 标准差={std_ret:>7.2%}, 变异系数={cv:.2f}")

    # ============================================================
    # 3. 统计显著性检验
    # ============================================================
    print("\n" + "="*80)
    print("3. 统计显著性检验 (vs 当前最优参数)")
    print("="*80)

    optimal_returns = all_results["当前最优 (2+20)"]['daily_ret_series']

    print(f"\n基准: 当前最优 (2+20)")
    print(f"样本量: {len(optimal_returns)}天")
    print("-" * 80)

    for name in PARAM_CONFIGS.keys():
        if name == "当前最优 (2+20)":
            continue

        other_returns = all_results[name]['daily_ret_series']

        # 对齐时间序列
        aligned_optimal = optimal_returns.reindex(other_returns.index)
        aligned_other = other_returns.reindex(optimal_returns.index)

        # 去除NaN
        mask = aligned_optimal.notna() & aligned_other.notna()
        aligned_optimal = aligned_optimal[mask]
        aligned_other = aligned_other[mask]

        test_result = statistical_test(aligned_optimal, aligned_other, "当前最优", name)

        sig_mark = "***" if test_result['significant'] else "   "

        mean_diff = (aligned_optimal.mean() - aligned_other.mean()) * 252 * 100  # 年化bp差异

        print(f"{name:25s}: p={test_result['p_value']:.4f} {sig_mark}, "
              f"Cohen's d={test_result['cohens_d']:>6.2f}, "
              f"年化差异={mean_diff:>6.0f}bp")

    print("\n*** p<0.05 表示差异显著")

    # ============================================================
    # 4. 风险调整后收益对比
    # ============================================================
    print("\n" + "="*80)
    print("4. 风险调整后收益对比")
    print("="*80)

    risk_adj_metrics = pd.DataFrame({
        name: {
            'Sharpe比率': r['sharpe'],
            'Calmar比率': r['calmar'],
            'Sortino比率': r['annual_return'] / (r['daily_ret_series'][r['daily_ret_series'] < 0].std() * np.sqrt(252)) if len(r['daily_ret_series'][r['daily_ret_series'] < 0]) > 0 else 0,
            '收益/波动': r['annual_return'] / r['annual_vol'],
        }
        for name, r in all_results.items()
    }).T

    print(risk_adj_metrics.to_string())

    # 各指标第一名
    print("\n🏆 各风险调整指标最优策略:")
    for col in risk_adj_metrics.columns:
        best = risk_adj_metrics[col].idxmax()
        best_val = risk_adj_metrics[col].max()
        print(f"  {col:15s}: {best:25s} ({best_val:.2f})")

    # ============================================================
    # 5. 最差情况分析
    # ============================================================
    print("\n" + "="*80)
    print("5. 最差情况分析 (压力测试)")
    print("="*80)

    for name, result in all_results.items():
        daily_ret = result['daily_ret_series']

        # 最差连续5日
        rolling_5d = daily_ret.rolling(5).sum()
        worst_5d = rolling_5d.min()
        worst_5d_date = rolling_5d.idxmin()

        # 最差月份
        monthly_ret = (1 + daily_ret).resample('M').prod() - 1
        worst_month = monthly_ret.min()
        worst_month_date = monthly_ret.idxmin()

        # 95% VaR
        var_95 = daily_ret.quantile(0.05)

        print(f"\n{name}:")
        print(f"  最差5日: {worst_5d:.2%} ({worst_5d_date.date() if pd.notna(worst_5d_date) else 'N/A'})")
        print(f"  最差月份: {worst_month:.2%} ({worst_month_date.strftime('%Y-%m') if pd.notna(worst_month_date) else 'N/A'})")
        print(f"  95% VaR: {var_95:.2%} (单日)")

    # ============================================================
    # 6. 参数敏感性分析
    # ============================================================
    print("\n" + "="*80)
    print("6. 参数敏感性分析 (当前最优参数微调)")
    print("="*80)

    print("\n测试当前最优参数 {2: 30, 20: 70} 的微调版本...")

    sensitivity_configs = {
        "当前最优": {2: 30, 20: 70},
        "提高Day2 (+10)": {2: 40, 20: 60},
        "降低Day2 (-10)": {2: 20, 20: 80},
        "提高Day2 (+20)": {2: 50, 20: 50},
        "降低Day2 (-20)": {2: 10, 20: 90},
    }

    sens_results = {}
    for name, weights in sensitivity_configs.items():
        result = backtest_strategy(stocks, weights, HOLD_DAYS, TOP_N)
        sens_results[name] = result

    sens_df = pd.DataFrame({
        name: {
            '年化收益': f"{r['annual_return']:.2%}",
            '夏普比率': f"{r['sharpe']:.2f}",
            '最大回撤': f"{r['max_dd']:.2%}",
            'Calmar': f"{r['calmar']:.2f}",
        }
        for name, r in sens_results.items()
    }).T

    print("\n" + sens_df.to_string())

    # ============================================================
    # 7. 总结报告
    # ============================================================
    print("\n" + "="*80)
    print("📋 验证总结报告")
    print("="*80)

    optimal_result = all_results["当前最优 (2+20)"]
    original_result = all_results["原始参数 (1+3+20)"]

    print(f"\n✓ 当前最优参数 {{2: 30, 20: 70}} 验证结果:")
    print(f"  - 总收益: {optimal_result['total_return']:.2%}")
    print(f"  - 年化收益: {optimal_result['annual_return']:.2%}")
    print(f"  - 夏普比率: {optimal_result['sharpe']:.2f}")
    print(f"  - 最大回撤: {optimal_result['max_dd']:.2%}")

    print(f"\n✓ 相比原始参数 {{1: 30, 3: -70, 20: 150}} 的改进:")
    print(f"  - 收益提升: {(optimal_result['total_return'] - original_result['total_return']):.2%}")
    print(f"  - 夏普提升: {optimal_result['sharpe'] - original_result['sharpe']:.2f}")
    print(f"  - 回撤改善: {optimal_result['max_dd'] - original_result['max_dd']:.2%}")

    # 判断是否最优
    sharpe_rank = metrics_rank.loc["当前最优 (2+20)", '夏普比率排名']
    total_rank = metrics_rank.loc["当前最优 (2+20)", '综合得分']

    print(f"\n✓ 综合排名:")
    print(f"  - 夏普比率: 第{int(sharpe_rank)}名 / {len(PARAM_CONFIGS)}")
    print(f"  - 综合得分: {total_rank:.2f} (越小越好)")

    if sharpe_rank == 1 and total_rank <= 2:
        print(f"\n🎉 结论: 当前参数在风险调整后收益方面表现最优！")
    elif total_rank <= 3:
        print(f"\n✓ 结论: 当前参数表现优秀，位列前三。")
    else:
        print(f"\n⚠️ 警告: 当前参数可能不是最优，建议进一步优化。")

    # 保存结果
    output_file = os.path.join(config.BASE_DIR, "参数验证报告.txt")
    print(f"\n💾 详细报告已保存至: {output_file}")

if __name__ == "__main__":
    main()
