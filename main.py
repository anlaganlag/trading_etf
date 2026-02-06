# 建议通过 replace_file_content 对 main.py 进行如下更新
# 这里我整理了完整的升级后的 main.py 内容

from __future__ import print_function, absolute_import
from gm.api import *
import pandas as pd
import numpy as np
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from config import config
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

# ... (Previous imports)

load_dotenv()
# 账户 ID：保留 main.py 原本使用的 ID 或从环境读取
ACCOUNT_ID = os.environ.get('GM_ACCOUNT_ID', '658419cf-ffe1-11f0-a908-00163e022aa6')

# === 策略参数 (支持环境变量，方便参数调优) ===
TOP_N = 4                 # 选前N只 (默认值)
REBALANCE_PERIOD_T = 10   # 每T个交易日调仓一次

# === 阶段五：动态 TOP_N ===
DYNAMIC_TOP_N = False     # 🔴 实验失败，关闭。SAFE时分散过度反而降低收益
TOP_N_BY_STATE = {
    'SAFE': 5,     # 强势市场：多持仓捕捉机会
    'CAUTION': 4,  # 警界市场：默认持仓
    'DANGER': 2    # 危险市场：集中持仓降低风险
}
STOP_LOSS = float(os.environ.get('OPT_STOP_LOSS', 0.20))
TRAILING_TRIGGER = float(os.environ.get('OPT_TRAILING_TRIGGER', 0.15))
TRAILING_DROP = float(os.environ.get('OPT_TRAILING_DROP', 0.03))

# === 时间窗口 ===
START_DATE='2021-12-03 09:00:00'
END_DATE='2026-01-23 16:00:00'

# === 风控开关 (追平收益的关键) ===
DYNAMIC_POSITION = True    # 开启动态趋势仓位
ENABLE_META_GATE = True    # 开启 Meta-Gate 防御 (关键差异)
SCORING_METHOD = 'SMOOTH'  # 线性权重评分
MAX_PER_THEME = 2          # 主题分散
MACRO_BENCHMARK = 'SZSE.159915' # 创业板指作为宏观锚点
STATE_FILE = "rolling_state_main.json"
MIN_SCORE = 20

# === 阶段一：新仓保护期（防止噪音止损）===
PROTECTION_DAYS = int(os.environ.get('OPT_PROTECTION_DAYS', 0))  # 默认关闭保护期

# === 阶段三：软冲销机制 (Turnover Buffer) ===
TURNOVER_BUFFER = 2    # 缓冲区大小：持仓在前 TOP_N + BUFFER 内不换手

# === 阶段四：动态止损 (ATR-Based Stop Loss) ===
DYNAMIC_STOP_LOSS = False          # 🔴 实验失败，关闭。ETF波动率低导致止损过紧
ATR_MULTIPLIER = 2.5               # 波动率乘数：止损 = 入场价 * (1 - K * 波动率)
ATR_LOOKBACK = 20                  # 计算波动率的回望天数

