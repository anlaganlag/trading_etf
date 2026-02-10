"""
配置中心 - 所有策略参数集中管理与环境校验
"""
import os
import logging
from datetime import datetime
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

class Config:
    """策略配置类"""
    
    # === 路径配置 ===
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_CACHE_DIR = os.path.join(BASE_DIR, "data_cache")
    LOG_DIR = os.path.join(BASE_DIR, "logs")
    OUTPUT_DIR = os.path.join(BASE_DIR, "output")
    DATA_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "data")
    REPORT_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "reports")
    CHART_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "charts")
    
    # === 基础文件 ===
    WHITELIST_FILE = os.path.join(BASE_DIR, "ETF合并筛选结果.xlsx")
    
    # === 账户配置 ===
    # 自适应双账户：未显式设置 GM_ACCOUNT_ID 时，按权重方案选账户
    # EQUAL → GM_ACCOUNT_ID_EQUAL，否则 → GM_ACCOUNT_ID_NON_EQUAL
    _weight = os.environ.get('WEIGHT_SCHEME', 'CHAMPION')
    _account_equal = os.environ.get('GM_ACCOUNT_ID_EQUAL')
    _account_non_equal = os.environ.get('GM_ACCOUNT_ID_NON_EQUAL')
    ACCOUNT_ID = (
        os.environ.get('GM_ACCOUNT_ID')
        or (_account_equal if _weight == 'EQUAL' else _account_non_equal)
        or '658419cf-ffe1-11f0-a908-00163e022aa6'
    )
    STRATEGY_ID = '02966fb6-0309-11f1-b829-00ffda9d6e63'
    # 用于确保回测一致性的 Token
    GM_TOKEN = os.environ.get('MY_QUANT_TGM_TOKEN')
    
    # === 时间窗口 ===
    START_DATE = '2021-12-03 09:00:00'
    END_DATE = '2026-01-23 16:00:00'
    EXEC_TIME = os.environ.get('OPT_EXEC_TIME', '14:55:00')
    # 压测/验证：14:00 起每 10 分钟执行一次（设 OPT_EXEC_EVERY_10MIN=1 开启）
    EXEC_EVERY_10MIN = os.environ.get('OPT_EXEC_EVERY_10MIN', '').strip().lower() in ('1', 'true', 'yes')
    
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
    
    # === 权重方案 ===
    # CHAMPION = 3:1:1:1 (冠军加权), EQUAL = 1:1:1:1 (等权)
    WEIGHT_SCHEME = os.environ.get('WEIGHT_SCHEME', 'CHAMPION')
    VERSION_SUFFIX = os.environ.get('VERSION_SUFFIX', '')  # 用于区分不同版本的文件
    
    # === 状态文件 ===
    MACRO_BENCHMARK = 'SZSE.159915'  # 创业板ETF作为宏观锚点
    STATE_FILE = f"rolling_state_main{VERSION_SUFFIX}.json"
    
    # === 保护期与缓冲 ===
    PROTECTION_DAYS = int(os.environ.get('OPT_PROTECTION_DAYS', 0))
    TURNOVER_BUFFER = 2          # 缓冲区大小
    
    # === 动态止损与 TOP_N (实验性) ===
    DYNAMIC_STOP_LOSS = False
    ATR_MULTIPLIER = 2.5
    ATR_LOOKBACK = 20
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
    
    # === 邮件通知配置 ===
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

    _logger = None

    @classmethod
    def get_logger(cls):
        """获取统一日志记录器"""
        if cls._logger is None:
            # 确保日志目录存在
            if not os.path.exists(cls.LOG_DIR):
                os.makedirs(cls.LOG_DIR, exist_ok=True)
            
            logger = logging.getLogger("ETF_Strategy")
            logger.setLevel(logging.INFO)
            
            # 控制台输出
            ch = logging.StreamHandler()
            ch.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            logger.addHandler(ch)
            
            # 文件输出 (包含版本后缀以区分不同策略)
            log_file = os.path.join(cls.LOG_DIR, f"strategy_{datetime.now().strftime('%Y%m%d')}{cls.VERSION_SUFFIX}.log")
            fh = logging.FileHandler(log_file, encoding='utf-8')
            fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            logger.addHandler(fh)
            
            cls._logger = logger
        return cls._logger

    @classmethod
    def validate_env(cls, mode='BACKTEST'):
        """环境预检"""
        log = cls.get_logger()
        log.info(f"🔍 Perform environment validation (Mode: {mode})...")
        
        # 1. 检查关键目录
        for d in [cls.DATA_CACHE_DIR, cls.LOG_DIR, cls.DATA_OUTPUT_DIR, 
                  cls.REPORT_OUTPUT_DIR, cls.CHART_OUTPUT_DIR]:
            if not os.path.exists(d):
                os.makedirs(d, exist_ok=True)
                log.info(f"📁 Created directory: {d}")

        # 2. 检查关键文件
        if not os.path.exists(cls.WHITELIST_FILE):
            log.error(f"❌ Missing critical file: {cls.WHITELIST_FILE}")
            return False

        # 3. 检查环境变量
        if not cls.GM_TOKEN:
            log.error("❌ Environment variable 'MY_QUANT_TGM_TOKEN' is missing!")
            return False
            
        if mode == 'LIVE' and not cls.ACCOUNT_ID:
            log.error("❌ LIVE MODE: 'GM_ACCOUNT_ID' must be configured!")
            return False

        log.info("✅ Environment validation passed.")
        return True

# 全局配置实例
config = Config()
logger = config.get_logger()
validate_env = config.validate_env

