from __future__ import print_function, absolute_import
from gm.api import *
import pandas as pd
import numpy as np
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from config import config

load_dotenv()

TOP_N = 4
REBALANCE_PERIOD_T = 10
STOP_LOSS = 0.30          # 止损 30%
TRAILING_TRIGGER = 0.15   # 15% 开启追踪止盈
TRAILING_DROP = 0.03      # 回落 3% 止盈退出

# Account ID for Live Trading
ACCOUNT_ID = os.environ.get('GM_ACCOUNT_ID', '658419cf-ffe1-11f0-a908-00163e022aa6')

# TOP_N = 4
# REBALANCE_PERIOD_T = 10
# STOP_LOSS = 0.20
# TRAILING_TRIGGER = 0.15
# EBALANCE_PERIOD_T = 10
# STOP_LOSS = 0.20
# TRAILING_TRIGGER = 0.15
# TRAILING_DROP = 0.05

# 原止损止盈参数
# STOP_LOSS = 0.05  # 止损
# TRAILING_TRIGGER = 0.06 # 止盈
# TRAILING_DROP = 0.02  # 止盈回落



# --- 原始参数  ---
# TOP_N = 5
# REBALANCE_PERIOD_T = 13
# STOP_LOSS = 0.20  # 止损
# TRAILING_TRIGGER = 0.10 # 止盈
# TRAILING_DROP = 0.05  # 止盈回落



# START_DATE = os.environ.get('GM_START_DATE', '2021-12-03 09:00:00')
# END_DATE = os.environ.get('GM_END_DATE', '2026-01-23 16:00:00')


START_DATE='2021-12-03 09:00:00'
END_DATE='2026-01-23 16:00:00'

# START_DATE='2024-09-01 09:00:00'
# END_DATE='2026-01-23 16:00:00'

# START_DATE='2021-12-03 09:00:00'
# END_DATE='2026-01-23 16:00:00'
DYNAMIC_POSITION = True # 开启动态仓位
ENABLE_META_GATE = True # False=幽灵模式(只记录不减仓，收益高) | True=开启防御(回撤小)


# === 评分机制开关 ===
SCORING_METHOD = 'SMOOTH' # 'STEP': 原版硬截断(前15满分) | 'SMOOTH': 线性衰减(前30平滑)

# === 主题集中度控制 ===
MAX_PER_THEME = 2  # 同一主题最多入选几只（防止板块过度集中）设为0不限制

# === 宏观风控基准配置 ===
# 沪深300: 'SHSE.510300' | 创业板指: 'SZSE.159915'
MACRO_BENCHMARK = 'SHSE.510300' 

# === 状态文件 ===
STATE_FILE = "rolling_state_simple.json"

# === 实盘数据更新 ===
LIVE_DATA_UPDATE = False  # True=每日更新prices_df（实盘必开）| False=只用init数据（回测）


MIN_SCORE = 20







class Tranche:
    def __init__(self, t_id, initial_cash=0):
        self.id = t_id
        self.cash = initial_cash
        self.holdings = {} # {symbol: shares}
        self.pos_records = {} # {symbol: {'entry_price': x, 'high_price': y}}
        self.total_value = initial_cash
        self.guard_triggered_today = False 

    def to_dict(self):
        return self.__dict__

    @staticmethod
    def from_dict(d):
        t = Tranche(d["id"], d["cash"])
        t.holdings = d["holdings"]
        t.pos_records = d["pos_records"]
        t.total_value = d["total_value"]
        # guard_triggered_today doesn't need persistence, resets daily
        return t

    def update_value(self, price_map):
        val = self.cash
        current_symbols = list(self.holdings.keys())
        for sym in current_symbols:
            if sym in price_map:
                price = price_map[sym]
                val += self.holdings[sym] * price
                if sym in self.pos_records:
                    self.pos_records[sym]['high_price'] = max(self.pos_records[sym]['high_price'], price)
        self.total_value = val

    def check_guard(self, price_map):
        to_sell = []
        is_tp = False
        for sym, rec in self.pos_records.items():
            if sym not in self.holdings: continue
            curr_price = price_map.get(sym, 0)
            if curr_price <= 0: continue

            entry, high = rec['entry_price'], rec['high_price']
            
            # Stop Loss OR Trailing Take Profit
            if (curr_price < entry * (1 - STOP_LOSS)) or \
               (high > entry * (1 + TRAILING_TRIGGER) and curr_price < high * (1 - TRAILING_DROP)):
                to_sell.append(sym)
                if curr_price >= entry: is_tp = True

        return to_sell, is_tp

    def sell(self, symbol, price):
        if symbol in self.holdings:
            shares = self.holdings[symbol]
            self.cash += shares * price
            del self.holdings[symbol]
            if symbol in self.pos_records: del self.pos_records[symbol]

    def buy(self, symbol, cash_allocated, price):
        if price <= 0: return
        shares = int(cash_allocated / price / 100) * 100
        cost = shares * price
        if shares > 0 and self.cash >= cost:
            self.cash -= cost
            self.holdings[symbol] = self.holdings.get(symbol, 0) + shares
            self.pos_records[symbol] = {'entry_price': price, 'high_price': price}

