# -*- coding: utf-8 -*-
import pandas as pd
from datetime import datetime
import sys
import os

# Windows 控制台 UTF-8，便于打印中文
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Add project root to path
sys.path.append(os.getcwd())

from config import config, logger
from core.portfolio import RollingPortfolioManager
from core.logic import calculate_target_holdings, calculate_position_scale
from core.signal import get_ranking
from gm.api import history, set_token, ADJUST_PREV, current
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


def _inject_today_bar(context):
    """
    用掘金 current() 拉取最新价，注入为「今天」的 K 线，
    使 get_ranking / 仓位计算基于今日数据。
    """
    today_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        ticks = current(symbols=list(context.whitelist))
        td = {t["symbol"]: t["price"] for t in ticks if t.get("price", 0) > 0}
        if td:
            row = pd.DataFrame(
                [td],
                index=[today_dt],
            )
            # 若已有今天日期则先去掉，再拼上当前实时
            context.prices_df = context.prices_df[context.prices_df.index != today_dt]
            context.prices_df = pd.concat([context.prices_df, row]).sort_index()
            context.prices_df = context.prices_df.ffill()
            print(f"Injected today bar: {today_dt.strftime('%Y-%m-%d')} ({len(td)} symbols)")
        else:
            print(f"No current prices for whitelist, using last bar date as data end.")
    except Exception as e:
        print(f"Warning: inject today bar failed ({e}), using history only.")

    try:
        bm_ticks = current(symbols=[config.MACRO_BENCHMARK])
        if bm_ticks and bm_ticks[0].get("price", 0) > 0:
            bm_val = bm_ticks[0]["price"]
            if today_dt not in context.benchmark_df.index:
                context.benchmark_df = pd.concat([
                    context.benchmark_df,
                    pd.Series([bm_val], index=[today_dt]),
                ]).sort_index()
    except Exception:
        pass


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
        hd = history(symbol=sym_str, frequency='1d', start_time=start_dt, end_time=end_dt,
                     fields='symbol,close,eob', fill_missing='last', adjust=ADJUST_PREV, df=True)
        hd['eob'] = pd.to_datetime(hd['eob']).dt.tz_localize(None)
        context.prices_df = hd.pivot(index='eob', columns='symbol', values='close').ffill()
        
        # Load benchmark for regime text
        bm_data = history(symbol=config.MACRO_BENCHMARK, frequency='1d', start_time=start_dt, end_time=end_dt,
                          fields='close,eob', fill_missing='last', adjust=ADJUST_PREV, df=True)
        bm_data['eob'] = pd.to_datetime(bm_data['eob']).dt.tz_localize(None)
        context.benchmark_df = bm_data.set_index('eob')['close']
        
        print(f"Data Loaded: {len(context.prices_df)} days (Up to {context.prices_df.index[-1]})")
        
    except Exception as e:
        print(f"Data Load Failed: {e}")
        sys.exit(1)

    # 2.5 注入今日实时行情，使选股基于“今天”的数据
    _inject_today_bar(context)

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
    
    # 实际用于选股的数据截止日期（行情最后一根 K 线）
    data_end_date = context.prices_df.index[-1].strftime("%Y-%m-%d") if not context.prices_df.empty else "N/A"
    
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
    
    # 2. 打印今日所选 ETF（标明数据截止日）
    today_etfs = list(weights_map.keys())
    today_str = datetime.now().strftime("%Y-%m-%d")
    print("\n" + "=" * 50)
    print("  今日所选 ETF")
    print(f"  数据截止: {data_end_date}" + (" (已含当日实时)" if data_end_date == today_str else ""))
    print("=" * 50)
    if today_etfs:
        for i, sym in enumerate(today_etfs, 1):
            name = context.name_map.get(sym, "—")
            w = weights_map[sym]
            print(f"  {i}. {sym}  {name}  (权重份数: {w})")
        print("=" * 50)
    else:
        print("  (无达标标的)")
        print("=" * 50)
    
    # 3. Calculate Scale
    scale, trend_scale, risk_scale = calculate_position_scale(context, current_dt)
    
    print(f"\nTraffic Lights:")
    print(f"  > Market State: {context.market_state}")
    print(f"  > Trend Scale:  {trend_scale:.2%}")
    print(f"  > Risk Scale:   {risk_scale:.2%}")
    print(f"  > Final Scale:  {scale:.2%}")
    
    total_w = sum(weights_map.values())
    
    print(f"\nActive Tranche Assets: {active_t.total_value:,.2f}")
    
    if total_w > 0:
        allocatable_value = active_t.total_value * 0.99 * scale
        unit_val = allocatable_value / total_w
        
        print(f"Allocatable (Scaled):  {allocatable_value:,.2f}")
        print("\n--- Target Execution Plan ---")
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
            
            print(f"{s:<12} {name:<14} {w:<8} {target_val:,.2f}      {current_val:,.2f}      {action:<10}")
            
    else:
        print("No targets identified (Weights map empty).")

    # 4. 验证选股逻辑是否正确
    verify_selection(context, current_dt, active_t, weights_map)


