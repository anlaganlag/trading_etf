"""
快速权重参数搜索脚本

目标：验证通过优化权重参数能否提升策略表现
方法：简化网格搜索（只优化3个核心周期）

使用方法：
    python scripts/quick_weight_search.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from itertools import product
from config import logger
from optimization.backtest_adapter import run_backtest_with_weights

def quick_search():
    """
    快速搜索最优权重（仅优化3个核心周期）
    """
    logger.info("=" * 70)
    logger.info("快速权重参数搜索")
    logger.info("=" * 70)

    # 定义搜索空间（只优化3个核心周期）
    periods = [1, 5, 20]  # 1日（短期爆发）、5日（中期）、20日（长期动量）
    weight_candidates = [-100, -50, 0, 50, 100, 150, 200]

    logger.info(f"\n搜索配置:")
    logger.info(f"  优化周期: {periods}")
    logger.info(f"  权重候选值: {weight_candidates}")
    logger.info(f"  组合总数: {len(weight_candidates) ** len(periods)} = {7**3}")

    # 存储结果
    results = []
    best_score = -float('inf')
    best_weights = None
    best_metrics = None

    # 遍历所有组合
    total_combinations = len(weight_candidates) ** len(periods)
    current = 0

    for w1, w5, w20 in product(weight_candidates, repeat=3):
        current += 1

        # 构建权重字典（其他周期设为0）
        weights = {i: 0 for i in range(1, 21)}
        weights[1] = w1
        weights[5] = w5
        weights[20] = w20

        # 运行回测（仅2023年，加快速度）
        try:
            result = run_backtest_with_weights(
                weights=weights,
                start_date='2023-01-01',
                end_date='2023-12-31'
            )

            metrics = result['metrics']
            win_rate = metrics['win_rate']
            excess_return = metrics['excess_return']
            max_drawdown = metrics['max_drawdown']

            # 计算综合得分
            # 硬约束：胜率 >= 65%（放宽到65%，因为仅1年数据）
            if win_rate < 0.65:
                score = -1000
            else:
                score = (
                    excess_return * 100 +        # 超额收益（主要目标）
                    (win_rate - 0.65) * 50 -     # 胜率奖励
                    max_drawdown * 30            # 回撤惩罚
                )

            # 记录结果
            results.append({
                'w1': w1,
                'w5': w5,
                'w20': w20,
                'win_rate': win_rate,
                'excess_return': excess_return,
                'max_drawdown': max_drawdown,
                'score': score
            })

            # 更新最佳结果
            if score > best_score:
                best_score = score
                best_weights = weights.copy()
                best_metrics = metrics.copy()

                logger.info(f"\n🎯 发现更优组合 [{current}/{total_combinations}]:")
                logger.info(f"  权重: 1日={w1}, 5日={w5}, 20日={w20}")
                logger.info(f"  胜率: {win_rate:.2%}")
                logger.info(f"  超额收益: {excess_return:.2%}")
                logger.info(f"  最大回撤: {max_drawdown:.2%}")
                logger.info(f"  综合得分: {score:.2f}")

        except Exception as e:
            logger.error(f"回测失败 [{w1}, {w5}, {w20}]: {e}")
            continue

        # 进度提示
        if current % 50 == 0:
            logger.info(f"进度: {current}/{total_combinations} ({current/total_combinations*100:.1f}%)")

    # 输出最终结果
    logger.info("\n" + "=" * 70)
    logger.info("搜索完成！最优结果：")
    logger.info("=" * 70)

    if best_weights:
        logger.info(f"\n📌 最优权重参数:")
        logger.info(f"  1日涨幅权重:  {best_weights[1]:>6.0f}")
        logger.info(f"  5日涨幅权重:  {best_weights[5]:>6.0f}")
        logger.info(f"  20日涨幅权重: {best_weights[20]:>6.0f}")

        logger.info(f"\n📊 性能指标:")
        logger.info(f"  胜率:       {best_metrics['win_rate']:.2%}")
        logger.info(f"  超额收益:   {best_metrics['excess_return']:.2%}")
        logger.info(f"  最大回撤:   {best_metrics['max_drawdown']:.2%}")
        logger.info(f"  夏普比率:   {best_metrics.get('sharpe_ratio', 0):.2f}")
        logger.info(f"  综合得分:   {best_score:.2f}")
    else:
        logger.warning("⚠️ 未找到满足约束的权重组合！")

    # 保存详细结果
    df_results = pd.DataFrame(results)
    df_results = df_results.sort_values('score', ascending=False)
    output_path = 'output/quick_search_results.csv'
    df_results.to_csv(output_path, index=False)
    logger.info(f"\n💾 详细结果已保存至: {output_path}")

    # 对比当前策略
    logger.info("\n" + "=" * 70)
    logger.info("与当前策略对比:")
    logger.info("=" * 70)

    current_weights = {i: 0 for i in range(1, 21)}
    current_weights[1] = 30
    current_weights[3] = -70
    current_weights[20] = 150

    try:
        current_result = run_backtest_with_weights(
            weights=current_weights,
            start_date='2023-01-01',
            end_date='2023-12-31'
        )
        current_metrics = current_result['metrics']

        comparison = pd.DataFrame({
            '当前策略': [
                current_metrics['win_rate'],
                current_metrics['excess_return'],
                current_metrics.get('sharpe_ratio', 0),
                current_metrics['max_drawdown']
            ],
            '优化策略': [
                best_metrics['win_rate'],
                best_metrics['excess_return'],
                best_metrics.get('sharpe_ratio', 0),
                best_metrics['max_drawdown']
            ]
        }, index=['胜率', '超额收益', '夏普比率', '最大回撤'])

        comparison['改进幅度(%)'] = (
            (comparison['优化策略'] / comparison['当前策略'] - 1) * 100
        )

        print("\n" + comparison.to_string())

    except Exception as e:
        logger.error(f"当前策略回测失败: {e}")

    logger.info("\n" + "=" * 70)
    logger.info("✅ 验证完成！")
    logger.info("=" * 70)

if __name__ == '__main__':
    quick_search()
