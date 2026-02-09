"""
实盘运行主入口 - 强化健壮版
1. 自动重连机制 (Auto-Reconnect)
2. 守护进程心跳 (Heartbeat Monitoring)
3. 异常捕获与微信报警
4. 日志自动清理
"""
import time
import os
import glob
import threading
from datetime import datetime, timedelta
from gm.api import run, set_token, MODE_LIVE, ADJUST_PREV
from config import config, logger, validate_env
from core.strategy import algo, on_bar, on_backtest_finished
from core.portfolio import RollingPortfolioManager
from core.risk import RiskController
from core.notify import EnterpriseWeChat, EmailNotifier

import pandas as pd

# === 心跳监控配置 ===
HEARTBEAT_INTERVAL_HOURS = 4  # 每4小时发送一次心跳
LOG_RETENTION_DAYS = 7        # 日志保留天数

# 全局心跳线程控制
_heartbeat_stop_event = threading.Event()

def _heartbeat_loop():
    """
    后台心跳线程 - 定期报告存活状态
    """
    wechat = EnterpriseWeChat()
    interval_seconds = HEARTBEAT_INTERVAL_HOURS * 3600
    
    while not _heartbeat_stop_event.is_set():
        try:
            # 等待指定时间或收到停止信号
            if _heartbeat_stop_event.wait(timeout=interval_seconds):
                break  # 收到停止信号
            
            # 发送心跳
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            msg = f"💓 心跳报告 ({now})\n✅ 策略正常运行中\n账号: {config.ACCOUNT_ID[-6:]}"
            wechat.send_text(msg)
            logger.info(f"💓 Heartbeat sent at {now}")
            
        except Exception as e:
            logger.warning(f"Heartbeat error: {e}")

def _cleanup_old_logs():
    """
    清理过期日志文件
    """
    try:
        log_dir = config.LOG_DIR
        if not os.path.exists(log_dir):
            return
            
        cutoff_date = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
        pattern = os.path.join(log_dir, "strategy_*.log")
        
        for log_file in glob.glob(pattern):
            try:
                # 从文件名提取日期 (strategy_20260207.log)
                basename = os.path.basename(log_file)
                date_str = basename.replace("strategy_", "").replace(".log", "")
                file_date = datetime.strptime(date_str, "%Y%m%d")
                
                if file_date < cutoff_date:
                    os.remove(log_file)
                    logger.info(f"🗑️ Removed old log: {basename}")
            except Exception as e:
                pass  # 跳过无法解析的文件
                
    except Exception as e:
        logger.warning(f"Log cleanup error: {e}")

def _start_heartbeat():
    """启动心跳监控线程"""
    _heartbeat_stop_event.clear()
    thread = threading.Thread(target=_heartbeat_loop, daemon=True, name="Heartbeat")
    thread.start()
    logger.info("💓 Heartbeat monitor started")
    return thread

def _stop_heartbeat():
    """停止心跳监控线程"""
    _heartbeat_stop_event.set()
    logger.info("💓 Heartbeat monitor stopped")

