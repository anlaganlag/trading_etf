
import os
import pandas as pd
import numpy as np
from scipy.optimize import differential_evolution
from config import config

# --- 配置 ---
DATA_DIR = os.path.join(config.BASE_DIR, "data_for_opt_stocks")
PRICES_FILE = os.path.join(DATA_DIR, "prices.csv")
BENCH_FILE = os.path.join(DATA_DIR, "benchmark.csv")

PERIODS = [1, 2, 3, 5, 7, 10, 14, 20]
HOLD_DAYS = 3  # 根据之前验证，3天是动量策略的甜点位
TOP_N = 4

class TradableOptimizer:
    def __init__(self):
        print("Loading data...")
        self.df_prices = pd.read_csv(PRICES_FILE, index_col=0, parse_dates=True)
        self.df_bench = pd.read_csv(BENCH_FILE, index_col=0, parse_dates=True).iloc[:, 0]
        
        # 统一日期
        common_idx = self.df_prices.index.intersection(self.df_bench.index)
        self.df_prices = self.df_prices.loc[common_idx]
        self.df_bench = self.df_bench.loc[common_idx]
        
        self.prepare_features()

    def prepare_features(self):
        print("Preparing features...")
        # 1. 每日收益率 (用于过滤涨停)
        self.daily_rets = self.df_prices.pct_change().fillna(0.0).values
        
        # 2. 预测目标：未来3天累计收益
        # 我们用未来的 (Price_t+3 / Price_t) - 1
        self.target_rets = (self.df_prices.shift(-HOLD_DAYS) / self.df_prices - 1).values
        # 基准未来收益
        self.bench_target = (self.df_bench.shift(-HOLD_DAYS) / self.df_bench - 1).values
        
        # 3. 维度特征 (Ranks)
        self.rank_matrices = []
        for p in PERIODS:
            ret = self.df_prices / self.df_prices.shift(p) - 1
            r = ret.rank(axis=1, pct=True).fillna(0.5).values
            self.rank_matrices.append(r)
        
        self.rank_tensor = np.stack(self.rank_matrices, axis=2) # Shape: (T, Stocks, n_periods)
        
        # 移除含有 NaN 的行（因为 shift 产生的）
        # 我们只需要有效的选股日
        self.valid_mask = ~np.isnan(self.target_rets).any(axis=1) & ~np.isnan(self.bench_target)
        self.valid_indices = np.where(self.valid_mask)[0]
        # 排除掉 PERIODS 最大值之前的行，因为特征会是 NaN
        self.valid_indices = [i for i in self.valid_indices if i > max(PERIODS)]
        
        print(f"Ready. Valid days for optimization: {len(self.valid_indices)}")

    def __call__(self, weights):
        # 归一化权重 (可选，如果不归一化，DE会自己处理量级)
        # weights shape: (8,)
        
        # 计算每一天、每一只股票的得分
        # Scores shape: (T, Stocks)
        scores = np.tensordot(self.rank_tensor, weights, axes=(2, 0))
        
        # === 可买入约束 ===
        # 如果当日涨幅 > 9.5%，分数设为极小值，不可被选中
        scores[self.daily_rets > 0.095] = -1e9
        
        total_excess = 0
        count = 0
        
        # 为了速度，我们采样 1/2 的日子进行优化，或者全部跑
        # 向量化计算平均收益
        for i in self.valid_indices:
            s_row = scores[i]
            # 选出 Top N
            # 使用 argpartition 提速
            top_idx = np.argpartition(-s_row, TOP_N)[:TOP_N]
            
            # 这里的 target_rets[i] 已经是未来3天的收益
            port_ret = np.mean(self.target_rets[i, top_idx])
            bench_ret = self.bench_target[i]
            
            total_excess += (port_ret - bench_ret)
            count += 1
            
        avg_excess = total_excess / count if count > 0 else -1e9
        # 我们希望最大化平均超额收益 (minimize -avg_excess)
        return -avg_excess

def run():
    opt = TradableOptimizer()
    bounds = [(-1.0, 1.0)] * len(PERIODS)
    
    print("Starting Differential Evolution Optimization (Tradable Only)...")
    result = differential_evolution(
        opt, 
        bounds, 
        popsize=10, 
        maxiter=15, 
        disp=True, 
        workers=1, # 避免 pickle 复杂对象
        seed=42
    )
    
    # 结果解读
    best_w = result.x
    print("\n" + "="*50)
    print("🏆 Best Tradable Weights Found:")
    for p, w in zip(PERIODS, best_w):
        print(f"  Day {p:2d}: {w:+.4f}")
    print(f"\nFinal Objective (Avg 3-Day Excess): {-result.fun:.4%}")
    print("="*50)

if __name__ == "__main__":
    run()
