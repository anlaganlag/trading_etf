"""
🎯 滚动持仓回测系统 - 真实账户模拟
Rolling Position Backtesting System

核心特性:
1. 每天开新仓（等权买入4只股票）
2. 持有期到期自动平仓
3. 实时计算账户净值（现金 + 所有持仓市值）
4. 真实的最大回撤（账户净值曲线）
5. 资金利用率跟踪
"""

import pandas as pd
import numpy as np
from gm.api import *
from config import config
from datetime import datetime, timedelta
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

# AI 最优权重
AI_WEIGHTS = np.array([
     0.040,  0.009, -0.071,  0.014, -0.073,  0.023,  0.083, -0.041,  0.061,  0.111,
     0.094,  0.014,  0.084,  0.055,  0.066, -0.035,  0.047, -0.003,  0.035, -0.040
])

class RollingPortfolioBacktest:
    """滚动持仓回测引擎"""

    def __init__(self, initial_capital=1_000_000, hold_period=10, stocks_per_day=4):
        """
        初始化回测引擎

        Parameters:
        - initial_capital: 初始资金（元）
        - hold_period: 持有天数
        - stocks_per_day: 每天买入股票数量
        """
        self.initial_capital = initial_capital
        self.hold_period = hold_period
        self.stocks_per_day = stocks_per_day

        # 每天开仓资金 = 初始资金 / 持有期（确保满仓运行）
        self.daily_budget = initial_capital / hold_period

        # 账户状态
        self.cash = initial_capital
        self.positions = []  # [{stock, shares, buy_price, buy_date, target_date}, ...]

        # 记录
        self.equity_curve = []  # 每日净值
        self.cash_curve = []    # 每日现金
        self.position_value_curve = []  # 每日持仓市值
        self.trades_log = []    # 交易记录
        self.daily_returns = [] # 每日收益率

    def calculate_ai_scores(self, prices_df, target_date):
        """计算AI评分"""
        hist = prices_df.loc[:target_date]
        if len(hist) < 22:
            return None

        latest_price = hist.iloc[-1]
        final_scores = pd.Series(0.0, index=hist.columns)

        for i in range(20):
            period = i + 1
            w = AI_WEIGHTS[i]

            prev_price = hist.iloc[-(period+1)]
            ret = latest_price / prev_price - 1

            ranks = ret.rank(ascending=False, method='min')
            top_100_mask = (ranks <= 100)

            score_p = (101 - ranks[top_100_mask]) / 100.0
            final_scores[top_100_mask] += score_p * w

        return final_scores

    def open_positions(self, date, stocks, prices):
        """
        开新仓位

        Parameters:
        - date: 买入日期
        - stocks: 要买入的股票列表
        - prices: 当日价格字典 {stock: price}
        """
        # 检查可用资金
        available = min(self.cash, self.daily_budget)

        if available < self.daily_budget * 0.1:  # 资金不足10%
            return

        # 等权分配
        per_stock_budget = available / len(stocks)

        for stock in stocks:
            if stock not in prices or pd.isna(prices[stock]) or prices[stock] <= 0:
                continue

            price = prices[stock]
            shares = int(per_stock_budget / price)  # 买入股数（取整）

            if shares <= 0:
                continue

            cost = shares * price

            # 扣除现金
            self.cash -= cost

            # 记录持仓
            target_date = date + pd.Timedelta(days=self.hold_period)
            self.positions.append({
                'stock': stock,
                'shares': shares,
                'buy_price': price,
                'buy_date': date,
                'target_date': target_date,
                'cost': cost
            })

            # 记录交易
            self.trades_log.append({
                'date': date,
                'type': 'BUY',
                'stock': stock,
                'shares': shares,
                'price': price,
                'amount': cost
            })

    def close_positions(self, date, prices):
        """
        平仓到期持仓

        Parameters:
        - date: 当前日期
        - prices: 当日价格字典
        """
        positions_to_close = []

        for i, pos in enumerate(self.positions):
            # 检查是否到期（实际交易日可能不是target_date，取最近的）
            if date >= pos['target_date']:
                positions_to_close.append(i)

        # 从后往前删除（避免索引错乱）
        for i in reversed(positions_to_close):
            pos = self.positions.pop(i)

            stock = pos['stock']

            # 获取卖出价格
            if stock in prices and pd.notna(prices[stock]) and prices[stock] > 0:
                sell_price = prices[stock]
            else:
                # 停牌或退市，按买入价计算（保守）
                sell_price = pos['buy_price']

            # 回笼资金
            proceeds = pos['shares'] * sell_price
            self.cash += proceeds

            # 记录交易
            self.trades_log.append({
                'date': date,
                'type': 'SELL',
                'stock': stock,
                'shares': pos['shares'],
                'price': sell_price,
                'amount': proceeds,
                'pnl': proceeds - pos['cost'],
                'return': (sell_price / pos['buy_price'] - 1) * 100
            })

    def calculate_equity(self, prices):
        """
        计算当前账户净值

        Parameters:
        - prices: 当日价格字典

        Returns:
        - equity: 总净值
        - position_value: 持仓市值
        """
        position_value = 0

        for pos in self.positions:
            stock = pos['stock']

            if stock in prices and pd.notna(prices[stock]) and prices[stock] > 0:
                current_price = prices[stock]
            else:
                # 停牌，用买入价
                current_price = pos['buy_price']

            position_value += pos['shares'] * current_price

        equity = self.cash + position_value

        return equity, position_value

    def run(self, prices_df, start_date=None, end_date=None):
        """
        运行回测

        Parameters:
        - prices_df: 价格数据 (index=date, columns=stocks)
        - start_date: 开始日期（None则从第30个交易日开始，确保有历史数据）
        - end_date: 结束日期（None则到最后）
        """
        trade_dates = prices_df.index

        # 确定回测区间
        if start_date is None:
            start_idx = 30  # 留出30天计算信号
        else:
            start_idx = trade_dates.get_loc(start_date)

        if end_date is None:
            end_idx = len(trade_dates)
        else:
            end_idx = trade_dates.get_loc(end_date) + 1

        print(f"🎯 滚动持仓回测")
        print(f"   初始资金: {self.initial_capital:,.0f} 元")
        print(f"   持有期: {self.hold_period} 天")
        print(f"   每天买入: {self.stocks_per_day} 只股票")
        print(f"   每天开仓资金: {self.daily_budget:,.0f} 元")
        print(f"   回测期间: {trade_dates[start_idx]} 到 {trade_dates[end_idx-1]}")
        print(f"   总交易日: {end_idx - start_idx}\n")

        # 逐日回测
        for idx in range(start_idx, end_idx):
            current_date = trade_dates[idx]

            # 当日价格
            current_prices = prices_df.loc[current_date].to_dict()

            # 1. 平仓到期持仓
            self.close_positions(current_date, current_prices)

            # 2. 计算AI评分，选股
            scores = self.calculate_ai_scores(prices_df, current_date)

            if scores is not None:
                # 选出Top N
                top_stocks = scores.nlargest(self.stocks_per_day).index.tolist()

                # 3. 开新仓
                self.open_positions(current_date, top_stocks, current_prices)

            # 4. 计算账户净值
            equity, position_value = self.calculate_equity(current_prices)

            # 5. 记录
            self.equity_curve.append(equity)
            self.cash_curve.append(self.cash)
            self.position_value_curve.append(position_value)

            # 计算日收益率
            if len(self.equity_curve) > 1:
                daily_ret = (equity / self.equity_curve[-2] - 1) * 100
                self.daily_returns.append(daily_ret)

            # 进度显示
            if (idx - start_idx + 1) % 20 == 0:
                progress = (idx - start_idx + 1) / (end_idx - start_idx) * 100
                print(f"  回测进度: {progress:.1f}% | 当前净值: {equity:,.0f} | 持仓数: {len(self.positions)}")

        print(f"\n✅ 回测完成!\n")

        # 转换为DataFrame便于分析
        self.results_df = pd.DataFrame({
            'date': trade_dates[start_idx:end_idx],
            'equity': self.equity_curve,
            'cash': self.cash_curve,
            'position_value': self.position_value_curve
        })

        return self.results_df

    def calculate_metrics(self):
        """计算回测指标"""
        equity_series = np.array(self.equity_curve)

        # 总收益
        total_return = (equity_series[-1] / self.initial_capital - 1) * 100

        # 最大回撤（真实账户净值回撤）
        running_max = np.maximum.accumulate(equity_series)
        drawdown = (equity_series - running_max) / running_max * 100
        max_drawdown = np.min(drawdown)

        # 找出最大回撤的位置
        max_dd_idx = np.argmin(drawdown)
        max_dd_peak_idx = np.argmax(equity_series[:max_dd_idx+1]) if max_dd_idx > 0 else 0

        # 年化收益（简化：假设252交易日）
        trading_days = len(equity_series)
        years = trading_days / 252
        annual_return = ((equity_series[-1] / self.initial_capital) ** (1/years) - 1) * 100 if years > 0 else 0

        # 波动率（年化）
        daily_returns = np.array(self.daily_returns) if self.daily_returns else np.array([0])
        annual_vol = np.std(daily_returns) * np.sqrt(252)

        # 夏普比率（假设无风险利率=3%）
        sharpe = (annual_return - 3) / annual_vol if annual_vol > 0 else 0

        # 交易统计
        trades = [t for t in self.trades_log if t['type'] == 'SELL']
        total_trades = len(trades)

        if trades:
            returns = [t['return'] for t in trades]
            win_trades = [r for r in returns if r > 0]
            loss_trades = [r for r in returns if r < 0]

            win_rate = len(win_trades) / total_trades * 100 if total_trades > 0 else 0
            avg_win = np.mean(win_trades) if win_trades else 0
            avg_loss = np.mean(loss_trades) if loss_trades else 0
            profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

            best_trade = max(returns)
            worst_trade = min(returns)
        else:
            win_rate = avg_win = avg_loss = profit_loss_ratio = 0
            best_trade = worst_trade = 0

        # 资金利用率
        avg_position_value = np.mean(self.position_value_curve)
        capital_utilization = avg_position_value / self.initial_capital * 100

        metrics = {
            '初始资金': f'{self.initial_capital:,.0f}',
            '最终净值': f'{equity_series[-1]:,.0f}',
            '总收益率': f'{total_return:.2f}%',
            '年化收益率': f'{annual_return:.2f}%',
            '最大回撤': f'{max_drawdown:.2f}%',
            '年化波动率': f'{annual_vol:.2f}%',
            '夏普比率': f'{sharpe:.2f}',
            '总交易次数': total_trades,
            '胜率': f'{win_rate:.1f}%',
            '平均盈利': f'{avg_win:.2f}%',
            '平均亏损': f'{avg_loss:.2f}%',
            '盈亏比': f'{profit_loss_ratio:.2f}',
            '最佳交易': f'{best_trade:.2f}%',
            '最差交易': f'{worst_trade:.2f}%',
            '平均资金利用率': f'{capital_utilization:.1f}%',
            '回测天数': trading_days
        }

        return metrics

    def print_summary(self):
        """打印回测总结"""
        metrics = self.calculate_metrics()

        print("="*80)
        print("📊 滚动持仓回测报告")
        print("="*80)

        print("\n💰 收益指标:")
        print(f"   初始资金: {metrics['初始资金']}")
        print(f"   最终净值: {metrics['最终净值']}")
        print(f"   总收益率: {metrics['总收益率']}")
        print(f"   年化收益: {metrics['年化收益率']}")

        print("\n📉 风险指标:")
        print(f"   最大回撤: {metrics['最大回撤']}")
        print(f"   年化波动: {metrics['年化波动率']}")
        print(f"   夏普比率: {metrics['夏普比率']}")

        print("\n📈 交易统计:")
        print(f"   总交易数: {metrics['总交易次数']}")
        print(f"   胜率: {metrics['胜率']}")
        print(f"   平均盈利: {metrics['平均盈利']}")
        print(f"   平均亏损: {metrics['平均亏损']}")
        print(f"   盈亏比: {metrics['盈亏比']}")
        print(f"   最佳交易: {metrics['最佳交易']}")
        print(f"   最差交易: {metrics['最差交易']}")

        print("\n💼 资金使用:")
        print(f"   平均仓位: {metrics['平均资金利用率']}")

        print("\n⏱️  时间跨度:")
        print(f"   回测天数: {metrics['回测天数']}")

        # 策略评估
        print("\n" + "="*80)
        print("🎯 策略评估:")
        print("="*80)

        score = 0
        max_score = 5

        total_ret = float(metrics['总收益率'].rstrip('%'))
        max_dd = float(metrics['最大回撤'].rstrip('%'))
        sharpe = float(metrics['夏普比率'])
        win_rate = float(metrics['胜率'].rstrip('%'))
        pnl_ratio = float(metrics['盈亏比'])

        if total_ret > 0:
            print(f"✅ 总收益为正: {metrics['总收益率']}")
            score += 1
        else:
            print(f"❌ 总收益为负: {metrics['总收益率']}")

        if max_dd > -30:
            print(f"✅ 最大回撤可控 (<30%): {metrics['最大回撤']}")
            score += 1
        elif max_dd > -50:
            print(f"⚠️  最大回撤较大 (30-50%): {metrics['最大回撤']}")
            score += 0.5
        else:
            print(f"❌ 最大回撤过大 (>50%): {metrics['最大回撤']}")

        if sharpe > 1.0:
            print(f"✅ 夏普比率优秀 (>1.0): {metrics['夏普比率']}")
            score += 1
        elif sharpe > 0.5:
            print(f"⚠️  夏普比率尚可 (0.5-1.0): {metrics['夏普比率']}")
            score += 0.5
        else:
            print(f"❌ 夏普比率较低 (<0.5): {metrics['夏普比率']}")

        if win_rate > 50:
            print(f"✅ 胜率过半: {metrics['胜率']}")
            score += 1
        else:
            print(f"⚠️  胜率不足50%: {metrics['胜率']}")

        if pnl_ratio > 1.2:
            print(f"✅ 盈亏比良好 (>1.2): {metrics['盈亏比']}")
            score += 1
        elif pnl_ratio > 1.0:
            print(f"⚠️  盈亏比一般 (1.0-1.2): {metrics['盈亏比']}")
            score += 0.5
        else:
            print(f"❌ 盈亏比不足: {metrics['盈亏比']}")

        print(f"\n📊 综合评分: {score}/{max_score}")

        if score >= 4:
            print("🎉 策略表现优秀,可考虑实盘!")
        elif score >= 3:
            print("⚠️  策略表现尚可,建议优化后再实盘!")
        else:
            print("❌策略表现不佳,需要重新调整!")

        return metrics

