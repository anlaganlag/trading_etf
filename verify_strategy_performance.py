"""
验证 AI 推荐策略的实际表现
Test if the AI recommendations actually make money!
"""

import os
import pandas as pd
import numpy as np
from gm.api import *
from config import config, logger
from datetime import datetime, timedelta

# AI 最优权重
AI_WEIGHTS = np.array([
     0.040,  0.009, -0.071,  0.014, -0.073,  0.023,  0.083, -0.041,  0.061,  0.111,
     0.094,  0.014,  0.084,  0.055,  0.066, -0.035,  0.047, -0.003,  0.035, -0.040
])

def get_universe_stocks():
    """获取全市场及核心指数成份股"""
    set_token(config.GM_TOKEN)
    indices = ['SHSE.000300', 'SHSE.000905', 'SHSE.000852']
    whitelist = set()
    for idx in indices:
        try:
            c = stk_get_index_constituents(index=idx)
            if not c.empty:
                whitelist.update(c['symbol'].tolist())
                print(f"  ✓ {idx}: {len(c)} 只股票")
        except Exception as e:
            print(f"  ✗ {idx} 获取失败: {e}")

    print(f"📦 总共获取到 {len(whitelist)} 只股票")
    return list(whitelist)

def calculate_ai_scores(prices_df, target_date):
    """
    计算指定日期的 AI 评分
    """
    # 获取截至该日的数据
    hist = prices_df.loc[:target_date]
    if len(hist) < 22:
        return None

    latest_price = hist.iloc[-1]
    final_scores = pd.Series(0.0, index=hist.columns)

    # 20个周期打分
    for i in range(20):
        period = i + 1
        w = AI_WEIGHTS[i]

        # 涨幅计算
        prev_price = hist.iloc[-(period+1)]
        ret = latest_price / prev_price - 1

        # RankScore (Top 100 线性打分)
        ranks = ret.rank(ascending=False, method='min')
        top_100_mask = (ranks <= 100)

        # 分数 = (101 - rank) / 100
        score_p = (101 - ranks[top_100_mask]) / 100.0
        final_scores[top_100_mask] += score_p * w

    return final_scores

def backtest_strategy(test_days=20, top_n=4, hold_days=[1, 3, 5]):
    """
    回测 AI 策略表现

    Parameters:
    - test_days: 回测多少个交易日
    - top_n: 每天选几只股票
    - hold_days: 持有天数列表 [1天, 3天, 5天]
    """
    set_token(config.GM_TOKEN)
    symbols = get_universe_stocks()
    print(f"🔍 正在检查 {len(symbols)} 只股票...")

    # 获取历史数据 (需要更长的时间窗口)
    end_dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    start_dt = (datetime.now() - timedelta(days=150)).strftime('%Y-%m-%d %H:%M:%S')

    print("📊 正在获取价格数据...")
    all_prices = []
    chunk_size = 50
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i+chunk_size]
        hd = history(symbol=",".join(chunk), frequency='1d', start_time=start_dt, end_time=end_dt,
                     fields='symbol,close,eob', adjust=ADJUST_PREV, df=True)
        if not hd.empty:
            all_prices.append(hd)
        if (i // chunk_size) % 10 == 0:
            print(f"  进度: {i}/{len(symbols)}")

    if not all_prices:
        print("❌ 没有获取到数据!")
        return

    df = pd.concat(all_prices)
    df['eob'] = pd.to_datetime(df['eob']).dt.tz_localize(None)

    # 透视价格
    prices_df = df.pivot(index='eob', columns='symbol', values='close').ffill()
    trade_dates = prices_df.index

    print(f"✅ 数据准备完成! 最新日期: {trade_dates[-1]}")
    print(f"📅 开始回测最近 {test_days} 个交易日...\n")

    # 存储每次推荐的结果
    all_results = []

    # 回测最近 test_days 个交易日
    for d_idx in range(-test_days, -max(hold_days)):  # 留出持有期
        recommend_date = trade_dates[d_idx]

        # 计算 AI 评分
        scores = calculate_ai_scores(prices_df, recommend_date)
        if scores is None:
            continue

        # 选出 Top N
        top_stocks = scores.nlargest(top_n)

        # 计算未来收益
        returns_dict = {'date': recommend_date.strftime('%Y-%m-%d')}

        for hold_period in hold_days:
            future_date_idx = d_idx + hold_period
            if future_date_idx >= 0:  # 超出数据范围
                continue

            future_date = trade_dates[future_date_idx]

            # 计算每只股票的收益
            stock_returns = []
            for stock in top_stocks.index:
                buy_price = prices_df.loc[recommend_date, stock]
                sell_price = prices_df.loc[future_date, stock]

                if pd.notna(buy_price) and pd.notna(sell_price) and buy_price > 0:
                    ret = (sell_price / buy_price - 1) * 100  # 转换为百分比
                    stock_returns.append(ret)

            # 平均收益
            if stock_returns:
                avg_return = np.mean(stock_returns)
                returns_dict[f'{hold_period}day_return'] = avg_return

        all_results.append(returns_dict)

    # 转换为 DataFrame
    results_df = pd.DataFrame(all_results)

    # 打印结果
    print("="*70)
    print("🎯 AI 策略回测结果")
    print("="*70)

    for hold_period in hold_days:
        col = f'{hold_period}day_return'
        if col in results_df.columns:
            returns = results_df[col].dropna()

            avg_ret = returns.mean()
            win_rate = (returns > 0).sum() / len(returns) * 100
            max_ret = returns.max()
            min_ret = returns.min()

            print(f"\n📈 持有 {hold_period} 天:")
            print(f"   平均收益: {avg_ret:.2f}%")
            print(f"   胜率: {win_rate:.1f}% ({(returns > 0).sum()}/{len(returns)} 次盈利)")
            print(f"   最大收益: {max_ret:.2f}%")
            print(f"   最大亏损: {min_ret:.2f}%")

    print("\n" + "="*70)
    print("📋 详细记录 (最近10次):")
    print("="*70)
    print(results_df.tail(10).to_string(index=False))

    # 保存到文件
    output_file = 'ai_strategy_backtest_results.csv'
    results_df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n💾 完整结果已保存到: {output_file}")

    return results_df

if __name__ == "__main__":
    print("🤖 AI 选股策略验证程序")
    print("="*70)
    print("这个程序会测试:")
    print("1. AI 每天推荐的 Top 4 股票")
    print("2. 如果你买了这些股票,持有 1/3/5 天后的收益")
    print("3. 平均赚钱还是亏钱?")
    print("="*70 + "\n")

    results = backtest_strategy(test_days=20, top_n=4, hold_days=[1, 3, 5])
