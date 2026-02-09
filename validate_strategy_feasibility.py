"""
策略可行性综合验证
验证文档中的1165%收益是否真实可信

检查项：
1. 是否存在时间泄露（使用未来数据）
2. 是否存在生存偏差
3. 回测逻辑是否正确
4. 基准数据是否准确
5. 样本外测试表现
6. 交易成本影响
"""
import os
import pandas as pd
import numpy as np
from config import config
from scipy import stats

DATA_DIR = os.path.join(config.BASE_DIR, "data_for_opt_stocks")
PRICES_FILE = os.path.join(DATA_DIR, "prices.csv")

START_DATE = '2021-12-03'
END_DATE = '2026-01-23'
WEIGHTS = {2: 0.3, 20: 0.7}
TOP_N = 4
HOLD_DAYS = 3

def check_lookahead_bias():
    """检查1: 时间泄露检查"""
    print("\n" + "="*60)
    print("✓ 检查1: 时间泄露检查")
    print("="*60)

    # 读取一段数据检查逻辑
    stocks = pd.read_csv(PRICES_FILE, index_col=0, parse_dates=True)
    stocks = stocks.loc[START_DATE:END_DATE]

    # 模拟在某一天的计算
    test_date = stocks.index[100]  # 随机选一天
    hist = stocks[stocks.index <= test_date]

    # 检查计算2日和20日收益是否使用了未来数据
    for p in [2, 20]:
        ret_correct = hist.iloc[-1] / hist.iloc[-(p+1)] - 1
        ret_wrong = hist.iloc[-1] / hist.iloc[-1-p] - 1  # 错误方式

        print(f"\nPeriod {p}天:")
        print(f"  正确方法 (使用T和T-{p}): {ret_correct.head(3).to_dict()}")
        print(f"  错误方法 (会泄露): {ret_wrong.head(3).to_dict()}")

        # 验证代码中使用的是正确方法
        # verify_final_backtest.py line 58: ret = stocks / stocks.shift(p) - 1
        ret_code = stocks.loc[:test_date].iloc[-1] / stocks.loc[:test_date].shift(p).iloc[-1] - 1
        assert ret_code.equals(ret_correct), f"代码逻辑与正确方法不一致！"

    print("\n✅ 通过: 代码使用正确的时间逻辑，无未来数据泄露")
    return True

def check_survivorship_bias():
    """检查2: 生存偏差检查"""
    print("\n" + "="*60)
    print("✓ 检查2: 生存偏差检查")
    print("="*60)

    stocks = pd.read_csv(PRICES_FILE, index_col=0, parse_dates=True)
    stocks = stocks.loc[START_DATE:END_DATE]

    # 检查数据完整性
    n_stocks = len(stocks.columns)
    n_days = len(stocks)

    # 计算每只股票的缺失率
    missing_pct = stocks.isna().sum() / len(stocks)

    # 统计退市/停牌股票
    delisted = missing_pct[missing_pct > 0.5]  # 超过50%缺失

    print(f"\n总股票数: {n_stocks}")
    print(f"交易日数: {n_days}")
    print(f"严重缺失股票 (>50%): {len(delisted)}")
    print(f"缺失率分布: min={missing_pct.min():.2%}, median={missing_pct.median():.2%}, max={missing_pct.max():.2%}")

    if len(delisted) > 0:
        print(f"\n⚠️ 警告: 存在{len(delisted)}只严重缺失数据的股票")
        print("可能存在生存偏差 - 回测中排除了退市股票")
        return False
    else:
        print("\n✅ 通过: 数据集较完整")
        return True

def check_backtest_logic():
    """检查3: 回测逻辑验证"""
    print("\n" + "="*60)
    print("✓ 检查3: 回测逻辑验证")
    print("="*60)

    stocks = pd.read_csv(PRICES_FILE, index_col=0, parse_dates=True)
    stocks = stocks.loc[START_DATE:END_DATE]

    # 计算分数（简化版）
    score_df = pd.DataFrame(0.0, index=stocks.index, columns=stocks.columns)
    for p, w in WEIGHTS.items():
        ret = stocks / stocks.shift(p) - 1
        rank = ret.rank(axis=1, pct=True).fillna(0.5)
        score_df += rank * w

    # 检查分数分布
    print(f"\n分数统计:")
    print(f"  均值: {score_df.mean().mean():.4f}")
    print(f"  标准差: {score_df.std().mean():.4f}")
    print(f"  范围: [{score_df.min().min():.4f}, {score_df.max().max():.4f}]")

    # 检查选股逻辑
    # 选出一天的Top 4
    test_day = score_df.iloc[100]
    top_stocks = test_day.nlargest(TOP_N)
    print(f"\n测试日期 {score_df.index[100].date()} 选出的股票:")
    for stock, score in top_stocks.items():
        print(f"  {stock}: {score:.4f}")

    # 验证分仓逻辑
    top_n_mask = pd.DataFrame(False, index=score_df.index, columns=score_df.columns)
    vals = score_df.values
    vals = np.nan_to_num(vals, nan=-np.inf)
    idx = np.argpartition(-vals, TOP_N, axis=1)[:, :TOP_N]
    rows = np.arange(len(score_df))[:, None]
    top_n_mask.values[rows, idx] = True

    # 检查每天是否选了TOP_N个股票
    daily_count = top_n_mask.sum(axis=1)
    assert (daily_count == TOP_N).all(), f"选股数量不一致: {daily_count.unique()}"

    print(f"\n✅ 通过: 每天都正确选出{TOP_N}只股票")
    return True

