
import os
import pandas as pd
import numpy as np
from scipy.optimize import differential_evolution
from datetime import datetime


# Load Data
data_dir = "data_for_opt"
prices = pd.read_csv(os.path.join(data_dir, "prices.csv"), index_col=0, parse_dates=True)
benchmark = pd.read_csv(os.path.join(data_dir, "benchmark.csv"), index_col=0, parse_dates=True)

# Ensure numeric (sometimes 'null' strings or headers can cause object type)
prices = prices.apply(pd.to_numeric, errors='coerce')
if isinstance(benchmark, pd.DataFrame):
     # If it's a DF, take the first column if multiple, or 'close'
     if 'close' in benchmark.columns:
         benchmark = benchmark['close']
     else:
         benchmark = benchmark.iloc[:, 0]
benchmark = pd.to_numeric(benchmark, errors='coerce')

print(f"Data Loaded. Prices: {prices.shape}, Benchmark: {benchmark.shape}")

# Calculate Returns for periods 1..20
periods = list(range(1, 21)) # 1 to 20
feature_matrices = {} # Key: period, Value: DataFrame of ranks
returns_matrices = {} # Key: period, Value: DataFrame of returns

print("Calculating features...")
for p in periods:
    # Calculate p-day return: (Pt / Pt-p) - 1
    # Note: Optimization looks at PAST returns to predict FUTURE.
    # So at day t, we know return from t-p to t.
    rets = prices.pct_change(p)
    returns_matrices[p] = rets
    
    # Calculate Ranks (0 to 1)
    # Higher return -> Higher rank (1.0 is best)
    ranks = rets.rank(axis=1, pct=True, ascending=True)
    feature_matrices[p] = ranks

# Calculate Forward Targets (20-day return)
# Target at day t is return from t to t+20 (approx 20 trading days)
# We use Shift(-20) to get future value aligned with current row
forward_p = 20
future_rets = prices.shift(-forward_p) / prices - 1
future_bm_rets = benchmark.shift(-forward_p) / benchmark - 1

# Align all data
# Start Date: 2024-09-01
# End Date: valid until we have future returns (end - 20 days)
start_date = '2024-09-01'
valid_mask = (prices.index >= start_date) & (future_rets.iloc[:, 0].notna())

target_dates = prices.index[valid_mask]
print(f"Training on {len(target_dates)} dates from {target_dates[0].date()} to {target_dates[-1].date()}")

# Prepare Numpy arrays for speed
# Shape: (Dates, Stocks)
Y_port = future_rets.loc[target_dates].values
Y_bm = future_bm_rets.loc[target_dates].values

# Shape: (Period, Dates, Stocks)
X_features = np.array([feature_matrices[p].loc[target_dates].values for p in periods])
# Check for NaNs (fill with 0.5 - median rank)
X_features = np.nan_to_num(X_features, nan=0.5)

# Constraint thresholds
WIN_RATE_THRESHOLD = 0.60 # Ensure > 60% win rate vs index
TOP_K = 4