class Tranche:
    def __init__(self, t_id, initial_cash=0):
        self.id = t_id
        self.cash = initial_cash
        self.holdings = {} 
        self.pos_records = {} # {symbol: {'entry_price', 'high_price', 'entry_dt', 'volatility'}}
        self.total_value = initial_cash
        self.guard_triggered_today = False 

    def to_dict(self):
        """序列化为字典，处理 datetime 对象"""
        d = self.__dict__.copy()
        # 处理 pos_records 中的 datetime 对象
        if 'pos_records' in d:
            serialized_records = {}
            for sym, rec in d['pos_records'].items():
                serialized_rec = rec.copy()
                # 将 datetime 转换为 ISO 格式字符串
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

        # 处理 pos_records 中的 datetime 字符串
        t.pos_records = {}
        for sym, rec in d.get("pos_records", {}).items():
            deserialized_rec = rec.copy()
            # 将 ISO 格式字符串转换回 datetime 对象
            if 'entry_dt' in deserialized_rec and deserialized_rec['entry_dt'] is not None:
                if isinstance(deserialized_rec['entry_dt'], str):
                    try:
                        deserialized_rec['entry_dt'] = datetime.fromisoformat(deserialized_rec['entry_dt'])
                    except (ValueError, AttributeError):
                        # 如果解析失败，设为 None
                        deserialized_rec['entry_dt'] = None
            t.pos_records[sym] = deserialized_rec

        return t

    def update_value(self, price_map):
        val = self.cash
        for sym, shares in self.holdings.items():
            if sym in price_map:
                price = price_map[sym]
                val += shares * price
                # 记录高点 (如果是 algo 调用，这里只能更新收盘价；on_bar 会更新盘中高点)
                if sym in self.pos_records:
                    self.pos_records[sym]['high_price'] = max(self.pos_records[sym]['high_price'], price)
        self.total_value = val

    def check_guard(self, price_map, current_dt=None):
        """检查止损/止盈条件，支持保护期和动态止损"""
        to_sell = []
        for sym, rec in self.pos_records.items():
            if sym not in self.holdings: continue
            
            # 保护期检查：买入后 N 天内不触发止损
            entry_dt = rec.get('entry_dt')
            if current_dt and entry_dt and PROTECTION_DAYS > 0:
                days_held = (current_dt - entry_dt).days
                if days_held <= PROTECTION_DAYS:
                    continue  # 跳过保护期内的标的
            
            curr_p = price_map.get(sym, 0)
            if curr_p <= 0: continue
            entry, high = rec['entry_price'], rec['high_price']
            
            # 🆕 动态止损：根据标的波动率调整止损线
            if DYNAMIC_STOP_LOSS and 'volatility' in rec:
                vol = rec['volatility']
                # 止损 = 入场价 * (1 - K * 波动率)
                # 但设置上下限：最小10%，最大30%
                dynamic_sl = max(0.10, min(0.30, ATR_MULTIPLIER * vol))
                is_sl = curr_p < entry * (1 - dynamic_sl)
            else:
                is_sl = curr_p < entry * (1 - STOP_LOSS)
            
            # 移动止盈回落
            is_tp = high > entry * (1 + TRAILING_TRIGGER) and curr_p < high * (1 - TRAILING_DROP)
            
            if is_sl or is_tp:
                to_sell.append(sym)
        return to_sell

    def sell(self, symbol, price):
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
        """买入标的，记录买入时间和波动率用于动态止损"""
        if price <= 0: return 0
        shares = int(cash_allocated / price / 100) * 100
        cost = shares * price
        if shares > 0 and self.cash >= cost:
            self.cash -= cost
            self.holdings[symbol] = self.holdings.get(symbol, 0) + shares
            self.pos_records[symbol] = {
                'entry_price': price, 
                'high_price': price,
                'entry_dt': current_dt,
                'volatility': volatility or 0.02  # 默认 2% 日波动
            }
            return shares
        return 0

class RollingPortfolioManager:
    def __init__(self, state_path=None):
        self.tranches = []
        self.initialized = False
        self.days_count = 0 
        self.state_path = state_path or os.path.join(config.BASE_DIR, STATE_FILE)
        self.nav_history = []

    def load_state(self):
        if not os.path.exists(self.state_path): return False
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
        try:
            temp_path = self.state_path + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump({"days_count": self.days_count, "tranches": [t.to_dict() for t in self.tranches]}, f, indent=2)
            if os.path.exists(self.state_path): os.remove(self.state_path)
            os.rename(temp_path, self.state_path)
        except Exception: pass

    def initialize_tranches(self, total_cash):
        share = total_cash / REBALANCE_PERIOD_T
        self.tranches = [Tranche(i, share) for i in range(REBALANCE_PERIOD_T)]
        self.initialized = True
        self.save_state()

    @property
    def total_holdings(self):
        combined = {}
        for t in self.tranches:
            for sym, shares in t.holdings.items():
                combined[sym] = combined.get(sym, 0) + shares
        return combined

    def reconcile_with_broker(self, real_pos):
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
                        if t.holdings[sym] == 0: t.holdings.pop(sym, None)
                        remaining -= remove_qty
                        if remaining <= 0: break

