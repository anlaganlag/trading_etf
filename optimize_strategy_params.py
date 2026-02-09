"""
为用户优化多周期权重打分选股模型

需求：
1. 基准：创业板指
2. 换仓周期：5-10天（倾向这个范围，最长20天）
3. 目标：跑赢创业板指
4. 约束：实盘可买入（涨停板占比<20%）

优化方案：
- 参数空间：周期1-20天的权重
- 优化目标：最大化（超额收益 / 最大回撤）即Calmar比率
- 约束条件：涨停板占比<20%
"""
import os
import pandas as pd
import numpy as np
from config import config
from scipy.optimize import differential_evolution
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = os.path.join(config.BASE_DIR, "data_for_opt_stocks")
PRICES_FILE = os.path.join(DATA_DIR, "prices.csv")

# 完整时间段
START_DATE = '2021-01-04'
END_DATE = '2026-02-06'

# 候选周期（1-20天）
CANDIDATE_PERIODS = [1, 2, 3, 5, 7, 10, 14, 20]

def backtest_strategy(stocks, weights, hold_days, top_n, start_date=None, end_date=None):
    """标准回测函数"""
    if start_date:
        stocks = stocks.loc[start_date:end_date]

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

    # 统计涨停板占比
    daily_ret = stocks.pct_change()
    selected_returns = []
    for date in top_n_mask.index[1:]:
        selected = top_n_mask.loc[date]
        ret_today = daily_ret.loc[date]
        for stock in selected[selected].index:
            ret = ret_today[stock]
            if pd.notna(ret):
                selected_returns.append(ret)

    limit_up_pct = (pd.Series(selected_returns) > 0.095).mean() if selected_returns else 0

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

    return {
        'total_return': total_ret,
        'annual_return': ann_ret,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'calmar': calmar,
        'limit_up_pct': limit_up_pct,
        'daily_ret': port_daily,
    }

def optimize_for_hold_days(stocks, hold_days, benchmark_ret):
    """针对特定换仓周期优化参数"""

    print(f"\n{'='*80}")
    print(f"优化换仓周期: {hold_days}天")
    print(f"{'='*80}")

    # 优化目标函数
    def objective(params):
        """
        优化目标：最大化Calmar比率（年化收益/最大回撤）
        约束：涨停板占比<20%
        """
        weights = {CANDIDATE_PERIODS[i]: params[i] for i in range(len(CANDIDATE_PERIODS))}

        # 过滤掉权重接近0的周期
        weights = {k: v for k, v in weights.items() if abs(v) > 0.01}

        if not weights:
            return -999

        try:
            result = backtest_strategy(stocks, weights, hold_days, top_n=4,
                                      start_date=START_DATE, end_date=END_DATE)

            # 惩罚涨停板占比过高的策略
            if result['limit_up_pct'] > 0.2:
                penalty = (result['limit_up_pct'] - 0.2) * 10
                return -(result['calmar'] - penalty)

            # 目标：最大化Calmar
            return -result['calmar']

        except:
            return -999

    # 参数边界：每个周期的权重在[-2, 2]之间
    bounds = [(-2, 2) for _ in CANDIDATE_PERIODS]

    print(f"\n开始优化（使用差异演化算法）...")
    print(f"参数空间: {len(CANDIDATE_PERIODS)}个周期，每个权重范围[-2, 2]")

    # 使用差异演化算法优化
    result = differential_evolution(
        objective,
        bounds,
        maxiter=50,  # 减少迭代次数以加快速度
        popsize=10,
        seed=42,
        disp=True,
        workers=1
    )

    optimal_params = result.x
    optimal_weights = {CANDIDATE_PERIODS[i]: optimal_params[i]
                      for i in range(len(CANDIDATE_PERIODS)) if abs(optimal_params[i]) > 0.01}

    # 回测最优参数
    optimal_result = backtest_strategy(stocks, optimal_weights, hold_days, top_n=4,
                                       start_date=START_DATE, end_date=END_DATE)

    # 计算vs基准的超额收益
    excess_ret = optimal_result['annual_return'] - benchmark_ret

    print(f"\n✅ 优化完成！")
    print(f"\n最优权重:")
    for period, weight in sorted(optimal_weights.items()):
        print(f"  Day {period:>2}: {weight:>7.3f}")

    print(f"\n回测结果:")
    print(f"  累计收益:     {optimal_result['total_return']:>7.2%}")
    print(f"  年化收益:     {optimal_result['annual_return']:>7.2%}")
    print(f"  夏普比率:     {optimal_result['sharpe']:>7.2f}")
    print(f"  最大回撤:     {optimal_result['max_dd']:>7.2%}")
    print(f"  Calmar比率:   {optimal_result['calmar']:>7.2f}")
    print(f"  涨停板占比:   {optimal_result['limit_up_pct']:>7.2%}")

    print(f"\n相对基准（创业板指）:")
    print(f"  基准年化:     {benchmark_ret:>7.2%}")
    print(f"  超额收益:     {excess_ret:>7.2%}")

    return {
        'hold_days': hold_days,
        'weights': optimal_weights,
        'result': optimal_result,
        'excess_return': excess_ret,
    }

