import pandas as pd
import os

# Tickers extracted from main.py 'missing_tickers' list
tickers = [
    '560860', '516650', '513690', '159516', '159995', 
    '517520', '512400', '159378', '159638', '516150', 
    '515400', '159852', '159599', '159998'
]

data = []
for code in tickers:
    # Guess exchange
    full_code = f"SHSE.{code}" if code.startswith('5') else f"SZSE.{code}"
    # Dummy name and theme
    data.append({
        'symbol': full_code,
        'sec_name': f"ETF_{code}",
        'name_cleaned': 'Auto_Restored_Theme'
    })

# Create DataFrame
df = pd.DataFrame(data)

# Save to Excel
filename = "ETF合并筛选结果.xlsx"
df.to_excel(filename, index=False)
print(f"Created {filename} with {len(df)} dummy entries.")
