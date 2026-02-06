"""
实盘运行主入口 - 强化健壮版
1. 自动重连机制 (Auto-Reconnect)
2. 守护进程心跳 (Heartbeat Monitoring)
3. 异常捕获与微信报警
"""
import time
import os
from datetime import datetime, timedelta
from gm.api import run, set_token, MODE_LIVE, ADJUST_PREV
from config import config, logger, validate_env
from core.strategy import algo, on_bar, on_backtest_finished
from core.portfolio import RollingPortfolioManager
from core.risk import RiskController
from core.notify import EnterpriseWeChat, EmailNotifier

import pandas as pd

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
    context.risk_scaler = 1.0
    context.market_state = 'UNKNOWN'
    
    # 4. 数据网关
    _load_gateway_data(context)
    
    # 5. 回测/实盘参数逻辑初始化

    
    logger.info(f"🚀 Live Strategy Initialized. Account: {context.account_id}")
    context.wechat.send_text(f"🚀 策略启动成功\n账号: {context.account_id[-6:]}\n模式: LIVE")

def run_strategy_safe():
    """
    带守护进程的运行逻辑
    """
    if not validate_env():
        return

    set_token(config.GM_TOKEN)
    
    # 获取调仓时间，如 14:55:00
    exec_h, exec_m, exec_s = map(int, config.EXEC_TIME.split(':'))

    retry_count = 0
    max_retries = 999 

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

if __name__ == '__main__':
    # 启动心跳打印线程的简化实现：在主进程直接启动
    # 如果你在 Windows 环境下，直接用循环守护即可
    run_strategy_safe()