
import os
import pandas as pd
import numpy as np
import scipy.stats as stats

def validate_claims():
    # Load optimization files
    try:
        data_dir = "data_for_opt_stocks"
        benchmark = pd.read_csv(os.path.join(data_dir, "benchmark.csv"), index_col=0, parse_dates=True)
        # Assuming we just simulate random outcomes to check if 57% is significant
        # If we have 328 samples.
        n_samples = 328
        win_rate = 0.57
        
        # Binomial Test
        # Null hypothesis: win rate = 0.5
        n_wins = int(n_samples * win_rate)
        p_value = stats.binomtest(n_wins, n=n_samples, p=0.5, alternative='greater').pvalue
        
        print("Statistical Validation of Claims:")
        print(f"Sample Size: {n_samples}")
        print(f"Claimed Win Rate: {win_rate:.2%}")
        print(f"P-Value (H0: WinRate=50%): {p_value:.4f}")
        
        if p_value < 0.05:
            print("Conclusion: Win Rate IS statistically significant (better than coin flip).")
        else:
            print("Conclusion: Win Rate is NOT statistically significant (could be luck).")
            
        # Check Excess Return Significance (assuming 5% mean, 10% std dev for 20-day returns)
        # T-statistic = (Mean - 0) / (Std / sqrt(N))
        # 5.46% return per 20 days is huge. 
        # Annualized is (1+0.0546)^(250/20) - 1 = 1.0546^12.5 - 1 = ~94%
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    validate_claims()
