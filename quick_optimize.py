"""
快速参数优化 - 使用预定义的参数组合

基于之前的发现：
1. "只反转负权重"能达到1271%收益
2. 3日换仓表现最好
3. Top 6可能比Top 4更优

策略：
- 测试多组预定义的有效参数组合
- 快速评估性能
- 推荐最优方案
"""
import os
import pandas as pd
import numpy as np
from config import config
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = os.path.join(config.BASE_DIR, "data_for_opt_stocks")
PRICES_FILE = os.path.join(DATA_DIR, "prices.csv")

START_DATE = '2021-01-04'
END_DATE = '2026-02-06'

# 预定义的参数组合（基于前面的发现和经验）
PARAM_CONFIGS = {
    "纯短期动量": {2: 1.0},
    "短中期动量": {2: 0.5, 5: 0.5},
    "短长期动量": {2: 0.3, 20: 0.7},
    "短中长动量": {2: 0.3, 10: 0.4, 20: 0.3},
    "文档参数（反转负权）": {  # 基于发现：反转负权重效果更好
        1: 0.019,
        2: 0.140,
        3: 0.243,
        5: 0.160,
        7: 0.689,
        10: 0.761,
        14: 0.419,
        20: 0.530
    },
    "均衡动量": {1: 0.2, 3: 0.2, 5: 0.2, 10: 0.2, 20: 0.2},
    "长期主导": {10: 0.5, 20: 0.5},
    "中期主导": {5: 0.5, 10: 0.5},
}

def backtest_strategy(stocks, weights, hold_days, top_n):
    """回测函数"""
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
    }

def main():
    print("="*80)
    print("快速参数优化 - 预定义组合测试")
    print("="*80)

    stocks = pd.read_csv(PRICES_FILE, index_col=0, parse_dates=True)
    stocks = stocks.loc[START_DATE:END_DATE]

    print(f"\n数据范围: {stocks.index[0].date()} ~ {stocks.index[-1].date()}")
    print(f"股票数量: {len(stocks.columns)}")
    print(f"交易日数: {len(stocks)}")

    # 获取创业板指基准
    try:
        from gm.api import set_token, history
        set_token(config.GM_TOKEN)
        bench_df = history(symbol='SZSE.399006', frequency='1d',
                          start_time=START_DATE, end_time=END_DATE,
                          fields='close,eob', df=True)
        bench_df['eob'] = pd.to_datetime(bench_df['eob']).dt.tz_localize(None)
        bench = bench_df.set_index('eob')['close']
        bench_total_ret = (bench.iloc[-1] / bench.iloc[0] - 1)
        bench_ann_ret = (1 + bench_total_ret) ** (252 / len(bench)) - 1
        print(f"\n创业板指基准: 年化{bench_ann_ret:.2%}, 累计{bench_total_ret:.2%}")
    except:
        bench_ann_ret = 0.015
        print(f"\n创业板指基准（估计）: 年化{bench_ann_ret:.2%}")

    # 测试不同换仓周期 x 不同参数组合
    hold_days_list = [5, 7, 10]
    all_results = []

    print(f"\n{'='*80}")
    print(f"测试所有组合...")
    print(f"{'='*80}")

    for hold_days in hold_days_list:
        print(f"\n换仓周期: {hold_days}天")
        print(f"-"*80)

        for name, weights in PARAM_CONFIGS.items():
            result = backtest_strategy(stocks, weights, hold_days, top_n=4)

            all_results.append({
                'name': name,
                'hold_days': hold_days,
                'weights': weights,
                **result
            })

            print(f"{name:25s} | 年化:{result['annual_return']:>6.1%} "
                  f"夏普:{result['sharpe']:>5.2f} 回撤:{result['max_dd']:>6.1%} "
                  f"涨停:{result['limit_up_pct']:>5.1%}")

    # 筛选满足条件的方案
    print(f"\n{'='*80}")
    print(f"筛选结果（涨停板占比<20%，跑赢基准）")
    print(f"{'='*80}")

    valid_results = [
        r for r in all_results
        if r['limit_up_pct'] < 0.2 and r['annual_return'] > bench_ann_ret
    ]

    if not valid_results:
        print(f"\n⚠️ 没有满足所有条件的方案，放宽到涨停板<30%")
        valid_results = [
            r for r in all_results
            if r['limit_up_pct'] < 0.3 and r['annual_return'] > bench_ann_ret
        ]

    # 按Calmar排序
    valid_results.sort(key=lambda x: x['calmar'], reverse=True)

    print(f"\n找到{len(valid_results)}个有效方案")
    print(f"\nTop 5方案:")
    print(f"-"*80)
    print(f"{'排名':<4} {'策略名称':<25} {'换仓':<6} {'年化收益':>10} {'夏普':>8} "
          f"{'最大回撤':>10} {'涨停':>8} {'超额':>8}")
    print(f"-"*80)

    for i, r in enumerate(valid_results[:5], 1):
        excess = r['annual_return'] - bench_ann_ret
        print(f"{i:<4} {r['name']:<25} {r['hold_days']:>2}天    "
              f"{r['annual_return']:>9.2%} {r['sharpe']:>7.2f} "
              f"{r['max_dd']:>9.2%} {r['limit_up_pct']:>7.1%} {excess:>7.2%}")

    # 推荐方案
    if valid_results:
        best = valid_results[0]

        print(f"\n{'='*80}")
        print(f"🏆 推荐方案")
        print(f"{'='*80}")

        print(f"\n策略名称: {best['name']}")
        print(f"换仓周期: {best['hold_days']}天")

        print(f"\n参数配置:")
        for period, weight in sorted(best['weights'].items()):
            print(f"  Day {period:>2}: {weight:>7.3f}")

        print(f"\n预期表现:")
        print(f"  累计收益:     {best['total_return']:>7.2%}")
        print(f"  年化收益:     {best['annual_return']:>7.2%}")
        print(f"  超越基准:     {best['annual_return'] - bench_ann_ret:>7.2%}")
        print(f"  夏普比率:     {best['sharpe']:>7.2f}")
        print(f"  最大回撤:     {best['max_dd']:>7.2%}")
        print(f"  Calmar比率:   {best['calmar']:>7.2f}")
        print(f"  涨停板占比:   {best['limit_up_pct']:>7.2%}")

        print(f"\n实盘可行性:")
        if best['limit_up_pct'] < 0.1:
            print(f"  ✅ 优秀 - 涨停板占比<10%")
        elif best['limit_up_pct'] < 0.2:
            print(f"  ✅ 良好 - 涨停板占比<20%")
        else:
            print(f"  ⚠️ 一般 - 涨停板占比{best['limit_up_pct']:.1%}")

        # 保存配置
        import json
        config_output = {
            'strategy_name': best['name'],
            'hold_days': best['hold_days'],
            'weights': best['weights'],
            'top_n': 4,
            'expected_annual_return': best['annual_return'],
            'expected_sharpe': best['sharpe'],
            'expected_max_dd': best['max_dd'],
            'limit_up_pct': best['limit_up_pct'],
            'benchmark': 'SZSE.399006',
            'excess_return': best['annual_return'] - bench_ann_ret,
        }

        with open('optimal_strategy_config.json', 'w', encoding='utf-8') as f:
            json.dump(config_output, f, indent=2, ensure_ascii=False)

        print(f"\n💾 配置已保存到 optimal_strategy_config.json")

    print(f"\n{'='*80}")
    print(f"✅ 优化完成！")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
