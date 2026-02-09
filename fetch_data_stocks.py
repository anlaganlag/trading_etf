
import os
import pandas as pd
from gm.api import *
from config import config

# We will use CSI 800 (300 large + 500 mid/small) as our stock universe
# This covers ~70-80% of market cap and is liquid enough for realistic trading.
UNIVERSE_INDEX = 'SHSE.000906' 

def fetch_stock_data():
    set_token(config.GM_TOKEN)
    

    # 1. Get Constituents (Full Market Composite)
    print("Fetching constituents for Full Market (Composite of 300, 500, 1000, 2000)...")
    indices = [
        'SHSE.000300',  # 沪深300
        'SHSE.000905',  # 中证500
        'SHSE.000852',  # 中证1000
        'SZSE.399303',  # 国证2000
    ]
    
    whitelist = set()
    for idx in indices:
        try:
            print(f"  Fetching {idx}...")
            c = stk_get_index_constituents(index=idx)
            if not c.empty:
                whitelist.update(c['symbol'].tolist())
                print(f"    found {len(c)} symbols")
        except Exception as e:
            print(f"    failed to fetch {idx}: {e}")
            
    whitelist = list(whitelist)
    print(f"Total Unique Universe size: {len(whitelist)} stocks")
    
    # 2. Date Range
    start_date = '2021-01-01'
    end_date = '2026-02-07'
    
    print(f"Fetching daily close from {start_date} to {end_date}...")
    
    # 3. Batch Fetch (GM limits might require batching, but let's try all at once first)
    # 800 symbols * 370 days is ~300k points, should be fine in one go or split.
    ids = ",".join(whitelist)
    
    # Split into chunks of 30 due to 5-year data limit
    chunk_size = 30
    all_prices = []
    
    for i in range(0, len(whitelist), chunk_size):
        chunk = whitelist[i:i+chunk_size]
        sym_str = ",".join(chunk)
        print(f"Fetching batch {i//chunk_size + 1}/{len(whitelist)//chunk_size + 1}...")
        
        hd = history(
            symbol=sym_str, frequency='1d', start_time=start_date, end_time=end_date,
            fields='symbol,close,volume,amount,eob', fill_missing='last', adjust=ADJUST_PREV, df=True
        )
        if not hd.empty:
            all_prices.append(hd)
            
    if not all_prices:
        print("No data fetched!")
        return

    full_df = pd.concat(all_prices)
    full_df['eob'] = pd.to_datetime(full_df['eob']).dt.tz_localize(None)
    
    # Save pivots for both Close and Volume
    prices = full_df.pivot(index='eob', columns='symbol', values='close').ffill()
    volumes = full_df.pivot(index='eob', columns='symbol', values='volume').ffill()
    
    # 4. Benchmark
    bm_data = history(
        symbol=UNIVERSE_INDEX, frequency='1d', start_time=start_date, end_time=end_date,
        fields='close,volume,eob', fill_missing='last', adjust=ADJUST_PREV, df=True
    )
    if not bm_data.empty:
        bm_data['eob'] = pd.to_datetime(bm_data['eob']).dt.tz_localize(None)
        benchmark = bm_data.set_index('eob')['close']
        bm_vol = bm_data.set_index('eob')['volume']
    else:
        benchmark = pd.Series()
        bm_vol = pd.Series()
        
    # 5. Save
    output_dir = "data_for_opt_stocks"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    prices.to_csv(os.path.join(output_dir, "prices.csv"))
    volumes.to_csv(os.path.join(output_dir, "volumes.csv"))
    benchmark.to_csv(os.path.join(output_dir, "benchmark.csv"))
    bm_vol.to_csv(os.path.join(output_dir, "benchmark_vol.csv"))
    print(f"Stock Data (Price & Volume) saved to {output_dir}")

if __name__ == "__main__":
    fetch_stock_data()