def get_universe_stocks():
    """获取股票池"""
    set_token(config.GM_TOKEN)
    indices = ['SHSE.000300', 'SHSE.000905', 'SHSE.000852']
    whitelist = set()

    for idx in indices:
        try:
            c = stk_get_index_constituents(index=idx)
            if not c.empty:
                whitelist.update(c['symbol'].tolist())
        except:
            pass

    return list(whitelist)

def fetch_price_data(symbols, days=250):
    """获取价格数据"""
    set_token(config.GM_TOKEN)

    end_dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    start_dt = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')

    print(f"📊 获取价格数据 ({days}天)...")

    all_prices = []
    chunk_size = 50

    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i+chunk_size]
        try:
            hd = history(
                symbol=",".join(chunk),
                frequency='1d',
                start_time=start_dt,
                end_time=end_dt,
                fields='symbol,close,eob',
                adjust=ADJUST_PREV,
                df=True
            )
            if not hd.empty:
                all_prices.append(hd)
        except Exception as e:
            pass

        if (i // chunk_size + 1) % 20 == 0:
            print(f"  进度: {i//chunk_size + 1}/{(len(symbols)+chunk_size-1)//chunk_size}")

    df = pd.concat(all_prices)
    df['eob'] = pd.to_datetime(df['eob']).dt.tz_localize(None)
    prices_df = df.pivot(index='eob', columns='symbol', values='close').ffill()

    print(f"✅ 数据就绪: {len(prices_df)} 交易日, {len(prices_df.columns)} 只股票\n")

    return prices_df

if __name__ == "__main__":
    print("="*80)
    print("🔬 AI策略滚动持仓回测 - 真实账户模拟")
    print("="*80 + "\n")

    # 获取数据
    print("📦 获取股票池...")
    stocks = get_universe_stocks()
    print(f"✅ 股票池: {len(stocks)} 只\n")

    prices_df = fetch_price_data(stocks, days=250)

    # 测试不同持有期
    for hold_period in [5, 10]:
        print("\n" + "="*80)
        print(f"🧪 测试持有期: {hold_period} 天")
        print("="*80 + "\n")

        # 初始化回测引擎
        backtest = RollingPortfolioBacktest(
            initial_capital=1_000_000,
            hold_period=hold_period,
            stocks_per_day=4
        )

        # 运行回测（最近100个交易日）
        results_df = backtest.run(prices_df, start_date=prices_df.index[-100])

        # 输出报告
        metrics = backtest.print_summary()

        # 保存结果
        output_file = f'rolling_backtest_hold{hold_period}d.csv'
        results_df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"\n💾 净值曲线已保存: {output_file}")

        # 保存交易记录
        trades_file = f'trades_log_hold{hold_period}d.csv'
        trades_df = pd.DataFrame(backtest.trades_log)
        trades_df.to_csv(trades_file, index=False, encoding='utf-8-sig')
        print(f"💾 交易记录已保存: {trades_file}")
