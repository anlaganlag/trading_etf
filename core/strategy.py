"""
策略核心模块
- algo: 主调仓逻辑
- on_bar: 盘中止损监控
- on_backtest_finished: 回测结束报告
- verify_orders: 订单成交验证
"""
import time
import pandas as pd
from gm.api import (
    MODE_BACKTEST, MODE_LIVE, current,
    order_volume, order_target_volume, order_target_percent,
    get_orders,
    OrderSide_Buy, OrderSide_Sell, OrderType_Market,
    PositionEffect_Open, PositionEffect_Close, PositionSide_Long
)

# 订单状态常量（GM API可能不提供，使用整数值）
try:
    from gm.api import OrderStatus_Filled, OrderStatus_PartFilled, OrderStatus_Canceled, OrderStatus_Rejected
except ImportError:
    # 如果GM API不提供这些常量，使用整数值
    # 参考GM API文档的订单状态定义
    OrderStatus_Filled = 3        # 完全成交
    OrderStatus_PartFilled = 2    # 部分成交
    OrderStatus_Canceled = 5      # 已撤销
    OrderStatus_Rejected = 8      # 已拒绝 (常见于实盘 status=8)
    # 增加额外备用常量
    OrderStatus_New = 1           # 已报
    OrderStatus_Expired = 12       # 已过期
    OrderStatus_Accepted = 14      # 已受理

from config import config, logger
from .account import get_account
from .signal import get_market_regime, get_ranking


