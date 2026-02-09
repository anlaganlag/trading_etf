
import os
import pandas as pd
import numpy as np
from gm.api import *
from config import config

# 最佳 AI 权重
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

def run_experiment(mode='base'):
    """
    mode: 
    - 'base': 纯 AI 20维权重
    - 'defense': AI + Breadth + Decay + 8% 过滤 (之前的 Full)
    - 'structural': defense + 洗盘/出货逻辑 + 板块硬过滤 (最新要求)
    """
    prices, volumes, benchmark = load_data()
    symbols = prices.columns
    
    # 模拟行业映射 (实战中用真实行业)
    ind_groups = pd.Series({s: s.split('.')[-1][0] for s in symbols})
    
    # 预计算特征
    returns_20d = prices.pct_change(20)
    vol_ma20 = volumes.rolling(20).mean()
    
    # 计算行业广度 (Breadth)
    above_ma20 = (prices > prices.rolling(20).mean()).astype(int)
    sector_breadth = above_ma20.T.groupby(ind_groups).mean().T
    sector_breadth_ma5 = sector_breadth.rolling(5).mean()
    
    # 计算行业收益率与热度
    sector_returns_20d = returns_20d.T.groupby(ind_groups).mean().T

    port_rets = []
    target_dates = prices.index[40:-20] 
    
    for i in range(len(target_dates)):
        date = target_dates[i]
        curr_idx = prices.index.get_loc(date)
        
        latest_prices = prices.iloc[curr_idx]
        latest_vols = volumes.iloc[curr_idx]
        
        # 1. AI 基础打分
        ai_scores = pd.Series(0.0, index=symbols)
        for p, w in AI_WEIGHTS.items():
            ret_p = latest_prices / prices.iloc[curr_idx - p] - 1
            ranks = ret_p.rank(ascending=False)
            top_100_mask = ranks <= 100
            ai_scores[top_100_mask] += (101 - ranks[top_100_mask]) / 100.0 * w
            
        final_scores = ai_scores.copy()
        
        # 2. 防御逻辑
        if mode in ['defense', 'structural']:
            # 8% 追高过滤
            today_ret = latest_prices / prices.iloc[curr_idx - 1] - 1
            final_scores[today_ret > 0.08] = -999
            
            # 板块衰减过滤
            s_br = sector_breadth.loc[date]
            s_br_prev = sector_breadth.iloc[curr_idx - 1]
            s_br_ma5 = sector_breadth_ma5.loc[date]
            decay_mask = ind_groups.map((s_br < s_br_prev) & (s_br < s_br_ma5))
            final_scores[decay_mask] = -999

        # 3. 结构特征过滤 (STRUCTURAL RULE)
        if mode == 'structural':
            # [1] 洗盘 vs 出货
            # 回调期 (3-5日前的 3 天)
            vol_callback = volumes.iloc[curr_idx-5:curr_idx-2].mean()
            # 上涨期 (10-20日前的 10 天)
            vol_uptrend = volumes.iloc[curr_idx-20:curr_idx-10].mean()
            
            # 排除放量下跌
            bad_wash = vol_callback > vol_uptrend
            # 排除缩量反弹 (今日量 < 回调均量 * 1.2)
            weak_rebound = latest_vols < (vol_callback * 1.2)
            
            final_scores[bad_wash | weak_rebound] = -999
            
            # [2] 板块主线过滤
            s_ret_20d = sector_returns_20d.loc[date]
            s_ret_5d = (prices.iloc[curr_idx] / prices.iloc[curr_idx-5] - 1).T.groupby(ind_groups).mean()
            
            # 板块 20 日排名在前 40%
            top_40_rank = s_ret_20d.rank(pct=True) > 0.6
            # 板块 5 日大于 0
            pos_5d = s_ret_5d >= 0
            
            # 板块 3 日无放量大跌
            s_ret_3d = (prices.iloc[curr_idx] / prices.iloc[curr_idx-3] - 1).T.groupby(ind_groups).mean()
            s_vol_3d = volumes.iloc[curr_idx-3:curr_idx].T.groupby(ind_groups).mean().mean(axis=1) # 简化
            s_vol_ma20 = vol_ma20.iloc[curr_idx].T.groupby(ind_groups).mean()
            
            no_crash = ~((s_ret_3d < -0.03) & (s_vol_3d > s_vol_ma20))
            
            valid_sector = top_40_rank & pos_5d & no_crash
            final_scores[~ind_groups.map(valid_sector)] = -999

        # 选股与收益计算
        top_4 = final_scores.nlargest(4)
        if top_4.iloc[0] <= -500:
            port_rets.append(0.0)
        else:
            fwd_ret = (prices.iloc[curr_idx + 20] / latest_prices - 1).reindex(top_4.index).mean()
            port_rets.append(fwd_ret)
            
    # 计算指标
    port_rets = np.array(port_rets)
    bm_rets = (benchmark.shift(-20) / benchmark - 1).loc[target_dates].values
    excess = port_rets - bm_rets
    
    loss_series = pd.Series(excess < 0).astype(int)
    consecutive_losses = loss_series.groupby((loss_series != loss_series.shift()).cumsum()).cumsum().max()
    
    return {
        'WinRate': f"{np.mean(excess > 0):.2%}",
        'MaxDD': f"{ (pd.Series(port_rets).cumsum() - pd.Series(port_rets).cumsum().cummax()).min():.2%}",
        'MaxConsLoss': int(consecutive_losses),
        'MeanExcess': f"{np.mean(excess):.2%}"
    }

if __name__ == "__main__":
    print("🚀 开始三代选股逻辑回测对比 (Behavioral vs Structural)...")
    results = {}
    for m in ['base', 'defense', 'structural']:
        print(f"  正在回测模式: {m} ...")
        results[m] = run_experiment(m)
        
    df = pd.DataFrame(results).T
    print("\n" + "="*70)
    print("📊 选股逻辑进化报告: 从“形态”到“行为结构”")
    print("="*70)
    print(df)
    print("="*70)
