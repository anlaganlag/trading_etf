
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

def run_trading_system(start_date='2021-12-03'):
    prices, volumes, benchmark = load_data()
    symbols = prices.columns
    ind_groups = pd.Series({s: s.split('.')[-1][0] for s in symbols})
    
    # 预计算
    returns_20d = prices.pct_change(20)
    bm_returns_20d = benchmark.pct_change(20)
    vol_ma20 = volumes.rolling(20).mean()
    sector_returns_20d = returns_20d.T.groupby(ind_groups).mean().T

    # 过滤时间
    target_dates = prices.index[prices.index >= start_date]
    if len(target_dates) == 0:
        print("No dates found.")
        return

def run_trading_system(start_date='2021-12-03'):
    prices, volumes, benchmark = load_data()
    symbols = prices.columns
    ind_groups = pd.Series({s: s.split('.')[-1][0] for s in symbols})
    
    # 预计算
    returns_20d = prices.pct_change(20)
    bm_returns_20d = benchmark.pct_change(20)
    sector_returns_20d = returns_20d.T.groupby(ind_groups).mean().T

    # 过滤时间
    target_dates = prices.index[prices.index >= start_date]
    if len(target_dates) == 0:
        print("No dates found.")
        return

    # 初始化资金曲线
    portfolio_value = [100.0]  # 初始净值 100
    dates = []
    
    # 滚动持仓模拟 (Rolling Portfolio)
    # 假设每日建立一个 Tranche，持有 20 天
    # 总仓位 = 所有 Active Tranche 的平均值
    active_tranches = [] # list of dict: {'end_date': date, 'stocks': [sym], 'weight': w}
    
    # 成本模型：单边万分之三 (0.0003) + 印花税 (0.0005) -> 双边 ~0.001
    # 每日只对新开仓的部分计提成本
    
    for i in range(len(target_dates)-1):
        date = target_dates[i]
        next_date = target_dates[i+1]
        curr_idx = prices.index.get_loc(date)
        
        # --- 信号生成 (同前) ---
        market_bull = bm_returns_20d.iloc[curr_idx] > 0
        latest_prices = prices.iloc[curr_idx]
        latest_vols = volumes.iloc[curr_idx]
        
        # 1. AI Score
        ai_scores = pd.Series(0.0, index=symbols)
        for p, w in AI_WEIGHTS.items():
            prev_idx = curr_idx - p
            if prev_idx < 0: continue
            ret_p = (latest_prices / prices.iloc[prev_idx]) - 1
            ranks = ret_p.rank(ascending=False, method='min')
            top_100_mask = ranks <= 100
            ai_scores[top_100_mask] += (101 - ranks[top_100_mask]) / 100.0 * w
            
        # 2. Structural Filters
        vol_cb = volumes.iloc[curr_idx-5:curr_idx-2].mean()
        vol_ut = volumes.iloc[curr_idx-20:curr_idx-10].mean()
        bad_wash = (vol_cb > vol_ut) | (latest_vols < vol_cb * 1.2)
        s_ret_20d = sector_returns_20d.loc[date]
        s_rank_valid = s_ret_20d.rank(pct=True) > 0.6
        bad_sector = ~ind_groups.map(s_rank_valid)
        today_ret = (latest_prices / prices.iloc[curr_idx - 1]) - 1
        is_too_high = today_ret > 0.08
        fail_mask = bad_wash | bad_sector | is_too_high
        
        # 3. Adaptive Gate & Selection
        final_scores = ai_scores.copy()
        if market_bull: final_scores[fail_mask] *= 0.5
        else: final_scores[fail_mask] = -999.0
            
        top_4 = final_scores.nlargest(4)
        valid_count = (~fail_mask[top_4.index]).sum()
        
        # 4. 仓位 (Pro Plus)
        # 每个 Tranche 占总资金的 1/20 (因为持有 20 天)
        # 该 Tranche 的内部仓位由 Pro Plus 决定
        base_weight = valid_count / 4.0
        min_weight = 0.5 if market_bull else 0.0
        tranche_exposure = max(min_weight, base_weight)
        
        if top_4.iloc[0] <= 0: # 极端情况
             if min_weight == 0: tranche_exposure = 0.0

        # 创建新 Tranche
        new_tranche = {
            'start_idx': curr_idx, # 买入日 (今日收盘)
            'stocks': top_4.index.tolist(),
            'exposure': tranche_exposure,
            'days_held': 0
        }
        active_tranches.append(new_tranche)
        
        # --- 组合每日收益计算 ---
        # 组合今日收益 = sum(每个 Tranche 的今日收益) / Tranches 数量 (20)
        # 实际上我们用“全仓平均”模型：Portfolio Return = Mean(Active Tranches Return)
        
        daily_ret_sum = 0.0
        active_count = 0
        
        # 清理过期 Tranche (持有超过 20 天)
        active_tranches = [t for t in active_tranches if t['days_held'] < 20]
        
        for t in active_tranches:
            # Tranche 今日收益 = (Stocks Daily Mean) * Exposure
            # Stocks Daily Mean = (Next Close / Current Close - 1)
            # 使用向量化计算加速
            stock_rets = (prices.iloc[curr_idx+1][t['stocks']] / prices.iloc[curr_idx][t['stocks']] - 1).mean()
            tranche_ret = stock_rets * t['exposure']
            
            daily_ret_sum += tranche_ret
            t['days_held'] += 1
            active_count += 1
            
        # 组合平均日收益 (归一化到资金池，假设最大 20 个并发)
        # 实际上相当于把资金分成 20 份，每份跑一个 Tranche
        portfolio_daily_ret = daily_ret_sum / 20.0
        
        # 扣除新开仓成本 (仅针对新加入的那个 1/20 资金)
        # Cost = 0.001 * Tranche_Exposure * (1/20)
        daily_cost = 0.001 * tranche_exposure / 20.0
        
        net_daily_ret = portfolio_daily_ret - daily_cost
        
        new_nav = portfolio_value[-1] * (1 + net_daily_ret)
        portfolio_value.append(new_nav)
        dates.append(next_date)
        
    # 结果统计
    nav = pd.Series(portfolio_value[1:], index=dates)
    bm = benchmark.loc[dates]
    bm_nav = bm / bm.iloc[0] * 100.0
    
    total_ret = nav.iloc[-1] / 100.0 - 1
    annual_ret = (1 + total_ret) ** (252 / len(nav)) - 1
    max_dd = (nav - nav.cummax()).min() / nav.cummax().max()
    
    # 分年度统计
    yearly_perf = []
    years = nav.index.year.unique()
    for yr in years:
        yr_nav = nav[nav.index.year == yr]
        yr_bm = bm[bm.index.year == yr]
        
        # 计算该年收益
        prev_yr_end_nav = nav[nav.index.year < yr].iloc[-1] if any(nav.index.year < yr) else 100.0
        prev_yr_end_bm = bm[bm.index.year < yr].iloc[-1] if any(bm.index.year < yr) else bm.iloc[0]
        
        y_ret = yr_nav.iloc[-1] / prev_yr_end_nav - 1
        y_bm_ret = yr_bm.iloc[-1] / prev_yr_end_bm - 1
        yearly_perf.append({'Year': yr, 'Strategy': y_ret, 'Benchmark': y_bm_ret, 'Excess': y_ret - y_bm_ret})

    df_yearly = pd.DataFrame(yearly_perf).set_index('Year')

    print("\n" + "="*60)
    print(f"📊 Pro Plus 策略终极回测报告 (2021-12-03 ~ {dates[-1].strftime('%Y-%m-%d')})")
    print("="*60)
    print(f"最终净值 (Final NAV):      {nav.iloc[-1]:.2f}")
    print(f"区间收益 (Total Return):   {total_ret:.2%}")
    print(f"年化收益 (Annual Return):  {annual_ret:.2%}")
    print(f"最大回撤 (Max Drawdown):   {max_dd:.2%}")
    print("-" * 60)
    print("📅 分年度表现 (Yearly Performance):")
    print(df_yearly.to_string(formatters={'Strategy': '{:,.2%}'.format, 'Benchmark': '{:,.2%}'.format, 'Excess': '{:,.2%}'.format}))
    print("-" * 60)
    print(f"基准总收益 (Total Benchmark): {bm_nav.iloc[-1]/100.0 - 1:.2%}")
    print("="*60)

if __name__ == "__main__":
    run_trading_system()