def verify_orders(context, submitted_orders, wait_seconds=30):
    """
    验证订单成交情况

    策略: 
    1. 调用 get_orders() 获取今日全部订单（含最新状态）
    2. 按 (symbol, side) 匹配我们提交的订单
    3. 报告成交/未成交情况

    Args:
        context: GM context对象
        submitted_orders: 订单列表 [{'order': order_obj, 'symbol': sym, 'side': 'BUY'/'SELL'}, ...]
        wait_seconds: 等待时间（秒）

    Returns:
        dict: {'all_filled': bool, 'failed_orders': list}
    """
    if not submitted_orders or context.mode != MODE_LIVE:
        return {'all_filled': True, 'failed_orders': []}

    logger.info(f"⏳ 等待 {wait_seconds} 秒检查 {len(submitted_orders)} 个订单成交...")
    time.sleep(wait_seconds)

    # ========== 从服务器获取最新订单状态 ==========
    # 1. cl-ord-id -> order 映射 (全球唯一匹配)
    latest_orders_id_map = {}
    # 2. (symbol, gm_side) -> [order, ...] 映射 (备用匹配)
    latest_orders_sym_map = {}  

    try:
        all_today_orders = get_orders()
        if all_today_orders:
            target_account_id = context.account_id
            for o in all_today_orders:
                # 统一转为 dict 风格读取
                if not isinstance(o, dict):
                    oid = getattr(o, 'cl_ord_id', None)
                    acc = getattr(o, 'account_id', None)
                    sym = getattr(o, 'symbol', '')
                    side = getattr(o, 'side', 0)
                else:
                    oid = o.get('cl_ord_id')
                    acc = o.get('account_id')
                    sym = o.get('symbol', '')
                    side = o.get('side', 0)
                
                # 核心过滤：必须属于当前账户
                if acc != target_account_id:
                    continue
                
                # 记录到 ID 映射表
                if oid:
                    latest_orders_id_map[oid] = o
                
                # 记录到品种映射表 (用于 fallback)
                key = (sym, side)
                if key not in latest_orders_sym_map:
                    latest_orders_sym_map[key] = []
                latest_orders_sym_map[key].append(o)
            
            logger.info(f"📋 从服务器获取到 {len(all_today_orders)} 个订单，所属账户过滤后剩余 {len(latest_orders_id_map)} 个 ID 匹配项")
        else:
            logger.warning("⚠️ get_orders() 返回空列表")
    except Exception as e:
        logger.warning(f"⚠️ get_orders() 调用失败: {e}")

    # GM API side 常量: 1=Buy, 2=Sell
    SIDE_MAP = {'BUY': 1, 'SELL': 2}

    failed_orders = []

    for order_info in submitted_orders:
        order = order_info['order']
        sym = order_info['symbol']
        side_str = order_info['side']
        gm_side = SIDE_MAP.get(side_str, 0)

        try:
            live_order = None
            cl_ord_id = getattr(order, 'cl_ord_id', None)

            # 策略 A: 优先使用身份证 (cl_ord_id) 匹配
            if cl_ord_id and cl_ord_id in latest_orders_id_map:
                live_order = latest_orders_id_map[cl_ord_id]
                match_type = "ID"
            else:
                # 策略 B: 使用品种 + 方向匹配 (fallback)
                key = (sym, gm_side)
                matched_list = latest_orders_sym_map.get(key, [])
                if matched_list:
                    live_order = matched_list[-1]
                    match_type = "SYM"
            
            if live_order:
                # 兼容读取
                if isinstance(live_order, dict):
                    status = live_order.get('status')
                    filled_vol = live_order.get('filled_volume', 0)
                    total_vol = live_order.get('volume', 0)
                else:
                    status = getattr(live_order, 'status', None)
                    filled_vol = getattr(live_order, 'filled_volume', 0)
                    total_vol = getattr(live_order, 'volume', 0)
                # logger.debug(f"🔍 [{match_type}] {sym} {side_str} status={status}")
            else:
                status = None
                filled_vol = 0
                total_vol = 0
                logger.warning(f"⚠️ 在服务器历史中找不到该订单: {sym} {side_str}")

            # 判断状态
            if status == OrderStatus_Filled:
                logger.info(f"✅ 订单已成交: {sym} {side_str} ({filled_vol}/{total_vol})")
            elif status == OrderStatus_PartFilled:
                logger.warning(
                    f"⚠️ 订单部分成交: {sym} "
                    f"{side_str} ({filled_vol}/{total_vol})"
                )
                failed_orders.append({
                    'symbol': sym,
                    'side': side_str,
                    'status': '部分成交',
                    'filled': filled_vol,
                    'total': total_vol
                })
            elif status in (OrderStatus_Canceled, OrderStatus_Rejected, 6, 8):
                reason = "已拒绝" if status in (OrderStatus_Rejected, 6, 8) else "已取消"
                logger.error(
                    f"❌ 订单失败: {sym} "
                    f"{side_str} (状态: {status}, {reason})"
                )
                failed_orders.append({
                    'symbol': sym,
                    'side': side_str,
                    'status': reason,
                    'code': status
                })
            elif status is None:
                logger.warning(
                    f"⚠️ 订单状态无法确认: {sym} {side_str} - 请在券商端手动确认"
                )
                failed_orders.append({
                    'symbol': sym,
                    'side': side_str,
                    'status': '无法确认(请手动检查)'
                })
            else:
                # status 有值但不是已知状态码
                logger.info(f"ℹ️ 订单状态码: {sym} {side_str} status={status} filled={filled_vol}/{total_vol}")
                # GM API 状态码: 1=已报, 3=已成, 等。如果不在已知常量中，不一定是错误
                # 保守处理：不标记为失败
                if filled_vol and total_vol and filled_vol >= total_vol:
                    logger.info(f"✅ 订单已成交(按量确认): {sym} {side_str} ({filled_vol}/{total_vol})")
                else:
                    logger.warning(f"⚠️ 订单状态未知: {sym} {side_str} (status={status}, filled={filled_vol}/{total_vol})")
                    failed_orders.append({
                        'symbol': sym,
                        'side': side_str,
                        'status': f'未知状态({status})'
                    })

        except Exception as e:
            logger.error(f"❌ 检查订单状态失败: {sym} - {e}")
            failed_orders.append({
                'symbol': sym,
                'side': side_str,
                'status': f'检查失败: {str(e)[:50]}'
            })

    # 发送汇总通知
    filled_count = len(submitted_orders) - len(failed_orders)
    if failed_orders:
        logger.warning(f"⚠️ {filled_count}/{len(submitted_orders)} 确认成交, {len(failed_orders)} 笔需注意")
        try:
            msg_lines = [f"⚠️ 订单验证汇总 ({filled_count} 成交 / {len(failed_orders)} 异常)"]
            for order in failed_orders[:5]:
                msg_lines.append(f"- {order['symbol']} {order['side']}: {order['status']}")
            if len(failed_orders) > 5:
                msg_lines.append(f"... 及其他 {len(failed_orders)-5} 个")
            context.wechat.send_text("\n".join(msg_lines))
        except Exception as e:
            logger.warning(f"⚠️ 微信通知失败: {e}")
    else:
        logger.info(f"✅ 全部 {len(submitted_orders)} 笔订单已成交")
        try:
            context.wechat.send_text(f"✅ 全部 {len(submitted_orders)} 笔订单已确认成交")
        except:
            pass

    return {
        'all_filled': len(failed_orders) == 0,
        'failed_orders': failed_orders
    }


