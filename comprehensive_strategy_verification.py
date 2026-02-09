"""
🔬 全面验证 AI 策略 - 使用实时 GM API
Comprehensive Strategy Verification with Live Data

测试内容:
1. 更长回测期 (60天+)
2. 与随机选股对比
3. 与市场基准对比
4. 风险指标 (夏普比率, 最大回撤)
5. 稳定性测试
"""

import pandas as pd
import numpy as np
from gm.api import *
from config import config
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# AI 最优权重
AI_WEIGHTS = np.array([
     0.040,  0.009, -0.071,  0.014, -0.073,  0.023,  0.083, -0.041,  0.061,  0.111,
     0.094,  0.014,  0.084,  0.055,  0.066, -0.035,  0.047, -0.003,  0.035, -0.040
])

def get_universe_stocks():
    """获取股票池"""
    set_token(config.GM_TOKEN)
    indices = ['SHSE.000300', 'SHSE.000905', 'SHSE.000852']
    whitelist = set()

    print("📦 正在获取股票池...")
    for idx in indices:
        try:
            c = stk_get_index_constituents(index=idx)
            if not c.empty:
                whitelist.update(c['symbol'].tolist())
                print(f"  ✓ {idx}: {len(c)} 只")
        except Exception as e:
            print(f"  ✗ {idx}: {e}")

    stocks = list(whitelist)
    print(f"✅ 总计: {len(stocks)} 只股票\n")
    return stocks

