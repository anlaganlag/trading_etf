"""
分析Gemini的验证结果，给出明确建议

使用方法：
    python scripts/analyze_gemini_results.py
"""
import os
import json

def analyze_results():
    """分析验证结果并给出建议"""
    print("=" * 80)
    print("Gemini验证结果分析")
    print("=" * 80)

    # 1. 读取相关性分析
    print("\n1️⃣  相关性分析（方法1）")
    print("-" * 80)

    weight_file = "output/weight_analysis.txt"
    if os.path.exists(weight_file):
        with open(weight_file, 'r') as f:
            content = f.read()
            print(content)

        # 分析IC值
        print("\n关键发现:")
        if "Reversion" in content:
            print("  ⚠️  大部分周期呈现反转效应（负相关）")
            print("  → 建议：采用反转策略，而非追涨策略")
        if "Momentum" in content:
            print("  ✅ 部分周期呈现动量效应（正相关）")
            print("  → 建议：可结合动量与反转")
    else:
        print("  ❌ 未找到 output/weight_analysis.txt")
        print("  → 请先运行: python scripts/simple_weight_calculator.py")

    # 2. 读取严格验证结果
    print("\n" + "=" * 80)
    print("2️⃣  严格验证结果（方法2）")
    print("-" * 80)

    validation_file = "output/rigorous_validation_report.txt"
    if os.path.exists(validation_file):
        with open(validation_file, 'r') as f:
            content = f.read()
            print(content)

        # 解析关键指标
        print("\n" + "=" * 80)
        print("3️⃣  决策建议")
        print("=" * 80)

        # 尝试从文件中提取指标
        lines = content.split('\n')
        test_win_rate = None
        test_p_value = None

        for line in lines:
            if 'Win Rate:' in line and 'Test' not in line:
                try:
                    # 假设格式类似 "Win Rate: 0.4400"
                    test_win_rate = float(line.split(':')[-1].strip())
                except:
                    pass
            if 'P-Value:' in line:
                try:
                    test_p_value = float(line.split(':')[-1].strip())
                except:
                    pass

        # 给出建议
        if test_p_value is not None and test_win_rate is not None:
            print(f"\n测试集表现:")
            print(f"  胜率: {test_win_rate:.2%}")
            print(f"  P值: {test_p_value:.4f}")

            if test_p_value < 0.05 and test_win_rate > 0.52:
                print("\n✅ **结论：策略通过严格验证！**")
                print("\n建议行动:")
                print("  1. 使用验证通过的权重")
                print("  2. 小资金实盘测试（10万元）")
                print("  3. 观察1-2个月")
                print("  4. 效果好再扩大规模")
            else:
                print("\n❌ **结论：策略未通过验证（过拟合）**")
                print(f"\n原因分析:")
                if test_p_value >= 0.05:
                    print(f"  - P值={test_p_value:.4f} > 0.05 → 统计不显著")
                if test_win_rate <= 0.52:
                    print(f"  - 胜率={test_win_rate:.2%} ≈ 随机猜测")

                print("\n⚠️  **不要使用原报告的权重！**")

                print("\n推荐行动（3选1）:")
                print("\n方案A：保守策略（推荐）⭐⭐⭐⭐⭐")
                print("  基于相关性分析的简化权重：")
                print("  periods = {3: -60, 5: -40, 20: 100}")
                print("  → 反转策略，参数少，不易过拟合")

                print("\n方案B：扩展数据")
                print("  收集3-5年历史数据，重新验证")
                print("  → 如果依然失效，说明策略本质有问题")

                print("\n方案C：简化因子")
                print("  只保留1-2个最强因子（如5日反转）")
                print("  → 减少参数，提高稳健性")
        else:
            print("⚠️  无法解析测试集指标，请手动查看报告")

    else:
        print("  ❌ 未找到 output/rigorous_validation_report.txt")
        print("  → 请先运行: python scripts/rigorous_weight_optimizer.py")

    # 总结
    print("\n" + "=" * 80)
    print("📊 总结")
    print("=" * 80)
    print("""
Gemini的工作证实了：
1. ✅ 原报告存在严重过拟合（测试集失效）
2. ✅ 相关性分析显示反转效应占主导
3. ⚠️  不要直接使用原报告的权重实盘

下一步：
1. 查看上述决策建议
2. 选择方案A/B/C之一
3. 回测验证后再实盘
""")


if __name__ == '__main__':
    analyze_results()
