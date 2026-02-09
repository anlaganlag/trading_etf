
import os
import pandas as pd
import numpy as np
from gm.api import *
from config import config

# AI 最优权重 (20维)
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

def run_trading_system(mode='hard'):
    """
    mode: 
    - 'hard': 原始硬过滤 (w=0)
    - 'soft': 软闸门限流 (w=0.5)
    - 'adaptive': 看天吃饭 (Bull -> Soft, Bear -> Hard)
    - 'pro': adaptive + 信号密度仓位控制
    """
    prices, volumes, benchmark = load_data()
    symbols = prices.columns
    ind_groups = pd.Series({s: s.split('.')[-1][0] for s in symbols})
    
    # 预计算
    returns_20d = prices.pct_change(20)
    bm_returns_20d = benchmark.pct_change(20)
    vol_ma20 = volumes.rolling(20).mean()
    above_ma20 = (prices > prices.rolling(20).mean()).astype(int)
    sector_breadth = above_ma20.T.groupby(ind_groups).mean().T
    sector_returns_20d = returns_20d.T.groupby(ind_groups).mean().T

    trade_returns = []
    daily_results = []
    target_dates = prices.index[40:-20]
    
    for i in range(len(target_dates)):
        date = target_dates[i]
        curr_idx = prices.index.get_loc(date)
        
        # 0. 路况感知: 大盘 20 日动量
        market_bull = bm_returns_20d.iloc[curr_idx] > 0
        
        # 1. AI Base Score
        latest_prices = prices.iloc[curr_idx]
        latest_vols = volumes.iloc[curr_idx]
        ai_scores = pd.Series(0.0, index=symbols)
        for p, w in AI_WEIGHTS.items():
            ret_p = (latest_prices / prices.iloc[curr_idx - p]) - 1
            ranks = ret_p.rank(ascending=False, method='min')
            top_100_mask = ranks <= 100
            ai_scores[top_100_mask] += (101 - ranks[top_100_mask]) / 100.0 * w
            
        # 2. 结构特征筛查 (Structural Check)
        # 量价结构
        vol_cb = volumes.iloc[curr_idx-5:curr_idx-2].mean() # 回调
        vol_ut = volumes.iloc[curr_idx-20:curr_idx-10].mean() # 上涨
        bad_wash = (vol_cb > vol_ut) | (latest_vols < vol_cb * 1.2)
        # 板块规则
        s_ret_20d = sector_returns_20d.loc[date]
        s_rank_valid = s_ret_20d.rank(pct=True) > 0.6
        bad_sector = ~ind_groups.map(s_rank_valid)
        # 追高过滤
        today_ret = (latest_prices / prices.iloc[curr_idx - 1]) - 1
        is_too_high = today_ret > 0.08
        
        # 综合判定“违规标的”
        fail_mask = bad_wash | bad_sector | is_too_high
        
        # 3. 不同的决策“闸门”
        final_scores = ai_scores.copy()
        
        current_gate = mode
        if mode in ['adaptive', 'pro', 'pro_plus']:
            current_gate = 'soft' if market_bull else 'hard'
            
        if current_gate == 'hard':
            final_scores[fail_mask] = -999 # 直接剔除
        elif current_gate == 'soft':
            final_scores[fail_mask] *= 0.5 # 限流分
            
        # 4. 选股与信号密度检测
        top_4 = final_scores.nlargest(4)
        # 统计“合格”（非违规）的标的数量
        valid_candidates_count = (~fail_mask[top_4.index]).sum()
        
        # 如果连 AI 分数都为 0，说明行情极差
        if top_4.iloc[0] <= 0:
            daily_results.append({'date': date, 'ret': 0.0, 'weight': 0.0})
            continue

        # 5. 限速器: 信号密度仓位控制
        pos_weight = 1.0 # 默认全仓
        
        if mode in ['pro', 'pro_plus', 'pro_dynamic']:
            # 基础仓位 = 合格票数 / 4
            base_weight = valid_candidates_count / 4.0
            
            # 牛市最低仓位约束
            min_weight = 0.0
            if mode == 'pro_plus' and market_bull:
                min_weight = 0.5
            elif mode == 'pro_dynamic':
                # Pro Dynamic: 随趋势强度连续变化的最低仓位
                # trend_strength = 20日大盘涨幅
                # 设定:涨幅 5% -> min_weight 0.5; 涨幅 8% -> min_weight 0.8 (封顶)
                trend_strength = bm_returns_20d.iloc[curr_idx]
                if trend_strength > 0:
                    min_weight = min(0.8, trend_strength * 10.0)
                else:
                    min_weight = 0.0
                
            pos_weight = max(min_weight, base_weight)
            
            # 极端情况保护: 如果所有票都被硬过滤剔除且不是强制仓位，则空仓
            if valid_candidates_count == 0 and min_weight == 0:
                pos_weight = 0.0

        # 计算收益 (20日后)
        fwd_ret = (prices.iloc[curr_idx + 20] / latest_prices - 1).reindex(top_4.index).mean()
        
        # 这里的收益需要乘以仓位权重
        actual_ret = fwd_ret * pos_weight
        daily_results.append({'date': date, 'ret': actual_ret, 'weight': pos_weight})

    # 指标计算
    df = pd.DataFrame(daily_results).set_index('date')
    bm_rets = (benchmark.shift(-20) / benchmark - 1).loc[target_dates]
    df['excess'] = df['ret'] - bm_rets
    
    win_rate = np.mean(df['excess'] > 0)
    max_dd = (df['ret'].cumsum() - df['ret'].cumsum().cummax()).min()
    
    # 2025年表现
    perf_2025 = df[df.index.year == 2025]['excess'].mean()
    
    # 获利因子
    gain = df[df['ret'] > 0]['ret'].sum()
    loss = abs(df[df['ret'] < 0]['ret'].sum())
    pf = gain / loss if loss != 0 else 0

    return {
        'WinRate': f"{win_rate:.2%}",
        'MaxDD': f"{max_dd:.2%}",
        'PF': f"{pf:.2f}",
        'Alpha_2025': f"{perf_2025:.4%}",
        'Avg_Weight': f"{df['weight'].mean():.2%}"
    }

if __name__ == "__main__":
    print("🚦 交易系统进化回测中: Pro -> Pro Plus -> Pro Dynamic ...")
    systems = ['pro', 'pro_plus', 'pro_dynamic']
    results = {}
    for s in systems:
        print(f"  测试方案: {s} ...")
        results[s] = run_trading_system(s)
        
    df_res = pd.DataFrame(results).T
    print("\n" + "="*85)
    print("📈 交易系统动态进化评估报告")
    print("="*85)
    print(df_res)
    print("="*85)
    print("💡 结论指引：")
    print("1. Pro Dynamic 是否在保留 Pro Plus Alpha 修复的同时，改善了 MaxDD？")
    print("2. 关注 Avg_Weight 是否比 Pro Plus 更合理（不盲目半仓）。")