def init(context):
    print(f"🚀 Main Strategy Upgrading to V2 (Meta-Gate Enabled)...")
    context.rpm = RollingPortfolioManager()
    context.mode = MODE_BACKTEST if os.environ.get('GM_MODE', 'BACKTEST').upper() == 'BACKTEST' else MODE_LIVE
    # 绑定账户 (仅实盘)
    if context.mode == MODE_LIVE:
        context.account_id = ACCOUNT_ID
        
    print(f"💳 Mode: {context.mode} | Account: {getattr(context, 'account_id', 'BACKTEST')}")
    
    # 风险状态机
    context.market_state, context.risk_scaler, context.br_history = 'SAFE', 1.0, []
    context.BR_CAUTION_IN, context.BR_CAUTION_OUT = 0.40, 0.30
    context.BR_DANGER_IN, context.BR_DANGER_OUT, context.BR_PRE_DANGER = 0.60, 0.50, 0.55
    
    # 加载白名单
    df_excel = pd.read_excel(os.path.join(config.BASE_DIR, "ETF合并筛选结果.xlsx"))
    df_excel.columns = df_excel.columns.str.strip()
    df_excel = df_excel.rename(columns={'symbol': 'etf_code', 'sec_name': 'etf_name', 'name_cleaned': 'theme'})
    context.whitelist = set(df_excel['etf_code'])
    context.theme_map = df_excel.set_index('etf_code')['theme'].to_dict()

    # 数据加载 (使用 Cache 逻辑以对齐 main2)
    start_dt = (pd.Timestamp(START_DATE) - timedelta(days=400)).strftime('%Y-%m-%d %H:%M:%S')
    end_dt = END_DATE if context.mode == MODE_BACKTEST else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    cache_file = os.path.join(config.BASE_DIR, "backtest_data_cache.pkl")
    need_refetch = True  # 默认需要重新获取
    USE_CACHE = False    # 🔧 纯 API 模式，不使用缓存
    
    if USE_CACHE and os.path.exists(cache_file) and context.mode == MODE_BACKTEST:
        try:
            cache = pd.read_pickle(cache_file)
            context.prices_df = cache['prices']
            context.benchmark_df = cache['benchmark']
            context.volumes_df = cache.get('volumes', pd.DataFrame())
            # 验证缓存完整性
            if context.volumes_df.empty:
                raise ValueError("Cache missing volumes")
            if context.benchmark_df is None or (hasattr(context.benchmark_df, 'empty') and context.benchmark_df.empty):
                raise ValueError("Cache missing benchmark")
            need_refetch = False
            print("✅ 缓存加载成功")
        except Exception as e:
            print(f"⚠️ Cache invalid/missing ({e}), refetching...")
            context.prices_df = None
            context.benchmark_df = None  # 🔧 修复: 同时重置 benchmark_df
            context.volumes_df = None
            need_refetch = True
    
    if need_refetch:
        sym_str = ",".join(context.whitelist)
        
        # 1. Prices
        print("📊 获取价格数据...")
        hd = history(symbol=sym_str, frequency='1d', start_time=start_dt, end_time=end_dt, fields='symbol,close,eob', fill_missing='last', adjust=ADJUST_PREV, df=True)
        hd['eob'] = pd.to_datetime(hd['eob']).dt.tz_localize(None)
        context.prices_df = hd.pivot(index='eob', columns='symbol', values='close').ffill()
        
        # 2. Volumes
        print("📊 获取成交量数据...")
        vol_data = history(symbol=sym_str, frequency='1d', start_time=start_dt, end_time=end_dt, fields='symbol,volume,eob', fill_missing='last', adjust=ADJUST_PREV, df=True)
        vol_data['eob'] = pd.to_datetime(vol_data['eob']).dt.tz_localize(None)
        context.volumes_df = vol_data.pivot(index='eob', columns='symbol', values='volume').ffill()
        
        # 3. Benchmark (🔧 修复: 正确获取基准数据)
        print(f"📊 获取基准数据 ({MACRO_BENCHMARK})...")
        bm_data = history(symbol=MACRO_BENCHMARK, frequency='1d', start_time=start_dt, end_time=end_dt, fields='close,eob', fill_missing='last', adjust=ADJUST_PREV, df=True)
        bm_data['eob'] = pd.to_datetime(bm_data['eob']).dt.tz_localize(None)
        context.benchmark_df = bm_data.set_index('eob')['close']
        print(f"✅ Benchmark 数据: {len(context.benchmark_df)} 条, 最新: {context.benchmark_df.iloc[-1]:.2f} @ {context.benchmark_df.index[-1]}")
        
        # 4. 保存缓存
        if context.mode == MODE_BACKTEST and USE_CACHE:
            print("💾 保存缓存...")
            pd.to_pickle({'prices': context.prices_df, 'benchmark': context.benchmark_df, 'volumes': context.volumes_df}, cache_file)

    if context.mode == MODE_LIVE: context.rpm.load_state()
    
    subscribe(symbols=list(context.whitelist) if context.mode == MODE_LIVE else 'SHSE.000001', frequency='60s' if context.mode == MODE_LIVE else '1d')
    exec_time = os.environ.get('OPT_EXEC_TIME', '14:55:00')
    schedule(schedule_func=algo, date_rule='1d', time_rule=exec_time)

