
import os
import pandas as pd
import numpy as np
from gm.api import *

# 当前使用的 20维 AI 权重
AI_WEIGHTS = {
    1: 0.040, 2: 0.009, 3: -0.071, 4: 0.014, 5: -0.073, 
    6: 0.023, 7: 0.083, 8: -0.041, 9: 0.061, 10: 0.111,
    11: 0.094, 12: 0.014, 13: 0.084, 14: 0.055, 15: 0.066, 
    16: -0.035, 17: 0.047, 18: -0.003, 19: 0.035, 20: -0.040
}

def load_data():
    data_dir = "data_for_opt_stocks"
    prices = pd.read_csv(os.path.join(data_dir, "prices.csv"), index_col=0, parse_dates=True)
    benchmark = pd.read_csv(os.path.join(data_dir, "benchmark.csv"), index_col=0, parse_dates=True)
    if 'close' in benchmark.columns: benchmark = benchmark['close']
    else: benchmark = benchmark.iloc[:, 0]
    return prices.ffill(), benchmark

def verify_alpha_raw():
    prices, benchmark = load_data()
    symbols = prices.columns
    
    # 仅回测 2025 年至今的数据，验证 Alpha 是否真实存在
    start_date = '2025-01-01'
    target_dates = prices.index[prices.index >= start_date]
    
    results = []
    
    print(f"🚀 验证原始 Alpha 效能 (无风控/无手续费) - {start_date} 之后...")
    
    # 为了速度，我们每 5 天采样一次，模拟持有 20 天的信号质量
    for i in range(0, len(target_dates)-20, 5):
        date = target_dates[i]
        curr_idx = prices.index.get_loc(date)
        
        # 1. 计算 AI 分数
        latest_prices = prices.iloc[curr_idx]
        scores = pd.Series(0.0, index=symbols)
        for p, w in AI_WEIGHTS.items():
            prev_idx = curr_idx - p
            if prev_idx < 0: continue
            ret_p = (latest_prices / prices.iloc[prev_idx]) - 1
            ranks = ret_p.rank(ascending=False, method='min')
            top_100_mask = ranks <= 100
            scores[top_100_mask] += (101 - ranks[top_100_mask]) / 100.0 * w
            
        # 2. 选取 Top 4 (完全不加任何过滤)
        top_4 = scores.nlargest(4)
        
        # 3. 计算未来 20 日收益
        fwd_20d_ret = (prices.iloc[curr_idx + 20] / latest_prices - 1).reindex(top_4.index).mean()
        bm_fwd_20d_ret = (benchmark.iloc[curr_idx + 20] / benchmark.iloc[curr_idx]) - 1
        
        results.append({
            'date': date,
            'ret': fwd_20d_ret,
            'bm_ret': bm_fwd_20d_ret,
            'excess': fwd_20d_ret - bm_fwd_20d_ret
        })
        
    df = pd.DataFrame(results)
    mean_excess = df['excess'].mean()
    win_rate = (df['excess'] > 0).mean()
    
    print("\n" + "="*50)
    print("📈 原始 Alpha (N字型权重) 2025 验证结果")
    print("="*50)
    print(f"样本周期数:       {len(df)}")
    print(f"平均 20日超额:     {mean_excess:.2%}")
    print(f"年化超额 (约):     {mean_excess * 12.5:.2%}")
    print(f"超额胜率:         {win_rate:.2%}")
    print("="*50)
    
    if mean_excess > 0.02:
        print("💡 结论：Alpha 依然极强！N字型权重在个股上拥有巨大的盈利空间。")
        print("问题核心：在于【摩擦成本】和【极端行情下的结构稳健性】。")
    else:
        print("💡 结论：规律正在变弱，建议重新训练。")

if __name__ == "__main__":
    verify_alpha_raw()
