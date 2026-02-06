"""
ETF 轮动策略 - 工业级入口脚本
- 职责: 环境初始化、组件装配、模式识别
- 核心逻辑已剥离至 core/ 文件夹
"""
from __future__ import print_function, absolute_import
import os
import pandas as pd
from datetime import datetime, timedelta

from gm.api import *
from config import config, logger
from core.portfolio import RollingPortfolioManager
from core.risk import RiskController
from core.strategy import algo as _algo
from core.strategy import on_bar as _on_bar
from core.strategy import on_backtest_finished as _on_backtest_finished
from notifiers.email import EmailNotifier
from notifiers.wechat import WechatNotifier


def init(context):
    """策略初始化入口"""
    # 1. 运行模式识别 (优先从环境变量读取)
    context.mode = MODE_LIVE if os.environ.get('GM_MODE') == 'LIVE' else MODE_BACKTEST
    
    # 2. 执行环境预检 (Robust Check)
    if not config.validate_env(mode='LIVE' if context.mode == MODE_LIVE else 'BACKTEST'):
        logger.error("🛑 Environment validation failed! Strategy halted.")
        return

    logger.info(f"🚀 Strategy Initializing (Mode: {'LIVE' if context.mode == MODE_LIVE else 'BACKTEST'})...")

    # 3. 注入账户信息
    if context.mode == MODE_LIVE:
        context.account_id = config.ACCOUNT_ID
    
    # 4. 挂配核心组件
    context.rpm = RollingPortfolioManager()
    context.risk_safe = RiskController()
    context.mailer = EmailNotifier()
    context.wechat = WechatNotifier()
    
    # 5. 初始化风险状态机
    context.market_state = 'SAFE'
    context.risk_scaler = 1.0
    context.br_history = []
    # 保持与黄金版本一致的阈值
    context.BR_CAUTION_IN, context.BR_CAUTION_OUT = 0.40, 0.30
    context.BR_DANGER_IN, context.BR_DANGER_OUT, context.BR_PRE_DANGER = 0.60, 0.50, 0.55
    
    # 6. 加载白名单并校验格式
    try:
        df_excel = pd.read_excel(config.WHITELIST_FILE)
        df_excel.columns = df_excel.columns.str.strip()
        df_excel = df_excel.rename(columns={
            'symbol': 'etf_code', 
            'sec_name': 'etf_name', 
            'name_cleaned': 'theme'
        })
        context.whitelist = set(df_excel['etf_code'])
        context.theme_map = df_excel.set_index('etf_code')['theme'].to_dict()
    except Exception as e:
        logger.error(f"❌ Failed to load whitelist: {e}")
        return
    
    # 7. 加载数据 (数据网关逻辑)
    _load_gateway_data(context)
    
    # 8. 持仓记忆加载 (仅实盘)
    if context.mode == MODE_LIVE:
        context.rpm.load_state()
    
    # 9. 订阅行情
    subscribe(
        symbols=list(context.whitelist) if context.mode == MODE_LIVE else 'SHSE.000001',
        frequency='60s' if context.mode == MODE_LIVE else '1d'
    )
    
    # 10. 注册任务
    schedule(schedule_func=algo, date_rule='1d', time_rule=config.EXEC_TIME)


def _load_gateway_data(context):
    """统一数据网关：确保回测与实盘看到完全一样的历史切片"""
    start_dt = (pd.Timestamp(config.START_DATE) - timedelta(days=400)).strftime('%Y-%m-%d %H:%M:%S')
    end_dt = config.END_DATE if context.mode == MODE_BACKTEST else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    sym_str = ",".join(context.whitelist)
    
    # 价格数据
    hd = history(
        symbol=sym_str, frequency='1d', start_time=start_dt, end_time=end_dt,
        fields='symbol,close,eob', fill_missing='last', adjust=ADJUST_PREV, df=True
    )
    hd['eob'] = pd.to_datetime(hd['eob']).dt.tz_localize(None)
    context.prices_df = hd.pivot(index='eob', columns='symbol', values='close').ffill()
    
    # 成交量数据
    vol_data = history(
        symbol=sym_str, frequency='1d', start_time=start_dt, end_time=end_dt,
        fields='symbol,volume,eob', fill_missing='last', adjust=ADJUST_PREV, df=True
    )
    vol_data['eob'] = pd.to_datetime(vol_data['eob']).dt.tz_localize(None)
    context.volumes_df = vol_data.pivot(index='eob', columns='symbol', values='volume').ffill()
    
    # 基准数据
    bm_data = history(
        symbol=config.MACRO_BENCHMARK, frequency='1d', start_time=start_dt, end_time=end_dt,
        fields='close,eob', fill_missing='last', adjust=ADJUST_PREV, df=True
    )
    bm_data['eob'] = pd.to_datetime(bm_data['eob']).dt.tz_localize(None)
    context.benchmark_df = bm_data.set_index('eob')['close']
    
    logger.info(f"📊 Data Gateway: Loaded {len(context.prices_df)} days.")


# --- 外部回调包装器 (确保 GM 引擎可见) ---

def algo(context):
    _algo(context)

def on_bar(context, bars):
    _on_bar(context, bars)

def on_backtest_finished(context, indicator):
    _on_backtest_finished(context, indicator)


if __name__ == '__main__':
    # 此入口仅供本地调试，正式运行建议通过 run_backtest.py 或 run_live.py
    run(
        strategy_id=config.STRATEGY_ID,
        filename='main.py',
        mode=MODE_BACKTEST,
        token=config.GM_TOKEN,
        backtest_start_time=config.START_DATE,
        backtest_end_time=config.END_DATE,
        backtest_adjust=ADJUST_PREV,
        backtest_initial_cash=1000000,
        backtest_commission_ratio=0.0001
    )