# === 硬核风控常量 ===
MAX_DAILY_LOSS_PCT = 0.04   # 单日亏损超过 4% -> 熔断 (只卖不买)
MAX_ORDER_VAL_PCT = 0.25    # 单笔订单最大占比 (防止乌龙指满仓)
MAX_REJECT_COUNT = 5        # 单日废单容忍度
DATA_TIMEOUT_SEC = 180      # 数据延迟容忍 (3分钟)

class RiskController:
    """宪兵队：凌驾于策略之上的硬风控"""
    def __init__(self):
        self.initial_nav_today = 0.0
        self.reject_count = 0
        self.active = True
        self.last_day = None

    def on_day_start(self, context):
        current_day = context.now.date()
        if self.last_day != current_day:
            # 新的一天，重置数据
            acc = context.account(account_id=context.account_id) if context.mode == MODE_LIVE else context.account()
            if acc:
                self.initial_nav_today = acc.cash.nav
            self.reject_count = 0
            self.active = True
            self.last_day = current_day
            print(f"️ [RISK] Day Start: NAV Locked at {self.initial_nav_today:.2f}")

    def check_daily_loss(self, context):
        """检查单日亏损是否触达熔断线"""
        acc = context.account(account_id=context.account_id) if context.mode == MODE_LIVE else context.account()
        if not acc or self.initial_nav_today <= 0: return True
        
        current_nav = acc.cash.nav
        dd_pct = 1 - (current_nav / self.initial_nav_today)
        
        if dd_pct > MAX_DAILY_LOSS_PCT:
            if self.active:
                print(f"🧨 [RISK MELTDOWN] Daily Loss {dd_pct:.2%} > Limit {MAX_DAILY_LOSS_PCT:.2%}. TRADING HALTED.")
                self.active = False
            return False # 熔断中
        return True # 正常

    def validate_order(self, context, symbol, value, total_scan_val):
        """检查单笔订单合规性"""
        if not self.active: return False
        
        # 1. 检查单笔金额占比
        if total_scan_val > 0 and (value / total_scan_val) > MAX_ORDER_VAL_PCT + 0.05: # 给5%容错
            print(f"🛡️ [RISK] Order Reject: {symbol} Val {value:.0f} > Max {MAX_ORDER_VAL_PCT:.0%} of NAV")
            return False
            
        return True

class DataGuard:
    """数据质检员：防止脏数据和延迟数据杀人"""
    @staticmethod
    def check_freshness(ticks, current_dt):
        return True # 暂略

