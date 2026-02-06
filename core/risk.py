"""
风控模块
- RiskController: 硬风控（熔断、订单校验）
- DataGuard: 数据质检
"""
from gm.api import MODE_LIVE
from config import config


class RiskController:
    """宪兵队：凌驾于策略之上的硬风控"""
    
    def __init__(self):
        self.initial_nav_today = 0.0
        self.reject_count = 0
        self.active = True
        self.last_day = None

    def on_day_start(self, context):
        """每日开盘初始化"""
        current_day = context.now.date()
        if self.last_day != current_day:
            acc = (context.account(account_id=context.account_id) 
                   if context.mode == MODE_LIVE else context.account())
            if acc:
                self.initial_nav_today = acc.cash.nav
            self.reject_count = 0
            self.active = True
            self.last_day = current_day
            print(f"🛡️ [RISK] Day Start: NAV Locked at {self.initial_nav_today:.2f}")

    def check_daily_loss(self, context):
        """检查单日亏损是否触达熔断线"""
        acc = (context.account(account_id=context.account_id) 
               if context.mode == MODE_LIVE else context.account())
        if not acc or self.initial_nav_today <= 0:
            return True

        current_nav = acc.cash.nav
        dd_pct = 1 - (current_nav / self.initial_nav_today)

        if dd_pct > config.MAX_DAILY_LOSS_PCT:
            if self.active:
                print(f"🧨 [RISK MELTDOWN] Daily Loss {dd_pct:.2%} > Limit "
                      f"{config.MAX_DAILY_LOSS_PCT:.2%}. TRADING HALTED.")
                self.active = False
            return False
        return True

    def validate_order(self, context, symbol, value, total_scan_val):
        """检查单笔订单合规性"""
        if not self.active:
            return False

        if total_scan_val > 0 and (value / total_scan_val) > config.MAX_ORDER_VAL_PCT + 0.05:
            print(f"🛡️ [RISK] Order Reject: {symbol} Val {value:.0f} > "
                  f"Max {config.MAX_ORDER_VAL_PCT:.0%} of NAV")
            return False
        return True


class DataGuard:
    """数据质检员：防止脏数据和延迟数据"""
    
    @staticmethod
    def check_freshness(ticks, current_dt):
        """检查数据新鲜度（待实现）"""
        return True
