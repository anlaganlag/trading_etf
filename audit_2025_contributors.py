
import os
import pandas as pd
import numpy as np

# Load data (Full history to support rolling window)
full_prices = pd.read_csv("data_for_opt_stocks/prices.csv", index_col=0, parse_dates=True)
prices_2025 = full_prices.loc['2025-01-01':'2025-12-31']

# Calculate Score on FULL data first
weights = {1: -0.019, 2: -0.140, 3: -0.243, 5: -0.160, 7: -0.689, 10: 0.761, 14: 0.419, 20: 0.530}
score_full = pd.DataFrame(0.0, index=full_prices.index, columns=full_prices.columns)

for p, w in weights.items():
    ret = full_prices / full_prices.shift(p) - 1
    rank = ret.rank(axis=1, pct=True).fillna(0.5)
    score_full += rank * w

# Slice to 2025 for simulation
score = score_full.loc['2025-01-01':'2025-12-31']
prices = prices_2025

# Simulate Selections
selections = []
for date in prices.index:
    try:
        daily_ret = prices.pct_change().loc[date]
        if daily_ret.isna().all(): continue
        
        s = score.loc[date].copy()
        # Filter Limit Up
        s[daily_ret > 0.095] = -1e9
        
        top4 = s.nlargest(4).index.tolist()
        
        # Calculate 3-day future return for these stocks
        # Not exact but good for attribution
        future_ret = (prices.shift(-3).loc[date, top4] / prices.loc[date, top4] - 1).mean()
        
        for stock in top4:
            selections.append({'Date': date, 'Stock': stock, '3Day_Ret': (prices.shift(-3).loc[date, stock]/prices.loc[date, stock]-1)})
            
    except Exception as e:
        continue

df = pd.DataFrame(selections).dropna()
top_contributors = df.sort_values('3Day_Ret', ascending=False).head(5)

print("🏆 2025 Top Contributors (Audit Sample):")
print(top_contributors[['Date', 'Stock', '3Day_Ret']])
