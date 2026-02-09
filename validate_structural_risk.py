
import os
import pandas as pd
import numpy as np
from gm.api import *
from config import config

# AI 最优权重
AI_WEIGHTS = {
    1: 0.040, 2: 0.009, 3: -0.071, 4: 0.014, 5: -0.073, 
    6: 0.023, 7: 0.083, 8: -0.041, 9: 0.061, 10: 0.111,
    11: 0.094, 12: 0.014, 13: 0.084, 14: 0.055, 15: 0.066, 
    16: -0.035, 17: 0.047, 18: -0.003, 19: 0.035, 20: -0.040
}

def load_data():
    data_dir = "data_for_opt_stocks"
    prices = pd.read_csv(os.path.join(data_dir, "prices.csv"), index_col=0, parse_dates=True)
    volumes = pd.read_csv(os.path.join(data_dir, "volumes.csv"), index_col=0, parse_dates=True)
    benchmark = pd.read_csv(os.path.join(data_dir, "benchmark.csv"), index_col=0, parse_dates=True)
    if 'close' in benchmark.columns: benchmark = benchmark['close']
    else: benchmark = benchmark.iloc[:, 0]
    return prices.ffill(), volumes.ffill(), benchmark

def run_risk_evaluation(mode='defense'):
    prices, volumes, benchmark = load_data()
    symbols = prices.columns
    ind_groups = pd.Series({s: s.split('.')[-1][0] for s in symbols})
    
    # 预计算
    returns_20d = prices.pct_change(20)
    vol_ma20 = volumes.rolling(20).mean()
    above_ma20 = (prices > prices.rolling(20).mean()).astype(int)
    sector_breadth = above_ma20.T.groupby(ind_groups).mean().T
    sector_breadth_ma5 = sector_breadth.rolling(5).mean()
    sector_returns_20d = returns_20d.T.groupby(ind_groups).mean().T

    trade_returns = []
    daily_metrics = []
    target_dates = prices.index[40:-20]
    
    for i in range(len(target_dates)):
        date = target_dates[i]
        curr_idx = prices.index.get_loc(date)
        
        latest_prices = prices.iloc[curr_idx]
        latest_vols = volumes.iloc[curr_idx]
        
        # 1. AI Base Score
        ai_scores = pd.Series(0.0, index=symbols)
        for p, w in AI_WEIGHTS.items():
            ret_p = (latest_prices / prices.iloc[curr_idx - p]) - 1
            ranks = ret_p.rank(ascending=False, method='min')
            top_100_mask = ranks <= 100
            ai_scores[top_100_mask] += (101 - ranks[top_100_mask]) / 100.0 * w
            
        final_scores = ai_scores.copy()

        # 2. Basic Filters (Defense)
        today_ret = latest_prices / prices.iloc[curr_idx - 1] - 1
        final_scores[today_ret > 0.08] = -999
        s_br = sector_breadth.loc[date]
        decay_mask = ind_groups.map((s_br < sector_breadth.iloc[curr_idx-1]) & (s_br < sector_breadth_ma5.loc[date]))
        final_scores[decay_mask] = -999

        # 3. Structural Filters
        if mode == 'structural':
            # V-P Structure
            vol_callback = volumes.iloc[curr_idx-5:curr_idx-2].mean()
            vol_uptrend = volumes.iloc[curr_idx-20:curr_idx-10].mean()
            final_scores[(vol_callback > vol_uptrend) | (latest_vols < vol_callback * 1.2)] = -999
            
            # Sector Mainline
            s_ret_20d = sector_returns_20d.loc[date]
            s_ret_5d = (prices.iloc[curr_idx] / prices.iloc[curr_idx-5] - 1).T.groupby(ind_groups).mean()
            s_ret_3d = (prices.iloc[curr_idx] / prices.iloc[curr_idx-3] - 1).T.groupby(ind_groups).mean()
            s_vol_3d = volumes.iloc[curr_idx-3:curr_idx].T.groupby(ind_groups).mean().mean(axis=1)
            s_vol_ma20 = vol_ma20.iloc[curr_idx].T.groupby(ind_groups).mean()
            
            valid_sector = (s_ret_20d.rank(pct=True) > 0.6) & (s_ret_5d >= 0) & (~((s_ret_3d < -0.03) & (s_vol_3d > s_vol_ma20)))
            final_scores[~ind_groups.map(valid_sector)] = -999

        # Selection
        top_4 = final_scores.nlargest(4)
        has_selection = top_4.iloc[0] > -500
        
        if has_selection:
            fwd_ret = (prices.iloc[curr_idx + 20] / latest_prices - 1).reindex(top_4.index).mean()
            trade_returns.append(fwd_ret)
            daily_metrics.append({'date': date, 'ret': fwd_ret, 'bm': (benchmark.iloc[curr_idx+20]/benchmark.iloc[curr_idx])-1})
        else:
            daily_metrics.append({'date': date, 'ret': 0.0, 'bm': (benchmark.iloc[curr_idx+20]/benchmark.iloc[curr_idx])-1})

    # Stats Calculation
    df_trades = pd.Series(trade_returns)
    df_daily = pd.DataFrame(daily_metrics).set_index('date')
    df_daily['excess'] = df_daily['ret'] - df_daily['bm']
    
    win_trades = df_trades[df_trades > 0]
    loss_trades = df_trades[df_trades <= 0]
    
    # Yearly breakdown
    df_daily['year'] = df_daily.index.year
    yearly = df_daily.groupby('year').apply(lambda x: pd.Series({
        'Samples': len(x[x['ret'] != 0]) if len(x[x['ret'] != 0]) > 0 else 1,
        'WinRate': np.mean(x['excess'] > 0),
        'AvgExcess': np.mean(x['excess'])
    }))

    return {
        'Total_Actions': len(trade_returns),
        'Avg_Gain': win_trades.mean() if len(win_trades)>0 else 0,
        'Avg_Loss': loss_trades.mean() if len(loss_trades)>0 else 0,
        'Profit_Factor': (win_trades.sum() / abs(loss_trades.sum())) if len(loss_trades)>0 and loss_trades.sum()!=0 else 0,
        'Win_Rate_Excess': np.mean(df_daily['excess'] > 0),
        'Yearly': yearly
    }

