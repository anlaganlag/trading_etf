
import os
import pandas as pd
import numpy as np

def calculate_correlations():
    # Load Data
    data_dir = "data_for_opt_stocks"
    try:
        prices = pd.read_csv(os.path.join(data_dir, "prices.csv"), index_col=0, parse_dates=True)
    except FileNotFoundError:
        print("Error: Prices data not found. Please run fetch_data_stocks.py first.")
        return

    prices = prices.apply(pd.to_numeric, errors='coerce')
    print(f"Data Loaded. Prices: {prices.shape}")

    # Calculate Forward 20-day Return (Target)
    # Target = P_{t+20} / P_t - 1
    # We want to predict this.
    forward_p = 20
    future_rets = prices.shift(-forward_p) / prices - 1

    print("Calculating correlations (IC) for 1-20 day returns...")
    
    correlation_results = {}
    
    for p in range(1, 21):
        # Feature: p-day return rank
        # We use rank because raw returns are volatile and non-stationary.
        # Higher rank (1.0) means better past performance.
        rets = prices.pct_change(p)
        ranks = rets.rank(axis=1, pct=True, ascending=True)
        
        # Calculate Rank IC (Information Coefficient)
        # Correlation between Past Rank and Future Return across all stocks for each day
        # We can calculate daily IC and then average it.
        
        # Align data
        valid_mask = ranks.notna() & future_rets.notna()
        
        daily_ics = []
        for date in ranks.index:
            row_rank = ranks.loc[date]
            row_future = future_rets.loc[date]
            
            # Use mask for this date
            mask = row_rank.notna() & row_future.notna()
            if mask.sum() > 10: # Need enough stocks
                # Spearman correlation
                ic = row_rank[mask].corr(row_future[mask], method='spearman')
                daily_ics.append(ic)
        
        mean_ic = np.mean(daily_ics) if daily_ics else 0
        ic_ir = mean_ic / np.std(daily_ics) if daily_ics and np.std(daily_ics) > 0 else 0
        
        correlation_results[p] = {
            "Mean_IC": mean_ic,
            "IC_IR": ic_ir,
            "Direction": "Momentum" if mean_ic > 0 else "Reversion"
        }
        
    print("\n" + "="*50)
    print("PERIOD ANALYSIS (Correlation with Future 20d Return)")
    print("="*50)
    print(f"{'Period':<6} | {'Mean IC':<10} | {'IC IR':<8} | {'Signal Type'}")
    print("-" * 50)
    
    sorted_periods = sorted(correlation_results.keys())
    
    for p in sorted_periods:
        res = correlation_results[p]
        signal = res['Direction']
        stars = ""
        if abs(res['Mean_IC']) > 0.05:
            stars = "⭐⭐"
        elif abs(res['Mean_IC']) > 0.02:
            stars = "⭐"
            
        print(f"{p:<6} | {res['Mean_IC']:<10.4f} | {res['IC_IR']:<8.2f} | {signal} {stars}")
        
    print("="*50)
    
    # Generate Recommended Weights (Simple Heuristic)
    # Weight ~ IC
    print("\nRecommended Simple Weights (Proportional to IC):")
    weights = [correlation_results[p]['Mean_IC'] for p in sorted_periods]
    # Normalize absolute sum to 1
    weights = np.array(weights) / np.sum(np.abs(weights))
    
    print(f"Weights: {list(np.round(weights, 4))}")
    
    with open("output/weight_analysis.txt", "w") as f:
        f.write("Simple Correlation Analysis\n")
        f.write("===========================\n")
        f.write(f"Weights: {list(np.round(weights, 4))}\n")
        for p in sorted_periods:
            f.write(f"Day {p}: IC={correlation_results[p]['Mean_IC']:.4f}\n")

if __name__ == "__main__":
    calculate_correlations()
