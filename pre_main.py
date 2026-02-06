"""
ETF 轮动策略 - 主入口
支持两种运行模式：
1. 回测模式: python run_backtest.py
2. 实盘模式: GM_MODE=LIVE python main.py

模块结构:
├── config.py          # 配置中心
├── core/
│   ├── portfolio.py   # 投资组合管理
│   ├── risk.py        # 风控模块
│   ├── signal.py      # 信号生成
│   └── strategy.py    # 策略核心
└── notifiers/
    ├── email.py       # 邮件通知
    └── wechat.py      # 微信通知
"""
from __future__ import print_function, absolute_import
import os
import pandas as pd
from datetime import datetime, timedelta

from gm.api import *
from config import config
from core.portfolio import RollingPortfolioManager
from core.risk import RiskController
from core.strategy import algo
from notifiers.email import EmailNotifier
from notifiers.wechat import WechatNotifier


def init(context):
    """策略初始化"""
    print(f"🚀 ETF Rotation Strategy V2 (Meta-Gate Enabled)...")
    
    # 运行模式
    context.mode = (
        MODE_LIVE if os.environ.get('GM_MODE', 'BACKTEST').upper() == 'LIVE' 
        else MODE_BACKTEST
    )
    
    # 账户绑定 (仅实盘)
    if context.mode == MODE_LIVE:
        context.account_id = config.ACCOUNT_ID
    print(f"💳 Mode: {'LIVE' if context.mode == MODE_LIVE else 'BACKTEST'} | "
          f"Account: {getattr(context, 'account_id', 'BACKTEST')}")
    
    # 初始化组件
    context.rpm = RollingPortfolioManager()
    context.risk_safe = RiskController()
    context.mailer = EmailNotifier()
    context.wechat = WechatNotifier()
    
    # 风险状态机
    context.market_state = 'SAFE'
    context.risk_scaler = 1.0
    context.br_history = []
    context.BR_CAUTION_IN, context.BR_CAUTION_OUT = 0.40, 0.30
    context.BR_DANGER_IN, context.BR_DANGER_OUT, context.BR_PRE_DANGER = 0.60, 0.50, 0.55
    
    # 加载白名单
    df_excel = pd.read_excel(os.path.join(config.BASE_DIR, "ETF合并筛选结果.xlsx"))
    df_excel.columns = df_excel.columns.str.strip()
    df_excel = df_excel.rename(columns={
        'symbol': 'etf_code', 
        'sec_name': 'etf_name', 
        'name_cleaned': 'theme'
    })
    context.whitelist = set(df_excel['etf_code'])
    context.theme_map = df_excel.set_index('etf_code')['theme'].to_dict()
    
    # 数据加载
    _load_data(context)
    
    # 加载状态 (实盘)
    if context.mode == MODE_LIVE:
        context.rpm.load_state()
    
    # 订阅和定时
    subscribe(
        symbols=list(context.whitelist) if context.mode == MODE_LIVE else 'SHSE.000001',
        frequency='60s' if context.mode == MODE_LIVE else '1d'
    )
    schedule(schedule_func=algo, date_rule='1d', time_rule=config.EXEC_TIME)


def _load_data(context):
    """加载历史数据"""
    start_dt = (
        pd.Timestamp(config.START_DATE) - timedelta(days=400)
    ).strftime('%Y-%m-%d %H:%M:%S')
    end_dt = (
        config.END_DATE if context.mode == MODE_BACKTEST 
        else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )
    
    sym_str = ",".join(context.whitelist)
    
    # 1. 价格数据
    print("📊 Loading price data...")
    hd = history(
        symbol=sym_str, frequency='1d',
        start_time=start_dt, end_time=end_dt,
        fields='symbol,close,eob',
        fill_missing='last', adjust=ADJUST_PREV, df=True
    )
    hd['eob'] = pd.to_datetime(hd['eob']).dt.tz_localize(None)
    context.prices_df = hd.pivot(index='eob', columns='symbol', values='close').ffill()
    
    # 2. 成交量数据
    print("📊 Loading volume data...")
    vol_data = history(
        symbol=sym_str, frequency='1d',
        start_time=start_dt, end_time=end_dt,
        fields='symbol,volume,eob',
        fill_missing='last', adjust=ADJUST_PREV, df=True
    )
    vol_data['eob'] = pd.to_datetime(vol_data['eob']).dt.tz_localize(None)
    context.volumes_df = vol_data.pivot(index='eob', columns='symbol', values='volume').ffill()
    
    # 3. 基准数据
    print(f"📊 Loading benchmark ({config.MACRO_BENCHMARK})...")
    bm_data = history(
        symbol=config.MACRO_BENCHMARK, frequency='1d',
        start_time=start_dt, end_time=end_dt,
        fields='close,eob',
        fill_missing='last', adjust=ADJUST_PREV, df=True
    )
    bm_data['eob'] = pd.to_datetime(bm_data['eob']).dt.tz_localize(None)
    context.benchmark_df = bm_data.set_index('eob')['close']
    print(f"✅ Benchmark: {len(context.benchmark_df)} records, "
          f"latest: {context.benchmark_df.iloc[-1]:.2f} @ {context.benchmark_df.index[-1]}")


# 回调函数包装器 (掘金框架需要在主模块中定义)
from core.strategy import on_bar as _on_bar
from core.strategy import on_backtest_finished as _on_backtest_finished

def on_bar(context, bars):
    """盘中止损监控"""
    _on_bar(context, bars)

def on_backtest_finished(context, indicator):
    """回测结束报告"""
    _on_backtest_finished(context, indicator)


if __name__ == '__main__':
    RUN_MODE = os.environ.get('GM_MODE', 'BACKTEST').upper()
    
    if RUN_MODE == 'LIVE':
        print("🚀 Starting LIVE trading...")
        run(
            strategy_id=config.STRATEGY_ID,
            filename='main.py',
            mode=MODE_LIVE,
            token=os.getenv('MY_QUANT_TGM_TOKEN')
        )
    else:
        print("📉 Starting BACKTEST...")
        run(
            strategy_id=config.STRATEGY_ID,
            filename='main.py',
            mode=MODE_BACKTEST,
            token=os.getenv('MY_QUANT_TGM_TOKEN'),
            backtest_start_time=config.START_DATE,
            backtest_end_time=config.END_DATE,
            backtest_adjust=ADJUST_PREV,
            backtest_initial_cash=1000000,
            backtest_commission_ratio=0.0001
        )