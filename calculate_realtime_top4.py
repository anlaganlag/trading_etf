
import os
import pandas as pd
import numpy as np
from gm.api import *
from config import config, logger
from datetime import datetime, timedelta

# AI 最优权重
AI_WEIGHTS = np.array([
     0.040,  0.009, -0.071,  0.014, -0.073,  0.023,  0.083, -0.041,  0.061,  0.111,
     0.094,  0.014,  0.084,  0.055,  0.066, -0.035,  0.047, -0.003,  0.035, -0.040
])

def get_universe_stocks():
    set_token(config.GM_TOKEN)
    indices = ['SHSE.000300', 'SHSE.000905', 'SHSE.000852']
    whitelist = set()
    for idx in indices:
        try:
            c = stk_get_index_constituents(index=idx)
            if not c.empty:
                whitelist.update(c['symbol'].tolist())
        except:
            pass
    return list(whitelist)

def calculate_realtime_top4():
    """使用实时行情计算当前的 Top 4"""
    set_token(config.GM_TOKEN)
    symbols = get_universe_stocks()
    print(f"Checking {len(symbols)} stocks with real-time data...")
    
    # 1. 获取历史日线 (截至昨日收盘)
    end_dt = datetime.now().strftime('%Y-%m-%d 15:30:00')
    start_dt = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d 09:00:00')
    
    all_prices = []
    chunk_size = 50 
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i+chunk_size]
        hd = history(symbol=",".join(chunk), frequency='1d', start_time=start_dt, end_time=end_dt, 
                     fields='symbol,close,eob', adjust=ADJUST_PREV, df=True)
        if not hd.empty:
            all_prices.append(hd)
    
    hist_df = pd.concat(all_prices)
    hist_df['eob'] = pd.to_datetime(hist_df['eob']).dt.tz_localize(None)
    prices_df = hist_df.pivot(index='eob', columns='symbol', values='close').ffill()
    
    # 2. 获取当日前快照 (Snapshot)
    print("Fetching current snapshots...")
    snaps = current(symbols=symbols)
    realtime_prices = {s['symbol']: s['price'] for s in snaps if s['price'] > 0}
    
    # 将实时价格作为最新一行加入 prices_df
    current_time = datetime.now()
    if realtime_prices:
        rt_row = pd.Series(realtime_prices, name=current_time)
        # 只保留 prices_df 中已有的 symbol
        rt_row = rt_row.reindex(prices_df.columns)
        prices_df = pd.concat([prices_df, rt_row.to_frame().T])
    
    print(f"Data combined. Latest tick at: {current_time}")
    
    # 3. 名称映射
    instruments = get_instruments(symbols=symbols, df=True)
    name_map = instruments.set_index('symbol')['sec_name'].to_dict()
    
    # 4. 计算 Top 100 逻辑打分
    latest_price = prices_df.iloc[-1]
    final_scores = pd.Series(0.0, index=prices_df.columns)
    
    # 基础信息用于分析“坑”
    details = []
    
    for i in range(20):
        period = i + 1
        w = AI_WEIGHTS[i]
        
        # 涨幅计算 (当日实时价 vs 前 N 日收盘价)
        prev_price = prices_df.iloc[-(period+1)]
        ret = latest_price / prev_price - 1
        
        ranks = ret.rank(ascending=False, method='min')
        top_100_mask = (ranks <= 100)
        
        score_p = (101 - ranks[top_100_mask]) / 100.0
        final_scores[top_100_mask] += score_p * w
        
    top_4 = final_scores.nlargest(4)
    
    print("\n" + "="*60)
    print(f"🔥 实时选股结果 ({current_time.strftime('%H:%M:%S')})")
    print("="*60)
    print(f"{'代码':<12} {'名称':<12} {'实时评分':<10} {'今日涨幅':<8}")
    print("-" * 55)
    
    for sym, score in top_4.items():
        name = name_map.get(sym, 'N/A')
        # 今日涨幅 = (今日实时价 / 昨日收盘价) - 1
        # prices_df.iloc[-1] 是实时价, prices_df.iloc[-2] 是昨日收盘
        try:
            p_now = prices_df.iloc[-1][sym]
            p_yesterday = prices_df.iloc[-2][sym]
            day_ret = (p_now / p_yesterday) - 1
        except:
            day_ret = 0.0
            
        print(f"{sym:<12} {name:<12} {score:<10.4f} {day_ret:>8.2%}")

if __name__ == "__main__":
    calculate_realtime_top4()
