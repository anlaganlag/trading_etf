"""
策略核心模块
- algo: 主调仓逻辑
- on_bar: 盘中止损监控
- on_backtest_finished: 回测结束报告
"""
import pandas as pd
from gm.api import (
    MODE_BACKTEST, MODE_LIVE, current,
    order_volume, order_target_volume, order_target_percent,
    OrderSide_Sell, OrderType_Market,
    PositionEffect_Close, PositionSide_Long
)
from config import config
from .signal import get_market_regime, get_ranking


def algo(context):
    """主调仓逻辑 - 每日定时执行"""
    current_dt = context.now.replace(tzinfo=None)

    # === 风控前置检查 (仅实盘) ===
    if context.mode == MODE_LIVE:
        context.risk_safe.on_day_start(context)
        if not context.risk_safe.check_daily_loss(context):
            print(f"⚠️ [ALGO] 触发熔断，今日不交易")
            return

    # 注入实时行情 (Live)
    if context.mode == MODE_LIVE:
        ticks = current(symbols=list(context.whitelist))
        td = {t['symbol']: t['price'] for t in ticks if t['price'] > 0}
        if td:
            rows = pd.DataFrame(
                [td], 
                index=[current_dt.replace(hour=0, minute=0, second=0, microsecond=0)]
            )
            context.prices_df = pd.concat([
                context.prices_df[~context.prices_df.index.isin(rows.index)], 
                rows
            ]).sort_index()

    context.rpm.days_count += 1
    if not context.rpm.initialized:
        acc = (context.account(account_id=context.account_id) 
               if context.mode == MODE_LIVE else context.account())
        if acc:
            context.rpm.initialize_tranches(acc.cash.nav)
        else:
            return

    # 1. 更新价值与止损
    price_map = context.prices_df[context.prices_df.index <= current_dt].iloc[-1].to_dict()
    for t in context.rpm.tranches:
        t.update_value(price_map)
        to_sell = t.check_guard(price_map, current_dt)
        if to_sell:
            t.guard_triggered_today = True
            for s in to_sell:
                t.sell(s, price_map.get(s, 0))
        else:
            t.guard_triggered_today = False

    # 2. 轮动调仓 (Soft Rotation)
    active_idx = (context.rpm.days_count - 1) % config.REBALANCE_PERIOD_T
    active_t = context.rpm.tranches[active_idx]

    rank_df, _ = get_ranking(context, current_dt)
    if rank_df is not None and not active_t.guard_triggered_today:
        # 动态 TOP_N
        if config.DYNAMIC_TOP_N:
            current_top_n = config.TOP_N_BY_STATE.get(context.market_state, config.TOP_N)
        else:
            current_top_n = config.TOP_N

        # A. 生成目标候选名单
        candidates = []
        themes = {}
        for code, row in rank_df.iterrows():
            if themes.get(row['theme'], 0) < config.MAX_PER_THEME:
                candidates.append(code)
                themes[row['theme']] = themes.get(row['theme'], 0) + 1

        core_targets = candidates[:current_top_n]
        buffer_targets = candidates[:current_top_n + config.TURNOVER_BUFFER]

        # B. 智能保留逻辑
        existing_holdings = list(active_t.holdings.keys())
        kept_holdings = []
        targets_to_buy = []

        current_slots_used = 0
        for s in existing_holdings:
            if s in buffer_targets and current_slots_used < current_top_n:
                kept_holdings.append(s)
                current_slots_used += 1
            else:
                active_t.sell(s, price_map.get(s, 0))

        # C. 填充新标的
        for s in core_targets:
            if current_slots_used >= current_top_n:
                break
            if s not in kept_holdings:
                targets_to_buy.append(s)
                current_slots_used += 1

        # D. 执行买入
        scale = (
            (get_market_regime(context, current_dt) if config.DYNAMIC_POSITION else 1.0) *
            (context.risk_scaler if config.ENABLE_META_GATE else 1.0)
        )

        final_list = kept_holdings + targets_to_buy
        weights = {
            s: (2 if i < 3 else 1) 
            for i, s in enumerate(candidates) if s in final_list
        }
        total_w = sum(weights.values())
        
        if total_w > 0:
            unit_val = (active_t.total_value * 0.99 * scale) / total_w
            for s in final_list:
                target_val = unit_val * weights[s]
                current_val = active_t.holdings.get(s, 0) * price_map.get(s, 0)
                diff_val = target_val - current_val

                if diff_val > 0:
                    vol = None
                    if config.DYNAMIC_STOP_LOSS:
                        hist = context.prices_df[context.prices_df.index <= current_dt]
                        if s in hist.columns and len(hist) > config.ATR_LOOKBACK:
                            daily_rets = hist[s].pct_change().dropna()
                            if len(daily_rets) >= config.ATR_LOOKBACK:
                                vol = daily_rets.tail(config.ATR_LOOKBACK).std()
                    active_t.buy(s, diff_val, price_map.get(s, 0), current_dt, vol)
                elif diff_val < -100:
                    if abs(diff_val) > target_val * 0.2:
                        qty = int(abs(diff_val) / price_map.get(s, 1) / 100) * 100
                        if qty > 0:
                            active_t.sell_qty(s, qty, price_map.get(s, 0))
    else:
        # 排名失败或当天止损，全卖
        for s in list(active_t.holdings.keys()):
            active_t.sell(s, price_map.get(s, 0))

    # 3. 最终同步
    tgt_qty = context.rpm.total_holdings
    acc = (context.account(account_id=context.account_id) 
           if context.mode == MODE_LIVE else context.account())
    for pos in acc.positions():
        diff = pos.amount - tgt_qty.get(pos.symbol, 0)
        if diff > 0 and pos.available > 0:
            order_volume(
                symbol=pos.symbol,
                volume=int(min(diff, pos.available)),
                side=OrderSide_Sell,
                order_type=OrderType_Market,
                position_effect=PositionEffect_Close
            )

    for sym, qty in tgt_qty.items():
        order_target_volume(
            symbol=sym,
            volume=int(qty),
            position_side=PositionSide_Long,
            order_type=OrderType_Market
        )

    context.rpm.save_state()

    # === 每日收盘汇报 (仅实盘) ===
    if context.mode == MODE_LIVE:
        print(f"📤 Sending Daily Reports...")
        context.mailer.send_report(context)
        context.wechat.send_report(context)


