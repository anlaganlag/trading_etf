
"""
AI 优化全市场个股模型权重训练脚本 (Sparse Features)
目标：在确定性战胜创业板指的前提下，最大化回报率
"""
import os
import glob
import numpy as np
import pandas as pd
from scipy.optimize import differential_evolution
from datetime import datetime
from config import config

# === 1. 配置参数 ===
# 稀疏特征周期 (天)
PERIODS = [1, 2, 3, 5, 8, 13, 21] 
# PERIODS = [1, 3, 5, 10, 20] # 用户提到的稀疏
# 既然要覆盖20天，不如用斐波那契数列，更符合自然规律？
# 或者按照用户的 1, 2, 3, 5, 7, 10, 14, 20
PERIODS = [1, 2, 3, 5, 7, 10, 14, 20]

BENCHMARK = 'SZSE.159915'  # 创业板指
TRAIN_START = '2024-09-01'
TRAIN_END = '2026-02-07'
TOP_N = 4  # 每次选4只
HOLD_DAYS = 20  # 持有20天

CACHE_DIR = config.DATA_CACHE_DIR

def load_data():
    data_dir = os.path.join(config.BASE_DIR, "data_for_opt_stocks")
    prices_file = os.path.join(data_dir, "prices.csv")
    bench_file = os.path.join(data_dir, "benchmark.csv")
    
    print(f"Loading data from {data_dir}...")
    
    if not os.path.exists(prices_file) or not os.path.exists(bench_file):
        print("❌ No csv data found! Please run fetch_data_stocks.py first.")
        # Try fall back to pkl if user ran old script? No, let's just return None
        return None, None

    # Load Prices
    df = pd.read_csv(prices_file, index_col=0, parse_dates=True)
    
    # Load Benchmark
    # Benchmark was saved as Series but to_csv saves as DF with index and 0 column or name
    # We need to check structure
    try:
        ben_df = pd.read_csv(bench_file, index_col=0, parse_dates=True)
        # Assuming single column
        if ben_df.shape[1] >= 1:
            benchmark = ben_df.iloc[:, 0]
        else:
            benchmark = df.mean(axis=1) # Fallback
    except:
        benchmark = df.mean(axis=1) # Fallback
    
    # Filter dates
    df = df[df.index >= TRAIN_START]
    df = df[df.index <= TRAIN_END]
    
    benchmark = benchmark.reindex(df.index).fillna(method='ffill')
    
    print(f"Data Loaded: {df.shape} points")
    
    return df, benchmark

def objective_function(weights, returns_dict, benchmark_ret, period_len):
    """
    weights: 权重向量
    returns_dict: {period: return_dataframe}
    benchmark_ret: Series of benchmark returns
    """
    # 1. 计算加权得分
    # weights归一化不是必须的，因为排名只看相对值，但为了稳定可以做
    score = pd.DataFrame(0.0, index=benchmark_ret.index, columns=returns_dict[PERIODS[0]].columns)
    
    # 确保 weights 和 PERIODS 对齐
    for i, p in enumerate(PERIODS):
        # 排名: 1.0 (Best) -> 0.0 (Worst)
        # rank(ascending=False) => max return has rank 1
        # score += rank * weight
        # 为了速度，直接用 returns * weight 近似 ranking? 不，排名是核心
        # 向量化计算太慢，我们用 simplified correlation
        
        # 实际上 differential evolution 需要多次迭代，全量计算太慢
        # 我们采用抽样计算：随机抽取 50 天进行评估
        pass

    # 由于这是计算密集型，我们在脚本里写一个高效版本
    # 直接计算最终收益
    
    return 0