def algo(context):
    """主调仓逻辑 - 每日定时执行"""
    current_dt = context.now.replace(tzinfo=None)
    logger.info(f"--- 🏁 Algo Triggered at {current_dt} ---")

    # === 风控前置检查 (仅实盘) ===
    if context.mode == MODE_LIVE:
        context.risk_controller.on_day_start(context)
        if not context.risk_controller.check_daily_loss(context):
            logger.warning(f"🧨 [ALGO] 触发每日亏损熔断，今日跳过交易")
            return

    # 注入实时行情 (Live)
    if context.mode == MODE_LIVE:
        logger.debug("💉 Injecting realtime ticks into prices_df...")
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
    
    # 如果已从状态文件加载，直接使用
    if context.rpm.initialized:
        logger.debug(f"✅ Portfolio Manager already initialized from state file")
    else:
        logger.info("🆕 Initializing Portfolio Manager...")
        try:
            if context.mode == MODE_LIVE:
                logger.info(f"📋 Attempting to get account: {context.account_id}")
                # 尝试多种方式获取账户
                acc = None
                try:
                    # 方式1: 使用 account_id 参数
                    acc = context.account(account_id=context.account_id)
                    logger.info(f"   Method 1 (with account_id): {'✅ Success' if acc else '❌ Failed'}")
                except Exception as e1:
                    logger.warning(f"   Method 1 exception: {e1}")
                
                if not acc:
                    try:
                        # 方式2: 不使用参数（可能返回默认账户）
                        acc = context.account()
                        logger.info(f"   Method 2 (no params): {'✅ Success' if acc else '❌ Failed'}")
                        if acc and hasattr(acc, 'account_id'):
                            logger.info(f"   Retrieved account ID: {acc.account_id}")
                    except Exception as e2:
                        logger.warning(f"   Method 2 exception: {e2}")
            else:
                acc = context.account()
            
            if acc:
                nav = acc.cash.nav if hasattr(acc, 'cash') and hasattr(acc.cash, 'nav') else 0.0
                if nav > 0:
                    context.rpm.initialize_tranches(nav)
                    logger.info(f"💰 Initialized {config.REBALANCE_PERIOD_T} tranches with NAV: {nav:,.2f}")
                else:
                    logger.warning(f"⚠️ Account NAV is 0: {nav}")
                    # 尝试从状态文件恢复
                    if hasattr(context.rpm, 'tranches') and len(context.rpm.tranches) > 0:
                        total_val = sum(t.total_value for t in context.rpm.tranches)
                        if total_val > 0:
                            logger.info(f"📊 Using state file value: {total_val:,.2f}")
                            context.rpm.initialized = True
                        else:
                            logger.error("❌ Cannot initialize: Account NAV is 0 and no valid state")
                            return
                    else:
                        # 如果状态文件也没有，尝试重新加载
                        logger.warning("⚠️ Attempting to reload state file...")
                        if context.rpm.load_state():
                            logger.info("✅ Successfully loaded from state file")
                        else:
                            logger.error("❌ Cannot initialize: Account NAV is 0 and state file unavailable")
                            logger.error("   Please check account ID and ensure account has funds")
                            return
            else:
                logger.error(f"❌ Failed to get account info. Account ID: {getattr(context, 'account_id', 'N/A')}")
                logger.error("   Possible reasons:")
                logger.error("   1. Invalid account ID")
                logger.error("   2. No permission to access this account")
                logger.error("   3. Account not found in GM platform")
                # 尝试从状态文件恢复
                logger.warning("⚠️ Attempting to use state file as fallback...")
                if context.rpm.load_state():
                    logger.info("✅ Successfully loaded from state file")
                else:
                    logger.error("❌ Cannot proceed: Account unavailable and no state file")
                    return
        except Exception as e:
            logger.error(f"❌ Exception while getting account: {e}")
            logger.error(f"   Account ID: {getattr(context, 'account_id', 'N/A')}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            # 尝试从状态文件恢复
            logger.warning("⚠️ Attempting to use state file as fallback...")
            if context.rpm.load_state():
                logger.info("✅ Successfully loaded from state file")
            else:
                logger.error("❌ Cannot proceed: Exception and no state file")
                return
    # === 🛡️ 安全检查：确保价格数据切片正确 ===
    prices_slice = context.prices_df[context.prices_df.index <= current_dt]

    # 1. 更新价值与止损
    if prices_slice.empty:
        logger.warning(f"⚠️ [ALGO] No price data available up to {current_dt}")
        return

    # 生成价格映射，过滤NaN值
    latest_prices = prices_slice.iloc[-1]
    price_map = {}
    missing_symbols = []

    for sym in context.whitelist:
        if sym in latest_prices.index:
            price = latest_prices[sym]
            if pd.notna(price) and price > 0:
                price_map[sym] = price
            else:
                # 尝试使用前一日价格
                if len(prices_slice) > 1:
                    prev_price = prices_slice[sym].iloc[-2]
                    if pd.notna(prev_price) and prev_price > 0:
                        logger.warning(f"⚠️ {sym} 今日数据缺失，使用昨日价格 {prev_price:.3f}")
                        price_map[sym] = prev_price
                    else:
                        missing_symbols.append(sym)
                else:
                    missing_symbols.append(sym)
        else:
            missing_symbols.append(sym)

    # 如果有缺失数据，发送警报
    if missing_symbols:
        logger.error(f"❌ {len(missing_symbols)} 个标的价格数据缺失: {missing_symbols}")
        try:
            context.wechat.send_text(
                f"⚠️ 价格数据缺失警报\n"
                f"缺失标的: {len(missing_symbols)} 个\n" +
                "\n".join([f"- {s}" for s in missing_symbols[:5]]) +
                (f"\n... 及其他 {len(missing_symbols)-5} 个" if len(missing_symbols) > 5 else "")
            )
        except Exception as e:
            logger.warning(f"⚠️ 微信通知失败: {e}")
    for t in context.rpm.tranches:
        t.update_value(price_map)
        to_sell = t.check_guard(price_map, current_dt)
        if to_sell:
            t.guard_triggered_today = True
            logger.warning(f"🛡️ [Tranche {t.id}] Guard Triggered! Selling: {to_sell}")
            for s in to_sell:
                t.sell(s, price_map.get(s, 0))
        else:
            t.guard_triggered_today = False

    # 2. 轮动调仓 (Soft Rotation) - logic delegated to core/logic.py
    active_idx = (context.rpm.days_count - 1) % config.REBALANCE_PERIOD_T
    active_t = context.rpm.tranches[active_idx]
    logger.info(f"🔄 Processing Tranche Index: {active_idx} (Day {context.rpm.days_count})")

    from core.logic import calculate_target_holdings, calculate_position_scale
    
    if not active_t.guard_triggered_today:
        # A. 计算目标持仓权力重 (纯权重份数)
        weights_map = calculate_target_holdings(context, current_dt, active_t, price_map)
        
        # B. 计算目标总仓位比例
        scale, trend_scale, risk_scale = calculate_position_scale(context, current_dt)
        logger.info(f"🚦 Market State: {context.market_state} | Scale: {scale:.2%} (Trend:{trend_scale:.0%} * Risk:{risk_scale:.0%})")
        
        # C. 挂载给邮件报告使用
        context.today_weights = weights_map
        context.today_scale_info = {'scale': scale, 'trend_scale': trend_scale, 'risk_scale': risk_scale}
        try:
            rank_df, _ = get_ranking(context, current_dt)
            context.today_targets = rank_df.head(config.TOP_N + 2) if rank_df is not None else None
        except Exception:
            context.today_targets = None
        
        final_list = list(weights_map.keys())
        total_w = sum(weights_map.values())
        
        if total_w > 0:
            unit_val = (active_t.total_value * 0.99 * scale) / total_w
            for s, w in weights_map.items():
                target_val = unit_val * w
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
                    logger.info(f"🛒 [Tranche {active_idx}] Buying {s} | W:{w} | Target Val: {target_val:,.0f}")
                elif diff_val < -100:
                    if abs(diff_val) > target_val * 0.2:
                        qty = int(abs(diff_val) / price_map.get(s, 1) / 100) * 100
                        if qty > 0:
                            active_t.sell_qty(s, qty, price_map.get(s, 0))
    else:
        logger.warning(f"⚠️ [ALGO] Ranking failed or guard triggered today. Tranche {active_idx} liquidation.")
        for s in list(active_t.holdings.keys()):
            active_t.sell(s, price_map.get(s, 0))

    # 3. 最终同步 (Order Execution)
    tgt_qty = context.rpm.total_holdings
    
    # 获取账户信息（带 fallback：指定 account_id 不可用时尝试默认账户）
    try:
        acc = get_account(context)
    except Exception as e:
        logger.error(f"❌ Failed to get account in sync_orders: {e}")
        return
    
    if not acc:
        logger.error("❌ Failed to sync: Account object is None")
        return

    order_summary = []
    submitted_orders = []  # 记录提交的订单（用于验证）

    # A. 卖出多余持仓
    # A. 卖出多余持仓 (强制整百，除非清仓)
    for pos in acc.positions():
        target = tgt_qty.get(pos.symbol, 0)
        diff = pos.amount - target
        if diff > 0 and pos.available > 0:
            if target <= 0:
                # 目标清仓：如果可用资产涵盖了全部持仓，则允许一次性卖出碎股
                if pos.available >= pos.amount:
                    vol_to_sell = int(pos.amount)
                else:
                    # 否则只能卖出整百部分
                    vol_to_sell = (int(pos.available) // 100) * 100
            else:
                # 目标减仓：强制整百卖出
                vol_to_sell = (int(min(diff, pos.available)) // 100) * 100
            
            if vol_to_sell > 0:
                order = order_volume(
                    symbol=pos.symbol,
                    volume=vol_to_sell,
                    side=OrderSide_Sell,
                    order_type=OrderType_Market,
                    position_effect=PositionEffect_Close,
                    account=context.account_id if context.mode == MODE_LIVE else ""
                )
                order_summary.append(f"SELL {pos.symbol} {vol_to_sell}股")
                submitted_orders.append({'order': order, 'symbol': pos.symbol, 'side': 'SELL'})

    # B. 买入目标仓位 (强制整百)
    for sym, target_qty in tgt_qty.items():
        if target_qty > 0:
            # 获取当前持仓
            pos = next((p for p in acc.positions() if p.symbol == sym), None)
            current_amount = pos.amount if pos else 0
            
            if target_qty > current_amount:
                # 计算买入缺口并下取整到100
                diff = target_qty - current_amount
                vol_to_buy = (int(diff) // 100) * 100
                
                if vol_to_buy > 0:
                    order = order_volume(
                        symbol=sym,
                        volume=vol_to_buy,
                        side=OrderSide_Buy,
                        order_type=OrderType_Market,
                        position_effect=PositionEffect_Open,
                        account=context.account_id if context.mode == MODE_LIVE else ""
                    )
                    order_summary.append(f"BUY  {sym} {vol_to_buy}股")
                    submitted_orders.append({'order': order, 'symbol': sym, 'side': 'BUY'})

    # === 订单成交验证（仅实盘） ===
    if context.mode == MODE_LIVE and submitted_orders:
        logger.info(f"📋 已提交 {len(submitted_orders)} 个订单，开始验证成交...")
        verification_result = verify_orders(context, submitted_orders, wait_seconds=30)

        if not verification_result['all_filled']:
            logger.warning(f"⚠️ 部分订单未成交，详见微信通知")

    # === 保存状态（关键步骤） ===
    try:
        context.rpm.save_state()
        logger.info("📝 State saved successfully")
    except Exception as e:
        logger.error(f"💥 状态保存失败，策略将停止: {e}")
        # 发送紧急通知
        try:
            context.wechat.send_text(
                f"🆘 状态保存失败!\n"
                f"错误: {str(e)[:100]}\n"
                f"时间: {current_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"建议: 检查磁盘空间和文件权限"
            )
        except:
            pass
        # 重新抛出异常，触发自动重启
        raise

    # === 每日收盘汇报 (仅实盘) ===
    if context.mode == MODE_LIVE:
        logger.info("📤 Algorithm finished. Triggering notifications...")
        
        # --- 收集邮件报告所需数据 ---
        context.today_order_summary = order_summary  # ['BUY xxx 1000股', ...]
        context.today_active_tranche_idx = active_idx
        
        # 收集排名 & 权重（可能在上面的分支中已计算）
        if not hasattr(context, 'today_targets'):
            # 如果还没挂载（例如 guard 触发跳过了排名），尝试重新计算
            try:
                rank_df, _ = get_ranking(context, current_dt)
                if rank_df is not None:
                    context.today_targets = rank_df.head(config.TOP_N)
                else:
                    context.today_targets = None
            except Exception:
                context.today_targets = None
        
        if not hasattr(context, 'today_weights'):
            context.today_weights = {}
        if not hasattr(context, 'today_scale_info'):
            try:
                s, ts, rs = calculate_position_scale(context, current_dt)
                context.today_scale_info = {'scale': s, 'trend_scale': ts, 'risk_scale': rs}
            except Exception:
                context.today_scale_info = {'scale': 1.0, 'trend_scale': 1.0, 'risk_scale': 1.0}
        
        # 实时微信简报
        if order_summary:
            summary_text = "📦 今日交易执行:\n" + "\n".join(order_summary)
        else:
            summary_text = "😴 今日持仓未变 (或已达标)"
            
        context.wechat.send_text(f"🏁 交易触发完毕\n指数状态: {context.market_state}\n当前切片: {active_idx}\n{summary_text}")
        
        context.mailer.send_report(context)
        context.wechat.send_report(context)


def on_bar(context, bars):
    """盘中高频止损监控"""
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
                    logger.warning(f"⚡ [on_bar] Guard Trigger for {bar.symbol}! Liquidating.")
                    order_target_percent(
                        symbol=bar.symbol,
                        percent=0,
                        position_side=PositionSide_Long,
                        order_type=OrderType_Market
                    )
                    t.sell(bar.symbol, curr)
                    # 保存状态（止损后）
                    try:
                        context.rpm.save_state()
                    except Exception as e:
                        logger.error(f"❌ 止损后状态保存失败: {e}")
                        # 止损情况下保存失败不中断策略，只记录警告
                        # 因为订单已提交，下次启动会重新同步


def on_backtest_finished(context, indicator):
    """回测结束报告"""
    dsl_status = (
        f"ATR*{config.ATR_MULTIPLIER}" if config.DYNAMIC_STOP_LOSS 
        else f"Fixed {config.STOP_LOSS*100:.0f}%"
    )
    dtn_status = "Dynamic" if config.DYNAMIC_TOP_N else f"Fixed {config.TOP_N}"
    
    logger.info("=" * 60)
    logger.info(f"📊 BACKTEST REPORT (BUFFER={config.TURNOVER_BUFFER}, SL={dsl_status}, TOP_N={dtn_status})")
    logger.info(f"🚀 Return: {indicator.get('pnl_ratio', 0)*100:.2f}%")
    logger.info(f"📉 MaxDD: {indicator.get('max_drawdown', 0)*100:.2f}%")
    logger.info(f"💎 Sharpe: {indicator.get('sharp_ratio', 0):.2f}")
    logger.info("=" * 60)