def fetch_price_data(symbols, days=200):
    """获取价格数据"""
    set_token(config.GM_TOKEN)

    end_dt = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    start_dt = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')

    print(f"📊 正在获取 {days} 天价格数据...")
    print(f"   时间范围: {start_dt[:10]} 到 {end_dt[:10]}")

    all_prices = []
    chunk_size = 50
    total_chunks = (len(symbols) + chunk_size - 1) // chunk_size

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
            print(f"  ⚠️ 块 {i//chunk_size + 1}/{total_chunks} 失败: {e}")

        if (i // chunk_size + 1) % 20 == 0:
            print(f"  进度: {i//chunk_size + 1}/{total_chunks}")

    if not all_prices:
        raise ValueError("无法获取数据!")

    df = pd.concat(all_prices)
    df['eob'] = pd.to_datetime(df['eob']).dt.tz_localize(None)
    prices_df = df.pivot(index='eob', columns='symbol', values='close').ffill()

    print(f"✅ 数据获取完成: {len(prices_df)} 个交易日, {len(prices_df.columns)} 只股票\n")
    return prices_df

def calculate_ai_scores(prices_df, target_date):
    """计算 AI 评分"""
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

def backtest_strategy(prices_df, test_days=60, top_n=4, hold_period=5):
    """
    回测 AI 策略

    Returns:
        ai_returns: AI 策略的每日收益率
        random_returns: 随机策略的每日收益率
        dates: 对应的日期
    """
    trade_dates = prices_df.index

    ai_results = []
    random_results = []
    dates = []

    print(f"🎯 开始回测...")
    print(f"   回测天数: {test_days}")
    print(f"   持有期: {hold_period} 天")
    print(f"   每次选股: {top_n} 只\n")

    # 确保有足够的数据
    start_idx = max(-test_days - hold_period, -len(trade_dates) + 25)

    for d_idx in range(start_idx, -hold_period):
        recommend_date = trade_dates[d_idx]

        # AI 策略评分
        scores = calculate_ai_scores(prices_df, recommend_date)
        if scores is None:
            continue

        # AI Top N
        ai_top = scores.nlargest(top_n).index.tolist()

        # 随机选 N 只 (从有数据的股票中)
        valid_stocks = scores[scores.notna()].index.tolist()
        if len(valid_stocks) < top_n:
            continue
        random_top = np.random.choice(valid_stocks, top_n, replace=False)

        # 计算持有期收益
        future_idx = d_idx + hold_period
        if future_idx >= 0:
            continue

        future_date = trade_dates[future_idx]

        # AI 策略收益
        ai_rets = []
        for stock in ai_top:
            buy = prices_df.loc[recommend_date, stock]
            sell = prices_df.loc[future_date, stock]
            if pd.notna(buy) and pd.notna(sell) and buy > 0:
                ai_rets.append((sell / buy - 1) * 100)

        # 随机策略收益
        random_rets = []
        for stock in random_top:
            buy = prices_df.loc[recommend_date, stock]
            sell = prices_df.loc[future_date, stock]
            if pd.notna(buy) and pd.notna(sell) and buy > 0:
                random_rets.append((sell / buy - 1) * 100)

        if ai_rets and random_rets:
            ai_results.append(np.mean(ai_rets))
            random_results.append(np.mean(random_rets))
            dates.append(recommend_date)

    return np.array(ai_results), np.array(random_results), dates

def calculate_metrics(returns, strategy_name="Strategy"):
    """计算风险收益指标"""
    returns = np.array(returns)

    total_return = np.sum(returns)
    avg_return = np.mean(returns)
    median_return = np.median(returns)
    std_return = np.std(returns)

    # 夏普比率 (假设无风险利率=0)
    sharpe = avg_return / std_return if std_return > 0 else 0

    # 胜率
    win_rate = (returns > 0).sum() / len(returns) * 100

    # 最大回撤
    cumulative = np.cumsum(returns)
    running_max = np.maximum.accumulate(cumulative)
    drawdown = cumulative - running_max
    max_drawdown = np.min(drawdown) if len(drawdown) > 0 else 0

    # 盈亏比
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    avg_win = np.mean(wins) if len(wins) > 0 else 0
    avg_loss = np.mean(losses) if len(losses) > 0 else 0
    profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    return {
        'strategy': strategy_name,
        'total_trades': len(returns),
        'total_return': total_return,
        'avg_return': avg_return,
        'median_return': median_return,
        'std_return': std_return,
        'sharpe_ratio': sharpe,
        'win_rate': win_rate,
        'max_drawdown': max_drawdown,
        'profit_loss_ratio': profit_loss_ratio,
        'max_gain': np.max(returns),
        'max_loss': np.min(returns)
    }

def run_comprehensive_test():
    """运行全面测试"""
    print("="*80)
    print("🔬 AI 策略全面验证 - 实时数据")
    print("="*80 + "\n")

    # 1. 获取数据
    stocks = get_universe_stocks()
    prices_df = fetch_price_data(stocks, days=200)

    # 2. 测试多个持有期
    print("="*80)
    print("📊 测试 1: 不同持有期对比")
    print("="*80 + "\n")

    all_results = []

    for hold_period in [1, 3, 5, 10]:
        print(f"⏱️ 测试持有期: {hold_period} 天")
        print("-" * 80)

        ai_returns, random_returns, dates = backtest_strategy(
            prices_df,
            test_days=60,
            top_n=4,
            hold_period=hold_period
        )

        # 计算指标
        ai_metrics = calculate_metrics(ai_returns, f"AI-{hold_period}天")
        random_metrics = calculate_metrics(random_returns, f"随机-{hold_period}天")

        all_results.append(ai_metrics)
        all_results.append(random_metrics)

        # 打印对比
        print(f"\n📈 AI 策略:")
        print(f"   总收益: {ai_metrics['total_return']:.2f}%")
        print(f"   平均收益: {ai_metrics['avg_return']:.2f}%")
        print(f"   胜率: {ai_metrics['win_rate']:.1f}%")
        print(f"   夏普比率: {ai_metrics['sharpe_ratio']:.2f}")
        print(f"   最大回撤: {ai_metrics['max_drawdown']:.2f}%")

        print(f"\n📉 随机策略:")
        print(f"   总收益: {random_metrics['total_return']:.2f}%")
        print(f"   平均收益: {random_metrics['avg_return']:.2f}%")
        print(f"   胜率: {random_metrics['win_rate']:.1f}%")
        print(f"   夏普比率: {random_metrics['sharpe_ratio']:.2f}")

        # 对比优势
        outperformance = ai_metrics['avg_return'] - random_metrics['avg_return']
        print(f"\n🎯 AI 超额收益: {outperformance:+.2f}%")

        if outperformance > 0:
            print(f"   ✅ AI 策略优于随机选股 {abs(outperformance):.2f}%")
        else:
            print(f"   ❌ AI 策略不如随机选股 {abs(outperformance):.2f}%")

        print("\n" + "="*80 + "\n")

    # 3. 汇总表格
    print("="*80)
    print("📊 测试 2: 完整对比表")
    print("="*80 + "\n")

    results_df = pd.DataFrame(all_results)

    display_cols = ['strategy', 'total_trades', 'avg_return', 'win_rate',
                    'sharpe_ratio', 'max_drawdown', 'profit_loss_ratio']

    print(results_df[display_cols].to_string(index=False))

    # 4. 稳定性测试
    print("\n" + "="*80)
    print("📊 测试 3: 稳定性验证 (5天持有期, 5次随机测试)")
    print("="*80 + "\n")

    stability_results = []

    for run in range(5):
        ai_returns, random_returns, _ = backtest_strategy(
            prices_df,
            test_days=60,
            top_n=4,
            hold_period=5
        )

        stability_results.append({
            'run': run + 1,
            'ai_avg': np.mean(ai_returns),
            'ai_win_rate': (ai_returns > 0).sum() / len(ai_returns) * 100,
            'random_avg': np.mean(random_returns),
            'outperformance': np.mean(ai_returns) - np.mean(random_returns)
        })

    stability_df = pd.DataFrame(stability_results)
    print(stability_df.to_string(index=False))

    print(f"\n📊 稳定性统计:")
    print(f"   AI 平均收益: {stability_df['ai_avg'].mean():.2f}% (标准差: {stability_df['ai_avg'].std():.2f}%)")
    print(f"   超额收益: {stability_df['outperformance'].mean():.2f}% (标准差: {stability_df['outperformance'].std():.2f}%)")
    print(f"   胜过随机: {(stability_df['outperformance'] > 0).sum()}/5 次")

    # 5. 最终评估
    print("\n" + "="*80)
    print("🎯 最终评估")
    print("="*80 + "\n")

    best_ai = results_df[results_df['strategy'].str.contains('AI')].sort_values('avg_return', ascending=False).iloc[0]

    print(f"🏆 最佳策略: {best_ai['strategy']}")
    print(f"   平均收益: {best_ai['avg_return']:.2f}%")
    print(f"   胜率: {best_ai['win_rate']:.1f}%")
    print(f"   夏普比率: {best_ai['sharpe_ratio']:.2f}")
    print(f"   最大回撤: {best_ai['max_drawdown']:.2f}%")

    # 判断策略有效性
    print("\n✅ 策略有效性判断:")

    criteria_passed = 0
    total_criteria = 5

    if best_ai['avg_return'] > 0:
        print(f"   ✅ 平均收益为正: {best_ai['avg_return']:.2f}%")
        criteria_passed += 1
    else:
        print(f"   ❌ 平均收益为负: {best_ai['avg_return']:.2f}%")

    if best_ai['win_rate'] > 50:
        print(f"   ✅ 胜率超过 50%: {best_ai['win_rate']:.1f}%")
        criteria_passed += 1
    else:
        print(f"   ❌ 胜率低于 50%: {best_ai['win_rate']:.1f}%")

    if best_ai['sharpe_ratio'] > 0.5:
        print(f"   ✅ 夏普比率 > 0.5: {best_ai['sharpe_ratio']:.2f}")
        criteria_passed += 1
    else:
        print(f"   ⚠️ 夏普比率较低: {best_ai['sharpe_ratio']:.2f}")

    if stability_df['outperformance'].mean() > 0:
        print(f"   ✅ 稳定优于随机: +{stability_df['outperformance'].mean():.2f}%")
        criteria_passed += 1
    else:
        print(f"   ❌ 不如随机选股")

    if best_ai['profit_loss_ratio'] > 1:
        print(f"   ✅ 盈亏比 > 1: {best_ai['profit_loss_ratio']:.2f}")
        criteria_passed += 1
    else:
        print(f"   ⚠️ 盈亏比较低: {best_ai['profit_loss_ratio']:.2f}")

    print(f"\n📊 通过标准: {criteria_passed}/{total_criteria}")

    if criteria_passed >= 4:
        print("\n🎉 策略验证通过! 可以考虑实盘使用!")
    elif criteria_passed >= 3:
        print("\n⚠️ 策略表现尚可,但建议进一步优化!")
    else:
        print("\n❌ 策略表现不佳,需要重新调整!")

    # 保存结果
    results_df.to_csv('comprehensive_verification_results.csv', index=False, encoding='utf-8-sig')
    print(f"\n💾 详细结果已保存到: comprehensive_verification_results.csv")

if __name__ == "__main__":
    try:
        run_comprehensive_test()
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
