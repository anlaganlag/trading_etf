
"""
verify_model_robustness.py - 量化策略终极体检仪
用于验证 AI 优化的权重是否具有普适性、稳健性和因果性。
"""
import os
import glob
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
from config import config

# === 1. 配置 ===
DATA_DIR = os.path.join(config.BASE_DIR, "data_for_opt_stocks")
PRICES_FILE = os.path.join(DATA_DIR, "prices.csv")
BENCH_FILE = os.path.join(DATA_DIR, "benchmark.csv")

# AI 优化的“神奇权重” (待验证对象)
OPTIMAL_WEIGHTS = {
    1: -0.045,
    2: 0.183,
    3: -0.290,
    5: -0.771,
    7: -0.816,
    10: -0.778,
    14: -0.772,
    20: 0.955
}
PERIODS = list(OPTIMAL_WEIGHTS.keys())
WEIGHT_VEC = np.array(list(OPTIMAL_WEIGHTS.values()))

def load_data():
    print(f"Loading data from {DATA_DIR}...")
    if not os.path.exists(PRICES_FILE):
        print("❌ Data not found. Please run fetch_data_stocks.py first.")
        return None, None
        
    df = pd.read_csv(PRICES_FILE, index_col=0, parse_dates=True)
    # Check if benchmark file exists, else use market mean
    if os.path.exists(BENCH_FILE):
        try:
            ben = pd.read_csv(BENCH_FILE, index_col=0, parse_dates=True).iloc[:, 0]
        except:
             ben = df.mean(axis=1)
    else:
        ben = df.mean(axis=1)
        
    ben = ben.reindex(df.index).fillna(method='ffill')
    print(f"Data Loaded: {df.shape}")
    return df, ben