def verify_selection(context, current_dt, active_t, weights_map):
    """
    复现 core/logic 的选股步骤，与 calculate_target_holdings 结果对比，验证是否一致。
    """
    from collections import Counter
    rank_df, _ = get_ranking(context, current_dt)
    if rank_df is None:
        print("\n[验证] 跳过: get_ranking 返回空")
        return

    TOP_N = config.TOP_N
    MAX_PER_THEME = config.MAX_PER_THEME
    TURNOVER_BUFFER = config.TURNOVER_BUFFER

    # 2. 生成 candidates（与 logic.py 一致）
    candidates = []
    themes = {}
    for code, row in rank_df.iterrows():
        if themes.get(row["theme"], 0) < MAX_PER_THEME:
            candidates.append(code)
            themes[row["theme"]] = themes.get(row["theme"], 0) + 1

    core_targets = candidates[:TOP_N]
    buffer_targets = candidates[: TOP_N + TURNOVER_BUFFER]

    # 3. 软轮动
    existing_holdings = list(active_t.holdings.keys())
    kept_holdings = []
    current_slots_used = 0
    for s in existing_holdings:
        if s in buffer_targets and current_slots_used < TOP_N:
            kept_holdings.append(s)
            current_slots_used += 1
    targets_to_buy = []
    for s in core_targets:
        if current_slots_used >= TOP_N:
            break
        if s not in kept_holdings:
            targets_to_buy.append(s)
            current_slots_used += 1
    final_list = kept_holdings + targets_to_buy

    # 4. 期望权重
    expected_weights = {}
    for i, s in enumerate(candidates):
        if s in final_list:
            w = 3 if (config.WEIGHT_SCHEME != "EQUAL" and i == 0) else 1
            expected_weights[s] = w

    # 对比与规则检查
    actual_set = set(weights_map.keys())
    expected_set = set(final_list)
    ok = True
    msgs = []

    if actual_set != expected_set:
        ok = False
        msgs.append(f"  选股集合不一致: 实际={actual_set}, 期望={expected_set}")
    for s in actual_set:
        if weights_map.get(s) != expected_weights.get(s):
            ok = False
            msgs.append(f"  权重不一致 {s}: 实际={weights_map.get(s)}, 期望={expected_weights.get(s)}")

    theme_counts = Counter(context.theme_map.get(s, "") for s in final_list)
    for theme, cnt in theme_counts.items():
        if cnt > MAX_PER_THEME:
            ok = False
            msgs.append(f"  主题 {theme} 超过 MAX_PER_THEME={MAX_PER_THEME}: {cnt} 只")

    expected_sum = 6 if (config.WEIGHT_SCHEME != "EQUAL") else 4
    if sum(weights_map.values()) != expected_sum:
        ok = False
        msgs.append(f"  权重份数之和应为 {expected_sum}, 实际={sum(weights_map.values())}")

    # 打印验证报告
    print("\n" + "=" * 50)
    print("  选股验证 (与 core/logic 复现对比)")
    print("=" * 50)
    print("  排名前 6 (score 降序):")
    for i, (code, row) in enumerate(rank_df.head(6).iterrows(), 1):
        name = (context.name_map.get(code, "") or "")[:16]
        print(f"    {i}. {code}  {name}  score={row['score']:.1f}  theme={row['theme']}")
    print("  candidates (主题约束后):", candidates[: TOP_N + TURNOVER_BUFFER])
    print("  core_targets (前4):     ", core_targets)
    print("  buffer_targets (前6):  ", buffer_targets)
    print("  final_list (最终4只):  ", final_list)
    print("  主题分布:              ", dict(theme_counts))
    if ok:
        print("  结果: 通过 (选股与权重与 logic 一致)")
    else:
        print("  结果: 未通过")
        for m in msgs:
            print(m)
    print("=" * 50)


if __name__ == "__main__":
    run_simulation()
