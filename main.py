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
from gm.api import run, set_token, set_account_id, MODE_LIVE, ADJUST_PREV, subscribe, schedule
from config import config, logger, validate_env
from core.strategy import algo, on_bar, on_backtest_finished
from core.portfolio import RollingPortfolioManager
from core.risk import RiskController
from core.notify import EnterpriseWeChat, EmailNotifier
from core.account import get_account

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
    预加载行情数据 (实盘必备)
    """
    from gm.api import history
    # 预加载 400 天数据以计算长周期均线/RSI
    start_dt = (datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d %H:%M:%S')
    end_dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sym_str = ",".join(context.whitelist)
    
    logger.info(f"⏳ Pre-loading market data for {len(context.whitelist)} symbols...")
    
    hd = history(
        symbol=sym_str, frequency='1d', start_time=start_dt, end_time=end_dt,
        fields='symbol,close,eob', fill_missing='last', adjust=ADJUST_PREV, df=True
    )
    hd['eob'] = pd.to_datetime(hd['eob']).dt.tz_localize(None)
    context.prices_df = hd.pivot(index='eob', columns='symbol', values='close').ffill()
    
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
    # 1. 加载白名单
    df_excel = pd.read_excel(config.WHITELIST_FILE)
    df_excel.columns = df_excel.columns.str.strip()
    df_excel = df_excel.rename(columns={'symbol':'etf_code', 'sec_name':'etf_name', 'name_cleaned':'theme'})
    context.whitelist = set(df_excel['etf_code'])
    context.theme_map = df_excel.set_index('etf_code')['theme'].to_dict()
    context.name_map = df_excel.set_index('etf_code')['etf_name'].to_dict()
    
    # 2. 组件组装
    context.rpm = RollingPortfolioManager()
    context.rpm.load_state() 
    context.risk_controller = RiskController()
    context.wechat = EnterpriseWeChat()
    context.mailer = EmailNotifier()
    
    # 3. 初始参数
    context.mode = MODE_LIVE
    context.account_id = config.ACCOUNT_ID
    set_account_id(config.ACCOUNT_ID)  # 确保 GM C 层下单使用等权账户，避免 1020 无效 ACCOUNT_ID
    context.risk_scaler = 1.0
    context.market_state = 'SAFE'
    context.br_history = []
    context.BR_CAUTION_IN, context.BR_CAUTION_OUT = 0.40, 0.30
    context.BR_DANGER_IN, context.BR_DANGER_OUT, context.BR_PRE_DANGER = 0.60, 0.50, 0.55
    
    # 3.5. 验证账户可访问性（提前检查，带默认账户 fallback）
    try:
        logger.info(f"🔍 Verifying account access: {context.account_id}")
        test_acc = get_account(context)
        if test_acc:
            nav = test_acc.cash.nav if hasattr(test_acc, 'cash') and hasattr(test_acc.cash, 'nav') else 0.0
            cash_available = test_acc.cash.available if hasattr(test_acc, 'cash') and hasattr(test_acc.cash, 'available') else 0.0
            logger.info(f"✅ Account verified: {context.account_id[-8:]} | NAV: {nav:,.2f} | Available: {cash_available:,.2f}")
        else:
            logger.error(f"❌ Account verification failed: {context.account_id}")
            logger.error("   Account object is None. Possible reasons:")
            logger.error("   1. Account ID does not exist in GM platform")
            logger.error("   2. Token does not have permission to access this account")
            logger.error("   3. Account is disabled or deleted")
            logger.warning("   Strategy will continue but may fail during initialization")
    except Exception as e:
        logger.error(f"❌ Account verification exception: {e}")
        logger.error(f"   Account ID: {context.account_id}")
        import traceback
        logger.error(f"   Traceback: {traceback.format_exc()}")
        logger.warning("   Strategy will continue but may fail during initialization")
    
    # 4. 数据网关
    _load_gateway_data(context)
    
    # 5. 订阅行情和注册定时任务
    subscribe(
        symbols=list(context.whitelist),
        frequency='60s'
    )
    
    # 6. 注册每日执行时间
    if config.EXEC_EVERY_10MIN:
        for t in ('14:00:00', '14:10:00', '14:20:00', '14:30:00', '14:40:00', '14:50:00', '14:55:00'):
            schedule(schedule_func=algo, date_rule='1d', time_rule=t)
        logger.info("⏰ Scheduled execution every 10 min: 14:00–14:55 (stress test)")
    else:
        schedule(schedule_func=algo, date_rule='1d', time_rule=config.EXEC_TIME)
        logger.info(f"⏰ Scheduled execution at {config.EXEC_TIME}")
    
    # 7. 回测/实盘参数逻辑初始化
    
    logger.info(f"🚀 Live Strategy Initialized. Account: {context.account_id}")
    exec_desc = "14:00起每10分钟" if config.EXEC_EVERY_10MIN else config.EXEC_TIME
    context.wechat.send_text(f"🚀 策略启动成功\n账号: {context.account_id[-6:]}\n模式: LIVE\n执行时间: {exec_desc}")

def run_strategy_safe():
    """
    带守护进程的运行逻辑
    - 自动重连
    - 心跳监控
    - 日志清理
    """
    if not validate_env():
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