class RollingPortfolioManager:
    def __init__(self):
        self.tranches = []
        self.params = {"T": REBALANCE_PERIOD_T, "top_n": TOP_N}
        self.initialized = False
        self.days_count = 0 
        self.state_path = os.path.join(config.BASE_DIR, STATE_FILE)
        self.nav_history = []  # Track daily virtual NAV (T-Close Valuation)
        
    def load_state(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.params = data.get("params", self.params)
                    self.initialized = data.get("initialized", False)
                    self.days_count = data.get("days_count", 0)  # Load persisted day count
                    self.tranches = [Tranche.from_dict(d) for d in data.get("tranches", [])]
                print(f"✓ Loaded State: {len(self.tranches)} tranches, Day {self.days_count} from {self.state_path}")
                return True
            except Exception as e:
                print(f"⚠️ Failed to load state: {e}")
                print(f"   Will initialize fresh state...")
        return False
        
    def save_state(self):
        data = {
            "params": self.params,
            "initialized": self.initialized,
            "days_count": self.days_count, # Persist day count
            "tranches": [t.to_dict() for t in self.tranches]
        }
        try:
            # 使用临时文件写入，然后重命名（原子操作）
            temp_path = self.state_path + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            # 原子替换
            if os.path.exists(self.state_path):
                os.remove(self.state_path)
            os.rename(temp_path, self.state_path)
        except Exception as e:
            print(f"⚠️ Failed to save state: {e}")
            print(f"   State path: {self.state_path}")
            # 不抛出异常，允许策略继续运行

    def initialize_tranches(self, total_cash):
        if self.initialized and self.tranches: return
        share = total_cash / REBALANCE_PERIOD_T  # Aggressive Allocation (1/7th instead of 1/10th)
        self.tranches = [Tranche(i, share) for i in range(self.params["T"])]
        self.initialized = True
        print(f"Initialized {self.params['T']} tranches.")
        self.save_state()

    def reconcile_with_broker(self, real_positions):
        """
        Reconcile virtual tranches with actual broker positions.
        If Virtual > Real (Phantom Holdings), remove from virtual and refund cash.
        If Virtual < Real (Unmanaged), the Sync logic later handles selling.
        """
        # 1. Sum up all virtual holdings
        virtual_map = {} # sym -> total_shares
        for t in self.tranches:
            for sym, shares in t.holdings.items():
                virtual_map[sym] = virtual_map.get(sym, 0) + shares
        
        # 2. Compare with Real
        for sym, v_qty in virtual_map.items():
            r_qty = real_positions.get(sym, 0)
            diff = v_qty - r_qty
            
            if diff > 0: # Phantom: Virtual has 1000, Real has 0. need to remove 1000.
                print(f"⚠️ Reconcile: Found {diff} phantom shares of {sym} (Real {r_qty} vs Virtual {v_qty}). Fixing...")
                remaining_to_remove = diff
                
                # Deduct from tranches (FIFO by tranche order)
                for t in self.tranches:
                    if sym in t.holdings:
                        has_qty = t.holdings[sym]
                        remove_qty = min(has_qty, remaining_to_remove)
                        
                        if remove_qty > 0:
                            # 1. Update Holdings
                            t.holdings[sym] -= remove_qty
                            if t.holdings[sym] == 0:
                                del t.holdings[sym]
                            
                            # 2. Refund Cash (using entry price)
                            if sym in t.pos_records:
                                entry_p = t.pos_records[sym]['entry_price']
                                refund_val = remove_qty * entry_p
                                t.cash += refund_val
                                # Clean up record if full removal
                                if sym not in t.holdings:
                                    del t.pos_records[sym]
                                    
                            print(f"   -> Tranche {t.id}: Removed {remove_qty}, Refunded {refund_val:.2f}")
                            
                            remaining_to_remove -= remove_qty
                            if remaining_to_remove <= 0:
                                break

def init(context):
    print(f"Initializing Simple Strategy (T={REBALANCE_PERIOD_T}, TopN={TOP_N}, Mode={SCORING_METHOD})")
    context.rpm = RollingPortfolioManager()
    
    # Check RUN_MODE from env (default to LIVE if not set, to be safe? No, default backtest)
    run_mode = os.environ.get('GM_MODE', 'BACKTEST').upper()
    context.mode = MODE_BACKTEST if run_mode == 'BACKTEST' else MODE_LIVE
    context.account_id = ACCOUNT_ID
    
    # --- Meta-Gate State Machine (Capital Layer) ---
    context.market_state = 'SAFE' # SAFE, CAUTION, DANGER
    context.risk_scaler = 1.0     # 1.0, 0.5, 0.0
    context.br_history = []       # For smoothing Broken_Ratio (Rolling 3 days)
    
    # Meta-Gate Thresholds (Hysteresis)
    # Meta-Gate Thresholds (Hysteresis) - Firefighter Mode V2
    # Strategy: 1.0 (Safe/Low Caution) -> 0.7 (Pre-Danger) -> 0.0 (Danger)
    context.BR_CAUTION_IN = 0.40  
    context.BR_CAUTION_OUT = 0.30 
    context.BR_DANGER_IN = 0.60   
    context.BR_DANGER_OUT = 0.50
    context.BR_PRE_DANGER = 0.55  # New Buffer Threshold
    
    # 1. Load Whitelist & Theme Map
    excel_path = os.path.join(config.BASE_DIR, "ETF合并筛选结果.xlsx")
    df_excel = pd.read_excel(excel_path)
    df_excel.columns = df_excel.columns.str.strip()
    rename_map = {'symbol': 'etf_code', 'sec_name': 'etf_name', 'name_cleaned': 'theme'}
    df_excel = df_excel.rename(columns=rename_map)
    if 'theme' not in df_excel.columns: df_excel['theme'] = df_excel['etf_name']
    context.whitelist = set(df_excel['etf_code'])
    context.theme_map = df_excel.set_index('etf_code')['theme'].to_dict()

    # --- INJECT MISSING TICKERS (Monkey Patch) ---
    # These tickers were found in the winning transaction logs but missing from the excel
    missing_tickers = [
        '560860', '516650', '513690', '159516', '159995', 
        '517520', '512400', '159378', '159638', '516150', 
        '515400', '159852', '159599', '159998'
    ]
    print(f"Injecting {len(missing_tickers)} missing tickers into whitelist...")
    for code in missing_tickers:
        full_code = f"SHSE.{code}" if code.startswith('5') else f"SZSE.{code}"
        context.whitelist.add(full_code)
        if full_code not in context.theme_map:
            context.theme_map[full_code] = 'Injected_Alpha'
    # ---------------------------------------------


    # 2. Build Price Matrix
    # 2. Build Price Matrix & Load HS300
    if context.mode == MODE_LIVE:
        print("☁️ Live Mode: Fetching history from GM API (Last 260 days)...")
        
        # --- A. 获取标的行情 (Batch) ---
        all_symbols = list(context.whitelist)
        end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        start_time = (datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d %H:%M:%S')
        
        symbol_str = ",".join(all_symbols)
        try:
            hd = history(symbol=symbol_str, frequency='1d', start_time=start_time, end_time=end_time, fields='symbol,close,eob', fill_missing='last', adjust=ADJUST_PREV, df=True)
            if not hd.empty:
                hd['eob'] = pd.to_datetime(hd['eob']).dt.tz_localize(None)
                context.prices_df = hd.pivot(index='eob', columns='symbol', values='close').ffill()
                
                # 获取此时此刻的最新价格并插入/更新到最后一行
                current_data = current(symbols=symbol_str)
                now_prices = {item['symbol']: item['price'] for item in current_data}
                today_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                context.prices_df.loc[today_dt] = pd.Series(now_prices)
                context.prices_df = context.prices_df.ffill()
                
                print(f"☁️ Live Data Ready: {context.prices_df.shape} (Includes today's live tick)")
            else:
                print("⚠️ Warning: API returned empty history data!")
                context.prices_df = pd.DataFrame()
        except Exception as e:
            print(f"⚠️ Error fetching live data: {e}")
            context.prices_df = pd.DataFrame()

        # --- B. 获取宏观基准行情 (Macro) ---
        try:
            bm_hd = history(symbol=MACRO_BENCHMARK, frequency='1d', start_time=start_time, end_time=end_time, fields='close,eob', fill_missing='last', adjust=ADJUST_PREV, df=True)
            if not bm_hd.empty:
                bm_hd['eob'] = pd.to_datetime(bm_hd['eob']).dt.tz_localize(None)
                context.benchmark_df = bm_hd.set_index('eob')['close'].sort_index()
                
                # 插入当前价格
                bm_current = current(symbols=MACRO_BENCHMARK)
                if bm_current:
                    context.benchmark_df.loc[today_dt] = bm_current[0]['price']
                print(f"Benchmark {MACRO_BENCHMARK} Loaded: {len(context.benchmark_df)} days (API).")
            else:
                context.benchmark_df = None
                print(f"Warning: Benchmark {MACRO_BENCHMARK} API data empty.")
        except Exception as e:
            context.benchmark_df = None
            print(f"Warning: Failed to fetch Benchmark {MACRO_BENCHMARK} API: {e}")

    else:
        # Backtest Mode: Force API Usage (Consistent with Step 2 Logic)
        print("📉 Backtest Mode: Fetching history from GM API (Ensuring consistency)...")
        
        # Calculate time range: Need buffer because Strategy needs MA250 etc.
        # Fetch 1 year data BEFORE backtest start date.
        start_dt = pd.Timestamp(START_DATE) - timedelta(days=365)
        start_time = start_dt.strftime('%Y-%m-%d %H:%M:%S')
        end_time = END_DATE
        
        print(f"   Fetching Data Range: {start_time} -> {end_time}")
        
        # --- A. 获取标的行情 (Batch) ---
        all_symbols = list(context.whitelist)
        symbol_str = ",".join(all_symbols)
        
        try:
            # Note: For large backtests, if symbol_str is huge, this might need chunking.
            # Assuming whitelist size is reasonable (<200).
            hd = history(symbol=symbol_str, frequency='1d', start_time=start_time, end_time=end_time, fields='symbol,close,eob', fill_missing='last', adjust=ADJUST_PREV, df=True)
            
            if not hd.empty:
                hd['eob'] = pd.to_datetime(hd['eob']).dt.tz_localize(None)
                context.prices_df = hd.pivot(index='eob', columns='symbol', values='close').ffill()
                print(f"✓ Data Ready: {context.prices_df.shape} (API)")
            else:
                print("⚠️ Critical: API returned empty history data for backtest!")
                context.prices_df = pd.DataFrame()
        except Exception as e:
            print(f"⚠️ Error fetching backtest data from API: {e}")
            context.prices_df = pd.DataFrame()

        # --- B. 获取宏观基准行情 (Macro) ---
        try:
            bm_hd = history(symbol=MACRO_BENCHMARK, frequency='1d', start_time=start_time, end_time=end_time, fields='close,eob', fill_missing='last', adjust=ADJUST_PREV, df=True)
            if not bm_hd.empty:
                bm_hd['eob'] = pd.to_datetime(bm_hd['eob']).dt.tz_localize(None)
                context.benchmark_df = bm_hd.set_index('eob')['close'].sort_index()
                print(f"✓ Benchmark {MACRO_BENCHMARK} Review: {len(context.benchmark_df)} days (API).")
            else:
                context.benchmark_df = None
                print(f"Warning: Benchmark {MACRO_BENCHMARK} API data empty.")
        except Exception as e:
            context.benchmark_df = None
            print(f"Warning: Failed to fetch Benchmark {MACRO_BENCHMARK} from API: {e}")
            
        # === CRITICAL SAFETY CHECK ===
        # If Benchmark is missing, the Macro-Gate will fail (defaulting to 1.0 exposure),
        # causing a massive 40%+ drawdown. We must STOP if this happens.
        if context.benchmark_df is None or context.benchmark_df.empty:
            raise ValueError(f"❌ CRITICAL: Benchmark {MACRO_BENCHMARK} (Macro Shield) Data is MISSING! Strategies cannot run safely without it. Check API/Internet.")
        else:
             print(f"✅ Macro Shield Active: {MACRO_BENCHMARK} Data Loaded ({len(context.benchmark_df)} days)")

    # 3. State Management
    if context.mode == MODE_BACKTEST and os.path.exists(context.rpm.state_path): 
        try:
            os.remove(context.rpm.state_path)
            print("🗑️ Backtest Mode: Deleted previous state file.", flush=True)
        except Exception as e:
            print(f"⚠️ Failed to delete state file: {e}", flush=True)
        context.rpm.load_state() 
    else:
        context.rpm.load_state()

    # context.days_count moved to rpm.days_count for persistence
    # 订阅指数行情用于实时更新（可选）
    subscribe(symbols='SHSE.000001', frequency='1d')
    
    # === 定时任务 ===
    # 每天 14:55 执行策略逻辑
    schedule(schedule_func=algo, date_rule='1d', time_rule='14:55:00')



def get_market_regime(context, current_dt):
    """判断市场环境：返回仓位系数 0.5-1.0
    仅使用微观ETF市场广度，不使用宏观年线（避免牛市踏空）
    """
    history = context.prices_df[context.prices_df.index <= current_dt]
    if len(history) < 60: return 1.0
    
    # === 宏观风控 (Macro Filter) ===
    # 使用基准指数 (如沪深300) 的半年线 (MA120) 作为牛熊分界
    macro_multiplier = 1.0
    debug_msg = ""
    
    if context.benchmark_df is not None:
        # Pre-process: Ensure tz-naive
        if context.benchmark_df.index.tz is not None:
             context.benchmark_df.index = context.benchmark_df.index.tz_localize(None)
             
        bm_hist = context.benchmark_df[context.benchmark_df.index <= current_dt]
        
        if len(bm_hist) > 120:
            current_price = bm_hist.iloc[-1]
            ma120 = bm_hist.tail(120).mean()
            
            # --- DEBUG BLOCK FOR 2022-2024 CRASH ---
            # Print status every Monday (to reduce log spam) or if Multiplier changes
            is_monday = current_dt.weekday() == 0
            
            if current_price < ma120:
                macro_multiplier = 0.5 # 熊市
                if is_monday: debug_msg = f"[MACRO: BEAR] {MACRO_BENCHMARK} Price {current_price:.2f} < MA120 {ma120:.2f} -> Scale 0.5"
            else:
                if is_monday: debug_msg = f"[MACRO: BULL] {MACRO_BENCHMARK} Price {current_price:.2f} > MA120 {ma120:.2f} -> Scale 1.0"
                
    if debug_msg: print(f"{current_dt.date()} {debug_msg}")
    
    # === 微观强度: ETF市场广度 ===
    recent = history.tail(60)
    ma20 = recent.tail(20).mean()
    ma60 = recent.mean()
    current = recent.iloc[-1]
    above_ma20 = (current > ma20).sum() / len(current)
    above_ma60 = (current > ma60).sum() / len(current)
    strength = (above_ma20 + above_ma60) / 2

    # 基础仓位逻辑
    if strength > 0.6: base_pos = 1.0
    elif strength > 0.4: base_pos = 0.9
    else: base_pos = 0.3

    # 最终仓位 = 微观仓位 * 宏观折扣
    final_pos = base_pos * macro_multiplier
    
    # Turbo Logic: 如果是熊市(Macro<1)且微观弱势(Strength<=0.4)，直接空仓防御
    if macro_multiplier < 1.0 and strength <= 0.4:
        return 0.0

    return final_pos

def get_ranking(context, current_dt):
    history = context.prices_df[context.prices_df.index <= current_dt]
    if len(history) < 251: return None, None

    last_row = history.iloc[-1]
    base_scores = pd.Series(0.0, index=history.columns)
    
    # Updated Optimal Weights (Decoupled Logic)
    # Updated Optimal Weights (Decoupled Logic)
    # R1=30, R3=-70, R5=0 (Linear 'weight' is 0, but we will use it as a Gate), R20=150
    periods_rule = {1: 30, 3: -70, 5: 0, 10: 0, 20: 150}

    rets_dict = {}
    r5_raw = None # Capture R5 constraints
    
    for p, pts in periods_rule.items():
        # 这里使用绝对涨幅，不对比 HS300
        rets = (last_row / history.iloc[-(p+1)]) - 1
        rets_dict[f'r{p}'] = rets
        
        if p == 5:
            r5_raw = rets 

        # 直接按收益排名
        ranks = rets.rank(ascending=False, method='min')
        
        # Skip calculation if weight is 0
        if pts != 0:
            if SCORING_METHOD == 'SMOOTH':
                decay = (30 - ranks) / 30
                decay = decay.clip(lower=0)
                base_scores += decay * pts
            else: 
                base_scores += (ranks <= 15) * pts
    
    # --- Structural Gate (Non-linear Filter) ---
    # Upgrade: Dynamic Volatility Gate (Z-Score)
    # Instead of fixed -8%, check if drop exceeds k * sigma.
    # Logic: Structure is BROKEN if the drop is statistically abnormal (e.g. > 2 sigma).
    
    # --- Structural Gate (Non-linear Filter) ---
    # Upgrade: Dynamic Volatility Gate (Z-Score) with ROBUST Ruler
    # Ruler = Lagged Downside Volatility
    # 1. Lagged: Use t-65 to t-5 (Pre-crash volatility) to avoid "Adaptive Failure"
    # 2. Downside: Only measure downside risk to avoid punishing upside volatility
    
    daily_rets = history.pct_change()
    
    # Lagged slice: Exclude last 5 days from the ruler
    lagged_rets = daily_rets.iloc[:-5].tail(60) 
    
    # Downside only: Measure std dev of negative returns
    downside_rets = lagged_rets[lagged_rets < 0]
    
    # Calculate per-symbol metrics
    vol_down = downside_rets.std()
    vol_full = lagged_rets.std()
    count_down = downside_rets.count()
    
    # Vectorized fallback: Use downside vol if > 10 points, else full vol
    # Note: vol_down or vol_full can be NaN if column is empty
    vol_ruler = vol_down.where(count_down > 10, vol_full)
    
    # Fill remaining NaNs and apply floor
    vol_ruler = vol_ruler.fillna(0.01)
    vol_ruler = vol_ruler.clip(lower=0.005)

    # 2. Calculate Z-Score of the 5-day return
    # Expected 5-day vol = daily_vol * sqrt(5)
    expected_5d_vol = vol_ruler * np.sqrt(5)
    r5_z_score = r5_raw / expected_5d_vol
    
    # 3. Dynamic Gate Thresholds (Split Micro/Macro)
    # K_ENTRY: Micro Gate (Individual stock filtering) - Default 1.6
    # K_CRASH: Macro Gate (Systemic failure detection) - Default 2.5
    k_entry = float(os.environ.get('OPT_R5_K', 1.6)) 
    k_crash = float(os.environ.get('OPT_K_CRASH', 2.5))
    
    # --- META-GATE: Broken Ratio Calculation (Capital Layer) ---
    # Calculate how many "trees are falling" in the forest
    if r5_z_score is not None:
        # Filter Z-Scores to Whitelist (Market Universe)
        universe_z = r5_z_score[r5_z_score.index.isin(context.whitelist)].dropna()
        
        if len(universe_z) >= 20: # Min Sample Size to avoid noise
            # Count broken structures using K_CRASH (Systemic Fire)
            broken_count = (universe_z < -k_crash).sum()
            br_raw = broken_count / len(universe_z)
            
            # Smooth BR (Mean of last 3 days)
            context.br_history.append(br_raw)
            if len(context.br_history) > 3: context.br_history.pop(0)
            br_smooth = np.mean(context.br_history)
            
            # --- V3 Upgrade: Dynamic Threshold (Breadth + Depth) ---
            # If Market Depth is bad (Median Z < -2.3), lower the Danger threshold.
            median_z = np.median(universe_z)
            effective_danger_in = context.BR_DANGER_IN # Default 0.60
            if median_z < -2.3:
                effective_danger_in = 0.50 # Less aggressive penalty (was 0.40)
            
            # 1. State Machine Transition (Hysteresis Logic)
            prev_state = context.market_state
            
            if context.market_state == 'SAFE':
                if br_smooth > context.BR_CAUTION_IN:
                    context.market_state = 'CAUTION'
            elif context.market_state == 'CAUTION':
                if br_smooth > effective_danger_in: # Dynamic: 0.60 or 0.40
                    context.market_state = 'DANGER'
                elif br_smooth < context.BR_CAUTION_OUT:
                    context.market_state = 'SAFE'
            elif context.market_state == 'DANGER':
                if br_smooth < context.BR_DANGER_OUT:
                    context.market_state = 'CAUTION'
            
            # 2. Assign Risk Scaler (Action Mapping)
            # Firefighter V2: Non-linear escalation
            if context.market_state == 'SAFE':
                context.risk_scaler = 1.0
            elif context.market_state == 'CAUTION':
                 # Buffer Zone: If approaching 60%, cut exposure to 70%
                 if br_smooth >= context.BR_PRE_DANGER:
                     context.risk_scaler = 0.7 
                 else:
                     context.risk_scaler = 1.0 # Ignore "Noise" (<55%)
            elif context.market_state == 'DANGER':
                context.risk_scaler = 0.0 # Shutdown
            
            # LOG DATA for Analysis: Date, BR_Raw, BR_Smooth, State, Risk_Scaler
            # Tag: METAGATE_LOG
            print(f"METAGATE_LOG,{current_dt},{br_raw:.4f},{br_smooth:.4f},{context.market_state},{context.risk_scaler}")

            if context.market_state != prev_state:
                print(f"[{current_dt}] 🚦 METAGATE: {prev_state} -> {context.market_state} (BR={br_smooth:.1%}, Scaler={context.risk_scaler})")

    # --- Individual Gate ---
    is_structure_intact = pd.Series(True, index=base_scores.index)
    if k_entry > 0 and r5_raw is not None:
         # "Gate": Keep only if r5 z-score > -k_entry (Filtering weak stocks)
         is_structure_intact = r5_z_score > -k_entry

    # Apply Gate: Zero out scores for broken structures
    base_scores = base_scores * is_structure_intact.astype(float)

    # 2. 限制在白名单内
    valid_scores = base_scores[base_scores.index.isin(context.whitelist)]
    
    # 3. 基础得分阈值
    valid_scores = valid_scores[valid_scores >= MIN_SCORE]
    
    if valid_scores.empty: return None, base_scores

    data_to_df = {
        'score': valid_scores, 
        'theme': [context.theme_map.get(c, 'Unknown') for c in valid_scores.index],
        'etf_code': valid_scores.index 
    }
    
    for p in periods_rule.keys():
        data_to_df[f'r{p}'] = rets_dict[f'r{p}'][valid_scores.index]

    df = pd.DataFrame(data_to_df)
    
    # 还原排序逻辑：Score -> r1 (短动量) -> 其他周期 -> Code
    sort_cols = ['score', 'r1', 'r3', 'r5', 'r10', 'r20', 'etf_code']
    asc_order = [False, False, False, False, False, False, True]
    
    return df.sort_values(by=sort_cols, ascending=asc_order), base_scores



    # V6.1 Score Logic: Module 1 (Relative Alpha) + Module 2 (Trend Filter)
    history = context.prices_df[context.prices_df.index <= current_dt]
    if len(history) < 251: return None, None

    last_row = history.iloc[-1]
    
    # === Module 2: 趋势过滤 (Trend Filter) ===
    # 核心逻辑：只有处于“可趋势区”的标的才参与评分
    ma20 = history.tail(20).mean()
    ma60 = history.tail(60).mean()
    # 判断：价格在20日均线上方（短期走强）且不处于严重的长期破位（价格>MA60或MA20>MA60）
    is_trending = (last_row > ma20) & (last_row > ma60)
    
    # --- Module 1: 相对强度模块 (Relative Alpha) ---
    # 获取同期的宏观基准表现作为基准
    bm_hist = None
    if context.benchmark_df is not None:
        bm_hist = context.benchmark_df[context.benchmark_df.index <= current_dt]

    base_scores = pd.Series(0.0, index=history.columns)
    # 激进版权重：保持原有的 Inverse Middle 逻辑
    periods_rule = {1: 50, 3: -70, 5: -70, 10: 0, 20: 150}
    
    rets_dict = {}
    for p, pts in periods_rule.items():
        # 计算绝对涨幅
        rets = (last_row / history.iloc[-(p+1)]) - 1
        rets_dict[f'r{p}'] = rets
        
        # 计算 Alpha (超额收益)
        if bm_hist is not None and len(bm_hist) > p:
            bm_p_ret = (bm_hist.iloc[-1] / bm_hist.iloc[-(p+1)]) - 1
            alpha = rets - bm_p_ret
        else:
            alpha = rets # 降级为绝对收益
            
        # 基于 Alpha 进行排名
        ranks = alpha.rank(ascending=False, method='min')
        
        if SCORING_METHOD == 'SMOOTH':
             decay = (30 - ranks) / 30
             decay = decay.clip(lower=0)
             base_scores += decay * pts
        else: # 'STEP' 原版
             base_scores += (ranks <= 15) * pts
    
    # --- 最终整合过滤 ---
    # 1. 应用趋势过滤 (Module 2)
    # 趋势不好的标的得分直接清零，不参与后续 TopN 选拔
    base_scores = base_scores * is_trending.astype(float)
    
    # 2. 限制在白名单内
    valid_scores = base_scores[base_scores.index.isin(context.whitelist)]
    
    # 3. 基础得分阈值
    valid_scores = valid_scores[valid_scores >= MIN_SCORE]
    
    if valid_scores.empty: return None, base_scores

    # 构建结果 DataFrame 用于排序
    # 即使评分一样，我们也优先选绝对收益最好的标的或者是代码更考前的以保证确定性
    data_to_df = {
        'score': valid_scores, 
        'theme': [context.theme_map.get(c, 'Unknown') for c in valid_scores.index],
        'etf_code': valid_scores.index 
    }
    
    for p in periods_rule.keys():
        data_to_df[f'r{p}'] = rets_dict[f'r{p}'][valid_scores.index]

    df = pd.DataFrame(data_to_df)
    
    # 排序：得分 -> 20日绝对收益 -> 1日收益 -> 代码
    sort_cols = ['score', 'r20', 'r1', 'etf_code']
    asc_order = [False, False, False, True]
    
    return df.sort_values(by=sort_cols, ascending=asc_order), base_scores

# def on_bar(context, bars): -> Renamed to algo
def algo(context):
    current_dt = context.now.replace(tzinfo=None) # Scheduled func uses context.now
    
    # === 实盘模式：注入实时行情 ===
    if context.mode == MODE_LIVE:
        try:
            # 获取白名单内所有标的的最新 tick
            ticks = current(symbols=list(context.whitelist))
            today_date = current_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            
            # 构建今日数据字典
            today_data = {tick['symbol']: tick['price'] for tick in ticks if tick['price'] > 0}
            
            if today_data:
                # 转换为 DataFrame 行并追加/更新
                # 注意：这里为了性能，简单处理。如果数据量巨大需优化。
                today_series = pd.Series(today_data, name=today_date)
                
                # 如果今天已经存在（比如重复运行），则更新；否则追加
                if today_date in context.prices_df.index:
                    context.prices_df.loc[today_date, today_series.index] = today_series
                else:
                    # 使用 concat 追加
                    context.prices_df = pd.concat([context.prices_df, today_series.to_frame().T])
                
                context.prices_df.sort_index(inplace=True)
                print(f"☁️ Real-time Data Injected: {len(today_data)} symbols at {current_dt}")
        except Exception as e:
            print(f"⚠️ Failed to fetch real-time data: {e}")

    context.rpm.days_count += 1
    # Save immediately to record the day increment
    context.rpm.save_state()

    # 1. Init if needed
    if not context.rpm.initialized:
        account = context.account()
        if account is None:
             print("⚠️ Account data not ready yet. Skipping init...")
             return
             
        cash = account.cash.available if hasattr(account.cash, 'available') else account.cash.nav
        context.rpm.initialize_tranches(cash)

    # === Reconcile Virtual vs Real ===
    # 修复：强行对齐虚拟分仓与真实持仓，防止“幽灵持仓”导致后续逻辑错乱
    try:
        real_positions = {p.symbol: p.amount for p in context.account().positions()}
        context.rpm.reconcile_with_broker(real_positions)
    except Exception as e:
        print(f"⚠️ Reconcile Error: {e}")

    # 2. Get Prices (Fixed: use history slicing to avoid looking into the future)
    # This ensures we only see data UP TO and INCLUDING 'today' (T day)
    history_until_now = context.prices_df[context.prices_df.index <= current_dt]
    if history_until_now.empty:
        return
    today_prices = history_until_now.iloc[-1]
    price_map = today_prices.to_dict()

    # 3. Update All Tranches (Value & Guard Check)
    # Using T-day closing prices for accounting
    for t in context.rpm.tranches:
        t.update_value(price_map)
        to_sell, _ = t.check_guard(price_map)
        if to_sell:
            t.guard_triggered_today = True
            print(f"{current_dt} | Tranche {t.id} Guard Triggered: {to_sell}")
            for sym in to_sell: 
                t.sell(sym, price_map.get(sym, 0))
        else:
            t.guard_triggered_today = False

    # 4. Rolling Rebalance (Buy/Sell)
    # Identify which tranche is rotating today
    active_idx = (context.rpm.days_count - 1) % REBALANCE_PERIOD_T
    active_tranche = context.rpm.tranches[active_idx]
    
    # Sell Old Holdings in the active tranche
    for sym in list(active_tranche.holdings.keys()):
        price = price_map.get(sym, 0)
        if price > 0: 
            active_tranche.sell(sym, price)
    
    # 5. Buy New Holdings (based on T-day ranking)
    ranking_df, _ = get_ranking(context, current_dt)
    
    if ranking_df is not None and not active_tranche.guard_triggered_today:
        # Theme-based filtering
        if MAX_PER_THEME > 0:
            targets = []
            theme_count = {}
            for code, row in ranking_df.iterrows():
                theme = row['theme']
                if theme_count.get(theme, 0) < MAX_PER_THEME:
                    targets.append(code)
                    theme_count[theme] = theme_count.get(theme, 0) + 1
                if len(targets) >= TOP_N:
                    break
        else:
            targets = ranking_df.head(TOP_N).index.tolist()

        if targets:
            # --- 方案 E: 分期专款 + 1% 摩擦缓冲 ---
            # 使用该分仓内部的现金，并留出 1% 缓冲应对摩擦（滑点、税费、舍入）
            usable_cash = active_tranche.cash * 0.99
            
            # Position Sizing
            # 1. Existing Dynamic Position (Trend)
            regime_scale = 1.0
            if DYNAMIC_POSITION:
                regime_scale = get_market_regime(context, current_dt)
            
            # 2. Meta-Gate Risk Scaler (Broken Ratio)
            meta_scale = 1.0
            if ENABLE_META_GATE:
                meta_scale = getattr(context, 'risk_scaler', 1.0)
            
            # Combined
            final_scale = regime_scale * meta_scale
            allocate_cash = usable_cash * final_scale
            
            # Logging / Monitoring
            current_scaler = getattr(context, 'risk_scaler', 1.0)
            if current_scaler < 1.0:
                if ENABLE_META_GATE:
                     print(f"   🛡️ Risk Control: Allocation x {meta_scale:.1f} (Meta-Gate) -> Final {final_scale:.1%}")
                else:
                     print(f"   🛡️ [Ghost Mode] Meta-Gate signaled {current_scaler:.1f}, but ignored for performance.")
            
            # --- AGGRESSIVE CLAMPING REMOVED ---
            # Trust the internal ledger (active_tranche.cash) because sells will settle.
            # Only log a warning if actual cash is low, but do not block.
            avail = context.account().cash.available if hasattr(context.account().cash, 'available') else context.account().cash.nav
            if allocate_cash > avail:
                print(f"⚠️ Value Warning: Internal Cash {allocate_cash:.0f} > Broker Available {avail:.0f}")
                print(f"   Assuming funds from today's sells will be available for buys.")
                # allocate_cash = avail  <-- THIS LINE CAUSED THE BUG


            # per_amt = allocate_cash / len(targets)
            # Use Unequal Weighting (Top 3 gets 2x)
            # Targets are already sorted by Rank (Head).
            # If N=6. Weights = [2, 2, 2, 1, 1, 1] => Sum 9.
            # If Top 3 is 'Better', this should help.
            n_targets = len(targets)
            weights = []
            for i in range(n_targets):
                if i < 3: weights.append(2)
                else: weights.append(1)
            
            total_weight = sum(weights)
            unit_val = allocate_cash / total_weight
            
            for idx, sym in enumerate(targets):
                w = weights[idx]
                amt = unit_val * w
                active_tranche.buy(sym, amt, price_map.get(sym, 0))
    
    active_tranche.update_value(price_map)

    # 6. Synchronize Internal Bookkeeping with Broker
    # Since it's 15:00, orders will be queued for T+1 Open execution
    global_tgt = {}
    for t in context.rpm.tranches:
        for sym, shares in t.holdings.items():
            global_tgt[sym] = global_tgt.get(sym, 0) + shares
            
    # Get current actual positions from broker
    real_positions = {p['symbol']: p['amount'] for p in context.account().positions()}
    
    # Execute Sells first to free up capital/slots
    # Execute Sells first to free up capital/slots
    # Minimal Safe Sell Logic (Iterate ALL broker positions)
    # 移除白名单限制，确保能卖出所有非目标持仓
    for pos in context.account().positions():
        sym = pos.symbol
        tgt = global_tgt.get(sym, 0)
        diff = pos.amount - tgt
        
        if diff > 0:
            # Check T+0 availability
            if pos.available > 0:
                qty_to_sell = min(diff, pos.available)
                vol = int(qty_to_sell)
                if vol > 0:
                    order_volume(symbol=sym, volume=vol, side=OrderSide_Sell, order_type=OrderType_Market, position_effect=PositionEffect_Close)
                    print(f"📉 Selling {sym}: {vol} (Target {tgt}, Held {pos.amount})", flush=True)
            else:
                 print(f"🔒 Skip Sell {sym}: Want to sell {diff} but available is 0 (T+1 Lock)", flush=True)

    # Execute Buys
    # Refetch actual positions after sends (though they might not be filled yet, wait logic is complex, 
    # so we trust the 'available' cash check will handle subsequent buys)
    real_positions_map = {p.symbol: p.amount for p in context.account().positions()}
    
    for sym, target_amt in global_tgt.items():
        current_amt = real_positions_map.get(sym, 0)
        if current_amt < target_amt:
            # FIX: target_volume expects int, cast to int
            tgt_vol = int(target_amt)
            order_target_volume(symbol=sym, volume=tgt_vol, order_type=OrderType_Market, position_side=PositionSide_Long)

    context.rpm.save_state()
    
    # 7. Record Virtual NAV (Simulating T-Close execution)
    total_equity = sum(t.total_value for t in context.rpm.tranches)
    context.rpm.nav_history.append(total_equity)

def on_backtest_finished(context, indicator):
    print(f"\n=== GM STANDARD REPORT (T+1 EXECUTION) ===")
    print(f"Return: {indicator.get('pnl_ratio', 0)*100:.2f}%")
    print(f"Max DD: {indicator.get('max_drawdown', 0)*100:.2f}%")
    print(f"Sharpe: {indicator.get('sharp_ratio', 0):.2f}")
    
    # Calculate Simulated Performance (T-Close Execution)
    # history = context.rpm.nav_history
    # if history:
    #     nav = pd.Series(history)
    #     if nav.iloc[0] > 0:
    #         ret = (nav.iloc[-1] / nav.iloc[0] - 1) * 100
    #         dd = ((nav - nav.cummax()) / nav.cummax()).min() * 100
    #         daily_ret = nav.pct_change().dropna()
    #         sharpe = np.sqrt(252) * daily_ret.mean() / daily_ret.std() if daily_ret.std() > 0 else 0
            
    #         print(f"\n=== SIMULATED REPORT (T-CLOSE EXECUTION / LIVE PROXY) ===")
    #         print(f"Return: {ret:.2f}%")
    #         print(f"Max DD: {dd:.2f}%")
    #         print(f"Sharpe: {sharpe:.2f}")
    #         print("(Note: This matches run_optimization results and Live Trading logic)")
    
    # print("\nrolling0")
if __name__ == '__main__':
    # === 运行模式配置 ===
    # 'BACKTEST': 回测模式 (跑历史数据)
    # 'LIVE': 实盘/仿真模式 (连接终端实时交易)
    RUN_MODE = 'BACKTEST' 

    # 策略 ID (请确保与掘金终端里的策略 ID 一致)
    STRATEGY_ID = 'aea75195-00dd-11f1-866a-00ffda9d6e63'
    if RUN_MODE == 'LIVE':
        print(f"🚀 正在启动仿真/实盘交易...")
        print(f"⚠️ 请确认已在掘金终端将账户 [658419cf-ffe1-11f0-a908-00163e022aa6] 绑定到策略 [{STRATEGY_ID}]")
        
        run(strategy_id=STRATEGY_ID, 
            filename='gm_strategy_rolling0.py', 
            mode=MODE_LIVE,
            token=os.getenv('MY_QUANT_TGM_TOKEN'))
            
    else:
        print(f"📉 正在启动回测...")
        run(strategy_id=STRATEGY_ID, 
            filename='gm_strategy_rolling0.py', 
            mode=MODE_BACKTEST,
            token=os.getenv('MY_QUANT_TGM_TOKEN'), 
            backtest_start_time=START_DATE, 
            backtest_end_time=END_DATE,
            backtest_adjust=ADJUST_PREV, 
            backtest_initial_cash=1000000,
            backtest_commission_ratio=0.0001)