class EmailNotifier:
    """战地通讯员：发送每日收盘战报"""
    def __init__(self):
        # === 📧 邮件配置 ===
        self.smtp_server = os.environ.get('EMAIL_HOST', 'smtp.163.com')
        self.smtp_port = int(os.environ.get('EMAIL_PORT', 465))
        self.sender = os.environ.get('EMAIL_USER', 'tanjhu@163.com')
        self.password = os.environ.get('EMAIL_PASS', 'KHdqTEPNXViSJpJs')
        self.receivers = [os.environ.get('EMAIL_TO', 'tanjhu@163.com')]
        
    def send_report(self, context):
        """生成并发送 HTML 战报"""
        if context.mode == MODE_BACKTEST: return
        
        try:
            acc = context.account(account_id=context.account_id)
            if not acc: return
            
            nav = acc.cash.nav
            cash = acc.cash.available
            initial = risk_safe.initial_nav_today if 'risk_safe' in globals() else nav
            ret_pct = (nav - initial) / initial if initial > 0 else 0.0
            
            # 持仓列表
            pos_rows = ""
            for p in acc.positions():
                name = context.theme_map.get(p.symbol, p.symbol)
                color = "red" if p.fpnl > 0 else "green"
                pos_rows += f"<tr><td>{p.symbol}</td><td>{name}</td><td>{int(p.amount)}</td><td>{p.market_value:.0f}</td><td style='color:{color}'>{p.fpnl:.0f}</td></tr>"
            
            state = getattr(context, 'market_state', 'UNKNOWN')
            status_color = {'SAFE': 'green', 'CAUTION': 'orange', 'DANGER': 'red'}.get(state, 'black')
            
            html_content = f"""
            <div style="font-family: Arial;">
                <h2 style="color: #333;">📈 量化策略日报 ({context.now.strftime('%Y-%m-%d')})</h2>
                <ul>
                    <li>💰 NAV: {nav:,.2f}</li>
                    <li>📊 Return: <span style="color: {'red' if ret_pct>=0 else 'green'}">{ret_pct:.2%}</span></li>
                    <li>🚦 State: <span style="background-color: {status_color}; color: white; padding: 2px;">{state}</span></li>
                </ul>
                <table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; width: 100%;">
                    <tr style="background-color: #f2f2f2;"><th>Symbol</th><th>Name</th><th>Vol</th><th>MktVal</th><th>PnL</th></tr>
                    {pos_rows}
                </table>
            </div>
            """
            
            msg = MIMEMultipart()
            msg['From'] = self.sender
            msg['To'] = ",".join(self.receivers)
            msg['Subject'] = Header(f"策略战报: {ret_pct:.2%} | NAV {int(nav)}", 'utf-8')
            msg.attach(MIMEText(html_content, 'html', 'utf-8'))
            
            server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
            server.login(self.sender, self.password)
            server.sendmail(self.sender, self.receivers, msg.as_string())
            server.quit()
            print(f"📧 Report sent to {self.receivers}")
        except Exception as e:
            print(f"⚠️ Email Failed: {e}")