def on_bar(context, bars):
    """盘中高频止损"""
    if context.mode == MODE_BACKTEST:
        return
    
    bar_dt = context.now.replace(tzinfo=None)
    for bar in bars:
        for t in context.rpm.tranches:
            if bar.symbol in t.holdings:
                rec = t.pos_records.get(bar.symbol)
                if not rec:
                    continue

                # 保护期检查
                entry_dt = rec.get('entry_dt')
                if entry_dt and config.PROTECTION_DAYS > 0:
                    days_held = (bar_dt - entry_dt).days
                    if days_held <= config.PROTECTION_DAYS:
                        continue

                rec['high_price'] = max(rec['high_price'], bar.high)
                entry, high, curr = rec['entry_price'], rec['high_price'], bar.close
                
                is_stop = (
                    curr < entry * (1 - config.STOP_LOSS) or
                    (high > entry * (1 + config.TRAILING_TRIGGER) and 
                     curr < high * (1 - config.TRAILING_DROP))
                )
                
                if is_stop:
                    print(f"⚡ Guard Trigger: {bar.symbol}")
                    order_target_percent(
                        symbol=bar.symbol,
                        percent=0,
                        position_side=PositionSide_Long,
                        order_type=OrderType_Market
                    )
                    t.sell(bar.symbol, curr)
                    context.rpm.save_state()


def on_backtest_finished(context, indicator):
    """回测结束报告"""
    dsl_status = (
        f"ATR*{config.ATR_MULTIPLIER}" if config.DYNAMIC_STOP_LOSS 
        else f"Fixed {config.STOP_LOSS*100:.0f}%"
    )
    dtn_status = "Dynamic" if config.DYNAMIC_TOP_N else f"Fixed {config.TOP_N}"
    
    print(f"\n=== REPORT (BUFFER={config.TURNOVER_BUFFER}, SL={dsl_status}, TOP_N={dtn_status}) ===")
    print(f"Return: {indicator.get('pnl_ratio', 0)*100:.2f}% | "
          f"MaxDD: {indicator.get('max_drawdown', 0)*100:.2f}% | "
          f"Sharpe: {indicator.get('sharp_ratio', 0):.2f}")
