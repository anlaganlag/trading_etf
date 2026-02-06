"""
配置中心 - 所有策略参数集中管理
"""
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """策略配置类"""
    
    # === 路径配置 ===
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_CACHE_DIR = os.path.join(BASE_DIR, "data_cache")
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")
    DATA_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "data")
    REPORT_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "reports")
    CHART_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "charts")
    
    # === 账户配置 ===
    ACCOUNT_ID = os.environ.get('GM_ACCOUNT_ID', '658419cf-ffe1-11f0-a908-00163e022aa6')
    STRATEGY_ID = '60e6472f-01ac-11f1-a1c0-00ffda9d6e63'
    
    # === 时间窗口 ===
    START_DATE = '2021-12-03 09:00:00'
    END_DATE = '2026-01-23 16:00:00'
    EXEC_TIME = os.environ.get('OPT_EXEC_TIME', '14:55:00')
    
    # === 策略核心参数 ===
    TOP_N = 4                    # 选前N只
    REBALANCE_PERIOD_T = 10      # 每T个交易日调仓一次
    MIN_SCORE = 20               # 最低评分阈值
    MAX_PER_THEME = 2            # 每主题最大持仓数
    
    # === 止损止盈参数 ===
    STOP_LOSS = float(os.environ.get('OPT_STOP_LOSS', 0.20))
    TRAILING_TRIGGER = float(os.environ.get('OPT_TRAILING_TRIGGER', 0.15))
    TRAILING_DROP = float(os.environ.get('OPT_TRAILING_DROP', 0.03))
    
    # === 风控开关 ===
    DYNAMIC_POSITION = True      # 开启动态趋势仓位
    ENABLE_META_GATE = True      # 开启 Meta-Gate 防御
    SCORING_METHOD = 'SMOOTH'    # 评分方法
    
    # === 基准配置 ===
    MACRO_BENCHMARK = 'SZSE.159915'  # 创业板ETF作为宏观锚点
    STATE_FILE = "rolling_state_main.json"
    
    # === 保护期配置 ===
    PROTECTION_DAYS = int(os.environ.get('OPT_PROTECTION_DAYS', 0))
    
    # === 软冲销配置 ===
    TURNOVER_BUFFER = 2          # 缓冲区大小
    
    # === 动态止损配置 (实验性，默认关闭) ===
    DYNAMIC_STOP_LOSS = False
    ATR_MULTIPLIER = 2.5
    ATR_LOOKBACK = 20
    
    # === 动态 TOP_N 配置 (实验性，默认关闭) ===
    DYNAMIC_TOP_N = False
    TOP_N_BY_STATE = {
        'SAFE': 5,
        'CAUTION': 4,
        'DANGER': 2
    }
    
    # === 硬核风控常量 ===
    MAX_DAILY_LOSS_PCT = 0.04    # 单日亏损熔断线
    MAX_ORDER_VAL_PCT = 0.25     # 单笔订单最大占比
    MAX_REJECT_COUNT = 5         # 单日废单容忍度
    DATA_TIMEOUT_SEC = 180       # 数据延迟容忍(秒)
    
    # === 板块评分配置 ===
    SECTOR_TOP_N_THRESHOLD = 15
    SECTOR_PERIOD_SCORES = {
        1: 100,
        3: 70,
        5: 50,
        10: 30,
        20: 20,
    }
    ETF_SECTOR_LIMIT = 1
    
    # === 邮件配置 ===
    EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.163.com')
    EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 465))
    EMAIL_USER = os.environ.get('EMAIL_USER', 'tanjhu@163.com')
    EMAIL_PASS = os.environ.get('EMAIL_PASS', 'KHdqTEPNXViSJpJs')
    EMAIL_TO = os.environ.get('EMAIL_TO', 'tanjhu@163.com')
    
    # === 微信配置 ===
    WECHAT_WEBHOOK = os.environ.get(
        'WECHAT_WEBHOOK', 
        'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=aa6eb940-0d50-489f-801e-26c467d77a30'
    )
    
    # === 缓存配置 ===
    USE_CACHE = False            # 是否使用数据缓存
    
    @classmethod
    def ensure_dirs(cls):
        """确保目录存在"""
        for path in [cls.DATA_CACHE_DIR, cls.DATA_OUTPUT_DIR, 
                     cls.REPORT_OUTPUT_DIR, cls.CHART_OUTPUT_DIR]:
            if not os.path.exists(path):
                os.makedirs(path, exist_ok=True)


# 全局配置实例
config = Config()
config.ensure_dirs()