class WechatNotifier:
    """通讯兵：企业微信群机器人通知"""
    def __init__(self):
        self.webhook_url = os.environ.get('WECHAT_WEBHOOK', 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=aa6eb940-0d50-489f-801e-26c467d77a30') 
        
    def send_report(self, context):
        if not self.webhook_url or context.mode == MODE_BACKTEST: return
        try:
            import urllib.request
            acc = context.account(account_id=context.account_id)
            if not acc: return
            
            nav = acc.cash.nav
            initial = risk_safe.initial_nav_today if 'risk_safe' in globals() else nav
            ret_pct = (nav - initial) / initial if initial > 0 else 0.0
            
            md_content = f"# 🚀 战报 {context.now.strftime('%m-%d')}\n**NAV**: {nav:,.2f}\n**P&L**: {ret_pct:.2%}\n**State**: {getattr(context, 'market_state', 'N/A')}"
            
            data = {"msgtype": "markdown", "markdown": {"content": md_content}}
            headers = {'Content-Type': 'application/json'}
            req = urllib.request.Request(url=self.webhook_url, headers=headers, data=json.dumps(data).encode('utf-8'))
            urllib.request.urlopen(req)
            print("🤖 WeChat Notification sent.")
        except Exception as e:
            print(f"⚠️ WeChat Send Failed: {e}")

# 全局单例
if 'risk_safe' not in globals(): risk_safe = RiskController()
if 'mailer' not in globals(): mailer = EmailNotifier()
if 'wechat' not in globals(): wechat = WechatNotifier()

def get_market_regime(context, current_dt):
    # 1/2 年线宏通风控 + 20/60日线微观风控
    hist = context.prices_df[context.prices_df.index <= current_dt]
    if len(hist) < 60: return 1.0
    bm_hist = context.benchmark_df[context.benchmark_df.index <= current_dt]
    
    macro_mult = 1.0
    if len(bm_hist) > 120 and bm_hist.iloc[-1] < bm_hist.tail(120).mean(): macro_mult = 0.5
    
    recent = hist.tail(60)
    strength = ((recent.iloc[-1] > recent.tail(20).mean()).mean() + (recent.iloc[-1] > recent.mean()).mean()) / 2
    base_pos = 1.0 if strength > 0.6 else 0.9 if strength > 0.4 else 0.3
    if macro_mult < 1.0 and strength <= 0.4: return 0.0
    return base_pos * macro_mult

def get_ranking(context, current_dt):
    # Meta-Gate 逻辑核心
    hist = context.prices_df[context.prices_df.index <= current_dt]
    if len(hist) < 251: return None, None
    last = hist.iloc[-1]
    
    # 动量评分
    scores = pd.Series(0.0, index=hist.columns)
    periods = {1: 30, 3: -70, 20: 150}
    rets = {f'r{p}': (last / hist.iloc[-(p+1)]) - 1 for p in [1, 3, 5, 20]}
    
    for p, pts in periods.items():
        ranks = rets[f'r{p}'].rank(ascending=False)
        scores += ((30 - ranks) / 30).clip(lower=0) * pts
    
    # Z-Score 结构门控 (核心防御)
    daily_rets = hist.pct_change()
    vol_ruler = daily_rets.iloc[:-5].tail(60).std().clip(lower=0.005)
    z_score = rets['r5'] / (vol_ruler * np.sqrt(5))
    
    # Meta-Gate 状态机
    k_crash = float(os.environ.get('OPT_K_CRASH', 2.5))
    universe_z = z_score[z_score.index.isin(context.whitelist)].dropna()
    if len(universe_z) >= 20:
        br_smooth = np.mean((context.br_history + [ (universe_z < -k_crash).mean() ])[-3:])
        context.br_history = (context.br_history + [ (universe_z < -k_crash).mean() ])[-3:]
        
        # 状态机维护
        danger_in = 0.5 if np.median(universe_z) < -2.3 else context.BR_DANGER_IN
        if context.market_state == 'SAFE' and br_smooth > context.BR_CAUTION_IN: context.market_state = 'CAUTION'
        elif context.market_state == 'CAUTION':
            if br_smooth > danger_in: context.market_state = 'DANGER'
            elif br_smooth < context.BR_CAUTION_OUT: context.market_state = 'SAFE'
        elif context.market_state == 'DANGER' and br_smooth < context.BR_DANGER_OUT: context.market_state = 'CAUTION'
        
        context.risk_scaler = 0.0 if context.market_state == 'DANGER' else (0.7 if br_smooth >= context.BR_PRE_DANGER else 1.0)

    # 过滤弱点
    k_entry = float(os.environ.get('OPT_R5_K', 1.6))
    valid = (scores * (z_score > -k_entry).astype(float)).loc[list(context.whitelist)]
    valid = valid[valid >= MIN_SCORE]
    if valid.empty: return None, scores
    
    df = pd.DataFrame({'score': valid, 'theme': [context.theme_map.get(c, 'Unknown') for c in valid.index]})
    for p in [1, 3, 5, 20]: df[f'r{p}'] = rets[f'r{p}'][valid.index]
    return df.sort_values(by=['score', 'r1', 'r20'], ascending=False), scores

def algo(context):
    current_dt = context.now.replace(tzinfo=None)

    # === 风控前置检查 (仅实盘) ===
    if context.mode == MODE_LIVE:
        # 1. 更新每日初始 NAV（用于熔断检测）
        risk_safe.on_day_start(context)

        # 2. 检查是否触发熔断
        if not risk_safe.check_daily_loss(context):
            print(f"⚠️  [ALGO] 触发熔断，今日不交易")
            return

    # 注入实时行情 (Live)
    if context.mode == MODE_LIVE:
        ticks = current(symbols=list(context.whitelist))
        td = {t['symbol']: t['price'] for t in ticks if t['price'] > 0}
        if td:
            rows = pd.DataFrame([td], index=[current_dt.replace(hour=0,minute=0,second=0,microsecond=0)])
            context.prices_df = pd.concat([context.prices_df[~context.prices_df.index.isin(rows.index)], rows]).sort_index()

    context.rpm.days_count += 1
    if not context.rpm.initialized:
        acc = context.account(account_id=context.account_id) if context.mode == MODE_LIVE else context.account()
        if acc: context.rpm.initialize_tranches(acc.cash.nav)
        else: return

    # 1. 更新价值与止损
    price_map = context.prices_df[context.prices_df.index <= current_dt].iloc[-1].to_dict()
    for t in context.rpm.tranches:
        t.update_value(price_map)
        to_sell = t.check_guard(price_map, current_dt)  # 🆕 传入当前时间
        if to_sell:
            t.guard_triggered_today = True
            for s in to_sell: t.sell(s, price_map.get(s, 0))
        else: t.guard_triggered_today = False

    # 2. 轮动调仓 (Soft Rotation)
    active_idx = (context.rpm.days_count - 1) % REBALANCE_PERIOD_T
    active_t = context.rpm.tranches[active_idx]
    
    rank_df, _ = get_ranking(context, current_dt)
    if rank_df is not None and not active_t.guard_triggered_today:
        # 🆕 动态 TOP_N：根据市场状态调整持仓数量
        if DYNAMIC_TOP_N:
            current_top_n = TOP_N_BY_STATE.get(context.market_state, TOP_N)
        else:
            current_top_n = TOP_N
        
        # A. 生成目标候选名单 (Top N + Buffer)
        candidates = []
        themes = {}
        for code, row in rank_df.iterrows():
            if themes.get(row['theme'], 0) < MAX_PER_THEME:
                candidates.append(code)
                themes[row['theme']] = themes.get(row['theme'], 0) + 1
        
        # 定义核心名单和缓冲区名单
        core_targets = candidates[:current_top_n]
        buffer_targets = candidates[:current_top_n + TURNOVER_BUFFER]
        
        # B. 智能保留逻辑
        existing_holdings = list(active_t.holdings.keys())
        kept_holdings = []
        targets_to_buy = []
        
        # 先处理持仓：如果在缓冲区内，则保留
        current_slots_used = 0
        for s in existing_holdings:
            # 如果持仓不仅在 Buffer 内，且没有触发主题限制（虽然上面生成candidates已经过滤了主题，但这里简单起见只校验Buffer）
            if s in buffer_targets and current_slots_used < current_top_n:
                kept_holdings.append(s)
                current_slots_used += 1
            else:
                # 掉出缓冲区，卖出
                active_t.sell(s, price_map.get(s, 0))
        
        # C. 填充新标的
        # 从核心名单中选，跳过已经保留的
        for s in core_targets:
            if current_slots_used >= current_top_n: break
            if s not in kept_holdings:
                targets_to_buy.append(s)
                current_slots_used += 1

        # D. 执行买入
        scale = (get_market_regime(context, current_dt) if DYNAMIC_POSITION else 1.0) * (context.risk_scaler if ENABLE_META_GATE else 1.0)
        
        # 动态分配资金：保留仓位的资金不轻举妄动，只对释放出的现金进行再分配
        # 简化逻辑：计算每个 Slot 应该分到的总资产 (Total Value / TOP_N)
        target_slot_val = (active_t.total_value * 0.99 * scale) / current_top_n
        
        # 补齐保留仓位 (Rebalance) + 买入新仓位
        final_list = kept_holdings + targets_to_buy
        
        # 排序：前3名双培权重 (如果启用权重逻辑)
        # 简单起见，这里假设均仓。如果需要权重逻辑，需要更复杂的配平。
        # 沿用原逻辑：前3名 2x，后面 1x。总份数 = 3*2 + (N-3)*1
        weights = {s: (2 if i < 3 else 1) for i, s in enumerate(candidates) if s in final_list} # 使用其在排名中的原始顺序决定权重
        total_w = sum(weights.values())
        if total_w > 0:
             unit_val = (active_t.total_value * 0.99 * scale) / total_w
             for s in final_list:
                 target_val = unit_val * weights[s]
                 current_val = active_t.holdings.get(s, 0) * price_map.get(s, 0)
                 diff_val = target_val - current_val
                 
                 if diff_val > 0:
                     # 🆕 计算标的历史波动率用于动态止损
                     vol = None
                     if DYNAMIC_STOP_LOSS:
                         hist = context.prices_df[context.prices_df.index <= current_dt]
                         if s in hist.columns and len(hist) > ATR_LOOKBACK:
                             daily_rets = hist[s].pct_change().dropna()
                             if len(daily_rets) >= ATR_LOOKBACK:
                                 vol = daily_rets.tail(ATR_LOOKBACK).std()
                     active_t.buy(s, diff_val, price_map.get(s, 0), current_dt, vol)
                 elif diff_val < -100: # 卖出再平衡 (由于Buffer的存在，这里可能不需要严格再平衡，但为了风控还是做)
                     # 软冲销的精髓：如果已经在持仓，尽量少动。
                     # 这里做一个阈值：只有偏离超过 20% 才再平衡，否则躺平
                     if abs(diff_val) > target_val * 0.2:
                         qty = int(abs(diff_val) / price_map.get(s, 1) / 100) * 100
                         if qty > 0: active_t.sell_qty(s, qty, price_map.get(s, 0)) # 需要新增 sell_qty 方法
    
    else:
        # 排名失败或当天止损，全卖
        for s in list(active_t.holdings.keys()): active_t.sell(s, price_map.get(s, 0))

    # 3. 最终同步
    tgt_qty = context.rpm.total_holdings
    acc = context.account(account_id=context.account_id) if context.mode == MODE_LIVE else context.account()
    for pos in acc.positions():
        diff = pos.amount - tgt_qty.get(pos.symbol, 0)
        if diff > 0 and pos.available > 0:
            order_volume(symbol=pos.symbol, volume=int(min(diff, pos.available)), side=OrderSide_Sell, order_type=OrderType_Market, position_effect=PositionEffect_Close)
    
    for sym, qty in tgt_qty.items():
        order_target_volume(symbol=sym, volume=int(qty), position_side=PositionSide_Long, order_type=OrderType_Market)

    context.rpm.save_state()
    
    # === 📧 每日收盘汇报 (仅实盘) ===
    if context.mode == MODE_LIVE:
        print(f"📤 Sending Daily Reports...")
        mailer.send_report(context)
        wechat.send_report(context)

def on_bar(context, bars):
    # 盘中高频止损 (追平实盘收益的关键)
    if context.mode == MODE_BACKTEST: return
    bar_dt = context.now.replace(tzinfo=None)  # 🆕 获取当前时间
    for bar in bars:
        for t in context.rpm.tranches:
            if bar.symbol in t.holdings:
                rec = t.pos_records.get(bar.symbol)
                if not rec: continue
                
                # 🆕 保护期检查
                entry_dt = rec.get('entry_dt')
                if entry_dt and PROTECTION_DAYS > 0:
                    days_held = (bar_dt - entry_dt).days
                    if days_held <= PROTECTION_DAYS:
                        continue  # 保护期内不触发止损
                
                rec['high_price'] = max(rec['high_price'], bar.high)
                entry, high, curr = rec['entry_price'], rec['high_price'], bar.close
                if curr < entry * (1-STOP_LOSS) or (high > entry*(1+TRAILING_TRIGGER) and curr < high*(1-TRAILING_DROP)):
                    print(f"⚡ Guard Trigger: {bar.symbol}")
                    order_target_percent(symbol=bar.symbol, percent=0, position_side=PositionSide_Long, order_type=OrderType_Market)
                    t.sell(bar.symbol, curr)
                    context.rpm.save_state()

def on_backtest_finished(context, indicator):
    dsl_status = f"ATR*{ATR_MULTIPLIER}" if DYNAMIC_STOP_LOSS else f"Fixed {STOP_LOSS*100:.0f}%"
    dtn_status = "Dynamic" if DYNAMIC_TOP_N else f"Fixed {TOP_N}"
    print(f"\n=== REPORT (BUFFER={TURNOVER_BUFFER}, SL={dsl_status}, TOP_N={dtn_status}) ===")
    print(f"Return: {indicator.get('pnl_ratio', 0)*100:.2f}% | MaxDD: {indicator.get('max_drawdown', 0)*100:.2f}% | Sharpe: {indicator.get('sharp_ratio', 0):.2f}")

if __name__ == '__main__':
    RUN_MODE = os.environ.get('GM_MODE', 'BACKTEST').upper()
    STRATEGY_ID = '60e6472f-01ac-11f1-a1c0-00ffda9d6e63'
    if RUN_MODE == 'LIVE':
        run(strategy_id=STRATEGY_ID, filename='main.py', mode=MODE_LIVE, token=os.getenv('MY_QUANT_TGM_TOKEN'))
    else:
        run(strategy_id=STRATEGY_ID, filename='main.py', mode=MODE_BACKTEST, token=os.getenv('MY_QUANT_TGM_TOKEN'), backtest_start_time=START_DATE, backtest_end_time=END_DATE, backtest_adjust=ADJUST_PREV, backtest_initial_cash=1000000, backtest_commission_ratio=0.0001)