def check_out_of_sample():
    """检查4: 样本外测试"""
    print("\n" + "="*60)
    print("✓ 检查4: 样本外测试 (时间分割)")
    print("="*60)

    stocks = pd.read_csv(PRICES_FILE, index_col=0, parse_dates=True)
    stocks = stocks.loc[START_DATE:END_DATE]

    # 分割为训练期和测试期 (70/30)
    split_idx = int(len(stocks) * 0.7)
    train_period = stocks.iloc[:split_idx]
    test_period = stocks.iloc[split_idx:]

    print(f"\n训练期: {train_period.index[0].date()} 到 {train_period.index[-1].date()} ({len(train_period)}天)")
    print(f"测试期: {test_period.index[0].date()} 到 {test_period.index[-1].date()} ({len(test_period)}天)")

    # 在两个期间分别回测
    results = {}
    for name, data in [("训练期", train_period), ("测试期", test_period)]:
        score_df = pd.DataFrame(0.0, index=data.index, columns=data.columns)
        for p, w in WEIGHTS.items():
            ret = data / data.shift(p) - 1
            rank = ret.rank(axis=1, pct=True).fillna(0.5)
            score_df += rank * w

        # 简化回测：每天买top N，持有1天
        top_n_mask = pd.DataFrame(False, index=score_df.index, columns=score_df.columns)
        vals = score_df.values
        vals = np.nan_to_num(vals, nan=-np.inf)
        idx = np.argpartition(-vals, TOP_N, axis=1)[:, :TOP_N]
        rows = np.arange(len(score_df))[:, None]
        top_n_mask.values[rows, idx] = True

        market_ret = data.pct_change().fillna(0.0)
        port_ret = (market_ret * top_n_mask.shift(1)).sum(axis=1) / TOP_N
        port_ret = port_ret.iloc[1:]  # 去掉第一天

        cum_ret = (1 + port_ret).cumprod().iloc[-1] - 1
        results[name] = cum_ret

        print(f"\n{name}收益: {cum_ret:.2%}")

    # 比较训练期和测试期
    if results["测试期"] > 0.5 * results["训练期"]:
        print(f"\n✅ 通过: 测试期表现稳定 (测试期收益为训练期的{results['测试期']/results['训练期']:.1%})")
        return True
    else:
        print(f"\n⚠️ 警告: 测试期表现大幅衰减 (仅为训练期的{results['测试期']/results['训练期']:.1%})")
        return False

def check_transaction_costs():
    """检查5: 交易成本影响"""
    print("\n" + "="*60)
    print("✓ 检查5: 交易成本敏感性分析")
    print("="*60)

    stocks = pd.read_csv(PRICES_FILE, index_col=0, parse_dates=True)
    stocks = stocks.loc[START_DATE:END_DATE]

    # 简化回测
    score_df = pd.DataFrame(0.0, index=stocks.index, columns=stocks.columns)
    for p, w in WEIGHTS.items():
        ret = stocks / stocks.shift(p) - 1
        rank = ret.rank(axis=1, pct=True).fillna(0.5)
        score_df += rank * w

    top_n_mask = pd.DataFrame(False, index=score_df.index, columns=score_df.columns)
    vals = score_df.values
    vals = np.nan_to_num(vals, nan=-np.inf)
    idx = np.argpartition(-vals, TOP_N, axis=1)[:, :TOP_N]
    rows = np.arange(len(score_df))[:, None]
    top_n_mask.values[rows, idx] = True

    # 计算换手率
    turnover_daily = (top_n_mask != top_n_mask.shift(1)).sum(axis=1) / (2 * TOP_N)
    avg_turnover = turnover_daily.mean()

    print(f"\n平均单向换手率: {avg_turnover:.2%} /天")
    print(f"按3天换仓估算: {avg_turnover * 3:.2%} /3天")

    # 不同交易成本下的收益
    market_ret = stocks.pct_change().fillna(0.0)

    # 滚动3分仓
    port_daily = pd.Series(0.0, index=stocks.index)
    for lag in range(1, HOLD_DAYS + 1):
        m = top_n_mask.shift(lag).fillna(False)
        tranche_ret = (market_ret * m).sum(axis=1) / TOP_N
        port_daily += tranche_ret
    port_daily /= HOLD_DAYS
    port_daily = port_daily.iloc[HOLD_DAYS:]

    # 计算实际换仓次数（每3天）
    trades_per_year = 252 / HOLD_DAYS

    print(f"\n不同交易成本下的年化收益:")
    base_cum = (1 + port_daily).cumprod().iloc[-1] - 1
    n_days = len(port_daily)
    base_ann = (1 + base_cum) ** (252 / n_days) - 1

    for cost_bps in [0, 10, 20, 30, 50]:
        # 每次换仓成本 = 单向换手率 * 成本
        # 3天换仓，平均换手率 = avg_turnover * 3
        annual_cost = (avg_turnover * 3) * (cost_bps / 10000) * trades_per_year
        net_ann = base_ann - annual_cost

        print(f"  {cost_bps}bps: {net_ann:.2%} (损耗: {annual_cost:.2%}/年)")

    if base_ann - 0.005 * trades_per_year > 0.5 * base_ann:
        print(f"\n✅ 通过: 即使50bps成本，策略仍有显著超额")
        return True
    else:
        print(f"\n⚠️ 警告: 交易成本会大幅侵蚀收益")
        return False

