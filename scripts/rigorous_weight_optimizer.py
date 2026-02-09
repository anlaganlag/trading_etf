
import os
import pandas as pd
import numpy as np
import scipy.stats as stats
from scipy.optimize import differential_evolution

# Constants
TOP_K = 4
WIN_RATE_THRESHOLD = 0.52

def run_rigorous_optimization():
    # Load Data
    data_dir = "data_for_opt_stocks"
    try:
        prices = pd.read_csv(os.path.join(data_dir, "prices.csv"), index_col=0, parse_dates=True)
        benchmark = pd.read_csv(os.path.join(data_dir, "benchmark.csv"), index_col=0, parse_dates=True)
    except FileNotFoundError:
        print("Error: Prices data not found.")
        return

    prices = prices.apply(pd.to_numeric, errors='coerce')
    if isinstance(benchmark, pd.DataFrame):
         if 'close' in benchmark.columns:
             benchmark = benchmark['close']
         else:
             benchmark = benchmark.iloc[:, 0]
    benchmark = pd.to_numeric(benchmark, errors='coerce')
    
    # Calculate Features (Top 100 Rank Normalization)
    periods = list(range(1, 21))
    feature_matrices = {}

    print("Calculating Features...")
    for p in periods:
        rets = prices.pct_change(p)
        ranks = rets.rank(axis=1, ascending=False, method='min')
        scores = (101 - ranks).clip(lower=0) / 100.0
        feature_matrices[p] = scores

    # Calculate Forward Returns
    forward_p = 20
    future_rets = prices.shift(-forward_p) / prices - 1
    future_bm_rets = benchmark.shift(-forward_p) / benchmark - 1

    # Data Alignment
    start_date = '2024-09-01'
    df_valid = (prices.index >= start_date) & (future_rets.iloc[:, 0].notna())
    target_dates = prices.index[df_valid]
    
    # Train / Test Split (Timewise)
    # Train: First 70% | Test: Last 30%
    n_samples = len(target_dates)
    train_size = int(n_samples * 0.70)
    
    train_dates = target_dates[:train_size]
    test_dates = target_dates[train_size:]
    
    print(f"Total Samples: {n_samples}")
    print(f"Train: {len(train_dates)} ({train_dates[0].date()} -> {train_dates[-1].date()})")
    print(f"Test:  {len(test_dates)}  ({test_dates[0].date()} -> {test_dates[-1].date()})")

    # Prepare Numpy Arrays
    def get_xyz(dates):
        Y_p = future_rets.loc[dates].values
        Y_p = np.nan_to_num(Y_p, nan=-0.01)
        Y_b = future_bm_rets.loc[dates].values
        X_feat = np.array([feature_matrices[p].loc[dates].values for p in periods])
        X_feat = np.nan_to_num(X_feat, nan=0.0)
        return X_feat, Y_p, Y_b
    
    X_train, Y_train, Y_bm_train = get_xyz(train_dates)
    X_test, Y_test, Y_bm_test = get_xyz(test_dates)
    
    # Objective Function (Optimized for Train)
    def objective(weights, X, Y_p, Y_b):
        final_scores = np.tensordot(weights, X, axes=([0], [0]))
        n_days = final_scores.shape[0]
        top_k_indices = np.argpartition(-final_scores, TOP_K-1, axis=1)[:, :TOP_K]
        
        row_indices = np.arange(n_days)[:, None]
        selected_rets = Y_p[row_indices, top_k_indices]
        port_ret = np.mean(selected_rets, axis=1)
        
        mean_ret = np.mean(port_ret)
        win_rate = np.mean(port_ret > Y_b)
        
        loss = -mean_ret
        if win_rate < WIN_RATE_THRESHOLD:
             loss += (WIN_RATE_THRESHOLD - win_rate) * 5.0 # Penalty
        return loss

    print("Starting Optimization on TRAINING set...")
    bounds = [(-1, 1) for _ in range(20)]
    
    # Optimization
    result = differential_evolution(
        lambda w: objective(w, X_train, Y_train, Y_bm_train), 
        bounds, 
        seed=42, 
        maxiter=30, 
        popsize=10,
        workers=1
    )
    
    best_weights = result.x / np.sum(np.abs(result.x))
    print(f"Optimal Weights (Train): {np.round(best_weights, 3)}")

    # Evaluation on TEST Set
    print("\nEvaluating on UNSEEN TEST set...")
    
    def evaluate(weights, X, Y_p, Y_b):
        final_scores = np.tensordot(weights, X, axes=([0], [0]))
        n_days = final_scores.shape[0]
        top_k_indices = np.argpartition(-final_scores, TOP_K-1, axis=1)[:, :TOP_K]
        row_indices = np.arange(n_days)[:, None]
        selected_rets = Y_p[row_indices, top_k_indices]
        port_ret = np.mean(selected_rets, axis=1) # Daily(period) return
        
        # Metrics
        mean_ret = np.mean(port_ret)
        win_rate = np.mean(port_ret > Y_b)
        excess_ret = port_ret - Y_b
        
        # T-Test for Excess Return
        t_stat, p_val = stats.ttest_1samp(excess_ret, 0)
        
        return {
            "mean_ret": mean_ret,
            "win_rate": win_rate,
            "mean_excess": np.mean(excess_ret),
            "t_stat": t_stat,
            "p_value": p_val
        }

    train_metrics = evaluate(best_weights, X_train, Y_train, Y_bm_train)
    test_metrics = evaluate(best_weights, X_test, Y_test, Y_bm_test)
    
    print("\n=== PERFORMANCE REPORT ===")
    print(f"{'Metric':<15} | {'Train':<10} | {'Test (Real)':<10}")
    print("-" * 45)
    print(f"{'Mean Return':<15} | {train_metrics['mean_ret']:.2%}     | {test_metrics['mean_ret']:.2%}")
    print(f"{'Win Rate':<15} | {train_metrics['win_rate']:.2%}     | {test_metrics['win_rate']:.2%}")
    print(f"{'Excess Ret':<15} | {train_metrics['mean_excess']:.2%}     | {test_metrics['mean_excess']:.2%}")
    print(f"{'P-Value (T)':<15} | {train_metrics['p_value']:.4f}     | {test_metrics['p_value']:.4f}")
    
    print("\nConclusion:")
    if test_metrics['p_value'] < 0.05 and test_metrics['mean_excess'] > 0:
        print("✅ Strategy shows STATISTICALLY SIGNIFICANT positive alpha on Test set.")
    else:
        print("❌ Strategy failed significance test on Test set. Likely Overfitted or Weak Signal.")
        
    # Save Report
    with open("output/rigorous_validation_report.txt", "w") as f:
        f.write("Rigorous Validation Report\n")
        f.write("==========================\n")
        f.write(f"Train Period: {train_dates[0].date()} - {train_dates[-1].date()}\n")
        f.write(f"Test Period:  {test_dates[0].date()} - {test_dates[-1].date()}\n\n")
        f.write(f"Weights: {list(np.round(best_weights, 4))}\n\n")
        f.write(f"Test Set Metrics:\n")
        f.write(f"Mean Return: {test_metrics['mean_ret']:.4f}\n")
        f.write(f"Win Rate: {test_metrics['win_rate']:.4f}\n")
        f.write(f"P-Value: {test_metrics['p_value']:.4f}\n")

if __name__ == "__main__":
    run_rigorous_optimization()
