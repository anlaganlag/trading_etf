
import os
import pandas as pd
from gm.api import *
from config import config

def fetch_data():
    # Set token
    set_token(config.GM_TOKEN)
    
    # 1. Load Whitelist
    df_excel = pd.read_excel(config.WHITELIST_FILE)
    df_excel.columns = df_excel.columns.str.strip()
    df_excel = df_excel.rename(columns={'symbol':'etf_code', 'sec_name':'etf_name', 'name_cleaned':'theme'})
    whitelist = list(df_excel['etf_code'])
    print(f"Whitelist size: {len(whitelist)}")
    
    # 2. Define Date Range
    # Need 20 days prior to 2024-09-01 for lookback calculation
    start_date = '2024-08-01'
    end_date = '2026-02-07' # Today
    
    print(f"Fetching data from {start_date} to {end_date}...")
    
    # 3. Fetch Prices
    sym_str = ",".join(whitelist)
    hd = history(
        symbol=sym_str, frequency='1d', start_time=start_date, end_time=end_date,
        fields='symbol,close,eob', fill_missing='last', adjust=ADJUST_PREV, df=True
    )
    
    if hd.empty:
        print("No data fetched!")
        return

    hd['eob'] = pd.to_datetime(hd['eob']).dt.tz_localize(None)
    prices = hd.pivot(index='eob', columns='symbol', values='close').ffill()
    
    # 4. Fetch Benchmark
    bm_symbol = config.MACRO_BENCHMARK
    bm_data = history(
        symbol=bm_symbol, frequency='1d', start_time=start_date, end_time=end_date,
        fields='close,eob', fill_missing='last', adjust=ADJUST_PREV, df=True
    )
    bm_data['eob'] = pd.to_datetime(bm_data['eob']).dt.tz_localize(None)
    benchmark = bm_data.set_index('eob')['close']
    
    # 5. Save to file
    output_dir = "data_for_opt"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    prices.to_csv(os.path.join(output_dir, "prices.csv"))
    benchmark.to_csv(os.path.join(output_dir, "benchmark.csv"))
    print(f"Data saved to {output_dir}")

if __name__ == "__main__":
    fetch_data()
