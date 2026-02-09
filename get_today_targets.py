
import pandas as pd
from datetime import datetime
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from config import config, logger
from core.portfolio import RollingPortfolioManager
from core.logic import calculate_target_holdings, calculate_position_scale
from gm.api import history, set_token, ADJUST_PREV
from datetime import timedelta

class MockContext:
    def __init__(self):
        self.mode = 'LIVE'
        self.whitelist = set()
        self.theme_map = {}
        self.prices_df = None
        self.volumes_df = None
        self.benchmark_df = None
        self.risk_scaler = 1.0
        self.market_state = 'SAFE'
        self.account_id = config.ACCOUNT_ID
        self.now = datetime.now()
        self.br_history = []
        # Mocking threshold params if needed by other utils, 
        # though core.logic mostly uses config
        self.BR_CAUTION_IN, self.BR_CAUTION_OUT = 0.40, 0.30
        self.BR_DANGER_IN, self.BR_DANGER_OUT, self.BR_PRE_DANGER = 0.60, 0.50, 0.55
        self.rpm = None

    def account(self, account_id=None):
        return None 

def load_data_and_init(context):
    # 1. Load Whitelist
    try:
        df_excel = pd.read_excel(config.WHITELIST_FILE)
        df_excel.columns = df_excel.columns.str.strip()
        # Rename columns to match expected schema
        df_excel = df_excel.rename(columns={
            'symbol': 'etf_code', 
            'sec_name': 'etf_name', 
            'name_cleaned': 'theme'
        })
        df_excel['etf_code'] = df_excel['etf_code'].astype(str).str.strip()
        context.whitelist = set(df_excel['etf_code'])
        context.theme_map = df_excel.set_index('etf_code')['theme'].to_dict()
        context.name_map = df_excel.set_index('etf_code')['etf_name'].to_dict()
    except Exception as e:
        print(f"Error loading whitelist: {e}")
        sys.exit(1)

    # 2. Load Market Data
    if not config.GM_TOKEN:
        print("Error: GM_TOKEN not set.")
        sys.exit(1)
        
    set_token(config.GM_TOKEN)
    print("Loading Data...")
    
    start_dt = (pd.Timestamp(config.START_DATE) - timedelta(days=400)).strftime('%Y-%m-%d %H:%M:%S')
    end_dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sym_str = ",".join(context.whitelist)
    
    try:
        # Fetch both close and volume
        hd = history(symbol=sym_str, frequency='1d', start_time=start_dt, end_time=end_dt,
                     fields='symbol,close,volume,eob', fill_missing='last', adjust=ADJUST_PREV, df=True)
        hd['eob'] = pd.to_datetime(hd['eob']).dt.tz_localize(None)
        context.prices_df = hd.pivot(index='eob', columns='symbol', values='close').ffill()
        context.volumes_df = hd.pivot(index='eob', columns='symbol', values='volume').ffill()
        
        # Load benchmark for regime text
        bm_data = history(symbol=config.MACRO_BENCHMARK, frequency='1d', start_time=start_dt, end_time=end_dt,
                          fields='close,eob', fill_missing='last', adjust=ADJUST_PREV, df=True)
        bm_data['eob'] = pd.to_datetime(bm_data['eob']).dt.tz_localize(None)
        context.benchmark_df = bm_data.set_index('eob')['close']
        
        print(f"Data Loaded: {len(context.prices_df)} days (Up to {context.prices_df.index[-1]})")
        
    except Exception as e:
        print(f"Data Load Failed: {e}")
        sys.exit(1)

    # 3. Init RPM - Forced to 10,000,000 for standard prediction
    rpm = RollingPortfolioManager()
    # Ignore saved state to use the fixed 10M base
    print("Forcing Initialization with 10,000,000 Base.")
    simulated_days_count = 1
    rpm.days_count = 0
    rpm.initialize_tranches(10000000)
    
    context.rpm = rpm
    return simulated_days_count

def run_simulation():
    context = MockContext()
    current_day_count = load_data_and_init(context)
    
    active_idx = (current_day_count - 1) % config.REBALANCE_PERIOD_T
    active_t = context.rpm.tranches[active_idx]
    
    print(f"\n--- Theoretical Prediction based on logic.py ---")
    print(f"Simulated Day: {current_day_count}")
    print(f"Active Tranche: {active_idx}")
    
    current_dt = context.now.replace(tzinfo=None)
    
    # Update Tranche Value
    if not context.prices_df.empty:
        price_map = context.prices_df.iloc[-1].to_dict()
        active_t.update_value(price_map)
    else:
        price_map = {}
        
    # === CALLING CORE LOGIC ===
    # This is the pixel-perfect alignment part
    
    # 1. Calculate Weights (Holdings & Weights)
    weights_map = calculate_target_holdings(context, current_dt, active_t, price_map)
    
    # 2. Calculate Scale
    scale, trend_scale, risk_scale = calculate_position_scale(context, current_dt)
    
    print(f"\nTraffic Lights:")
    print(f"  > Market State: {context.market_state}")
    print(f"  > Trend Scale:  {trend_scale:.2%}")
    print(f"  > Risk Scale:   {risk_scale:.2%}")
    print(f"  > Final Scale:  {scale:.2%}")
    
    total_w = sum(weights_map.values())
    
    print(f"\nActive Tranche Assets: ¥{active_t.total_value:,.2f}")
    
    if total_w > 0:
        allocatable_value = active_t.total_value * 0.99 * scale
        unit_val = allocatable_value / total_w
        
        print(f"Allocatable (Scaled):  ¥{allocatable_value:,.2f}")
        print("\n--- 💰 Target Execution Plan ---")
        print(f"{'Ticker':<12} {'Name':<14} {'Weight':<8} {'Target Value':<15} {'Current Val':<15} {'Action':<10}")
        print("-" * 85)
        
        sorted_holdings = sorted(weights_map.items(), key=lambda x: x[1], reverse=True)
        
        for s, w in sorted_holdings:
            name = context.name_map.get(s, 'Unknown')[:12] # Truncate for display
            target_val = unit_val * w
            current_val = active_t.holdings.get(s, 0) * price_map.get(s, 0)
            diff = target_val - current_val
            
            action = "HOLD"
            if diff > 100: action = f"BUY (+{diff:,.0f})"
            elif diff < -100: action = f"SELL ({diff:,.0f})"
            
            print(f"{s:<12} {name:<14} {w:<8} ¥{target_val:,.2f}      ¥{current_val:,.2f}      {action:<10}")
            
    else:
        print("No targets identified (Weights map empty).")

if __name__ == "__main__":
    run_simulation()
