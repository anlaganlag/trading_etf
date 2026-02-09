"""
验证 AI 推荐策略的实际表现 (使用缓存数据)
Simple verification using cached data - no GM terminal needed!
"""

import pandas as pd
import numpy as np
from datetime import datetime

# AI 最优权重
AI_WEIGHTS = np.array([
     0.040,  0.009, -0.071,  0.014, -0.073,  0.023,  0.083, -0.041,  0.061,  0.111,
     0.094,  0.014,  0.084,  0.055,  0.066, -0.035,  0.047, -0.003,  0.035, -0.040
])

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

def backtest_with_cached_data(data_path='data_for_opt_stocks/prices.csv',
                               test_days=30,
                               top_n=4,
                               hold_days=[1, 3, 5, 10]):
    """
    使用缓存数据回测 AI 策略
    """
    print("📊 正在加载缓存数据...")

    # 读取价格数据
    prices_df = pd.read_csv(data_path, index_col=0, parse_dates=True)
    print(f"✅ 数据加载完成!")
    print(f"   时间范围: {prices_df.index[0]} 到 {prices_df.index[-1]}")
    print(f"   股票数量: {len(prices_df.columns)}")
    print(f"   交易日数: {len(prices_df)}\n")

    trade_dates = prices_df.index

    # 存储每次推荐的结果
    all_results = []
    max_hold = max(hold_days)

    print(f"🎯 开始回测最近 {test_days} 个交易日...")
    print(f"   每天选 Top {top_n} 股票")
    print(f"   持有期: {hold_days} 天\n")

    # 回测最近 test_days 个交易日
    for d_idx in range(-test_days - max_hold, -max_hold):
        recommend_date = trade_dates[d_idx]

        # 计算 AI 评分
        scores = calculate_ai_scores(prices_df, recommend_date)
        if scores is None:
            continue

        # 选出 Top N
        top_stocks = scores.nlargest(top_n)

        # 计算未来收益
        returns_dict = {
            'date': recommend_date.strftime('%Y-%m-%d'),
            'stocks': ','.join([s.split('.')[1][:6] for s in top_stocks.index[:3]])  # 显示前3只
        }

        for hold_period in hold_days:
            future_date_idx = d_idx + hold_period
            if future_date_idx >= 0 or future_date_idx < -len(trade_dates):
                continue

            future_date = trade_dates[future_date_idx]

            # 计算每只股票的收益
            stock_returns = []
            for stock in top_stocks.index:
                if stock not in prices_df.columns:
                    continue

                buy_price = prices_df.loc[recommend_date, stock]
                sell_price = prices_df.loc[future_date, stock]

                if pd.notna(buy_price) and pd.notna(sell_price) and buy_price > 0:
                    ret = (sell_price / buy_price - 1) * 100  # 转换为百分比
                    stock_returns.append(ret)

            # 平均收益 (等权重)
            if stock_returns:
                avg_return = np.mean(stock_returns)
                returns_dict[f'{hold_period}d'] = round(avg_return, 2)

        all_results.append(returns_dict)

    # 转换为 DataFrame
    results_df = pd.DataFrame(all_results)

    # 计算统计数据
    print("\n" + "="*80)
    print("🎯 AI 策略回测结果 (等权重买入 Top 4 股票)")
    print("="*80)

    stats_summary = []

    for hold_period in hold_days:
        col = f'{hold_period}d'
        if col in results_df.columns:
            returns = results_df[col].dropna()

            if len(returns) == 0:
                continue

            avg_ret = returns.mean()
            median_ret = returns.median()
            win_rate = (returns > 0).sum() / len(returns) * 100
            max_ret = returns.max()
            min_ret = returns.min()
            std_ret = returns.std()

            # 年化收益 (简化计算)
            annual_trades = 252 / hold_period  # 一年交易次数
            annualized_return = avg_ret * annual_trades

            stats_summary.append({
                '持有期': f'{hold_period}天',
                '平均收益': f'{avg_ret:.2f}%',
                '年化收益': f'{annualized_return:.1f}%',
                '胜率': f'{win_rate:.1f}%',
                '最大收益': f'{max_ret:.2f}%',
                '最大亏损': f'{min_ret:.2f}%',
                '标准差': f'{std_ret:.2f}%'
            })

            print(f"\n📈 持有 {hold_period} 天:")
            print(f"   平均收益: {avg_ret:.2f}%  (中位数: {median_ret:.2f}%)")
            print(f"   年化收益: {annualized_return:.1f}%")
            print(f"   胜率: {win_rate:.1f}% ({(returns > 0).sum()}/{len(returns)} 次)")
            print(f"   最佳: {max_ret:.2f}%  |  最差: {min_ret:.2f}%")
            print(f"   波动率: {std_ret:.2f}%")

    # 打印详细记录
    print("\n" + "="*80)
    print("📋 最近 10 次推荐详情:")
    print("="*80)
    display_cols = ['date', 'stocks'] + [f'{h}d' for h in hold_days if f'{h}d' in results_df.columns]
    print(results_df[display_cols].tail(10).to_string(index=False))

    # 保存统计摘要
    stats_df = pd.DataFrame(stats_summary)
    print("\n" + "="*80)
    print("📊 统计摘要:")
    print("="*80)
    print(stats_df.to_string(index=False))

    # 保存到文件
    output_file = 'ai_strategy_backtest_results.csv'
    results_df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n💾 完整结果已保存到: {output_file}")

    # 判断策略是否有效
    print("\n" + "="*80)
    print("🤔 策略评估:")
    print("="*80)

    best_hold = None
    best_return = -999

    for hold_period in hold_days:
        col = f'{hold_period}d'
        if col in results_df.columns:
            returns = results_df[col].dropna()
            avg = returns.mean()
            win_rate = (returns > 0).sum() / len(returns) * 100

            if avg > best_return:
                best_return = avg
                best_hold = hold_period

            # 判断标准: 平均收益>0 且 胜率>50%
            if avg > 0 and win_rate > 50:
                print(f"✅ 持有{hold_period}天: 有效 (平均+{avg:.2f}%, 胜率{win_rate:.1f}%)")
            elif avg > 0:
                print(f"⚠️  持有{hold_period}天: 收益为正但胜率低 ({win_rate:.1f}%)")
            else:
                print(f"❌ 持有{hold_period}天: 平均亏损 ({avg:.2f}%)")

    if best_return > 0:
        print(f"\n🏆 最佳策略: 持有 {best_hold} 天 (平均收益 {best_return:.2f}%)")
    else:
        print(f"\n⚠️  所有持有期都显示负收益,策略可能需要调整!")

    return results_df

if __name__ == "__main__":
    print("🤖 AI 选股策略验证程序 (离线版)")
    print("="*80)
    print("这个程序会测试:")
    print("1. AI 每天推荐的 Top 4 股票")
    print("2. 如果你等权买入这些股票,持有 1/3/5/10 天后的收益")
    print("3. 平均赚钱还是亏钱?胜率多少?")
    print("="*80 + "\n")

    # 尝试股票数据,如果不存在则用 ETF 数据
    try:
        results = backtest_with_cached_data(
            data_path='data_for_opt_stocks/prices.csv',
            test_days=30,
            top_n=4,
            hold_days=[1, 3, 5, 10]
        )
    except FileNotFoundError:
        print("股票数据未找到,尝试使用 ETF 数据...\n")
        results = backtest_with_cached_data(
            data_path='data_for_opt/prices.csv',
            test_days=30,
            top_n=4,
            hold_days=[1, 3, 5, 10]
        )
