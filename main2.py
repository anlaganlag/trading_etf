# 建议通过 replace_file_content 对 main.py 进行如下更新
# 这里我整理了完整的升级后的 main.py 内容

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
# 账户 ID：保留 main.py 原本使用的 ID 或从环境读取
ACCOUNT_ID = os.environ.get('GM_ACCOUNT_ID', '658419cf-ffe1-11f0-a908-00163e022aa6')

# === 策略参数 (支持环境变量，方便参数调优) ===
TOP_N = 4                 # 选前N只
REBALANCE_PERIOD_T = 10   # 每T个交易日调仓一次
STOP_LOSS = float(os.environ.get('OPT_STOP_LOSS', 0.20))
TRAILING_TRIGGER = float(os.environ.get('OPT_TRAILING_TRIGGER', 0.15))
TRAILING_DROP = float(os.environ.get('OPT_TRAILING_DROP', 0.03))

# === 时间窗口 ===
START_DATE='2021-12-03 09:00:00'
END_DATE='2026-01-23 16:00:00'

# === 风控开关 (追平收益的关键) ===
DYNAMIC_POSITION = True    # 开启动态趋势仓位
ENABLE_META_GATE = True    # 开启 Meta-Gate 防御 (关键差异)
SCORING_METHOD = 'SMOOTH'  # 线性权重评分
MAX_PER_THEME = 2          # 主题分散
MACRO_BENCHMARK = 'SZSE.159915' # 创业板指作为宏观锚点
STATE_FILE = "rolling_state_main.json"
MIN_SCORE = 20

class Tranche:
    def __init__(self, t_id, initial_cash=0):
        self.id = t_id
        self.cash = initial_cash
        self.holdings = {} 
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
        return t

    def update_value(self, price_map):
        val = self.cash
        for sym, shares in self.holdings.items():
            if sym in price_map:
                price = price_map[sym]
                val += shares * price
                # 记录高点 (如果是 algo 调用，这里只能更新收盘价；on_bar 会更新盘中高点)
                if sym in self.pos_records:
                    self.pos_records[sym]['high_price'] = max(self.pos_records[sym]['high_price'], price)
        self.total_value = val

    def check_guard(self, price_map):
        to_sell = []
        for sym, rec in self.pos_records.items():
            if sym not in self.holdings: continue
            curr_p = price_map.get(sym, 0)
            if curr_p <= 0: continue
            entry, high = rec['entry_price'], rec['high_price']
            
            # 硬止损 OR 移动止盈回落
            is_sl = curr_p < entry * (1 - STOP_LOSS)
            is_tp = high > entry * (1 + TRAILING_TRIGGER) and curr_p < high * (1 - TRAILING_DROP)
            
            if is_sl or is_tp:
                to_sell.append(sym)
        return to_sell

    def sell(self, symbol, price):
        if symbol in self.holdings:
            self.cash += self.holdings[symbol] * price
            self.holdings.pop(symbol, None)
            self.pos_records.pop(symbol, None)

    def buy(self, symbol, cash_allocated, price):
        if price <= 0: return
        shares = int(cash_allocated / price / 100) * 100
        cost = shares * price
        if shares > 0 and self.cash >= cost:
            self.cash -= cost
            self.holdings[symbol] = self.holdings.get(symbol, 0) + shares
            self.pos_records[symbol] = {'entry_price': price, 'high_price': price}
            return shares
        return 0

