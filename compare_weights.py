"""
权重方案对比分析脚本
对比等额权重 vs 不等额权重(2:1)的回测表现差异
"""
import os
import sys
import json
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False

class WeightComparisonAnalyzer:
    """权重方案对比分析器"""
    
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.output_dir = os.path.join(base_dir, "output", "weight_comparison")
        os.makedirs(self.output_dir, exist_ok=True)
        
    def run_backtest_with_weight_scheme(self, weight_scheme='unequal'):
        """
        运行指定权重方案的回测
        
        Args:
            weight_scheme: 'equal' 或 'unequal'
        """
        print(f"\n{'='*60}")
        print(f"🚀 开始运行回测 - 权重方案: {weight_scheme.upper()}")
        print(f"{'='*60}\n")
        
        # 修改 strategy.py 中的权重配置
        strategy_file = os.path.join(self.base_dir, "core", "strategy.py")
        
        with open(strategy_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 备份原始内容
        backup_file = strategy_file + '.backup'
        with open(backup_file, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # 修改权重逻辑
        if weight_scheme == 'equal':
            # 等额权重：所有持仓权重都为1
            new_weights_code = """        weights = {
            s: 1  # 等额权重
            for i, s in enumerate(candidates) if s in final_list
        }"""
        else:
            # 不等额权重：前3只权重为2，其余为1
            new_weights_code = """        weights = {
            s: (2 if i < 3 else 1) 
            for i, s in enumerate(candidates) if s in final_list
        }"""
        
        # 替换权重代码
        import re
        pattern = r'weights = \{[^}]+\}'
        content = re.sub(pattern, new_weights_code.strip(), content, flags=re.DOTALL)
        
        with open(strategy_file, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"✅ 已修改权重方案为: {weight_scheme}")
        
        # 运行回测
        backtest_script = os.path.join(self.base_dir, "run_backtest.py")
        result_file = os.path.join(self.output_dir, f"result_{weight_scheme}.json")
        
        import subprocess
        cmd = f'python "{backtest_script}"'
        print(f"📊 执行回测命令: {cmd}\n")
        
        try:
            result = subprocess.run(
                cmd, 
                shell=True, 
                cwd=self.base_dir,
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
            
            print("回测输出:")
            print(result.stdout)
            if result.stderr:
                print("错误信息:")
                print(result.stderr)
            
            # 保存回测输出
            output_file = os.path.join(self.output_dir, f"backtest_log_{weight_scheme}.txt")
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"=== {weight_scheme.upper()} 权重方案回测日志 ===\n\n")
                f.write("STDOUT:\n")
                f.write(result.stdout)
                f.write("\n\nSTDERR:\n")
                f.write(result.stderr)
            
            print(f"✅ 回测日志已保存至: {output_file}")
            
        except Exception as e:
            print(f"❌ 回测执行失败: {e}")
            raise
        finally:
            # 恢复原始文件
            with open(backup_file, 'r', encoding='utf-8') as f:
                original_content = f.read()
            with open(strategy_file, 'w', encoding='utf-8') as f:
                f.write(original_content)
            os.remove(backup_file)
            print(f"✅ 已恢复原始 strategy.py 文件\n")
        
        return self.extract_metrics_from_log(result.stdout)
    
    def extract_metrics_from_log(self, log_text):
        """从回测日志中提取关键指标"""
        metrics = {
            'gm_return': None,
            'gm_max_dd': None,
            'gm_sharpe': None,
            'rpm_return': None,
            'rpm_max_dd': None,
            'rpm_sharpe': None
        }
        
        import re
        
        # 提取掘金回测指标
        gm_return_match = re.search(r'Return:\s+([-\d.]+)%', log_text)
        gm_dd_match = re.search(r'MaxDD:\s+([-\d.]+)%', log_text)
        gm_sharpe_match = re.search(r'Sharpe:\s+([-\d.]+)', log_text)
        
        if gm_return_match:
            metrics['gm_return'] = float(gm_return_match.group(1))
        if gm_dd_match:
            metrics['gm_max_dd'] = float(gm_dd_match.group(1))
        if gm_sharpe_match:
            metrics['gm_sharpe'] = float(gm_sharpe_match.group(1))
        
        # 提取RPM回测指标（尾盘模拟）
        rpm_section = log_text.split('尾盘模回测报告')
        if len(rpm_section) > 1:
            rpm_text = rpm_section[1]
            rpm_return_match = re.search(r'Return:\s+([-\d.]+)%', rpm_text)
            rpm_dd_match = re.search(r'MaxDD:\s+([-\d.]+)%', rpm_text)
            rpm_sharpe_match = re.search(r'Sharpe:\s+([-\d.]+)', rpm_text)
            
            if rpm_return_match:
                metrics['rpm_return'] = float(rpm_return_match.group(1))
            if rpm_dd_match:
                metrics['rpm_max_dd'] = float(rpm_dd_match.group(1))
            if rpm_sharpe_match:
                metrics['rpm_sharpe'] = float(rpm_sharpe_match.group(1))
        
        return metrics
    
    def compare_results(self, equal_metrics, unequal_metrics):
        """对比两种权重方案的结果"""
        print(f"\n{'='*80}")
        print("📊 权重方案对比分析报告")
        print(f"{'='*80}\n")
        
        # 创建对比表格
        comparison_data = []
        
        metrics_names = {
            'gm_return': '掘金回测收益率 (%)',
            'gm_max_dd': '掘金回测最大回撤 (%)',
            'gm_sharpe': '掘金回测夏普比率',
            'rpm_return': 'RPM回测收益率 (%)',
            'rpm_max_dd': 'RPM回测最大回撤 (%)',
            'rpm_sharpe': 'RPM回测夏普比率'
        }
        
        for key, name in metrics_names.items():
            equal_val = equal_metrics.get(key)
            unequal_val = unequal_metrics.get(key)
            
            if equal_val is not None and unequal_val is not None:
                diff = unequal_val - equal_val
                diff_pct = (diff / abs(equal_val) * 100) if equal_val != 0 else 0
                
                comparison_data.append({
                    '指标': name,
                    '等额权重': f"{equal_val:.2f}",
                    '不等额权重(2:1)': f"{unequal_val:.2f}",
                    '差异': f"{diff:+.2f}",
                    '差异百分比': f"{diff_pct:+.2f}%"
                })
        
        df = pd.DataFrame(comparison_data)
        
        print(df.to_string(index=False))
        print(f"\n{'='*80}\n")
        
        # 保存对比结果
        report_file = os.path.join(self.output_dir, "comparison_report.txt")
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(f"权重方案对比分析报告\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{'='*80}\n\n")
            f.write(df.to_string(index=False))
            f.write(f"\n\n{'='*80}\n\n")
            
            # 添加结论分析
            f.write("📈 关键发现:\n\n")
            
            if equal_metrics.get('rpm_return') and unequal_metrics.get('rpm_return'):
                return_diff = unequal_metrics['rpm_return'] - equal_metrics['rpm_return']
                f.write(f"1. 收益率差异: 不等额权重相比等额权重 {return_diff:+.2f}%\n")
                if return_diff > 0:
                    f.write(f"   → 不等额权重(2:1)方案表现更优，提升了 {return_diff:.2f}% 的收益\n")
                else:
                    f.write(f"   → 等额权重方案表现更优，不等额权重降低了 {abs(return_diff):.2f}% 的收益\n")
            
            if equal_metrics.get('rpm_max_dd') and unequal_metrics.get('rpm_max_dd'):
                dd_diff = unequal_metrics['rpm_max_dd'] - equal_metrics['rpm_max_dd']
                f.write(f"\n2. 最大回撤差异: {dd_diff:+.2f}%\n")
                if dd_diff < 0:
                    f.write(f"   → 不等额权重降低了 {abs(dd_diff):.2f}% 的最大回撤，风险控制更好\n")
                else:
                    f.write(f"   → 不等额权重增加了 {dd_diff:.2f}% 的最大回撤，风险略高\n")
            
            if equal_metrics.get('rpm_sharpe') and unequal_metrics.get('rpm_sharpe'):
                sharpe_diff = unequal_metrics['rpm_sharpe'] - equal_metrics['rpm_sharpe']
                f.write(f"\n3. 夏普比率差异: {sharpe_diff:+.2f}\n")
                if sharpe_diff > 0:
                    f.write(f"   → 不等额权重的风险调整后收益更优\n")
                else:
                    f.write(f"   → 等额权重的风险调整后收益更优\n")
        
        print(f"✅ 详细报告已保存至: {report_file}\n")
        
        # 保存JSON格式
        json_file = os.path.join(self.output_dir, "comparison_data.json")
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump({
                'equal_weight': equal_metrics,
                'unequal_weight': unequal_metrics,
                'timestamp': datetime.now().isoformat()
            }, f, indent=2, ensure_ascii=False)
        
        return df
    
    def plot_comparison(self, equal_metrics, unequal_metrics):
        """绘制对比图表"""
        fig, axes = plt.subplots(1, 3, figsize=(15, 5))
        
        # 1. 收益率对比
        ax1 = axes[0]
        categories = ['等额权重', '不等额权重(2:1)']
        returns = [
            equal_metrics.get('rpm_return', 0),
            unequal_metrics.get('rpm_return', 0)
        ]
        colors = ['#3498db', '#e74c3c']
        bars1 = ax1.bar(categories, returns, color=colors, alpha=0.7)
        ax1.set_ylabel('收益率 (%)', fontsize=12)
        ax1.set_title('收益率对比', fontsize=14, fontweight='bold')
        ax1.grid(axis='y', alpha=0.3)
        
        # 添加数值标签
        for bar in bars1:
            height = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width()/2., height,
                    f'{height:.2f}%',
                    ha='center', va='bottom', fontsize=10)
        
        # 2. 最大回撤对比
        ax2 = axes[1]
        drawdowns = [
            equal_metrics.get('rpm_max_dd', 0),
            unequal_metrics.get('rpm_max_dd', 0)
        ]
        bars2 = ax2.bar(categories, drawdowns, color=colors, alpha=0.7)
        ax2.set_ylabel('最大回撤 (%)', fontsize=12)
        ax2.set_title('最大回撤对比', fontsize=14, fontweight='bold')
        ax2.grid(axis='y', alpha=0.3)
        
        for bar in bars2:
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width()/2., height,
                    f'{height:.2f}%',
                    ha='center', va='bottom', fontsize=10)
        
        # 3. 夏普比率对比
        ax3 = axes[2]
        sharpes = [
            equal_metrics.get('rpm_sharpe', 0),
            unequal_metrics.get('rpm_sharpe', 0)
        ]
        bars3 = ax3.bar(categories, sharpes, color=colors, alpha=0.7)
        ax3.set_ylabel('夏普比率', fontsize=12)
        ax3.set_title('夏普比率对比', fontsize=14, fontweight='bold')
        ax3.grid(axis='y', alpha=0.3)
        
        for bar in bars3:
            height = bar.get_height()
            ax3.text(bar.get_x() + bar.get_width()/2., height,
                    f'{height:.2f}',
                    ha='center', va='bottom', fontsize=10)
        
        plt.tight_layout()
        
        # 保存图表
        chart_file = os.path.join(self.output_dir, "weight_comparison_chart.png")
        plt.savefig(chart_file, dpi=300, bbox_inches='tight')
        print(f"✅ 对比图表已保存至: {chart_file}\n")
        
        plt.close()
    
    def run_full_comparison(self):
        """运行完整的权重对比分析"""
        print("\n" + "="*80)
        print("🎯 权重方案对比分析 - 开始执行")
        print("="*80)
        
        # 1. 运行等额权重回测
        print("\n【步骤 1/3】运行等额权重回测...")
        equal_metrics = self.run_backtest_with_weight_scheme('equal')
        
        # 2. 运行不等额权重回测
        print("\n【步骤 2/3】运行不等额权重(2:1)回测...")
        unequal_metrics = self.run_backtest_with_weight_scheme('unequal')
        
        # 3. 对比分析
        print("\n【步骤 3/3】生成对比分析报告...")
        df = self.compare_results(equal_metrics, unequal_metrics)
        
        # 4. 绘制图表
        self.plot_comparison(equal_metrics, unequal_metrics)
        
        print("\n" + "="*80)
        print("✅ 权重方案对比分析完成！")
        print(f"📁 所有结果已保存至: {self.output_dir}")
        print("="*80 + "\n")
        
        return equal_metrics, unequal_metrics


if __name__ == "__main__":
    # 获取项目根目录
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 创建分析器
    analyzer = WeightComparisonAnalyzer(base_dir)
    
    # 运行完整对比分析
    equal_metrics, unequal_metrics = analyzer.run_full_comparison()
