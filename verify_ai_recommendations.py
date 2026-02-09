
import os
import pandas as pd
import numpy as np
from gm.api import *
from config import config, logger
from datetime import datetime, timedelta

# 1. AI 最优权重 (从报告中提取)
AI_WEIGHTS = np.array([
     0.040,  0.009, -0.071,  0.014, -0.073,  0.023,  0.083, -0.041,  0.061,  0.111,
     0.094,  0.014,  0.084,  0.055,  0.066, -0.035,  0.047, -0.003,  0.035, -0.040
])

def get_universe_stocks():
    """获取全市场及核心指数成份股（与训练集保持一致）"""
    set_token(config.GM_TOKEN)
    indices = ['SHSE.000300', 'SHSE.000905', 'SHSE.000852'] # 沪深300, 中证500, 中证1000
    whitelist = set()
    for idx in indices:
        try:
            c = stk_get_index_constituents(index=idx)
            if not c.empty:
                whitelist.update(c['symbol'].tolist())
        except:
            pass
    return list(whitelist)

def predict_top_stocks(n_days=4):
    """
    计算最近 N 个交易日的 AI 模型推荐
    """
    set_token(config.GM_TOKEN)
    symbols = get_universe_stocks()
    print(f"Checking {len(symbols)} stocks...")
    
    # 获取名称映射
    print("Fetching symbol names...")
    instruments = get_instruments(symbols=symbols, df=True)
    name_map = instruments.set_index('symbol')['sec_name'].to_dict()
    
    # 获取最近 40 天数据 (需要 20 天计算特征)
    end_dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # 扩大范围到 90 天确保有足够的交易日
    start_dt = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d %H:%M:%S')
    
    all_prices = []
    chunk_size = 50 
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i+chunk_size]
        # 只获取必要字段
        hd = history(symbol=",".join(chunk), frequency='1d', start_time=start_dt, end_time=end_dt, 
                     fields='symbol,close,eob', adjust=ADJUST_PREV, df=True)
        if not hd.empty:
            all_prices.append(hd)
            
    if not all_prices:
        print("No data fetched.")
        return
        
    df = pd.concat(all_prices)
    df['eob'] = pd.to_datetime(df['eob']).dt.tz_localize(None)
    
    # 透视价格
    prices_df = df.pivot(index='eob', columns='symbol', values='close').ffill()
    trade_dates = prices_df.index
    
    print(f"Data ready. Latest date: {trade_dates[-1]}")
    
    # 计算最近 N 个交易日
    results = []
    # 确保我们有足够的时间窗口
    available_days = len(trade_dates)
    start_idx = max(-n_days, -available_days + 21)
    
    for d_idx in range(start_idx, 0):
        target_date = trade_dates[d_idx]
        # 获取截至该日的数据
        hist = prices_df.loc[:target_date]
        if len(hist) < 22: continue
        
        latest_price = hist.iloc[-1]
        final_scores = pd.Series(0.0, index=hist.columns)
        
        # 严格执行 Top 100 逻辑
        for i in range(20):
            period = i + 1
            w = AI_WEIGHTS[i]
            
            # 涨幅计算
            prev_price = hist.iloc[-(period+1)]
            ret = latest_price / prev_price - 1
            
            # RankScore (Top 100 线性打分)
            ranks = ret.rank(ascending=False, method='min')
            top_100_mask = (ranks <= 100)
            
            # 分数 = (101 - rank) / 100 (1 到 0.01)
            score_p = (101 - ranks[top_100_mask]) / 100.0
            final_scores[top_100_mask] += score_p * w
            
        top_4 = final_scores.nlargest(4)
        
        day_res = {
            'date': target_date.strftime('%Y-%m-%d'),
            'stocks': []
        }
        for sym, score in top_4.items():
            day_res['stocks'].append({
                'symbol': sym,
                'name': name_map.get(sym, 'N/A'),
                'score': round(score, 4)
            })
        results.append(day_res)
        
    return results

if __name__ == "__main__":
    res = predict_top_stocks()
    print("\n" + "="*50)
    print("🤖 AI 模型多周期选股推荐 (最近 4 个交易日)")
    print("="*50)
    for day in res:
        print(f"\n📅 日期: {day['date']}")
        print(f"{'代码':<10} {'名称':<12} {'AI 综合评分':<10}")
        print("-" * 35)
        for s in day['stocks']:
            print(f"{s['symbol']:<12} {s['name']:<12} {s['score']:<10}")