if __name__ == "__main__":
    print("📋 开始对比风险模型: Defense vs Structural...")
    res_def = run_risk_evaluation('defense')
    res_str = run_risk_evaluation('structural')
    
    print("\n" + "="*85)
    print(f"{'指标 (Metric)':<30} {'Defense 方案':<25} {'Structural 方案':<25}")
    print("="*85)
    print(f"{'出手总次数 (Trade Counts)':<30} {res_def['Total_Actions']:<25} {res_str['Total_Actions']:<25}")
    print(f"{'平均盈利 (Avg Gain)':<30} {res_def['Avg_Gain']:<25.2%} {res_str['Avg_Gain']:<25.2%}")
    print(f"{'平均亏损 (Avg Loss)':<30} {res_def['Avg_Loss']:<25.2%} {res_str['Avg_Loss']:<25.2%}")
    print(f"{'盈亏比 (Risk/Reward Ratio)':<30} {abs(res_str['Avg_Gain']/res_str['Avg_Loss']):<25.2f} {abs(res_str['Avg_Gain']/res_str['Avg_Loss']):<25.2f}")
    print(f"{'获利因子 (Profit Factor)':<30} {res_def['Profit_Factor']:<25.2f} {res_str['Profit_Factor']:<25.2f}")
    print(f"{'总胜率 (vs Bench)':<30} {res_def['Win_Rate_Excess']:<25.2%} {res_str['Win_Rate_Excess']:<25.2%}")
    
    print("\n" + "="*85)
    print("📅 分年度样本外表现 (Yearly Out-of-Sample)")
    print("="*85)
    print("Defense:")
    print(res_def['Yearly'])
    print("-" * 40)
    print("Structural:")
    print(res_str['Yearly'])
    print("="*85)
