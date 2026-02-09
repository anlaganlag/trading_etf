
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

from core.signal import get_ranking

class MockContext:
    def __init__(self, symbols, prices_df, volumes_df, whitelist):
        self.mode = 'LIVE'
        self.whitelist = whitelist
        self.prices_df = prices_df
        self.volumes_df = volumes_df
        self.theme_map = {}
        self.name_map = {}
        self.market_state = 'SAFE'
        self.risk_scaler = 1.0
        self.BR_CAUTION_IN, self.BR_CAUTION_OUT = 0.40, 0.30
        self.BR_DANGER_IN, self.BR_DANGER_OUT, self.BR_PRE_DANGER = 0.60, 0.50, 0.55

def calculate_realtime_top4():
    """使用核心 signal.py 逻辑计算当前的 Top 4 Survivors"""
    set_token(config.GM_TOKEN)
    symbols = get_universe_stocks()
    print(f"Fetching data for {len(symbols)} symbols...")
    
    # 1. 获取基础数据
    end_dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    start_dt = (datetime.now() - timedelta(days=250)).strftime('%Y-%m-%d %H:%M:%S')
    
    all_data = []
    chunk_size = 30
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i+chunk_size]
        hd = history(symbol=",".join(chunk), frequency='1d', start_time=start_dt, end_time=end_dt, 
                     fields='symbol,close,volume,eob', adjust=ADJUST_PREV, df=True)
        if not hd.empty:
            all_data.append(hd)
            
    if not all_data:
        print("❌ No data fetched from GM.")
        return
        
    df = pd.concat(all_data)
    df['eob'] = pd.to_datetime(df['eob']).dt.tz_localize(None)
    prices_df = df.pivot(index='eob', columns='symbol', values='close').ffill()
    volumes_df = df.pivot(index='eob', columns='symbol', values='volume').ffill()
    
    # 2. 注入实时价
    snaps = current(symbols=symbols)
    realtime_prices = {s['symbol']: s['price'] for s in snaps if s['price'] > 0}
    realtime_vols = {s['symbol']: s['amount'] / s['price'] if s['price'] > 0 else 0 for s in snaps} # Approximate volume
    
    current_time = datetime.now()
    if realtime_prices:
        rt_p = pd.Series(realtime_prices, name=current_time).reindex(prices_df.columns)
        prices_df = pd.concat([prices_df, rt_p.to_frame().T])
        rt_v = pd.Series(realtime_vols, name=current_time).reindex(volumes_df.columns)
        volumes_df = pd.concat([volumes_df, rt_v.to_frame().T])

    # 3. 创建上下文
    context = MockContext(symbols, prices_df, volumes_df, set(symbols))
    # 为 context 补全 mapping
    inst = get_instruments(symbols=symbols, df=True)
    context.name_map = inst.set_index('symbol')['sec_name'].to_dict()
    
    # 4. 调用统一生成的 get_ranking (包含 Structural Filters)
    print("\nApplying Behavioral Structural Filters...")
    rank_df, _ = get_ranking(context, current_time)
    
    if rank_df is None or rank_df.empty:
        print("🚫 No stocks matched the strict structural requirements today.")
        return

    top_4 = rank_df.head(4)
    
    print("\n" + "="*75)
    print(f"🌟 行为结构选股: 今日真正“幸存者”名单 ({current_time.strftime('%H:%M:%S')})")
    print("="*75)
    print(f"{'代码':<12} {'名称':<12} {'AI共振分':<10} {'20日涨幅':<10} {'今日涨幅':<8}")
    print("-" * 75)
    
    for sym, row in top_4.iterrows():
        name = context.name_map.get(sym, 'N/A')
        print(f"{sym:<12} {name:<12} {row['score']:<10.4f} {row['r20']:>10.2%} {row['r1']:>8.2%}")

if __name__ == "__main__":
    calculate_realtime_top4()
