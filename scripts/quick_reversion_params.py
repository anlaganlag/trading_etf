"""
快速反转策略参数推荐

基于IC分析直接给出推荐参数，无需长时间优化

使用方法：
    python scripts/quick_reversion_params.py
"""
import os
import pandas as pd
import numpy as np
from scipy import stats

def quick_recommend():
    """快速推荐反转策略参数"""
    print("=" * 80)
    print("快速反转策略参数推荐")
    print("=" * 80)

    # 加载数据
    data_dir = 'data_for_opt_stocks'
    prices_file = os.path.join(data_dir, "prices.csv")

    if not os.path.exists(prices_file):
        print(f"❌ 数据文件不存在: {prices_file}")
        return

    prices = pd.read_csv(prices_file, index_col=0, parse_dates=True)
    prices = prices.apply(pd.to_numeric, errors='coerce')

    print(f"\n数据加载: {prices.shape}")
    print(f"时间范围: {prices.index[0].date()} ~ {prices.index[-1].date()}")

    # 计算未来20日收益
    forward_p = 20
    future_rets = prices.shift(-forward_p) / prices - 1

    # 计算各周期IC
    print(f"\n分析各周期的反转效应（IC值）:")
    print("-" * 60)

    ic_values = {}
    for period in range(1, 21):
        rets = prices.pct_change(period)
        ranks = rets.rank(axis=1, pct=True, ascending=True)

        daily_ics = []
        for date in prices.index:
            if date not in ranks.index or date not in future_rets.index:
                continue

            row_rank = ranks.loc[date]
            row_future = future_rets.loc[date]

            mask = row_rank.notna() & row_future.notna()
            if mask.sum() > 10:
                ic = row_rank[mask].corr(row_future[mask], method='spearman')
                if not np.isnan(ic):
                    daily_ics.append(ic)

        mean_ic = np.mean(daily_ics) if daily_ics else 0
        ic_values[period] = mean_ic

        stars = ""
        if abs(mean_ic) > 0.025:
            stars = " ⭐⭐⭐"
        elif abs(mean_ic) > 0.020:
            stars = " ⭐⭐"
        elif abs(mean_ic) > 0.015:
            stars = " ⭐"

        print(f"  {period:2d}日: IC = {mean_ic:>7.4f}{stars}")

    # 找出最强的反转周期
    sorted_ic = sorted(ic_values.items(), key=lambda x: abs(x[1]), reverse=True)

    print("\n" + "=" * 80)
    print("推荐策略方案")
    print("=" * 80)

    # 方案1：最强的3个周期
    top_3 = sorted_ic[:3]
    print(f"\n方案1：IC最强的3个周期 ⭐⭐⭐⭐⭐（推荐）")
    print("-" * 60)
    print(f"周期: {[p for p, ic in top_3]}")
    print(f"IC值: {[round(ic, 4) for p, ic in top_3]}")

    # 计算权重（与IC绝对值成正比）
    weights_1 = []
    for p, ic in top_3:
        # 反转策略：IC负数，权重也应该是负数
        # 绝对值大的IC给更大的权重
        weight = ic / sum(abs(ic) for _, ic in top_3) * 100
        weights_1.append(weight)

    print(f"推荐权重:")
    for (p, ic), w in zip(top_3, weights_1):
        print(f"  {p:2d}日: {w:>6.1f}  (IC={ic:.4f})")

    periods_dict_1 = {p: int(round(w, 0)) for (p, _), w in zip(top_3, weights_1)}
    print(f"\n代码格式:")
    print(f"periods = {periods_dict_1}")

    # 方案2：仅用最强的1个周期（最简单）
    print(f"\n方案2：仅用最强的1个周期（最简单）⭐⭐⭐⭐")
    print("-" * 60)
    strongest = sorted_ic[0]
    print(f"周期: {strongest[0]}日")
    print(f"IC值: {strongest[1]:.4f}")
    print(f"\n代码格式:")
    print(f"periods = {{{strongest[0]}: -100}}")

    # 方案3：长期反转（15-20日）
    print(f"\n方案3：长期反转组合（15-20日）⭐⭐⭐")
    print("-" * 60)
    long_term_periods = [15, 18, 20]
    long_term_ics = [ic_values[p] for p in long_term_periods]
    print(f"周期: {long_term_periods}")
    print(f"IC值: {[round(ic, 4) for ic in long_term_ics]}")

    weights_3 = []
    for ic in long_term_ics:
        weight = ic / sum(abs(ic) for ic in long_term_ics) * 100
        weights_3.append(weight)

    print(f"推荐权重:")
    for p, w, ic in zip(long_term_periods, weights_3, long_term_ics):
        print(f"  {p:2d}日: {w:>6.1f}  (IC={ic:.4f})")

    periods_dict_3 = {p: int(round(w, 0)) for p, w in zip(long_term_periods, weights_3)}
    print(f"\n代码格式:")
    print(f"periods = {periods_dict_3}")

    # 给出明确建议
    print("\n" + "=" * 80)
    print("使用建议")
    print("=" * 80)

    print(f"""
1. 如果追求稳健：使用方案1（3个周期）
   - 分散风险
   - 基于最强IC
   - 参数适中（3个）

2. 如果追求简单：使用方案2（1个周期）
   - 极简策略
   - 不易过拟合
   - 易于理解和维护

3. 如果偏好长期：使用方案3（长期反转）
   - 捕捉长期调整
   - 减少短期噪音
   - 持有周期友好

下一步：
1. 选择一个方案
2. 在 core/signal.py 中应用权重
3. 回测2023-2024年数据
4. 如果胜率 > 55%，考虑小资金实盘测试
""")

    # 保存结果
    output_dir = 'output'
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, 'quick_reversion_recommendations.txt'), 'w') as f:
        f.write("反转策略快速推荐\n")
        f.write("=" * 60 + "\n\n")

        f.write("方案1（推荐）:\n")
        f.write(f"periods = {periods_dict_1}\n\n")

        f.write("方案2（最简）:\n")
        f.write(f"periods = {{{strongest[0]}: -100}}\n\n")

        f.write("方案3（长期）:\n")
        f.write(f"periods = {periods_dict_3}\n")

    print(f"\n推荐参数已保存至: output/quick_reversion_recommendations.txt")


if __name__ == '__main__':
    quick_recommend()
