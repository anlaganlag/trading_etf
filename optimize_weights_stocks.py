
import os
import pandas as pd
import numpy as np
from scipy.optimize import differential_evolution

# Load Data
data_dir = "data_for_opt_stocks"
try:
    prices = pd.read_csv(os.path.join(data_dir, "prices.csv"), index_col=0, parse_dates=True)
    benchmark = pd.read_csv(os.path.join(data_dir, "benchmark.csv"), index_col=0, parse_dates=True)
except FileNotFoundError:
    print("Data not found. Please run fetch_data_stocks.py first.")
    exit(1)

# Ensure numeric
prices = prices.apply(pd.to_numeric, errors='coerce')
if isinstance(benchmark, pd.DataFrame):
     if 'close' in benchmark.columns:
         benchmark = benchmark['close']
     else:
         benchmark = benchmark.iloc[:, 0]
benchmark = pd.to_numeric(benchmark, errors='coerce')

print(f"Data Loaded. Prices: {prices.shape}, Benchmark: {benchmark.shape}")

# Calculate Features based on Top 100 Logic
periods = list(range(1, 21))
feature_matrices = {} 

print("Calculating Top 100 features...")
for p in periods:
    # 1. Calculate p-day return
    rets = prices.pct_change(p)
    
    # 2. For each day, keep only Top 100 values, set others to 0 or NaN
    # We want a score: 
    # Rank 1 = 1.0
    # Rank 100 = ~0.01
    # Rank > 100 = 0.0
    
    # Use rank(ascending=False). Rank 1 is highest return.
    ranks = rets.rank(axis=1, ascending=False, method='min')
    
    # Create mask for Top 100
    top_100_mask = ranks <= 100
    
    # Create feature score: 
    # Linear decay: Score = (101 - Rank) / 100.  (Rank 1 -> 1.0, Rank 100 -> 0.01)
    # Others -> 0
    scores = (101 - ranks).clip(lower=0) / 100.0
    
    # Apply mask strictly (though clip handles it, explicit mask is safer for NaNs)
    scores[~top_100_mask] = 0.0
    
    feature_matrices[p] = scores

# Calculate Forward Targets (20-day return)
forward_p = 20
future_rets = prices.shift(-forward_p) / prices - 1
future_bm_rets = benchmark.shift(-forward_p) / benchmark - 1

# Align Data
start_date = '2024-09-01'
valid_mask = (prices.index >= start_date) & (future_rets.iloc[:, 0].notna())

target_dates = prices.index[valid_mask]
print(f"Training on {len(target_dates)} dates from {target_dates[0].date()} to {target_dates[-1].date()}")

# Shapes
Y_port = future_rets.loc[target_dates].values
Y_bm = future_bm_rets.loc[target_dates].values
# Fill NaN in returns 
Y_port = np.nan_to_num(Y_port, nan=-0.01) # Assume 0 or slight loss if missing price, but filled in pivot

X_features = np.array([feature_matrices[p].loc[target_dates].values for p in periods])
X_features = np.nan_to_num(X_features, nan=0.0)

WIN_RATE_THRESHOLD = 0.55 # Slightly lower threshold for stocks as volatility is higher
TOP_K_SELECTION = 4 # Portfolio Size

def objective(weights):
    # weights: (20,)
    
    # 1. Total Score
    # weighted sum of features
    # Feature is (101-Rank)/100 if in Top 100, else 0.
    final_scores = np.tensordot(weights, X_features, axes=([0], [0])) # (D, S)
    
    # 2. Select Top K stocks based on Final Score
    # We only care about stocks that have NON-ZERO score? 
    # The optimization might find negative weights.
    # If weights are negative, we might select stock with LOW feature score?
    # No, we always select LARGEST final_score.
    
    # Use argpartition to find indices of Top K
    n_days = final_scores.shape[0]
    top_k_indices = np.argpartition(-final_scores, TOP_K_SELECTION-1, axis=1)[:, :TOP_K_SELECTION]
    
    row_indices = np.arange(n_days)[:, None]
    selected_rets = Y_port[row_indices, top_k_indices]
    
    port_daily_ret = np.mean(selected_rets, axis=1)
    
    # Metrics
    mean_ret = np.mean(port_daily_ret)
    win_rate = np.mean(port_daily_ret > Y_bm)
    
    # Loss
    penalty = 0
    if win_rate < WIN_RATE_THRESHOLD:
        penalty = (WIN_RATE_THRESHOLD - win_rate) * 10.0
        
    return -mean_ret + penalty

def evaluate(weights):
    final_scores = np.tensordot(weights, X_features, axes=([0], [0]))
    top_k_indices = np.argpartition(-final_scores, TOP_K_SELECTION-1, axis=1)[:, :TOP_K_SELECTION]
    row_indices = np.arange(final_scores.shape[0])[:, None]
    selected_rets = Y_port[row_indices, top_k_indices]
    port_daily_ret = np.mean(selected_rets, axis=1)
    
    win_rate = np.mean(port_daily_ret > Y_bm)
    mean_ret = np.mean(port_daily_ret)
    
    # Cumulative
    cum_ret = np.prod(1 + port_daily_ret) - 1
    cum_bm = np.prod(1 + Y_bm) - 1
    
    return {
        "win_rate": win_rate,
        "mean_20d": mean_ret,
        "cum_ret": cum_ret,
        "cum_bm": cum_bm
    }

print("Starting Optimization...")
# Bounds: -1 to 1 
bounds = [(-1, 1) for _ in range(20)]

result = differential_evolution(objective, bounds, seed=42, maxiter=20, popsize=6, workers=1)

best_weights = result.x
best_weights = best_weights / np.sum(np.abs(best_weights))

metrics = evaluate(best_weights)
print("Optimization Complete.")
print(f"Optimal Weights: {np.round(best_weights, 3)}")
print(f"Win Rate: {metrics['win_rate']:.2%}")
print(f"Mean 20d Return: {metrics['mean_20d']:.2%}")
print(f"Benchmark Mean 20d: {np.mean(Y_bm):.2%}")

with open("optimization_report_stocks.txt", "w") as f:
    f.write("Stock Optimization Report\n")
    f.write(f"Weights: {list(np.round(best_weights, 4))}\n")
    f.write(f"Win Rate: {metrics['win_rate']:.4f}\n")
    f.write(f"Mean Return: {metrics['mean_20d']:.4f}\n")