def objective(weights):
    # weights: shape (20,)
    
    # 1. Calculate Score: sum(w * rank)
    # X_features: (20, D, S)
    # Weights: (20, 1, 1) broadcast
    weighted_scores = np.tensordot(weights, X_features, axes=([0], [0])) # Shape: (D, S)
    
    # 2. Select Top K
    # We want indices of top K scores for each day
    # argsort gives ascending, so take last K
    # efficient way: argpartition
    # Note: we need returns of selected stocks
    
    # Simple Loop for readability/logic (vectorized is harder with TopK selection)
    # But loop is slow for optimization.
    # Vectorized TopK:
    # Use -score for smallest K partition (top K largest)
    
    n_days, n_stocks = weighted_scores.shape
    
    # Partition to find top K indices
    # We want indices where score is in top K
    # Using argpartition on -scores
    top_k_indices = np.argpartition(-weighted_scores, TOP_K-1, axis=1)[:, :TOP_K]
    
    # Gather returns
    # Y_port: (D, S)
    # We need to select specific columns for each row
    # row_indices: [[0, 0, 0, 0], [1, 1, 1, 1], ...]
    row_indices = np.arange(n_days)[:, None]
    
    selected_returns = Y_port[row_indices, top_k_indices] # Shape: (D, K)
    
    # Portfolio return per day
    port_rets = np.mean(selected_returns, axis=1) # Shape: (D,)
    
    # Calculate Metrics
    excess_rets = port_rets - Y_bm
    mean_excess = np.mean(excess_rets)
    mean_port_ret = np.mean(port_rets)
    
    win_rate = np.mean(port_rets > Y_bm)
    
    # Loss Function
    # We want to Maximize Mean Return subject to Win Rate constraint
    # Minimize: -MeanReturn + Penalty
    
    penalty = 0
    if win_rate < WIN_RATE_THRESHOLD:
        penalty += (WIN_RATE_THRESHOLD - win_rate) * 10.0 # Heavy penalty
    
    # Normalize return to roughly similar scale
    loss = -mean_port_ret + penalty
    
    return loss

def evaluate_final(weights):
    weighted_scores = np.tensordot(weights, X_features, axes=([0], [0]))
    top_k_indices = np.argpartition(-weighted_scores, TOP_K-1, axis=1)[:, :TOP_K]
    row_indices = np.arange(weighted_scores.shape[0])[:, None]
    selected_returns = Y_port[row_indices, top_k_indices]
    port_rets = np.mean(selected_returns, axis=1)
    
    win_rate = np.mean(port_rets > Y_bm)
    mean_ret = np.mean(port_rets)
    total_ret = np.prod(1 + port_rets) - 1
    bm_total = np.prod(1 + Y_bm) - 1
    
    return {
        "win_rate": win_rate,
        "mean_20d_ret": mean_ret,
        "total_period_return": total_ret,
        "benchmark_return": bm_total,
        "excess_return": total_ret - bm_total
    }


print("Starting Optimization (Differential Evolution) with bounds [-1, 1]...")
# Bounds: -1 to 1 for each weight
bounds = [(-1, 1) for _ in range(20)]

# Run DE
result = differential_evolution(objective, bounds, seed=42, maxiter=50, popsize=10, workers=1)

best_weights = result.x
# Normalize by sum of absolute values to keep scale meaningful
best_weights = best_weights / np.sum(np.abs(best_weights)) 

print("\nOptimization Complete.")
print(f"Optimal Weights: {np.round(best_weights, 3)}")

metrics = evaluate_final(best_weights)
print("\nIn-Sample Performance (2024-09-01 to Present):")
print(f"Win Rate (>Index): {metrics['win_rate']:.2%}")
print(f"Avg 20-Day Return: {metrics['mean_20d_ret']:.2%}")
bm_mean = np.mean(Y_bm)
print(f"Benchmark Avg 20-Day Return: {bm_mean:.2%}")
print(f"Excess Return per 20-Day: {metrics['mean_20d_ret'] - bm_mean:.2%}")

# Save results to file
with open("optimization_report.txt", "w") as f:
    f.write("Optimization Report (Negative Weights Allowed)\n")
    f.write("==============================================\n")
    f.write(f"Weights (Day 1 to 20):\n")
    for i, w in enumerate(best_weights):
        f.write(f"Day {i+1}: {w:.4f}\n")
    f.write("\nMetrics:\n")
    f.write(f"Win Rate: {metrics['win_rate']:.4f}\n")
    f.write(f"Mean Portfolio 20d Return: {metrics['mean_20d_ret']:.4f}\n")
    f.write(f"Mean Benchmark 20d Return: {bm_mean:.4f}\n")
    f.write(f"Excess Return: {metrics['mean_20d_ret'] - bm_mean:.4f}\n")

print("Report saved to optimization_report.txt")
