
import os
import pandas as pd
import numpy as np
import sys
from datetime import datetime

# 模拟 GM 环境
class Context:
    def __init__(self, prices, benchmark, whitelist):
        self.prices_df = prices
        self.benchmark_df = benchmark
        self.whitelist = whitelist
        self.theme_map = {s: 'Default' for s in whitelist}
        self.risk_scaler = 1.0 # 默认

class Tranche:
    def __init__(self):
        self.holdings = {} # {symbol: weight}

# 加载生产代码
from core.signal import get_ranking, get_market_regime
from core.logic import calculate_target_holdings, calculate_position_scale

def load_data():
    data_dir = "data_for_opt_stocks"
    prices = pd.read_csv(os.path.join(data_dir, "prices.csv"), index_col=0, parse_dates=True)
    benchmark = pd.read_csv(os.path.join(data_dir, "benchmark.csv"), index_col=0, parse_dates=True)
    if 'close' in benchmark.columns: benchmark = benchmark['close']
    else: benchmark = benchmark.iloc[:, 0]
    return prices.ffill(), benchmark

def run_integrated_backtest(start_date='2021-12-03'):
    prices, benchmark = load_data()
    whitelist = prices.columns.tolist()
    context = Context(prices, benchmark, whitelist)
    
    target_dates = prices.index[prices.index >= start_date]
    portfolio_value = [100.0]
    dates = []
    
    active_tranches = [Tranche() for _ in range(20)]
    idx_in_tranches = 0
    
    # 成本模型：减半到单边万分之五 (0.0005) 以体现降摩擦后的预期
    # 虽然实际滑点还在，但 Smart Retention 会减少交易频次
    
    for i in range(len(target_dates)-1):
        date = target_dates[i]
        next_date = target_dates[i+1]
        
        # 1. 获取当前轮动的 Tranche
        current_tranche = active_tranches[i % 20]
        
        # 2. 计算目标持仓 (Logic)
        target_weights = calculate_target_holdings(context, date, current_tranche, prices.loc[date].to_dict())
        
        # 3. 计算仓位缩放 (Scale)
        # 注意：calculate_position_scale 依赖 calculate_target_holdings 存入的 last_rank_info
        pos_scale, _, _ = calculate_position_scale(context, date)
        
        # 4. 模拟交易并计算成本
        # 统计变动标的
        old_set = set(current_tranche.holdings.keys())
        new_set = set(target_weights.keys())
        # 只有真正改变的标的才计费
        trades_count = len(new_set - old_set) + len(old_set - new_set)
        
        # 更新持仓
        current_tranche.holdings = target_weights
        current_tranche.scale = pos_scale
        
        # --- 组合每日收益 ---
        daily_ret_sum = 0.0
        for t in active_tranches:
            if not hasattr(t, 'holdings') or not t.holdings: continue
            
            # 计算该 Tranche 内部各标的平均收益
            # 权重处理 (Champion 3:1:1:1 or Equal)
            total_w = sum(t.holdings.values())
            t_ret = 0.0
            for s, w in t.holdings.items():
                s_ret = (prices.loc[next_date, s] / prices.loc[date, s]) - 1
                t_ret += s_ret * (w / total_w)
            
            daily_ret_sum += t_ret * t.scale
            
        # 费用：精准成本 (万分之11 = 0.0011)
        # 变动一个标位 (换仓) 产生的双边摩擦估算
        daily_cost = (trades_count / 4.0) * 0.0011 / 20.0 
        
        port_daily_ret = (daily_ret_sum / 20.0) - daily_cost
        
        new_nav = portfolio_value[-1] * (1 + port_daily_ret)
        portfolio_value.append(new_nav)
        dates.append(next_date)
        
    nav = pd.Series(portfolio_value[1:], index=dates)
    bm = benchmark.loc[dates]
    bm_nav = bm / bm.iloc[0] * 100.0
    
    print("\n" + "="*60)
    print(f"🚀 Release Alpha (释放 Alpha) 整合系统回测报告")
    print("="*60)
    print(f"最终净值 (Final NAV):      {nav.iloc[-1]:.2f}")
    print(f"区间收益 (Total Return):   {nav.iloc[-1]/100.0 - 1:.2%}")
    print(f"最大回撤 (Max Drawdown):   {(nav - nav.cummax()).min() / nav.cummax().max():.2%}")
    print("-" * 60)
    
    # 年度对比
    yearly = []
    for yr in nav.index.year.unique():
        y_nav = nav[nav.index.year == yr]
        y_bm = bm[bm.index.year == yr]
        prev_nav = nav[nav.index.year < yr].iloc[-1] if any(nav.index.year < yr) else 100.0
        prev_bm = bm[bm.index.year < yr].iloc[-1] if any(bm.index.year < yr) else bm.iloc[0]
        y_ret = y_nav.iloc[-1] / prev_nav - 1
        y_bm_ret = y_bm.iloc[-1] / prev_bm - 1
        yearly.append({'Year': yr, 'ReleaseAlpha': y_ret, 'Bench': y_bm_ret, 'Alpha': y_ret - y_bm_ret})
    
    print(pd.DataFrame(yearly).set_index('Year').to_string(formatters={'ReleaseAlpha': '{:,.2%}'.format, 'Bench': '{:,.2%}'.format, 'Alpha': '{:,.2%}'.format}))
    print("="*60)

if __name__ == "__main__":
    run_integrated_backtest()
