
"""
verify_20d_performance.py
专门验证：选出的 Top N 股票，在持有 20 天后，是否战胜创业板指。
"""
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from gm.api import *
from config import config

# 配置
DATA_DIR = os.path.join(config.BASE_DIR, "data_for_opt_stocks")
PRICES_FILE = os.path.join(DATA_DIR, "prices.csv")
BENCH_SYMBOL = 'SZSE.159915' # 创业板指
START_DATE = '2021-01-01'
END_DATE = '2026-02-07'
HOLD_DAYS = 20
TOP_N = 4

# 新策略权重 (Simplified Momentum)
WEIGHTS = {
    2: 0.3,
    20: 0.7
}

def fetch_benchmark():
    """专门获取创业板指数据"""
    set_token(config.GM_TOKEN)
    print(f"Fetching benchmark {BENCH_SYMBOL}...")
    try:
        df = history(symbol=BENCH_SYMBOL, frequency='1d', start_time=START_DATE, end_time=END_DATE, 
                     fields='close,eob', adjust=ADJUST_PREV, df=True)
        if df.empty:
            print("❌ Benchmark fetch failed.")
            return None
        df['eob'] = pd.to_datetime(df['eob']).dt.tz_localize(None)
        return df.set_index('eob')['close']
    except Exception as e:
        print(f"Error: {e}")
        return None

def main():
    # 1. 加载个股数据
    print(f"Loading stock data from {PRICES_FILE}...")
    if not os.path.exists(PRICES_FILE):
        print("❌ Stock data not found. Please run fetch_data_stocks.py first.")
        return
    stocks = pd.read_csv(PRICES_FILE, index_col=0, parse_dates=True)
    stocks = stocks.loc[START_DATE:END_DATE]
    
    # 2. 获取基准数据
    bench = fetch_benchmark()
    if bench is None: return
    bench = bench.reindex(stocks.index).fillna(method='ffill')
    
    # 3. 计算选股分数 (Score)
    print("Calculating scores based on Day 2 + Day 20 momentum...")
    score_df = pd.DataFrame(0.0, index=stocks.index, columns=stocks.columns)
    
    for p, w in WEIGHTS.items():
        # Ret_p = Price / Price_shift(p) - 1
        ret = stocks / stocks.shift(p) - 1
        # Rank (Pct)
        rank = ret.rank(axis=1, pct=True).fillna(0.5)
        score_df += rank * w
        
    # 4. 模拟不同持有期
    for HOLD_DAYS in [3, 5, 10, 20]:
        print(f"\nSimulating {HOLD_DAYS}-day hold...")
        results = [] 
        
        # Shift data
        stocks_fwd = stocks.shift(-HOLD_DAYS) / stocks - 1
        bench_fwd = bench.shift(-HOLD_DAYS) / bench - 1
        
        valid_dates = stocks_fwd.dropna(how='all').index
        
        for date in valid_dates:
            if date not in score_df.index: continue
            
            s_row = score_df.loc[date]
            if s_row.isna().all(): continue
            
            top_syms = s_row.nlargest(TOP_N).index
            
            port_ret = stocks_fwd.loc[date, top_syms].mean()
            ben_ret = bench_fwd.loc[date]
            
            if pd.isna(port_ret) or pd.isna(ben_ret): continue
                
            excess = port_ret - ben_ret
            results.append({'excess': excess, 'win': excess > 0})
            
        res_df = pd.DataFrame(results)
        if res_df.empty: continue
            
        win_rate = res_df['win'].mean()
        avg_excess = res_df['excess'].mean()
        
        print(f"  👉 Hold {HOLD_DAYS} Days: Win {win_rate:.1%} | Avg Excess {avg_excess:.2%}")

if __name__ == "__main__":
    main()
