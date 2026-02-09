"""
测试推荐方案：中等激进策略

配置：
WEIGHTS = {2: 0.3, 5: 0.4, 10: 0.2, 20: 0.1}
HOLD_DAYS = 5
TOP_N = 4

目标：
- 年化收益：50-80%
- 涨停板占比：55-65%
- 战胜创业板指
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

# 推荐方案
RECOMMENDED_WEIGHTS = {2: 0.3, 5: 0.4, 10: 0.2, 20: 0.1}
HOLD_DAYS = 5
TOP_N = 4

def backtest_detailed(stocks, weights, hold_days, top_n):
    """详细回测"""
    # 计算分数
    score_df = pd.DataFrame(0.0, index=stocks.index, columns=stocks.columns)

    print(f"\n计算各周期得分...")
    for p, w in weights.items():
        ret = stocks / stocks.shift(p) - 1
        rank = ret.rank(axis=1, pct=True).fillna(0.5)
        score_df += rank * w
        print(f"  Day {p:>2}: 权重={w:.2f}")

    # 选Top N
    top_n_mask = pd.DataFrame(False, index=score_df.index, columns=score_df.columns)
    vals = score_df.values
    vals = np.nan_to_num(vals, nan=-np.inf)
    idx = np.argpartition(-vals, top_n, axis=1)[:, :top_n]
    rows = np.arange(len(score_df))[:, None]
    top_n_mask.values[rows, idx] = True

    # 分析选中股票特征
    print(f"\n分析选中股票特征...")
    daily_ret = stocks.pct_change()
    selected_returns = []

    for date in top_n_mask.index[1:]:
        selected = top_n_mask.loc[date]
        ret_today = daily_ret.loc[date]
        for stock in selected[selected].index:
            ret = ret_today[stock]
            if pd.notna(ret):
                selected_returns.append(ret)

    selected_returns = pd.Series(selected_returns)

    # 涨幅分布
    limit_up_20 = (selected_returns > 0.195).sum()
    limit_up_10 = (selected_returns > 0.095).sum()
    strong = ((selected_returns > 0.05) & (selected_returns <= 0.095)).sum()
    medium = ((selected_returns > 0.0) & (selected_returns <= 0.05)).sum()
    down = (selected_returns <= 0.0).sum()
    total = len(selected_returns)

    print(f"\n选中股票涨幅分布（{total}次选股）:")
    print(f"  >19.5% (20cm涨停):  {limit_up_20:>6} ({limit_up_20/total:>6.2%})")
    print(f"  9.5%-19.5% (涨停):  {limit_up_10-limit_up_20:>6} ({(limit_up_10-limit_up_20)/total:>6.2%})")
    print(f"  5%-9.5% (强势):     {strong:>6} ({strong/total:>6.2%})")
    print(f"  0%-5% (普涨):       {medium:>6} ({medium/total:>6.2%})")
    print(f"  ≤0% (下跌):         {down:>6} ({down/total:>6.2%})")
    print(f"  涨停板总占比:       {limit_up_10/total:.2%}")

    limit_up_pct = limit_up_10 / total

    # 计算收益
    print(f"\n计算组合收益...")
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
    calmar = ann_ret / abs(max_dd) if max_dd < 0 else 0

    # Sortino
    downside_ret = port_daily[port_daily < 0]
    downside_std = downside_ret.std() * np.sqrt(252)
    sortino = ann_ret / downside_std if downside_std > 0 else 0

    # 胜率
    win_rate = (port_daily > 0).mean()

    # 月度统计
    monthly_ret = (1 + port_daily).resample('M').prod() - 1
    win_months = (monthly_ret > 0).sum()
    total_months = len(monthly_ret)

    return {
        'total_return': total_ret,
        'annual_return': ann_ret,
        'annual_vol': ann_vol,
        'sharpe': sharpe,
        'sortino': sortino,
        'max_dd': max_dd,
        'calmar': calmar,
        'win_rate': win_rate,
        'limit_up_pct': limit_up_pct,
        'cum_ret': cum_ret,
        'daily_ret': port_daily,
        'monthly_ret': monthly_ret,
        'win_months': win_months,
        'total_months': total_months,
        'selected_returns_dist': {
            'mean': selected_returns.mean(),
            'median': selected_returns.median(),
            'std': selected_returns.std(),
        }
    }

def main():
    print("="*80)
    print("测试推荐方案：中等激进策略")
    print("="*80)

    print(f"\n策略配置:")
    print(f"  权重: {RECOMMENDED_WEIGHTS}")
    print(f"  换仓周期: {HOLD_DAYS}天")
    print(f"  选股数量: Top {TOP_N}")

    # 加载数据
    stocks = pd.read_csv(PRICES_FILE, index_col=0, parse_dates=True)
    stocks = stocks.loc[START_DATE:END_DATE]

    print(f"\n数据范围: {stocks.index[0].date()} ~ {stocks.index[-1].date()}")
    print(f"股票数量: {len(stocks.columns)}")
    print(f"交易日数: {len(stocks)}")

    # 获取创业板指基准
    print(f"\n获取创业板指基准...")
    try:
        from gm.api import set_token, history
        set_token(config.GM_TOKEN)
        bench_df = history(symbol='SZSE.399006', frequency='1d',
                          start_time=START_DATE, end_time=END_DATE,
                          fields='close,eob', df=True)
        bench_df['eob'] = pd.to_datetime(bench_df['eob']).dt.tz_localize(None)
        bench = bench_df.set_index('eob')['close']

        bench_ret = bench.pct_change().fillna(0)
        bench_cum = (1 + bench_ret).cumprod()
        bench_total_ret = bench_cum.iloc[-1] - 1
        bench_ann_ret = (1 + bench_total_ret) ** (252 / len(bench)) - 1

        bench_cum_max = np.maximum.accumulate(bench_cum)
        bench_dd = (bench_cum - bench_cum_max) / bench_cum_max
        bench_max_dd = bench_dd.min()

        print(f"✓ 创业板指数据获取成功")
    except Exception as e:
        print(f"⚠️ 无法获取创业板指: {e}")
        bench_ann_ret = 0.0103
        bench_total_ret = 0.0514
        bench_max_dd = -0.55

    print(f"\n创业板指基准表现:")
    print(f"  累计收益: {bench_total_ret:.2%}")
    print(f"  年化收益: {bench_ann_ret:.2%}")
    print(f"  最大回撤: {bench_max_dd:.2%}")

    # 回测推荐方案
    print(f"\n{'='*80}")
    print(f"开始回测...")
    print(f"{'='*80}")

    result = backtest_detailed(stocks, RECOMMENDED_WEIGHTS, HOLD_DAYS, TOP_N)

    # 输出完整报告
    print(f"\n{'='*80}")
    print(f"📊 回测结果报告")
    print(f"{'='*80}")

    print(f"\n【收益指标】")
    print(f"  累计收益:     {result['total_return']:>10.2%}")
    print(f"  年化收益:     {result['annual_return']:>10.2%}")
    print(f"  超越基准:     {result['annual_return'] - bench_ann_ret:>10.2%}")
    print(f"  年化波动:     {result['annual_vol']:>10.2%}")

    print(f"\n【风险指标】")
    print(f"  最大回撤:     {result['max_dd']:>10.2%}")
    print(f"  基准回撤:     {bench_max_dd:>10.2%}")
    print(f"  日胜率:       {result['win_rate']:>10.2%}")
    print(f"  月胜率:       {result['win_months']}/{result['total_months']} ({result['win_months']/result['total_months']:.1%})")

    print(f"\n【风险调整收益】")
    print(f"  夏普比率:     {result['sharpe']:>10.2f}")
    print(f"  Sortino比率:  {result['sortino']:>10.2f}")
    print(f"  Calmar比率:   {result['calmar']:>10.2f}")

    print(f"\n【实盘可行性】")
    print(f"  涨停板占比:   {result['limit_up_pct']:>10.2%}")
    print(f"  选股均值涨幅: {result['selected_returns_dist']['mean']:>10.2%}")
    print(f"  选股中位涨幅: {result['selected_returns_dist']['median']:>10.2%}")

    # 评估
    print(f"\n{'='*80}")
    print(f"🎯 策略评估")
    print(f"{'='*80}")

    # 预期 vs 实际
    print(f"\n【预期 vs 实际】")
    print(f"  年化收益:     预期50-80%, 实际{result['annual_return']:.1%}")
    print(f"  涨停占比:     预期55-65%, 实际{result['limit_up_pct']:.1%}")
    print(f"  夏普比率:     预期1.2-1.8, 实际{result['sharpe']:.2f}")

    # 判断是否达标
    targets_met = []

    if result['annual_return'] > bench_ann_ret:
        targets_met.append("✅ 战胜基准")
    else:
        targets_met.append("❌ 未能战胜基准")

    if 0.5 <= result['limit_up_pct'] <= 0.7:
        targets_met.append("✅ 涨停板占比在可接受范围")
    elif result['limit_up_pct'] > 0.7:
        targets_met.append("⚠️ 涨停板占比偏高")
    else:
        targets_met.append("✅ 涨停板占比较低")

    if result['sharpe'] > 1.0:
        targets_met.append("✅ 夏普比率良好")
    else:
        targets_met.append("⚠️ 夏普比率偏低")

    print(f"\n【达标情况】")
    for item in targets_met:
        print(f"  {item}")

    # 实盘建议
    print(f"\n{'='*80}")
    print(f"💡 实盘建议")
    print(f"{'='*80}")

    if result['limit_up_pct'] < 0.5:
        print(f"\n✅ 优秀 - 涨停板占比{result['limit_up_pct']:.1%}，散户可轻松操作")
        print(f"  • 普通散户成交率预计：60-80%")
        print(f"  • 预期实盘年化：{result['annual_return']*0.7:.1%}（考虑滑点）")
    elif result['limit_up_pct'] < 0.65:
        print(f"\n⭐ 良好 - 涨停板占比{result['limit_up_pct']:.1%}，需要一定打板能力")
        print(f"  • 普通散户成交率预计：40-60%")
        print(f"  • 预期实盘年化：{result['annual_return']*0.5:.1%}（考虑滑点）")
        print(f"  • 建议：使用快速交易通道，提高涨停板成交率")
    else:
        print(f"\n⚠️ 一般 - 涨停板占比{result['limit_up_pct']:.1%}，对打板要求较高")
        print(f"  • 普通散户成交率预计：30-50%")
        print(f"  • 预期实盘年化：{result['annual_return']*0.4:.1%}（考虑滑点）")
        print(f"  • 建议：考虑降低Day2权重，增加Day10/20权重")

    # 保存配置
    print(f"\n💾 保存策略配置...")

    import json
    config_output = {
        'strategy_name': '推荐方案-中等激进',
        'weights': RECOMMENDED_WEIGHTS,
        'hold_days': HOLD_DAYS,
        'top_n': TOP_N,
        'backtest_period': f'{START_DATE} ~ {END_DATE}',
        'performance': {
            'total_return': float(result['total_return']),
            'annual_return': float(result['annual_return']),
            'sharpe': float(result['sharpe']),
            'max_dd': float(result['max_dd']),
            'calmar': float(result['calmar']),
            'limit_up_pct': float(result['limit_up_pct']),
        },
        'vs_benchmark': {
            'benchmark': '创业板指 (SZSE.399006)',
            'benchmark_annual_return': float(bench_ann_ret),
            'excess_return': float(result['annual_return'] - bench_ann_ret),
        }
    }

    with open('recommended_strategy_config.json', 'w', encoding='utf-8') as f:
        json.dump(config_output, f, indent=2, ensure_ascii=False)

    print(f"✅ 已保存到 recommended_strategy_config.json")

    print(f"\n{'='*80}")
    print(f"✅ 测试完成！")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