class StockWeightOptimizer:
    def __init__(self, df_prices, df_benchmark, periods, top_n=TOP_N, hold_days=HOLD_DAYS):
        self.periods = periods
        self.top_n = top_n
        self.hold_days = hold_days
        self.prepare_data(df_prices, df_benchmark)

    def prepare_data(self, df_prices, df_benchmark):
        print("Preparing features...")
        self.ranks = {}
        
        # Calculate Forward Returns (Target)
        # Shift -HOLD_DAYS means future return
        returns_fwd = df_prices.shift(-self.hold_days) / df_prices - 1
        
        # Benchmark Forward Returns
        ben_returns_fwd = df_benchmark.shift(-self.hold_days) / df_benchmark - 1
        
        # Calculate Ranks for each period
        for p in self.periods:
            # Ret_lag: Price / Price_shift(p) - 1
            ret_lag = df_prices / df_prices.shift(p) - 1
            
            # Percentile Rank across stocks (axis=1)
            # This is the most expensive part
            rank_lag = ret_lag.rank(axis=1, pct=True)
            rank_lag = rank_lag.fillna(0.5) # Neutral fill
            
            self.ranks[p] = rank_lag

        # Align all data to valid index
        # Valid index: where we have both lagged ranks (p=max) and future returns (hold_days)
        max_lookback = max(self.periods)
        
        # Start: max_lookback
        # End: -hold_days
        valid_idx = df_prices.index[max_lookback : -self.hold_days]
        
        # Intersect with returns_fwd index (drop nans)
        valid_idx = valid_idx.intersection(returns_fwd.dropna(how='all').index)
        
        print(f"Aligning to {len(valid_idx)} valid dates...")
        
        self.valid_dates = valid_idx
        self.y_true = returns_fwd.reindex(valid_idx).values
        self.y_ben = ben_returns_fwd.reindex(valid_idx).values
        
        # Convert ranks to numpy 3D array for speed: (Dates, Stocks, Periods)
        # or dictionary of 2D arrays
        self.rank_matrices = []
        for p in self.periods:
            self.rank_matrices.append(self.ranks[p].reindex(valid_idx).values)
            
        self.rank_tensor = np.stack(self.rank_matrices, axis=2) # Shape: (Dates, Stocks, n_periods)
        print(f"Feature Tensor Shape: {self.rank_tensor.shape}")

    def __call__(self, weights):
        """
        Objective Function called by optimizer
        weights: 1D array of len(periods)
        """
        # 1. Calculate weighted score: (Dates, Stocks)
        # sum(Ranks * Weights, axis=2)
        # weights shape: (n_periods,)
        # score shape: (Dates, Stocks)
        
        score = np.dot(self.rank_tensor, weights)
        
        # 2. Select Top N
        # We want indices of largest scores.
        # Use argpartition on -score
        n_samples = score.shape[0]
        
        # Find indices of top N
        # We only care about the sum of returns of these indices
        
        # partition by score (ascending), take last N
        # argpartition puts smallest k elements first.
        # we want largest N, so we partition (n_stocks - N)
        # or use -score and take first N
        
        k = self.top_n
        top_idx = np.argpartition(-score, k, axis=1)[:, :k]
        
        # 3. Calculate Returns
        # Gather returns at top_idx
        # rows: (n_samples, 1)
        rows = np.arange(n_samples)[:, None]
        selected_rets = self.y_true[rows, top_idx] # (Dates, TopN)
        
        daily_avg_ret = np.mean(selected_rets, axis=1) # (Dates,)
        
        # 4. Metrics
        # Win Rate vs Benchmark
        excess = daily_avg_ret - self.y_ben
        win_rate = np.mean(excess > 0)
        
        mean_ret = np.mean(daily_avg_ret) # per hold period (20 days) return
        
        # 5. Objective: Maximize Return, conditional on WinRate
        # If WinRate < 0.55, heavy penalty
        penalty = 0.0
        if win_rate < 0.55:
            penalty = (0.55 - win_rate) * 5.0 # Scale up penalty
            
        # Also penalty for negative return
        if mean_ret < 0:
            penalty += -mean_ret * 2.0
            
        # Maximize: mean_ret - penalty
        # Minimizer expects negative
        return -(mean_ret - penalty)

def run_optimization(df_prices, df_benchmark):
    optimizer = StockWeightOptimizer(df_prices, df_benchmark, PERIODS)
    
    # Differential Evolution
    bounds = [(-1.0, 1.0)] * len(PERIODS)
    
    print("🚀 Optimizing weights (Multiprocessing enabled)...")
    
    # Using workers=-1 for parallel
    # Note: Class instance must be picklable. Since it contains large arrays, pickling might be slow.
    # But for differential_evolution, func is pickled once per worker.
    
    result = differential_evolution(
        optimizer,
        bounds,
        maxiter=15, # Faster convergence
        popsize=5,
        workers=1, # Single Process for stability
        seed=42,
        disp=True # Show progress
    )

    best_w = result.x
    
    print("\n✅ Optimization Complete!")
    print(f"Message: {result.message}")
    
    # Validate final
    final_loss = optimizer(best_w)
    
    # Calculate nice metrics for display
    # We need to run logic inside __call__ again basically
    # Or just interpret result
    
    print("-" * 40)
    print(f"  {'Period':<6} | {'Weight':<8}")
    print("-" * 40)
    for i, p in enumerate(PERIODS):
        print(f"  Day {p:<2} | {best_w[i]:>8.4f}")
    print("-" * 40)
    print(f"Final Score: {-final_loss:.4f}")
    
    return best_w

if __name__ == "__main__":
    try:
        # Enable multiprocessing support on Windows
        import multiprocessing
        multiprocessing.freeze_support()
        
        df, ben = load_data()
        if df is not None and not df.empty:
            weights = run_optimization(df, ben)
            
            print("\nSuggesting implementation code:")
            w_str = ", ".join([f"{w:.3f}" for w in weights])
            print(f"PERIODS = {PERIODS}")
            print(f"WEIGHTS = [{w_str}]")
        else:
            print("Failed to load data.")
    except Exception as e:
        import traceback
        traceback.print_exc()
