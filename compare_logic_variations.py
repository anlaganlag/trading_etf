
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
    benchmark = pd.read_csv(os.path.join(data_dir, "benchmark.csv"), index_col=0, parse_dates=True)
    if 'close' in benchmark.columns: benchmark = benchmark['close']
    else: benchmark = benchmark.iloc[:, 0]
    return prices.ffill(), benchmark

def run_experiment(mode='base'):
    """
    mode: 
    - 'base': 纯 AI 20维权重
    - 'resonance': AI + 板块收益 + 板块广度
    - 'full': resonance + 衰减检测 + 8%过滤
    """
    prices, benchmark = load_data()
    symbols = prices.columns
    
    # 建立模拟行业映射 (将股票按首字母分组作为模拟行业，实战中用真实行业)
    industries = {s: s.split('.')[-1][0] for s in symbols} # 按股票代码第一位分组
    ind_groups = pd.Series(industries)
    
    # 预计算特征
    returns_20d = prices.pct_change(20)
    ma20 = prices.rolling(20).mean()
    above_ma20 = (prices > ma20).astype(int)
    
    # 计算行业广度 (Breadth)
    sector_breadth = above_ma20.T.groupby(ind_groups).mean().T # (Dates, Industries)
    sector_breadth_ma5 = sector_breadth.rolling(5).mean()
    
    # 计算行业收益率
    sector_returns = prices.pct_change(20).T.groupby(ind_groups).mean().T

    # 回测变量
    port_rets = []
    target_dates = prices.index[40:-20] # 留出计算窗口
    
    for i in range(len(target_dates)):
        date = target_dates[i]
        curr_idx = prices.index.get_loc(date)
        
        # 1. AI 基础打分
        latest_prices = prices.iloc[curr_idx]
        ai_scores = pd.Series(0.0, index=symbols)
        for p, w in AI_WEIGHTS.items():
            ret_p = latest_prices / prices.iloc[curr_idx - p] - 1
            ranks = ret_p.rank(ascending=False)
            top_100_mask = ranks <= 100
            ai_scores[top_100_mask] += (101 - ranks[top_100_mask]) / 100.0 * w
            
        final_scores = ai_scores.copy()
        
        # 2. 逻辑加持
        if mode in ['resonance', 'full']:
            # 板块得分 = 0.5 * 收益分 + 0.5 * 广度分
            s_ret = sector_returns.loc[date]
            s_breadth = sector_breadth.loc[date]
            
            # 将板块分映射回个股
            stock_sector_ret = ind_groups.map(s_ret)
            stock_sector_breadth = ind_groups.map(s_breadth)
            
            # 如果板块不强（收益或广度在末尾 40%），个股分打折
            threshold_ret = s_ret.quantile(0.4)
            threshold_br = s_breadth.quantile(0.4)
            
            weak_mask = (stock_sector_ret < threshold_ret) | (stock_sector_breadth < threshold_br)
            final_scores[weak_mask] *= 0.5
            
        if mode == 'full':
            # 衰减检测：如果所属板块广度在下降 (昨日 > 今日 且 今日 < MA5)，禁止开仓
            s_breadth_prev = sector_breadth.iloc[curr_idx - 1]
            s_breadth_ma5 = sector_breadth_ma5.iloc[curr_idx]
            
            decay_sectors = (sector_breadth.loc[date] < s_breadth_prev) & (sector_breadth.loc[date] < s_breadth_ma5)
            decay_mask = ind_groups.map(decay_sectors)
            final_scores[decay_mask] = -999 # 禁买
            
            # 8% 追高过滤
            today_ret = latest_prices / prices.iloc[curr_idx - 1] - 1
            too_high_mask = today_ret > 0.08
            final_scores[too_high_mask] = -999

        # 选股
        top_4 = final_scores.nlargest(4)
        if top_4.iloc[0] <= -500: # 没得选了
            port_rets.append(0.0)
            continue
            
        # 计算 20 日后收益
        fwd_ret = (prices.iloc[curr_idx + 20] / latest_prices - 1).reindex(top_4.index).mean()
        port_rets.append(fwd_ret)
        
    # 计算指标
    port_rets = np.array(port_rets)
    bm_rets = (benchmark.shift(-20) / benchmark - 1).loc[target_dates].values
    
    excess = port_rets - bm_rets
    win_rate = np.mean(excess > 0)
    max_dd = (pd.Series(port_rets).cumsum() - pd.Series(port_rets).cumsum().cummax()).min()
    
    # 连续亏损天数
    loss_series = pd.Series(excess < 0).astype(int)
    consecutive_losses = loss_series.groupby((loss_series != loss_series.shift()).cumsum()).cumsum().max()

    return {
        'WinRate': win_rate,
        'MaxDD': max_dd,
        'MaxConsLoss': consecutive_losses,
        'MeanExcess': np.mean(excess)
    }

if __name__ == "__main__":
    print("🚀 开始三组方案回测对比...")
    results = {}
    for m in ['base', 'resonance', 'full']:
        print(f"  正在回测: {m} ...")
        results[m] = run_experiment(m)
        
    df = pd.DataFrame(results).T
    print("\n" + "="*60)
    print("📊 策略逻辑对比报告")
    print("="*60)
    print(df[['WinRate', 'MaxDD', 'MaxConsLoss', 'MeanExcess']])
    print("="*60)