def _load_gateway_data(context):
    """
    预加载行情数据 (实盘/回测通用)
    """
    from gm.api import history
    
    # 确定数据加载的时间范围
    if context.mode == MODE_LIVE:
        # 实盘：加载过去 400 天到当前
        start_dt = (datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d %H:%M:%S')
        end_dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    else:
        # 回测：加载配置的整个回测区间 (加一点缓冲)
        # 注意: config.START_DATE 是字符串 'YYYY-MM-DD HH:MM:SS'
        # 我们需要往前推 400 天以确保指标计算有足够数据
        s_dt = datetime.strptime(config.START_DATE, '%Y-%m-%d %H:%M:%S')
        start_dt = (s_dt - timedelta(days=400)).strftime('%Y-%m-%d %H:%M:%S')
        end_dt = config.END_DATE
    
    sym_list = list(context.whitelist)
    chunk_size = 50
    all_dfs = []

    logger.info(f"⏳ Pre-loading market data for {len(sym_list)} symbols in batches...")
    logger.info(f"   Range: {start_dt} -> {end_dt}")

    for i in range(0, len(sym_list), chunk_size):
        chunk = sym_list[i : i + chunk_size]
        sym_str = ",".join(chunk)
        try:
            hd = history(
                symbol=sym_str, frequency='1d', start_time=start_dt, end_time=end_dt,
                fields='symbol,close,eob', fill_missing='last', adjust=ADJUST_PREV, df=True
            )
            if not hd.empty:
                all_dfs.append(hd)
        except Exception as e:
            logger.warning(f"⚠️ Batch load failed for chunk {i}: {e}")

    if all_dfs:
        full_hd = pd.concat(all_dfs)
        full_hd['eob'] = pd.to_datetime(full_hd['eob']).dt.tz_localize(None)
        # Drop duplicates just in case
        full_hd = full_hd.drop_duplicates(subset=['eob', 'symbol'])
        context.prices_df = full_hd.pivot(index='eob', columns='symbol', values='close').ffill()
    else:
        logger.error("❌ Failed to load ANY market data!")
        context.prices_df = pd.DataFrame()
    
    # 补齐：如果某些批次失败，可能会有没有数据的列，但 pivot 会自动处理，只是全 NaN。
    # 填充缺失值：对于停牌股票保持 NaN 或 ffill
    
    # 加载基准数据用于 Regime 计算
    bm_data = history(
        symbol=config.MACRO_BENCHMARK, frequency='1d', start_time=start_dt, end_time=end_dt,
        fields='close,eob', fill_missing='last', adjust=ADJUST_PREV, df=True
    )
    bm_data['eob'] = pd.to_datetime(bm_data['eob']).dt.tz_localize(None)
    context.benchmark_df = bm_data.set_index('eob')['close']
    
    logger.info(f"✅ Data Gateway: Loaded {len(context.prices_df)} days.")

def init(context):
    """
    实盘资源初始化
    """
    # 1. 加载白名单/成分股
    if config.TARGET_MODE == 'ETF':
        logger.info(f"🆕 Switching to ETF MODE: Loading from {config.WHITELIST_FILE}...")
        try:
            df_excel = pd.read_excel(config.WHITELIST_FILE)
            df_excel.columns = df_excel.columns.str.strip()
            # 兼容旧列名或新列名
            sym_col = 'symbol' if 'symbol' in df_excel.columns else 'etf_code'
            name_col = 'sec_name' if 'sec_name' in df_excel.columns else 'etf_name'
            theme_col = 'theme' if 'theme' in df_excel.columns else 'name_cleaned'
            
            context.whitelist = set(df_excel[sym_col].tolist())
            context.name_map = dict(zip(df_excel[sym_col], df_excel[name_col]))
            context.theme_map = dict(zip(df_excel[sym_col], df_excel[theme_col]))
            logger.info(f"✅ Loaded {len(context.whitelist)} ETFs from Excel.")
        except Exception as e:
            logger.error(f"❌ Failed to load ETF whitelist: {e}")
            context.whitelist = set()
    else:
        logger.info(f"🆕 Switching to STOCK MODE: Loading constituents for {config.UNIVERSE_INDEX}...")
        from gm.api import stk_get_index_constituents
        try:
            if config.UNIVERSE_INDEX == 'SHSE.000985':
                component_indices = ['SHSE.000300', 'SHSE.000905', 'SHSE.000852', 'SZSE.399303']
                all_symbols = set()
                for idx in component_indices:
                    try:
                        df_part = stk_get_index_constituents(index=idx)
                        if not df_part.empty:
                            all_symbols.update(df_part['symbol'].tolist())
                    except: pass
                context.whitelist = all_symbols
            else:
                df_const = stk_get_index_constituents(index=config.UNIVERSE_INDEX)
                context.whitelist = set(df_const['symbol'])
            
            context.name_map = {s: s for s in context.whitelist}
            context.theme_map = {s: 'STOCK' for s in context.whitelist}
            logger.info(f"✅ Loaded {len(context.whitelist)} stocks (STOCK MODE).")
        except Exception as e:
            logger.error(f"❌ Failed to load stock constituents: {e}")
            context.whitelist = set()

    
    # 2. 组件组装
    context.rpm = RollingPortfolioManager()
    context.rpm.load_state() 
    context.risk_controller = RiskController()
    context.wechat = EnterpriseWeChat()
    context.mailer = EmailNotifier()
    
    # 3. 初始参数
    if not hasattr(context, 'mode'):
        context.mode = MODE_LIVE
    context.account_id = config.ACCOUNT_ID
    context.risk_scaler = 1.0
    context.market_state = 'UNKNOWN'
    context.br_history = []
    
    # Meta-Gate Thresholds
    context.BR_CAUTION_IN = 0.6
    context.BR_CAUTION_OUT = 0.4
    context.BR_DANGER_IN = 0.8
    context.BR_DANGER_OUT = 0.6
    context.BR_PRE_DANGER = 0.7
    
    # 4. 数据网关
    _load_gateway_data(context)
    
    # 5. 回测/实盘参数逻辑初始化
    from gm.api import schedule
    schedule(schedule_func=algo, date_rule='1d', time_rule=config.EXEC_TIME)

    
    logger.info(f"🚀 Live Strategy Initialized. Account: {context.account_id}")
    context.wechat.send_text(f"🚀 策略启动成功\n账号: {context.account_id[-6:]}\n模式: LIVE")

def run_strategy_safe():
    """
    带守护进程的运行逻辑
    - 自动重连
    - 心跳监控
    - 日志清理
    """
    if not validate_env('LIVE'):  # 明确指定为 LIVE 模式
        return

    set_token(config.GM_TOKEN)
    
    # 启动前清理旧日志
    _cleanup_old_logs()
    
    # 启动心跳监控线程
    heartbeat_thread = _start_heartbeat()
    
    # 获取调仓时间，如 14:55:00
    exec_h, exec_m, exec_s = map(int, config.EXEC_TIME.split(':'))

    retry_count = 0
    max_retries = 999 

    try:
        while retry_count < max_retries:
            try:
                logger.info("📡 Connecting to GM Cloud...")
                
                # 使用 schedule 模式或直接 run。实盘通常建议直接 run。
                run(
                    strategy_id=config.STRATEGY_ID,
                    filename='main.py',
                    mode=MODE_LIVE,
                    token=config.GM_TOKEN
                )
                
                # 如果 run 正常结束 (通常不会，除非手动停止)
                break

            except Exception as e:
                retry_count += 1
                error_msg = f"💥 系统崩溃! 错误详情: {str(e)}"
                logger.error(error_msg)
                
                # 尝试微信报警
                try:
                    msg = f"⚠️ 策略异常中断!\n错误: {str(e)[:100]}\n将在30秒后尝试第 {retry_count} 次自动重连..."
                    EnterpriseWeChat().send_text(msg)
                except:
                    pass
                    
                time.sleep(30) # 等待 30 秒后重连
    finally:
        # 无论如何都停止心跳线程
        _stop_heartbeat()

if __name__ == '__main__':
    weight_label = "等权 (1:1:1:1)" if config.WEIGHT_SCHEME == 'EQUAL' else "冠军加权 (3:1:1:1)"
    print("=" * 50)
    print(f"  ETF 量化交易策略 - {weight_label}")
    print("=" * 50)
    print(f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  账号: {config.ACCOUNT_ID[-6:]}")
    print(f"  权重方案: {config.WEIGHT_SCHEME}")
    print(f"  调仓时间: {config.EXEC_TIME}")
    print(f"  状态文件: {config.STATE_FILE}")
    print("=" * 50)
    print()
    
    # 启动策略
    run_strategy_safe()
