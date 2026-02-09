
"""
verify_final_backtest.py
专门验证用户指定的 "Day 2 + Day 20" + "3日换仓" 策略
在 2021-12-03 到 2026-01-23 期间的最终表现。
"""
import os
import pandas as pd
import numpy as np
from config import config

# 配置
DATA_DIR = os.path.join(config.BASE_DIR, "data_for_opt_stocks")
PRICES_FILE = os.path.join(DATA_DIR, "prices.csv")
BENCH_FILE = os.path.join(DATA_DIR, "benchmark.csv") # 假设 verify_20d_perf 已下载，或 fetch_data 已下载

# 用户指定参数
START_DATE = '2021-12-03'
END_DATE = '2026-01-23'
HOLD_DAYS = 3
TOP_N = 4
WEIGHTS = {2: 0.3, 20: 0.7}

def main():
    # 1. 加载数据
    print(f"Loading data from {DATA_DIR}...")
    if not os.path.exists(PRICES_FILE):
        print("❌ Data not found.")
        return
        
    stocks = pd.read_csv(PRICES_FILE, index_col=0, parse_dates=True)
    
    # 加载基准 (Force Fetch ChiNext for accuracy)
    # if os.path.exists(BENCH_FILE):
    #     bench = pd.read_csv(BENCH_FILE, index_col=0, parse_dates=True).iloc[:, 0]
    # else:
    
    # Always fetch 'SZSE.159915'
    from gm.api import set_token, history, ADJUST_PREV
    set_token(config.GM_TOKEN)
    print("Fetching ChiNext benchmark (SZSE.159915)...")
    try:
        df = history(symbol='SZSE.159915', frequency='1d', start_time=START_DATE, end_time=END_DATE, fields='close,eob', adjust=ADJUST_PREV, df=True)
        if df.empty: raise ValueError("Empty df")
        df['eob'] = pd.to_datetime(df['eob']).dt.tz_localize(None)
        bench = df.set_index('eob')['close']
    except Exception as e:
        print(f"Failed to fetch benchmark: {e}. Using Mean of Stocks.")
        bench = stocks.mean(axis=1)

    # 切片
    stocks = stocks.loc[START_DATE:END_DATE]
    bench = bench.reindex(stocks.index).fillna(method='ffill')
    
    # 2. 计算分数
    score_df = pd.DataFrame(0.0, index=stocks.index, columns=stocks.columns)
    for p, w in WEIGHTS.items():
        ret = stocks / stocks.shift(p) - 1
        rank = ret.rank(axis=1, pct=True).fillna(0.5)
        score_df += rank * w
        
    # 3. 模拟滚动分仓回测 (Tranche Backtest)
    # ... (existing logic for returns) ...
    # We also want to analyze the ENTRY DAY conditions to check feasibility.
    
    # Selected stocks mask (boolean)
    # score_df has scores at day T.
    # top_idx has indices of selections.
    
    # Calculate Entry Day Returns (Day T returns) to see if we are buying limit ups
    # stocks.pct_change() gives return from T-1 to T.
    day_ret_matrix = stocks.pct_change().fillna(0.0).values
    
    selections_ret = []
    selections_is_limit_up = [] # > 9.5%
    selections_is_20cm = []     # > 19.5%
    
    # Calculate daily returns for filtering
    day_ret_matrix = stocks.pct_change().fillna(0.0).values
    
    # Determine top N stocks for each day
    vals = score_df.values
    
    # === REALITY FILTER: EXCLUDE LIMIT UPS ===
    # If a stock is already Limit Up (>9.5%) on selection day, we assume we CANNOT buy it.
    # So we set its score to -inf.
    # day_ret_matrix stores returns on day T (selection day).
    # Mask out Limit Ups
    is_limit_up = (day_ret_matrix > 0.095)
    vals[is_limit_up] = -np.inf
    
    # Check if we have enough stocks left?
    # If all represent -inf, we pick nothing?
    # -inf values will be picked last.
    # argpartition with -inf at bottom.
    # We want largest. -inf is smallest.
    # So they won't be in Top N unless N is larger than valid stocks.
    
    vals = np.nan_to_num(vals, nan=-np.inf)
    
    # Calculate feasible selections count
    valid_counts = np.sum(~np.isinf(vals), axis=1)
    avg_valid = np.mean(valid_counts)
    print(f"DEBUG: Avg Valid Stocks per day (Not Limit Up): {avg_valid:.1f}")
    
    top_idx = np.argpartition(-vals, TOP_N, axis=1)[:, :TOP_N]
    
    # Create a boolean mask for selected stocks
    top_n_mask = pd.DataFrame(False, index=score_df.index, columns=score_df.columns)
    rows = np.arange(len(score_df))[:, None]
    top_n_mask.values[rows, top_idx] = True
    
    # Iterate to collect stats
    # top_idx shape: (T, TOP_N)
    for i in range(len(score_df)):
        # Indices of selected stocks for day i
        sel_indices = top_idx[i]
        # Returns of these stocks on day i
        rets = day_ret_matrix[i, sel_indices]
        selections_ret.extend(rets)
        
        # Check thresholds
        curr_is_lu = np.sum(rets > 0.095)
        curr_is_20 = np.sum(rets > 0.195)
        
        selections_is_limit_up.append(curr_is_lu)
        selections_is_20cm.append(curr_is_20)
        
    avg_entry_ret = np.mean(selections_ret)
    total_selections = len(selections_ret)
    total_lu = np.sum(selections_is_limit_up)
    total_20cm = np.sum(selections_is_20cm)
    
    pct_lu = total_lu / total_selections
    pct_20cm = total_20cm / total_selections
        
    print("\n" + "="*50)
    print(f"🕵️ Feasibility & Reality Check")
    print("="*50)
    print(f"Total Selections: {total_selections}")
    print(f"Avg Return on Entry Day: {avg_entry_ret:.2%}")
    print(f"🚨 Limit Up Entries (>9.5%):  {total_lu} ({pct_lu:.1%})")
    print(f"🚨 20cm Entries (>19.5%):     {total_20cm} ({pct_20cm:.1%})")
    
    if pct_lu > 0.3:
        print("⚠️  WARNING: High portion of Limit Up buys. Slippage will be high or untradeable.")
    else:
        print("✅ Limit Up portion is manageable.")

    # ... (Rest of backtest logic) ...
    
    # Re-implement Tranche logic for PnL (same as before)
    # Actual Market Returns on day T: stocks.pct_change()
    market_ret = stocks.pct_change().fillna(0.0)
    
    strat_daily_rets = pd.Series(0.0, index=stocks.index)
    
    active_masks = []
    for lag in range(1, HOLD_DAYS + 1):
        m = top_n_mask.shift(lag).fillna(False)
        active_masks.append(m)
        
    total_tranche_ret = pd.Series(0.0, index=stocks.index)
    
    for m in active_masks:
        tranche_ret = (market_ret * m).sum(axis=1) / TOP_N
        total_tranche_ret += tranche_ret
        
    port_daily = total_tranche_ret / HOLD_DAYS
    ben_daily = bench.pct_change().fillna(0.0)
    
    start_idx = HOLD_DAYS
    port_daily = port_daily.iloc[start_idx:]
    ben_daily = ben_daily.iloc[start_idx:]
    
    strategy_cum = (1 + port_daily).cumprod()
    bench_cum = (1 + ben_daily).cumprod()
    
    total_ret = strategy_cum.iloc[-1] - 1
    bench_total_ret = bench_cum.iloc[-1] - 1
    excess_ret = total_ret - bench_total_ret
    
    n_days = len(port_daily)
    ann_ret = (1 + total_ret) ** (252 / n_days) - 1
    
    cum_max = np.maximum.accumulate(strategy_cum)
    drawdown = (strategy_cum - cum_max) / cum_max
    max_dd = drawdown.min()
    
    print("\n" + "="*50)
    print(f"📊 Final Backtest Report ({START_DATE} ~ {END_DATE})")
    print("="*50)
    print(f"Strategy: Day 2 + Day 20 Momentum (3-Day Rolling)")
    print(f"Selection: Top {TOP_N} stocks")
    print("-" * 50)
    print(f"📈 Total Return:     {total_ret:>7.2%}")
    print(f"📉 Max Drawdown:     {max_dd:>7.2%}")
    print(f"📅 Annualized Ret:   {ann_ret:>7.2%}")
    print("-" * 50)
    print(f"🏦 Benchmark (ChiNext): {bench_total_ret:.2%}")
    print(f"💰 Excess Return:       {excess_ret:.2%}")
    print("="*50)
    
    # Daily breakdown check
    # print(pd.concat([port_daily, ben_daily], axis=1).tail())

if __name__ == "__main__":
    main()
