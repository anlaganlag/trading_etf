
import os
import pandas as pd
import numpy as np
from gm.api import *
import config

START_DATE = '2021-01-01'
END_DATE = '2026-02-07' # 稍微多涵盖一点
TOP_N = 4
HOLD_DAYS = 3

# AI 刚才生成的权重
best_w = {
    1: -0.0198,
    2: -0.1400,
    3: -0.2436,
    5: -0.1599,
    7: -0.6888,
    10: +0.7613,
    14: +0.4187,
    20: +0.5298
}

def main():
    DATA_DIR = os.path.join(config.config.BASE_DIR, "data_for_opt_stocks")
    PRICES_FILE = os.path.join(DATA_DIR, "prices.csv")
    
    print("Loading prices...")
    stocks = pd.read_csv(PRICES_FILE, index_col=0, parse_dates=True)
    
    # 1. 计算评分
    print("Calculating scores...")
    score_df = pd.DataFrame(0.0, index=stocks.index, columns=stocks.columns)
    for p, w in best_w.items():
        ret = stocks / stocks.shift(p) - 1
        rank = ret.rank(axis=1, pct=True).fillna(0.5)
        score_df += rank * w
        
    # 2. 模拟切片数据 (回测区间)
    s_stocks = stocks.loc[START_DATE:END_DATE]
    s_score = score_df.loc[START_DATE:END_DATE]
    
    # 获取当日收益率用于过滤
    daily_ret = s_stocks.pct_change().fillna(0.0)
    
    # 3. 模拟滚动分仓 (Tranche Backtest)
    top_n_mask = pd.DataFrame(False, index=s_score.index, columns=s_score.columns)
    
    vals = s_score.values
    rets = daily_ret.values
    
    # 强力过滤：涨幅 > 9.5% 的股票分数设为极小值
    vals[rets > 0.095] = -1e9
    
    # 取 Top N
    top_idx = np.argpartition(-vals, TOP_N, axis=1)[:, :TOP_N]
    
    rows = np.arange(len(s_score))[:, None]
    top_n_mask.values[rows, top_idx] = True
    
    # 策略日收益计算
    market_ret = s_stocks.pct_change().fillna(0.0)
    total_tranche_ret = pd.Series(0.0, index=s_score.index)
    
    for lag in range(1, HOLD_DAYS + 1):
        m = top_n_mask.shift(lag).fillna(False)
        tranche_ret = (market_ret * m).sum(axis=1) / TOP_N
        total_tranche_ret += tranche_ret
        
    port_daily = total_tranche_ret / HOLD_DAYS
    
    # 4. 获取基准 (创业板指)
    set_token(config.config.GM_TOKEN)
    print("Fetching benchmark (SZSE.159915)...")
    try:
        df_bench = history(symbol='SZSE.159915', frequency='1d', start_time=START_DATE, end_time=END_DATE, fields='close,eob', adjust=ADJUST_PREV, df=True)
        df_bench['eob'] = pd.to_datetime(df_bench['eob']).dt.tz_localize(None)
        bench = df_bench.set_index('eob')['close']
        ben_daily = bench.pct_change().fillna(0.0)
    except:
        print("Fallback: Use simple mean as benchmark")
        ben_daily = stocks.mean(axis=1).pct_change().fillna(0.0)

    # 5. 统计结果
    common_idx = port_daily.index.intersection(ben_daily.index)
    p_ret = port_daily.loc[common_idx].iloc[HOLD_DAYS:]
    b_ret = ben_daily.loc[common_idx].iloc[HOLD_DAYS:]
    
    # 年度拆解
    yearly_p = p_ret.groupby(p_ret.index.year).apply(lambda x: (1 + x).prod() - 1)
    yearly_b = b_ret.groupby(b_ret.index.year).apply(lambda x: (1 + x).prod() - 1)
    
    strat_cum = (1 + p_ret).cumprod()
    bench_cum = (1 + b_ret).cumprod()
    
    total_ret = strat_cum.iloc[-1] - 1
    bench_ret = bench_cum.iloc[-1] - 1
    
    ann_ret = (1 + total_ret) ** (252/len(p_ret)) - 1
    max_dd = ((strat_cum - strat_cum.cummax()) / strat_cum.cummax()).min()
    
    print("\n" + "="*50)
    print(f"📈 YEARLY PERFORMANCE BREAKDOWN")
    print("-" * 50)
    for yr in yearly_p.index:
        print(f"Year {yr}: Strategy {yearly_p[yr]:>7.2%} | Bench {yearly_b[yr]:>7.2%} | Excess {yearly_p[yr]-yearly_b[yr]:>7.2%}")
    print("-" * 50)
    
    print("\n" + "="*50)
    print(f"✅ REAL TRADABLE BACKTEST (NO LIMIT-UP BUYS)")
    print("="*50)
    print(f"Time Range: {p_ret.index[0].date()} to {p_ret.index[-1].date()}")
    print(f"Cumulative Return: {total_ret:.2%}")
    print(f"Annualized Return: {ann_ret:.2%}")
    print(f"Max Drawdown:      {max_dd:.2%}")
    print("-" * 50)
    print(f"Benchmark (159915): {bench_ret:.2%}")
    print(f"Total Excess:       {(total_ret - bench_ret):.2%}")
    print("="*50)

if __name__ == "__main__":
    main()
