from gm.api import *
import pandas as pd
import os

# Use the token provided by the user
TOKEN = 'e2e96d719135bbf887df4ee5c633b97d9e1aa482'
set_token(TOKEN)

def test_data():
    # Try to fetch some 2021 data
    symbol = 'SHSE.000001'
    start_time = '2021-12-01 09:00:00'
    end_time = '2021-12-31 16:00:00'
    
    print(f"--- Testing Data Retrieval for 2024 ---")
    print(f"Symbol: {symbol}")
    print(f"Range: {start_time} to {end_time}")
    
    try:
        # Fetch daily bars
        hd = history(symbol=symbol, frequency='1d', start_time=start_time, end_time=end_time, df=True)
        
        if hd is not None and not hd.empty:
            start_found = hd.iloc[0]['bob'].strftime('%Y-%m-%d')
            end_found = hd.iloc[-1]['bob'].strftime('%Y-%m-%d')
            print(f"\n[SUCCESS] Successfully retrieved 2024 data for {symbol}!")
            print(f"Data range in result: {start_found} to {end_found}")
            print(f"Total trading days: {len(hd)}")
        else:
            print(f"\n[FAILED] Retrieved empty data frame for {symbol}.")
            
    except Exception as e:
        print(f"\n[ERROR] An exception occurred while fetching {symbol}: {e}")

    # Also test a common stock/ETF from 2024
    symbol_etf = 'SHSE.510300' # HS300 ETF
    print(f"\n--- Testing Data Retrieval for ETF {symbol_etf} ---")
    try:
        hd_etf = history(symbol=symbol_etf, frequency='1d', start_time=start_time, end_time=end_time, df=True)
        if hd_etf is not None and not hd_etf.empty:
            start_found = hd_etf.iloc[0]['bob'].strftime('%Y-%m-%d')
            end_found = hd_etf.iloc[-1]['bob'].strftime('%Y-%m-%d')
            print(f"[SUCCESS] Successfully retrieved 2024 data for {symbol_etf}!")
            print(f"Data range in result: {start_found} to {end_found}")
            print(f"Total trading days: {len(hd_etf)}")
        else:
            print(f"[FAILED] No data for {symbol_etf} in 2024.")
    except Exception as e:
        print(f"[ERROR] An exception occurred while fetching {symbol_etf}: {e}")

if __name__ == '__main__':
    test_data()