class RobustnessTester:
    def __init__(self, df_prices, df_benchmark):
        self.prices = df_prices
        self.benchmark = df_benchmark
        self.ranks = {}
        self.prepare_features()

    def prepare_features(self):
        print("Preparing features (Ranks)...")
        for p in PERIODS:
            # Ret_lag: Price / Price_shift(p) - 1
            ret_lag = self.prices / self.prices.shift(p) - 1
            # Percentile Rank (0~1)
            rank_lag = ret_lag.rank(axis=1, pct=True).fillna(0.5)
            self.ranks[p] = rank_lag

    def run_backtest(self, start_date, end_date, weights=None, universe_mask=None):
        """
        快速向量化回测
        universe_mask: boolean Series (stocks to include)
        """
        if weights is None:
            weights = WEIGHT_VEC
            
        # Slice Data
        sub_prices = self.prices.loc[start_date:end_date]
        sub_ben = self.benchmark.loc[start_date:end_date]
        
        if sub_prices.empty:
            return None
            
        # Calculate Score Matrix
        score = pd.DataFrame(0.0, index=sub_prices.index, columns=sub_prices.columns)
        for i, p in enumerate(PERIODS):
            r = self.ranks[p].loc[start_date:end_date]
            score += r * weights[i]
            
        # Apply Universe Mask (if any)
        if universe_mask is not None:
            # Keep only columns in universe
            valid_cols = universe_mask.index[universe_mask].intersection(score.columns)
            score = score[valid_cols]
            
        # Select Top N (Daily)
        TOP_N = 4
        
        # Calculate Forward Return (simulating T+1 entry, holding 1 day for simplicity of daily attribution)
        # Actually strategy holds 20 days, but for signal testing, daily rebal is cleaner to see signal power.
        # Let's simple daily rebalance for factor testing (Standard IC/Long-Short approach)
        
        # Ret_1d_fwd
        ret_1d_fwd = sub_prices.shift(-1) / sub_prices - 1
        if universe_mask is not None:
             ret_1d_fwd = ret_1d_fwd[valid_cols]
             
        # Top N Mask
        # We need numpy for speed
        score_val = score.values
        ret_val = ret_1d_fwd.values
        
        # Indices of Top N
        # Argpartition (-score) -> Smallest indices are largest score
        # Handle Check: if n_cols < TOP_N
        n_cols = score_val.shape[1]
        if n_cols < TOP_N:
             # Take all
             top_mask = np.ones_like(score_val, dtype=bool)
        else:
             # This is tricky with NaNs. Fill NaNs with -inf
             score_val = np.nan_to_num(score_val, nan=-np.inf)
             # argpartition
             idx = np.argpartition(-score_val, TOP_N, axis=1)[:, :TOP_N]
             top_mask = np.zeros_like(score_val, dtype=bool)
             rows = np.arange(score_val.shape[0])[:, None]
             top_mask[rows, idx] = True
             
        # Portfolio Return
        # Mean of selected stocks
        # Avoid mean of empty slice warning
        port_ret = np.nanmean(np.where(top_mask, ret_val, np.nan), axis=1)
        port_ret = np.nan_to_num(port_ret, nan=0.0) # No trade days
        
        # Benchmark Return
        ben_ret = sub_ben.pct_change().shift(-1).fillna(0.0).values
        
        # Metrics
        port_cum = (1 + port_ret).cumprod()
        ben_cum = (1 + ben_ret).cumprod()
        
        # Excess
        excess = port_ret - ben_ret
        
        # Annualized
        ann_ret = np.mean(port_ret) * 252
        ann_vol = np.std(port_ret) * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        
        win_rate = np.mean(excess > 0)
        
        # Alpha / Beta
        # cov(port, ben) / var(ben)
        # Need to align dates perfectly. They are aligned by index
        # ben_ret might have zeros where port_ret has values?
        # Use common valid indices
        valid_idx = ~np.isnan(port_ret) & ~np.isnan(ben_ret)
        if np.sum(valid_idx) > 20:
            cov = np.cov(port_ret[valid_idx], ben_ret[valid_idx])[0, 1]
            var = np.var(ben_ret[valid_idx])
            beta = cov / var if var > 1e-6 else 0
            
            # Jensen's Alpha (Annualized)
            # alpha = r_p - (r_f + beta * (r_m - r_f))
            # assume r_f = 0
            alpha = (np.mean(port_ret[valid_idx]) - beta * np.mean(ben_ret[valid_idx])) * 252
        else:
            beta = 0
            alpha = 0

        return {
            'return': ann_ret,
            'sharpe': sharpe,
            'win_rate': win_rate,
            'excess_cum': np.nansum(excess),
            'port_cum': port_cum[-1] - 1 if len(port_cum) > 0 else 0,
            'alpha': alpha,
            'beta': beta
        }
    
    # ==========================
    # 🧪 测试 5：特征洗牌 (Placebo Test)
    # ==========================
    def test_feature_shuffle(self):
        print("\n=== 🧪 Test 5: Feature Permutation (Placebo) ===")
        # Shuffle the features (ranks) along time axis, breaking causality
        # If strategy still works, it's overfitting or luck
        
        # We need to temporarily corrupt self.ranks
        original_ranks = {k: v.copy() for k, v in self.ranks.items()}
        
        try:
            print("🔀 Shuffling features time-wise...")
            for p in PERIODS:
                # Shuffle dataframe index
                shuffled_idx = np.random.permutation(self.ranks[p].index)
                self.ranks[p].index = shuffled_idx
                self.ranks[p] = self.ranks[p].sort_index() # Re-sort to match price index, effectively shuffling content relative to dates? 
                # No, reindexing with shuffled index just aligns it back if index is datetime.
                # To shuffle values:
                vals = self.ranks[p].values
                np.random.shuffle(vals) # Shuffle in place along axis 0 (Time)
                self.ranks[p] = pd.DataFrame(vals, index=self.ranks[p].index, columns=self.ranks[p].columns)
                
            m = self.run_backtest('2021-01-01', '2026-02-07')
            print(f"🎰 Placebo Return: {m['return']:.1%} | Sharpe: {m['sharpe']:.2f}")
            
            if m['sharpe'] > 0.5:
                print("⚠️ Warning: Strategy works on random data! (Bug or Overfitting)")
            else:
                print("✅ Passed Placebo Test (Random processing yields no alpha)")
                
        finally:
            # Restore
            self.ranks = original_ranks

    # ==========================
    # 🧪 测试 1：时间外推
    # ==========================
    def test_time_robustness(self):
        print("\n=== 🧪 Test 1: Time Series Walk-Forward ===")
        print(f"Testing across years...")
        
        years = sorted(list(set(self.prices.index.year)))
        
        results = []
        for year in years:
            start = f"{year}-01-01"
            end = f"{year}-12-31"
            
            # Check if data exists for this year
            if year == sorted(years)[-1]:
                 # current year
                 end = datetime.now().strftime("%Y-%m-%d")
            
            m = self.run_backtest(start, end)
            if m:
                print(f"📅 {year}: Ret {m['return']:.1%} | Sharpe {m['sharpe']:.2f} | Alpha {m['alpha']:.1%} | Beta {m['beta']:.2f}")
                results.append(m)
                
        # Simple Pass/Fail check
        # Look for negative years
        if not results: return
        
        neg_years = [years[i] for i, m in enumerate(results) if m['return'] < -0.15]
        if neg_years:
            print(f"⚠️ Warning: Strategy failed in {neg_years}")
        else:
            print("✅ Passed Time Robustness (No catastrophic years)")

    # ==========================
    # 🧪 测试 2：子市场一致性
    # ==========================
    def test_universe_consistency(self):
        print("\n=== 🧪 Test 2: Sub-Universe Consistency ===")
        # We don't have explicit index constituents loaded here easily without downloading again.
        # But we can segment by Volatility or Market Cap proxy?
        # We don't have Market Cap.
        # We can substitute with Volatility Tiers.
        # Low Vol ~= Large Cap (HS300)
        # High Vol ~= Micro Cap (GZ2000)
        
        # Calculate Volatility (last 60 days of full data)
        vol = self.prices.pct_change().std()
        
        # Divide into 3 tiers
        q33 = vol.quantile(0.33)
        q66 = vol.quantile(0.66)
        
        tiers = {
            'Low Vol (Large Cap Proxy)': vol[vol <= q33].index,
            'Mid Vol (Mid Cap Proxy)': vol[(vol > q33) & (vol <= q66)].index,
            'High Vol (Micro Cap Proxy)': vol[vol > q66].index
        }
        
        for name, symbols in tiers.items():
            # Create mask
            mask = pd.Series(False, index=self.prices.columns)
            mask.loc[symbols] = True
            
            m = self.run_backtest('2021-01-01', '2026-02-07', universe_mask=mask)
            print(f"🏘️ {name}: Return {m['return']:.1%} | Sharpe {m['sharpe']:.2f}")

    # ==========================
    # 🧪 测试 3：参数扰动
    # ==========================
    def test_param_sensitivity(self):
        print("\n=== 🧪 Test 3: Parameter Perturbation ===")
        base_sharpe = self.run_backtest('2021-01-01', '2026-02-07')['sharpe']
        print(f"Base Sharpe: {base_sharpe:.2f}")
        
        sharpes = []
        n_trials = 20
        print(f"Running {n_trials} perturbations (+/- 20% noise)...")
        
        for _ in range(n_trials):
            noise = np.random.normal(1, 0.2, len(WEIGHT_VEC))
            # Keep sign!
            new_w = WEIGHT_VEC * noise
            m = self.run_backtest('2021-01-01', '2026-02-07', weights=new_w)
            sharpes.append(m['sharpe'])
            
        avg_s = np.mean(sharpes)
        std_s = np.std(sharpes)
        print(f"Perturbed Sharpe: {avg_s:.2f} +/- {std_s:.2f}")
        
        if avg_s > base_sharpe * 0.8:
            print("✅ Passed Stability Test (Robust to noise)")
        else:
            print("⚠️ Failed Stability Test (Sensitive to parameters)")

    # ==========================
    # 🧪 测试 4：信号分解
    # ==========================
    def test_signal_decomp(self):
        print("\n=== 🧪 Test 4: Signal Decomposition ===")
        
        # A: Momentum Only (Day 20)
        w_mom = np.zeros_like(WEIGHT_VEC)
        w_mom[-1] = 1.0 # Day 20
        m_mom = self.run_backtest('2021-01-01', '2026-02-07', weights=w_mom)
        
        # B: Reversion Only (Day 5, 7, 10, 14) -> Indices 3, 4, 5, 6
        w_rev = np.zeros_like(WEIGHT_VEC)
        w_rev[3:7] = -1.0 
        m_rev = self.run_backtest('2021-01-01', '2026-02-07', weights=w_rev)
        
        # C: Short Term (Day 2) -> Index 1
        w_short = np.zeros_like(WEIGHT_VEC)
        w_short[1] = 1.0
        m_short = self.run_backtest('2021-01-01', '2026-02-07', weights=w_short)
        
        print(f"📈 Momentum Only (Day 20): Sharpe {m_mom['sharpe']:.2f}")
        print(f"📉 Reversion Only (Mid):  Sharpe {m_rev['sharpe']:.2f}")
        print(f"⚡ Short Term (Day 2):     Sharpe {m_short['sharpe']:.2f}")
        
        # Conclusion
        if m_rev['sharpe'] > m_mom['sharpe'] and m_rev['sharpe'] > m_short['sharpe']:
            print("🔍 Core Driver: MEAN REVERSION (超跌反弹)")
        elif m_mom['sharpe'] > m_rev['sharpe']:
             print("🔍 Core Driver: MOMENTUM (趋势)")
        else:
             print("🔍 Core Driver: BALANCED/SHORT-TERM")


    # ==========================
    # 🧪 测试 6：纯动量组合 (Day 2 + Day 20)
    # ==========================
    def test_momentum_only_strategy(self):
        print("\n=== 🧪 Test 6: Simplified Momentum (Day 2 + Day 20) ===")
        # Logic: 0.2 * Day 2 + 0.8 * Day 20 (Simulate Momentum mix)
        # Weights normalized roughly
        w = np.zeros_like(WEIGHT_VEC)
        w[1] = 0.3  # Day 2
        w[-1] = 0.7 # Day 20
        
        m = self.run_backtest('2021-01-01', '2026-02-07', weights=w)
        print(f"🚀 Momentum Combo Return: {m['return']:.1%} | Sharpe: {m['sharpe']:.2f}")
        
        # Breakdown by volatility
        vol = self.prices.pct_change().std()
        high_vol_idx = vol[vol > vol.quantile(0.66)].index
        mask = pd.Series(False, index=self.prices.columns)
        mask.loc[high_vol_idx] = True
        
        m_micro = self.run_backtest('2021-01-01', '2026-02-07', weights=w, universe_mask=mask)
        print(f"👉 On Micro Caps (High Vol): Sharpe {m_micro['sharpe']:.2f}")

if __name__ == "__main__":
    df, ben = load_data()
    if df is not None:
        tester = RobustnessTester(df, ben)
        
        # Run Sequence
        tester.test_time_robustness()
        tester.test_universe_consistency()
        tester.test_signal_decomp() 
        tester.test_feature_shuffle()
        tester.test_param_sensitivity()
        tester.test_momentum_only_strategy() # Added