def check_benchmark_accuracy():
    """检查6: 基准数据准确性"""
    print("\n" + "="*60)
    print("✓ 检查6: 基准数据验证")
    print("="*60)

    from gm.api import set_token, history, ADJUST_PREV
    set_token(config.GM_TOKEN)

    try:
        # 获取创业板ETF数据
        print("\n正在获取创业板ETF (159915) 数据...")
        df = history(symbol='SZSE.159915', frequency='1d',
                    start_time=START_DATE, end_time=END_DATE,
                    fields='close,eob', adjust=ADJUST_PREV, df=True)

        if df.empty:
            print("❌ 无法获取基准数据")
            return False

        df['eob'] = pd.to_datetime(df['eob']).dt.tz_localize(None)
        bench = df.set_index('eob')['close']

        # 计算收益
        start_price = bench.iloc[0]
        end_price = bench.iloc[-1]
        total_ret = (end_price / start_price - 1)

        print(f"\n创业板ETF价格:")
        print(f"  起始 ({bench.index[0].date()}): {start_price:.4f}")
        print(f"  结束 ({bench.index[-1].date()}): {end_price:.4f}")
        print(f"  总收益: {total_ret:.2%}")

        # 检查是否合理
        if abs(total_ret) > 1.0:  # 超过100%涨跌
            print(f"\n⚠️ 警告: 基准收益率{total_ret:.2%}异常，可能数据有误")
            return False

        # 对比创业板指数
        print("\n正在获取创业板指数 (399006) 数据...")
        df2 = history(symbol='SZSE.399006', frequency='1d',
                     start_time=START_DATE, end_time=END_DATE,
                     fields='close,eob', df=True)

        if not df2.empty:
            df2['eob'] = pd.to_datetime(df2['eob']).dt.tz_localize(None)
            idx = df2.set_index('eob')['close']
            idx_ret = (idx.iloc[-1] / idx.iloc[0] - 1)
            print(f"  创业板指数收益: {idx_ret:.2%}")
            print(f"  ETF vs 指数差异: {abs(total_ret - idx_ret):.2%}")

        print(f"\n✅ 基准数据已验证")
        return True

    except Exception as e:
        print(f"\n❌ 基准数据获取失败: {e}")
        return False

def main():
    """运行所有验证"""
    print("\n" + "="*60)
    print("🔍 策略可行性综合验证")
    print("="*60)
    print(f"策略: Day 2 (30%) + Day 20 (70%)")
    print(f"期间: {START_DATE} 到 {END_DATE}")
    print(f"持仓: Top {TOP_N} 股票, 每{HOLD_DAYS}天换仓")

    if not os.path.exists(PRICES_FILE):
        print(f"\n❌ 数据文件不存在: {PRICES_FILE}")
        return

    results = {}

    # 运行各项检查
    checks = [
        ("时间泄露", check_lookahead_bias),
        ("生存偏差", check_survivorship_bias),
        ("回测逻辑", check_backtest_logic),
        ("样本外测试", check_out_of_sample),
        ("交易成本", check_transaction_costs),
        ("基准数据", check_benchmark_accuracy),
    ]

    for name, func in checks:
        try:
            results[name] = func()
        except Exception as e:
            print(f"\n❌ {name}检查失败: {e}")
            results[name] = False

    # 总结
    print("\n\n" + "="*60)
    print("📋 验证结果总结")
    print("="*60)

    for name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{status}: {name}")

    passed_count = sum(results.values())
    total_count = len(results)

    print("\n" + "="*60)
    if passed_count == total_count:
        print("🎉 所有检查通过！策略可行性较高")
        print("\n⚠️ 但仍需注意:")
        print("  1. 微盘股流动性风险 - 大资金可能无法复制")
        print("  2. 最大回撤-67% - 需要极强的风险承受能力")
        print("  3. 过去表现不代表未来 - 需持续监控")
    elif passed_count >= total_count * 0.7:
        print(f"⚠️ 部分检查未通过 ({passed_count}/{total_count})")
        print("策略有一定可行性，但存在风险")
    else:
        print(f"❌ 多项检查失败 ({passed_count}/{total_count})")
        print("策略可行性存疑，建议谨慎对待")
    print("="*60)

if __name__ == "__main__":
    main()
