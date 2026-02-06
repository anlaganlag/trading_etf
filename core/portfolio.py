"""
投资组合管理模块
- Tranche: 份额类，管理单个调仓周期的持仓
- RollingPortfolioManager: 滚动投资组合管理器
"""
import os
import json
from datetime import datetime
from config import config


class Tranche:
    """份额类：管理单个调仓周期的持仓"""
    
    def __init__(self, t_id, initial_cash=0):
        self.id = t_id
        self.cash = initial_cash
        self.holdings = {}
        self.pos_records = {}  # {symbol: {'entry_price', 'high_price', 'entry_dt', 'volatility'}}
        self.total_value = initial_cash
        self.guard_triggered_today = False

    def to_dict(self):
        """序列化为字典，处理 datetime 对象"""
        d = self.__dict__.copy()
        if 'pos_records' in d:
            serialized_records = {}
            for sym, rec in d['pos_records'].items():
                serialized_rec = rec.copy()
                if 'entry_dt' in serialized_rec and serialized_rec['entry_dt'] is not None:
                    if isinstance(serialized_rec['entry_dt'], datetime):
                        serialized_rec['entry_dt'] = serialized_rec['entry_dt'].isoformat()
                serialized_records[sym] = serialized_rec
            d['pos_records'] = serialized_records
        return d

    @staticmethod
    def from_dict(d):
        """从字典反序列化，处理 datetime 字符串"""
        t = Tranche(d["id"], d["cash"])
        t.holdings = d["holdings"]
        t.total_value = d["total_value"]
        t.pos_records = {}
        for sym, rec in d.get("pos_records", {}).items():
            deserialized_rec = rec.copy()
            if 'entry_dt' in deserialized_rec and deserialized_rec['entry_dt'] is not None:
                if isinstance(deserialized_rec['entry_dt'], str):
                    try:
                        deserialized_rec['entry_dt'] = datetime.fromisoformat(deserialized_rec['entry_dt'])
                    except (ValueError, AttributeError):
                        deserialized_rec['entry_dt'] = None
            t.pos_records[sym] = deserialized_rec
        return t

    def update_value(self, price_map):
        """更新份额净值"""
        val = self.cash
        for sym, shares in self.holdings.items():
            if sym in price_map:
                price = price_map[sym]
                val += shares * price
                if sym in self.pos_records:
                    self.pos_records[sym]['high_price'] = max(
                        self.pos_records[sym]['high_price'], price
                    )
        self.total_value = val

    def check_guard(self, price_map, current_dt=None):
        """检查止损/止盈条件，支持保护期和动态止损"""
        to_sell = []
        for sym, rec in self.pos_records.items():
            if sym not in self.holdings:
                continue

            # 保护期检查
            entry_dt = rec.get('entry_dt')
            if current_dt and entry_dt and config.PROTECTION_DAYS > 0:
                days_held = (current_dt - entry_dt).days
                if days_held <= config.PROTECTION_DAYS:
                    continue

            curr_p = price_map.get(sym, 0)
            if curr_p <= 0:
                continue
            entry, high = rec['entry_price'], rec['high_price']

            # 动态止损
            if config.DYNAMIC_STOP_LOSS and 'volatility' in rec:
                vol = rec['volatility']
                dynamic_sl = max(0.10, min(0.30, config.ATR_MULTIPLIER * vol))
                is_sl = curr_p < entry * (1 - dynamic_sl)
            else:
                is_sl = curr_p < entry * (1 - config.STOP_LOSS)

            # 移动止盈回落
            is_tp = (high > entry * (1 + config.TRAILING_TRIGGER) and 
                     curr_p < high * (1 - config.TRAILING_DROP))

            if is_sl or is_tp:
                to_sell.append(sym)
        return to_sell

    def sell(self, symbol, price):
        """全部卖出指定标的"""
        if symbol in self.holdings:
            self.cash += self.holdings[symbol] * price
            self.holdings.pop(symbol, None)
            self.pos_records.pop(symbol, None)

    def sell_qty(self, symbol, qty, price):
        """卖出指定数量"""
        if symbol in self.holdings:
            actual_qty = min(qty, self.holdings[symbol])
            self.cash += actual_qty * price
            self.holdings[symbol] -= actual_qty
            if self.holdings[symbol] == 0:
                self.holdings.pop(symbol, None)
                self.pos_records.pop(symbol, None)

    def buy(self, symbol, cash_allocated, price, current_dt=None, volatility=None):
        """买入标的，记录买入时间和波动率"""
        if price <= 0:
            return 0
        shares = int(cash_allocated / price / 100) * 100
        cost = shares * price
        if shares > 0 and self.cash >= cost:
            self.cash -= cost
            self.holdings[symbol] = self.holdings.get(symbol, 0) + shares
            self.pos_records[symbol] = {
                'entry_price': price,
                'high_price': price,
                'entry_dt': current_dt,
                'volatility': volatility or 0.02
            }
            return shares
        return 0


class RollingPortfolioManager:
    """滚动投资组合管理器"""
    
    def __init__(self, state_path=None):
        self.tranches = []
        self.initialized = False
        self.days_count = 0
        self.state_path = state_path or os.path.join(config.BASE_DIR, config.STATE_FILE)
        self.nav_history = []

    def load_state(self):
        """加载状态"""
        if not os.path.exists(self.state_path):
            return False
        try:
            with open(self.state_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.days_count = data.get("days_count", 0)
                self.tranches = [Tranche.from_dict(d) for d in data.get("tranches", [])]
                self.initialized = True
            print(f"✅ Loaded State: Day {self.days_count}")
            return True
        except Exception as e:
            print(f"⚠️ Load State Failed: {e}")
        return False

    def save_state(self):
        """保存状态"""
        try:
            temp_path = self.state_path + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "days_count": self.days_count,
                    "tranches": [t.to_dict() for t in self.tranches]
                }, f, indent=2)
            if os.path.exists(self.state_path):
                os.remove(self.state_path)
            os.rename(temp_path, self.state_path)
        except Exception:
            pass

    def initialize_tranches(self, total_cash):
        """初始化份额"""
        share = total_cash / config.REBALANCE_PERIOD_T
        self.tranches = [Tranche(i, share) for i in range(config.REBALANCE_PERIOD_T)]
        self.initialized = True
        self.save_state()

    @property
    def total_holdings(self):
        """汇总所有份额的持仓"""
        combined = {}
        for t in self.tranches:
            for sym, shares in t.holdings.items():
                combined[sym] = combined.get(sym, 0) + shares
        return combined

    def reconcile_with_broker(self, real_pos):
        """与券商实际持仓对账"""
        virtual_map = self.total_holdings
        for sym, v_qty in virtual_map.items():
            r_qty = real_pos.get(sym, 0)
            diff = v_qty - r_qty
            if diff > 0:
                remaining = diff
                for t in self.tranches:
                    if sym in t.holdings:
                        remove_qty = min(t.holdings[sym], remaining)
                        t.holdings[sym] -= remove_qty
                        if t.holdings[sym] == 0:
                            t.holdings.pop(sym, None)
                        remaining -= remove_qty
                        if remaining <= 0:
                            break