def main():
    print("="*80)
    print("多周期权重打分选股模型 - 参数优化")
    print("="*80)

    # 加载数据
    stocks = pd.read_csv(PRICES_FILE, index_col=0, parse_dates=True)
    stocks = stocks.loc[START_DATE:END_DATE]

    print(f"\n数据范围: {stocks.index[0].date()} ~ {stocks.index[-1].date()}")
    print(f"股票数量: {len(stocks.columns)}")
    print(f"交易日数: {len(stocks)}")

    # 获取创业板指收益
    try:
        from gm.api import set_token, history, ADJUST_PREV
        set_token(config.GM_TOKEN)
        print(f"\n获取创业板指数据...")
        bench_df = history(symbol='SZSE.399006', frequency='1d',
                          start_time=START_DATE, end_time=END_DATE,
                          fields='close,eob', df=True)
        bench_df['eob'] = pd.to_datetime(bench_df['eob']).dt.tz_localize(None)
        bench = bench_df.set_index('eob')['close']
        bench_total_ret = (bench.iloc[-1] / bench.iloc[0] - 1)
        n_days = len(bench)
        bench_ann_ret = (1 + bench_total_ret) ** (252 / n_days) - 1

        print(f"创业板指表现:")
        print(f"  累计收益: {bench_total_ret:.2%}")
        print(f"  年化收益: {bench_ann_ret:.2%}")
    except:
        print(f"\n⚠️ 无法获取创业板指数据，使用估计值")
        bench_ann_ret = 0.015  # 估计年化1.5%

    # 针对不同换仓周期优化
    print(f"\n{'='*80}")
    print(f"开始针对不同换仓周期进行优化")
    print(f"{'='*80}")

    hold_days_list = [5, 7, 10]  # 用户倾向的范围
    all_results = []

    for hold_days in hold_days_list:
        result = optimize_for_hold_days(stocks, hold_days, bench_ann_ret)
        all_results.append(result)

    # 对比结果
    print(f"\n{'='*80}")
    print(f"📊 不同换仓周期的最优策略对比")
    print(f"{'='*80}")

    print(f"\n{'换仓周期':<12} {'年化收益':>10} {'夏普':>8} {'最大回撤':>10} "
          f"{'Calmar':>8} {'涨停占比':>10} {'超额收益':>10}")
    print(f"-"*80)

    for r in all_results:
        print(f"{r['hold_days']:>2}天        "
              f"{r['result']['annual_return']:>9.2%} "
              f"{r['result']['sharpe']:>7.2f} "
              f"{r['result']['max_dd']:>9.2%} "
              f"{r['result']['calmar']:>7.2f} "
              f"{r['result']['limit_up_pct']:>9.2%} "
              f"{r['excess_return']:>9.2%}")

    # 推荐最优方案
    print(f"\n{'='*80}")
    print(f"🏆 推荐方案")
    print(f"{'='*80}")

    # 按超额收益排序
    all_results.sort(key=lambda x: x['excess_return'], reverse=True)
    best = all_results[0]

    print(f"\n最佳换仓周期: {best['hold_days']}天")
    print(f"\n最优权重配置:")
    for period, weight in sorted(best['weights'].items()):
        attr = "动量" if weight > 0 else "反转"
        print(f"  Day {period:>2}: {weight:>7.3f}  ({attr})")

    print(f"\n预期表现:")
    print(f"  年化收益:     {best['result']['annual_return']:>7.2%}")
    print(f"  超越基准:     {best['excess_return']:>7.2%}")
    print(f"  夏普比率:     {best['result']['sharpe']:>7.2f}")
    print(f"  最大回撤:     {best['result']['max_dd']:>7.2%}")
    print(f"  Calmar比率:   {best['result']['calmar']:>7.2f}")
    print(f"  涨停板占比:   {best['result']['limit_up_pct']:>7.2%}")

    print(f"\n✅ 实盘可行性评估:")
    if best['result']['limit_up_pct'] < 0.1:
        print(f"  优秀 - 涨停板占比<10%，散户可轻松操作")
    elif best['result']['limit_up_pct'] < 0.2:
        print(f"  良好 - 涨停板占比<20%，大部分情况可成交")
    else:
        print(f"  一般 - 涨停板占比较高，需要一定打板能力")

    # 保存结果
    print(f"\n💾 保存最优参数到配置文件...")
    output = {
        'hold_days': best['hold_days'],
        'weights': best['weights'],
        'expected_annual_return': best['result']['annual_return'],
        'expected_sharpe': best['result']['sharpe'],
        'expected_max_dd': best['result']['max_dd'],
        'limit_up_pct': best['result']['limit_up_pct'],
    }

    import json
    with open('optimal_strategy_config.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"✅ 已保存到 optimal_strategy_config.json")

    print(f"\n{'='*80}")
    print(f"🎯 优化完成！")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
