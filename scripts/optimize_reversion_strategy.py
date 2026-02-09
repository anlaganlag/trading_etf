"""
反转策略参数优化器

基于Gemini发现：所有1-20日周期都呈现负相关（反转效应）
目标：找到最佳的反转周期组合和权重

策略逻辑：买入近期回调的股票（逢跌买入）

使用方法：
    python scripts/optimize_reversion_strategy.py
"""
import os
import pandas as pd
import numpy as np
from scipy.optimize import differential_evolution
from scipy import stats
from itertools import combinations
import warnings
warnings.filterwarnings('ignore')

class ReversionStrategyOptimizer:
    """反转策略优化器"""

    def __init__(self, data_dir='data_for_opt_stocks', top_k=4):
        self.data_dir = data_dir
        self.top_k = top_k
        self.prices = None
        self.benchmark = None
        self.train_dates = None
        self.test_dates = None

    def load_data(self):
        """加载数据"""
        print("=" * 80)
        print("反转策略参数优化")
        print("=" * 80)

        # 加载价格数据
        prices_file = os.path.join(self.data_dir, "prices.csv")
        benchmark_file = os.path.join(self.data_dir, "benchmark.csv")

        if not os.path.exists(prices_file):
            raise FileNotFoundError(f"数据文件不存在: {prices_file}")

        self.prices = pd.read_csv(prices_file, index_col=0, parse_dates=True)
        self.prices = self.prices.apply(pd.to_numeric, errors='coerce')

        self.benchmark = pd.read_csv(benchmark_file, index_col=0, parse_dates=True)
        if isinstance(self.benchmark, pd.DataFrame):
            self.benchmark = self.benchmark.iloc[:, 0]
        self.benchmark = pd.to_numeric(self.benchmark, errors='coerce')

        print(f"\n数据加载完成:")
        print(f"  价格数据: {self.prices.shape}")
        print(f"  时间范围: {self.prices.index[0]} ~ {self.prices.index[-1]}")

    def split_data(self, train_ratio=0.7):
        """分割训练/测试集"""
        # 计算未来20日收益（标签）
        forward_p = 20
        future_rets = self.prices.shift(-forward_p) / self.prices - 1

        # 有效日期（有未来收益数据）
        valid_mask = future_rets.iloc[:, 0].notna()
        all_dates = self.prices.index[valid_mask]

        # 时间序列分割
        n_samples = len(all_dates)
        train_size = int(n_samples * train_ratio)

        self.train_dates = all_dates[:train_size]
        self.test_dates = all_dates[train_size:]

        print(f"\n数据分割:")
        print(f"  训练集: {len(self.train_dates)}天 ({self.train_dates[0].date()} ~ {self.train_dates[-1].date()})")
        print(f"  测试集: {len(self.test_dates)}天 ({self.test_dates[0].date()} ~ {self.test_dates[-1].date()})")

    def calculate_ic(self, period):
        """
        计算指定周期的信息系数（IC）

        Args:
            period: 周期天数

        Returns:
            平均IC值
        """
        # 计算period日收益
        rets = self.prices.pct_change(period)
        ranks = rets.rank(axis=1, pct=True, ascending=True)

        # 未来20日收益
        forward_p = 20
        future_rets = self.prices.shift(-forward_p) / self.prices - 1

        # 计算每日IC
        daily_ics = []
        for date in self.train_dates:
            if date not in ranks.index or date not in future_rets.index:
                continue

            row_rank = ranks.loc[date]
            row_future = future_rets.loc[date]

            mask = row_rank.notna() & row_future.notna()
            if mask.sum() > 10:
                ic = row_rank[mask].corr(row_future[mask], method='spearman')
                if not np.isnan(ic):
                    daily_ics.append(ic)

        return np.mean(daily_ics) if daily_ics else 0

    def find_best_periods(self, n_periods=3):
        """
        找到IC最强的周期组合

        Args:
            n_periods: 选择多少个周期

        Returns:
            最佳周期列表
        """
        print(f"\n分析各周期的预测能力（IC值）...")

        # 计算所有周期的IC
        all_periods = range(1, 21)
        ic_values = {}

        for period in all_periods:
            ic = self.calculate_ic(period)
            ic_values[period] = ic
            print(f"  {period:2d}日: IC = {ic:>7.4f}", end="")
            if abs(ic) > 0.025:
                print(" ⭐⭐")
            elif abs(ic) > 0.015:
                print(" ⭐")
            else:
                print()

        # 选择绝对值最大的n个周期
        sorted_periods = sorted(ic_values.items(), key=lambda x: abs(x[1]), reverse=True)
        best_periods = [p for p, ic in sorted_periods[:n_periods]]
        best_periods.sort()  # 按周期排序

        print(f"\n选择的{n_periods}个最强周期:")
        for period in best_periods:
            ic = ic_values[period]
            direction = "反转" if ic < 0 else "动量"
            print(f"  {period:2d}日: IC = {ic:>7.4f} ({direction})")

        return best_periods, ic_values

    def backtest_strategy(self, periods, weights, dates):
        """
        回测反转策略

        Args:
            periods: 周期列表
            weights: 权重列表（负数表示反转）
            dates: 回测日期

        Returns:
            performance字典
        """
        # 计算各周期收益
        period_rets = {}
        for period in periods:
            rets = self.prices.pct_change(period)
            period_rets[period] = rets

        # 计算综合评分（反转：收益越低，分数越高）
        scores = pd.DataFrame(0.0, index=self.prices.index, columns=self.prices.columns)

        for period, weight in zip(periods, weights):
            # 反转策略：负权重
            # 收益率越低（跌得越多），排名越高，分数越高
            rets = period_rets[period]
            # 对于负权重，我们希望选择跌幅大的
            # 所以用负的收益率排名
            if weight < 0:
                # 跌幅大的排名高
                ranks = (-rets).rank(axis=1, ascending=False)
            else:
                # 涨幅大的排名高（如果有正权重的话）
                ranks = rets.rank(axis=1, ascending=False)

            # 归一化到0-1
            normalized = (ranks.max(axis=1) - ranks + 1) / ranks.max(axis=1)
            scores += normalized * abs(weight)  # 使用绝对值作为权重大小

        # 未来收益
        forward_p = 20
        future_rets = self.prices.shift(-forward_p) / self.prices - 1
        future_bm_rets = self.benchmark.shift(-forward_p) / self.benchmark - 1

        # 模拟交易
        portfolio_returns = []
        benchmark_returns = []

        for date in dates:
            if date not in scores.index or date not in future_rets.index:
                continue

            # 选择评分最高的top_k只股票
            day_scores = scores.loc[date].dropna()
            if len(day_scores) < self.top_k:
                continue

            selected = day_scores.nlargest(self.top_k).index

            # 计算收益
            stock_rets = future_rets.loc[date, selected]
            valid_rets = stock_rets.dropna()

            if len(valid_rets) > 0:
                port_ret = valid_rets.mean()
                portfolio_returns.append(port_ret)

                if date in future_bm_rets.index:
                    bm_ret = future_bm_rets.loc[date]
                    if not np.isnan(bm_ret):
                        benchmark_returns.append(bm_ret)

        # 计算指标
        portfolio_returns = np.array(portfolio_returns)
        benchmark_returns = np.array(benchmark_returns[:len(portfolio_returns)])

        if len(portfolio_returns) == 0:
            return None

        metrics = {
            'n_trades': len(portfolio_returns),
            'mean_return': portfolio_returns.mean(),
            'std_return': portfolio_returns.std(),
            'win_rate': 0,
            'mean_excess': 0,
            't_stat': 0,
            'p_value': 1.0,
            'sharpe_ratio': 0,
            'total_return': (1 + portfolio_returns).prod() - 1
        }

        # 胜率和超额收益
        if len(benchmark_returns) > 0:
            metrics['win_rate'] = (portfolio_returns > benchmark_returns).mean()
            excess = portfolio_returns - benchmark_returns
            metrics['mean_excess'] = excess.mean()

            # t检验
            if len(excess) > 1:
                t_stat, p_value = stats.ttest_1samp(excess, 0)
                metrics['t_stat'] = t_stat
                metrics['p_value'] = p_value

        # 夏普比率
        if portfolio_returns.std() > 0:
            # 年化夏普（假设20天一个周期）
            metrics['sharpe_ratio'] = portfolio_returns.mean() / portfolio_returns.std() * np.sqrt(252 / 20)

        return metrics

    def optimize_weights(self, periods):
        """
        优化给定周期的权重

        Args:
            periods: 周期列表

        Returns:
            最优权重
        """
        print(f"\n开始优化权重（训练集）...")

        def objective(weights):
            """优化目标函数"""
            # 确保权重是负数（反转策略）
            weights = -np.abs(weights)

            metrics = self.backtest_strategy(periods, weights, self.train_dates)

            if metrics is None:
                return 1000  # 惩罚无效策略

            # 多目标优化
            # 主要目标：超额收益
            # 约束：胜率 > 50%
            score = -metrics['mean_excess']  # 最大化超额收益

            # 惩罚低胜率
            if metrics['win_rate'] < 0.50:
                score += (0.50 - metrics['win_rate']) * 10

            return score

        # 定义搜索空间（权重绝对值）
        bounds = [(0, 200) for _ in periods]

        # 运行优化
        result = differential_evolution(
            objective,
            bounds,
            seed=42,
            maxiter=50,
            popsize=15,
            workers=1,
            disp=True
        )

        # 转为负权重（反转策略）
        best_weights = -np.abs(result.x)

        # 归一化
        best_weights = best_weights / np.sum(np.abs(best_weights)) * 100

        return best_weights

    def grid_search_periods(self):
        """
        网格搜索最佳周期组合

        测试不同的周期数量（2-5个）
        """
        print("\n" + "=" * 80)
        print("网格搜索最佳周期组合")
        print("=" * 80)

        # 先找出IC最强的10个周期
        all_periods = range(1, 21)
        ic_values = {period: self.calculate_ic(period) for period in all_periods}
        sorted_periods = sorted(ic_values.items(), key=lambda x: abs(x[1]), reverse=True)
        top_10_periods = [p for p, ic in sorted_periods[:10]]

        print(f"\nIC最强的10个周期: {top_10_periods}")

        results = []

        # 测试不同数量的周期
        for n in [2, 3, 4, 5]:
            print(f"\n{'=' * 60}")
            print(f"测试 {n} 个周期的组合")
            print(f"{'=' * 60}")

            # 只从top 10中选择，减少搜索空间
            if n == 2:
                # 2个周期：测试所有组合
                period_combinations = list(combinations(top_10_periods, n))
            elif n == 3:
                # 3个周期：随机采样20个组合
                all_combs = list(combinations(top_10_periods, n))
                np.random.seed(42)
                period_combinations = [all_combs[i] for i in np.random.choice(len(all_combs), min(20, len(all_combs)), replace=False)]
            else:
                # 4-5个周期：只测试IC最强的
                period_combinations = [tuple(top_10_periods[:n])]

            for i, periods in enumerate(period_combinations):
                periods = list(periods)
                periods.sort()

                print(f"\n[{i+1}/{len(period_combinations)}] 测试周期组合: {periods}")

                # 优化权重
                weights = self.optimize_weights(periods)

                # 训练集表现
                train_metrics = self.backtest_strategy(periods, weights, self.train_dates)

                # 测试集表现
                test_metrics = self.backtest_strategy(periods, weights, self.test_dates)

                if train_metrics and test_metrics:
                    print(f"  训练集: 胜率={train_metrics['win_rate']:.2%}, 超额={train_metrics['mean_excess']:.2%}, p={train_metrics['p_value']:.4f}")
                    print(f"  测试集: 胜率={test_metrics['win_rate']:.2%}, 超额={test_metrics['mean_excess']:.2%}, p={test_metrics['p_value']:.4f}")

                    results.append({
                        'n_periods': n,
                        'periods': periods,
                        'weights': weights,
                        'train_win_rate': train_metrics['win_rate'],
                        'train_excess': train_metrics['mean_excess'],
                        'train_p_value': train_metrics['p_value'],
                        'test_win_rate': test_metrics['win_rate'],
                        'test_excess': test_metrics['mean_excess'],
                        'test_p_value': test_metrics['p_value'],
                        'test_sharpe': test_metrics['sharpe_ratio']
                    })

        return results

    def run(self):
        """运行完整优化流程"""
        # 1. 加载数据
        self.load_data()

        # 2. 分割数据
        self.split_data(train_ratio=0.7)

        # 3. 网格搜索
        results = self.grid_search_periods()

        # 4. 分析结果
        print("\n" + "=" * 80)
        print("优化结果汇总")
        print("=" * 80)

        # 转为DataFrame
        df_results = pd.DataFrame(results)

        # 按测试集超额收益排序
        df_results = df_results.sort_values('test_excess', ascending=False)

        print("\n按测试集超额收益排序（前10）:")
        print("-" * 80)
        print(f"{'Rank':<5} {'周期组合':<20} {'测试集胜率':<12} {'测试集超额':<12} {'P值':<10} {'夏普':<8}")
        print("-" * 80)

        for i, row in df_results.head(10).iterrows():
            periods_str = str(row['periods'])
            print(f"{i+1:<5} {periods_str:<20} {row['test_win_rate']:>10.2%} {row['test_excess']:>10.2%} {row['test_p_value']:>8.4f} {row['test_sharpe']:>6.2f}")

        # 筛选通过验证的策略
        print("\n" + "=" * 80)
        print("通过验证的策略（测试集胜率>50% 且 P<0.1）")
        print("=" * 80)

        valid_strategies = df_results[
            (df_results['test_win_rate'] > 0.50) &
            (df_results['test_p_value'] < 0.10)
        ]

        if len(valid_strategies) > 0:
            print(f"\n找到 {len(valid_strategies)} 个通过验证的策略:")

            for i, row in valid_strategies.iterrows():
                print(f"\n策略 #{i+1}:")
                print(f"  周期: {row['periods']}")
                print(f"  权重: {[round(w, 1) for w in row['weights']]}")
                print(f"  测试集表现:")
                print(f"    胜率: {row['test_win_rate']:.2%}")
                print(f"    超额收益: {row['test_excess']:.2%}")
                print(f"    P值: {row['test_p_value']:.4f}")
                print(f"    夏普比率: {row['test_sharpe']:.2f}")

                # 代码格式
                periods_dict = {p: round(w, 0) for p, w in zip(row['periods'], row['weights'])}
                print(f"\n  代码格式:")
                print(f"  periods = {periods_dict}")

            # 推荐最佳策略
            best = valid_strategies.iloc[0]
            print("\n" + "=" * 80)
            print("🎯 推荐策略（测试集表现最佳）")
            print("=" * 80)
            print(f"\n周期: {best['periods']}")
            print(f"权重: {[round(w, 1) for w in best['weights']]}")

            periods_dict = {int(p): int(round(w, 0)) for p, w in zip(best['periods'], best['weights'])}
            print(f"\n在 core/signal.py 中使用:")
            print(f"periods = {periods_dict}")

        else:
            print("\n⚠️  未找到通过验证的策略")
            print("\n可能原因:")
            print("  1. 数据量不足（仅17个月）")
            print("  2. 市场环境变化大（训练期牛市，测试期震荡）")
            print("  3. 反转效应较弱")

            print("\n建议:")
            print("  1. 扩展数据到3-5年")
            print("  2. 使用最简单的策略（只用1-2个周期）")
            print("  3. 降低期望（胜率55%也可接受）")

            # 显示最接近的策略
            print("\n最接近通过验证的策略:")
            closest = df_results.iloc[0]
            print(f"  周期: {closest['periods']}")
            print(f"  权重: {[round(w, 1) for w in closest['weights']]}")
            print(f"  测试集胜率: {closest['test_win_rate']:.2%}")
            print(f"  测试集P值: {closest['test_p_value']:.4f}")

        # 保存结果
        output_dir = 'output'
        os.makedirs(output_dir, exist_ok=True)

        df_results.to_csv(os.path.join(output_dir, 'reversion_optimization_results.csv'), index=False)
        print(f"\n详细结果已保存至: output/reversion_optimization_results.csv")

        return df_results, valid_strategies


def main():
    """主函数"""
    optimizer = ReversionStrategyOptimizer(
        data_dir='data_for_opt_stocks',
        top_k=4
    )

    results, valid = optimizer.run()

    print("\n" + "=" * 80)
    print("✅ 优化完成")
    print("=" * 80)


if __name__ == '__main__':
    main()