class RollingPortfolioManager:
    def __init__(self, state_path=None):
        self.tranches = []
        self.initialized = False
        self.days_count = 0 
        self.state_path = state_path or os.path.join(config.BASE_DIR, STATE_FILE)
        self.nav_history = []

    def load_state(self):
        if not os.path.exists(self.state_path): return False
        try:
            with open(self.state_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.days_count = data.get("days_count", 0)
                self.tranches = [Tranche.from_dict(d) for d in data.get("tranches", [])]
                self.initialized = True
            print(f"✅ Loaded State: Day {self.days_count}")
            return True
        except Exception as e:
            print(f"⚠️ Load State Failed: {e}")
        return False
        
    def save_state(self):
        try:
            temp_path = self.state_path + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump({"days_count": self.days_count, "tranches": [t.to_dict() for t in self.tranches]}, f, indent=2)
            if os.path.exists(self.state_path): os.remove(self.state_path)
            os.rename(temp_path, self.state_path)
        except Exception: pass

    def initialize_tranches(self, total_cash):
        share = total_cash / REBALANCE_PERIOD_T
        self.tranches = [Tranche(i, share) for i in range(REBALANCE_PERIOD_T)]
        self.initialized = True
        self.save_state()

    @property
    def total_holdings(self):
        combined = {}
        for t in self.tranches:
            for sym, shares in t.holdings.items():
                combined[sym] = combined.get(sym, 0) + shares
        return combined

    def reconcile_with_broker(self, real_pos):
        virtual_map = self.total_holdings
        for sym, v_qty in virtual_map.items():
            r_qty = real_pos.get(sym, 0)
            diff = v_qty - r_qty
            if diff > 0:
                remaining = diff
                for t in self.tranches:
                    if sym in t.holdings:
                        remove_qty = min(t.holdings[sym], remaining)
                        t.holdings[sym] -= remove_qty
                        if t.holdings[sym] == 0: t.holdings.pop(sym, None)
                        remaining -= remove_qty
                        if remaining <= 0: break

def init(context):
    print(f"🚀 Main Strategy Upgrading to V2 (Meta-Gate Enabled)...")
    context.rpm = RollingPortfolioManager()
    context.mode = MODE_BACKTEST if os.environ.get('GM_MODE', 'BACKTEST').upper() == 'BACKTEST' else MODE_LIVE
    
    # 风险状态机
    context.market_state, context.risk_scaler, context.br_history = 'SAFE', 1.0, []
    context.BR_CAUTION_IN, context.BR_CAUTION_OUT = 0.40, 0.30
    context.BR_DANGER_IN, context.BR_DANGER_OUT, context.BR_PRE_DANGER = 0.60, 0.50, 0.55
    
    # 加载白名单
    df_excel = pd.read_excel(os.path.join(config.BASE_DIR, "ETF合并筛选结果.xlsx"))
    df_excel.columns = df_excel.columns.str.strip()
    df_excel = df_excel.rename(columns={'symbol': 'etf_code', 'sec_name': 'etf_name', 'name_cleaned': 'theme'})
    context.whitelist = set(df_excel['etf_code'])
    context.theme_map = df_excel.set_index('etf_code')['theme'].to_dict()

    # 数据加载 (使用 Cache 逻辑以对齐 main2)
    start_dt = (pd.Timestamp(START_DATE) - timedelta(days=400)).strftime('%Y-%m-%d %H:%M:%S')
    end_dt = END_DATE if context.mode == MODE_BACKTEST else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    cache_file = os.path.join(config.BASE_DIR, "backtest_data_cache.pkl")
    if os.path.exists(cache_file) and context.mode == MODE_BACKTEST:
        cache = pd.read_pickle(cache_file)
        context.prices_df, context.benchmark_df = cache['prices'], cache['benchmark']
    else:
        sym_str = ",".join(context.whitelist)
        hd = history(symbol=sym_str, frequency='1d', start_time=start_dt, end_time=end_dt, fields='symbol,close,eob', fill_missing='last', adjust=ADJUST_PREV, df=True)
        hd['eob'] = pd.to_datetime(hd['eob']).dt.tz_localize(None)
        context.prices_df = hd.pivot(index='eob', columns='symbol', values='close').ffill()
        
        bm_hd = history(symbol=MACRO_BENCHMARK, frequency='1d', start_time=start_dt, end_time=end_dt, fields='close,eob', fill_missing='last', adjust=ADJUST_PREV, df=True)
        bm_hd['eob'] = pd.to_datetime(bm_hd['eob']).dt.tz_localize(None)
        context.benchmark_df = bm_hd.set_index('eob')['close']
        if context.mode == MODE_BACKTEST:
             pd.to_pickle({'prices': context.prices_df, 'benchmark': context.benchmark_df}, cache_file)

    if context.mode == MODE_LIVE: context.rpm.load_state()
    
    subscribe(symbols=list(context.whitelist) if context.mode == MODE_LIVE else 'SHSE.000001', frequency='60s' if context.mode == MODE_LIVE else '1d')
    schedule(schedule_func=algo, date_rule='1d', time_rule='14:55:00')

def get_market_regime(context, current_dt):
    # 1/2 年线宏通风控 + 20/60日线微观风控
    hist = context.prices_df[context.prices_df.index <= current_dt]
    if len(hist) < 60: return 1.0
    bm_hist = context.benchmark_df[context.benchmark_df.index <= current_dt]
    
    macro_mult = 1.0
    if len(bm_hist) > 120 and bm_hist.iloc[-1] < bm_hist.tail(120).mean(): macro_mult = 0.5
    
    recent = hist.tail(60)
    strength = ((recent.iloc[-1] > recent.tail(20).mean()).mean() + (recent.iloc[-1] > recent.mean()).mean()) / 2
    base_pos = 1.0 if strength > 0.6 else 0.9 if strength > 0.4 else 0.3
    if macro_mult < 1.0 and strength <= 0.4: return 0.0
    return base_pos * macro_mult

def get_ranking(context, current_dt):
    # Meta-Gate 逻辑核心
    hist = context.prices_df[context.prices_df.index <= current_dt]
    if len(hist) < 251: return None, None
    last = hist.iloc[-1]
    
    # 动量评分
    scores = pd.Series(0.0, index=hist.columns)
    periods = {1: 30, 3: -70, 20: 150}
    rets = {f'r{p}': (last / hist.iloc[-(p+1)]) - 1 for p in [1, 3, 5, 20]}
    
    for p, pts in periods.items():
        ranks = rets[f'r{p}'].rank(ascending=False)
        scores += ((30 - ranks) / 30).clip(lower=0) * pts
    
    # Z-Score 结构门控 (核心防御)
    daily_rets = hist.pct_change()
    vol_ruler = daily_rets.iloc[:-5].tail(60).std().clip(lower=0.005)
    z_score = rets['r5'] / (vol_ruler * np.sqrt(5))
    
    # Meta-Gate 状态机
    k_crash = float(os.environ.get('OPT_K_CRASH', 2.5))
    universe_z = z_score[z_score.index.isin(context.whitelist)].dropna()
    if len(universe_z) >= 20:
        br_smooth = np.mean((context.br_history + [ (universe_z < -k_crash).mean() ])[-3:])
        context.br_history = (context.br_history + [ (universe_z < -k_crash).mean() ])[-3:]
        
        # 状态机维护
        danger_in = 0.5 if np.median(universe_z) < -2.3 else context.BR_DANGER_IN
        if context.market_state == 'SAFE' and br_smooth > context.BR_CAUTION_IN: context.market_state = 'CAUTION'
        elif context.market_state == 'CAUTION':
            if br_smooth > danger_in: context.market_state = 'DANGER'
            elif br_smooth < context.BR_CAUTION_OUT: context.market_state = 'SAFE'
        elif context.market_state == 'DANGER' and br_smooth < context.BR_DANGER_OUT: context.market_state = 'CAUTION'
        
        context.risk_scaler = 0.0 if context.market_state == 'DANGER' else (0.7 if br_smooth >= context.BR_PRE_DANGER else 1.0)

    # 过滤弱点
    k_entry = float(os.environ.get('OPT_R5_K', 1.6))
    valid = (scores * (z_score > -k_entry).astype(float)).loc[list(context.whitelist)]
    valid = valid[valid >= MIN_SCORE]
    if valid.empty: return None, scores
    
    df = pd.DataFrame({'score': valid, 'theme': [context.theme_map.get(c, 'Unknown') for c in valid.index]})
    for p in [1, 3, 5, 20]: df[f'r{p}'] = rets[f'r{p}'][valid.index]
    return df.sort_values(by=['score', 'r1', 'r20'], ascending=False), scores

def algo(context):
    current_dt = context.now.replace(tzinfo=None)
    
    # 注入实时行情 (Live)
    if context.mode == MODE_LIVE:
        ticks = current(symbols=list(context.whitelist))
        td = {t['symbol']: t['price'] for t in ticks if t['price'] > 0}
        if td:
            rows = pd.DataFrame([td], index=[current_dt.replace(hour=0,minute=0,second=0,microsecond=0)])
            context.prices_df = pd.concat([context.prices_df[~context.prices_df.index.isin(rows.index)], rows]).sort_index()

    context.rpm.days_count += 1
    if not context.rpm.initialized:
        acc = context.account()
        if acc: context.rpm.initialize_tranches(acc.cash.nav)
        else: return

    # 1. 更新价值与止损
    price_map = context.prices_df[context.prices_df.index <= current_dt].iloc[-1].to_dict()
    for t in context.rpm.tranches:
        t.update_value(price_map)
        to_sell = t.check_guard(price_map)
        if to_sell:
            t.guard_triggered_today = True
            for s in to_sell: t.sell(s, price_map.get(s, 0))
        else: t.guard_triggered_today = False

    # 2. 轮动调仓
    active_idx = (context.rpm.days_count - 1) % REBALANCE_PERIOD_T
    active_t = context.rpm.tranches[active_idx]
    for s in list(active_t.holdings.keys()): active_t.sell(s, price_map.get(s, 0))
    
    rank_df, _ = get_ranking(context, current_dt)
    if rank_df is not None and not active_t.guard_triggered_today:
        targets, themes = [], {}
        for code, row in rank_df.iterrows():
            if themes.get(row['theme'], 0) < MAX_PER_THEME:
                targets.append(code); themes[row['theme']] = themes.get(row['theme'], 0) + 1
            if len(targets) >= TOP_N: break
        
        if targets:
            scale = (get_market_regime(context, current_dt) if DYNAMIC_POSITION else 1.0) * (context.risk_scaler if ENABLE_META_GATE else 1.0)
            unit = (active_t.cash * 0.99 * scale) / (len(targets) + min(len(targets), 3)) # 前3只双倍
            for i, s in enumerate(targets):
                active_t.buy(s, unit * (2 if i < 3 else 1), price_map.get(s, 0))

    # 3. 最终同步
    tgt_qty = context.rpm.total_holdings
    for pos in context.account().positions():
        diff = pos.amount - tgt_qty.get(pos.symbol, 0)
        if diff > 0 and pos.available > 0:
            order_volume(symbol=pos.symbol, volume=int(min(diff, pos.available)), side=OrderSide_Sell, order_type=OrderType_Market, position_effect=PositionEffect_Close)
    
    for sym, qty in tgt_qty.items():
        order_target_volume(symbol=sym, volume=int(qty), position_side=PositionSide_Long, order_type=OrderType_Market)

    context.rpm.save_state()

def on_bar(context, bars):
    # 盘中高频止损 (追平实盘收益的关键)
    if context.mode == MODE_BACKTEST: return
    for bar in bars:
        for t in context.rpm.tranches:
            if bar.symbol in t.holdings:
                rec = t.pos_records.get(bar.symbol)
                if not rec: continue
                rec['high_price'] = max(rec['high_price'], bar.high)
                entry, high, curr = rec['entry_price'], rec['high_price'], bar.close
                if curr < entry * (1-STOP_LOSS) or (high > entry*(1+TRAILING_TRIGGER) and curr < high*(1-TRAILING_DROP)):
                    print(f"⚡ Guard Trigger: {bar.symbol}")
                    order_target_percent(symbol=bar.symbol, percent=0, position_side=PositionSide_Long, order_type=OrderType_Market)
                    t.sell(bar.symbol, curr)
                    context.rpm.save_state()

def on_backtest_finished(context, indicator):
    print(f"\n=== UPGRADED MAIN REPORT ===")
    print(f"Return: {indicator.get('pnl_ratio', 0)*100:.2f}% | MaxDD: {indicator.get('max_drawdown', 0)*100:.2f}% | Sharpe: {indicator.get('sharp_ratio', 0):.2f}")

if __name__ == '__main__':
    RUN_MODE = 'BACKTEST' 
    STRATEGY_ID = '60e6472f-01ac-11f1-a1c0-00ffda9d6e63'
    if RUN_MODE == 'MODE_LIVE':
        run(strategy_id=STRATEGY_ID, filename='main.py', mode=MODE_LIVE, token=os.getenv('MY_QUANT_TGM_TOKEN'))
    else:
        run(strategy_id=STRATEGY_ID, filename='main.py', mode=MODE_BACKTEST, token=os.getenv('MY_QUANT_TGM_TOKEN'), backtest_start_time=START_DATE, backtest_end_time=END_DATE, backtest_adjust=ADJUST_PREV, backtest_initial_cash=1000000, backtest_commission_ratio=0.0001)