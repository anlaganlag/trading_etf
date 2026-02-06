"""
扩展策略对比分析脚本
验证不同 TOP_N 和 权重方案 的组合效果
"""
import os
import sys
import json
import re
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False

class StrategyComparisonAnalyzer:
    """策略组合对比分析器"""
    
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.output_dir = os.path.join(base_dir, "output", "strategy_comparison")
        os.makedirs(self.output_dir, exist_ok=True)
        self.strategy_file = os.path.join(self.base_dir, "core", "strategy.py")
        self.config_file = os.path.join(self.base_dir, "config.py")
        
    def modify_code(self, top_n, weight_type):
        """修改代码配置"""
        
        # 1. 修改 config.py 中的 TOP_N
        with open(self.config_file, 'r', encoding='utf-8') as f:
            config_content = f.read()
        
        # 使用正则替换 TOP_N
        # 假设格式: TOP_N = 4  # 注释
        new_config_content = re.sub(
            r'TOP_N\s*=\s*\d+',
            f'TOP_N = {top_n}',
            config_content
        )
        
        with open(self.config_file, 'w', encoding='utf-8') as f:
            f.write(new_config_content)
            
        # 2. 修改 strategy.py 中的权重逻辑
        with open(self.strategy_file, 'r', encoding='utf-8') as f:
            strat_content = f.read()
            
        if weight_type == 'equal':
            new_weights_code = """        weights = {
            s: 1
            for i, s in enumerate(candidates) if s in final_list
        }"""
        elif weight_type == '2_1':
            new_weights_code = """        weights = {
            s: (2 if i < 3 else 1)
            for i, s in enumerate(candidates) if s in final_list
        }"""
        elif weight_type == 'linear':
            new_weights_code = """        weights = {
            s: (4 - i)  # 4, 3, 2, 1
            for i, s in enumerate(candidates) if s in final_list
        }"""
        elif weight_type == 'heavy_top':
            new_weights_code = """        weights = {
            s: (3 if i == 0 else 1)  # 3, 1, 1, 1
            for i, s in enumerate(candidates) if s in final_list
        }"""
        elif weight_type == 'weighted_5':
            new_weights_code = """        weights = {
            s: (2 if i < 3 else 1)  # 2, 2, 2, 1, 1
            for i, s in enumerate(candidates) if s in final_list
        }"""
        
        # 替换权重代码块
        pattern = r'weights = \{[^}]+\}'
        new_strat_content = re.sub(pattern, new_weights_code.strip(), strat_content, flags=re.DOTALL)
        
        with open(self.strategy_file, 'w', encoding='utf-8') as f:
            f.write(new_strat_content)
            
        print(f"✅ 已应用配置: TOP_N={top_n}, Weights={weight_type}")

    def run_scenario(self, name, top_n, weight_type):
        """运行单个场景"""
        print(f"\n{'='*60}")
        print(f"🚀 运行场景: {name} [TOP_N={top_n}, Weights={weight_type}]")
        print(f"{'='*60}")
        
        # 备份文件
        self._backup_files()
        
        try:
            # 修改代码
            self.modify_code(top_n, weight_type)
            
            # 执行回测
            backtest_script = os.path.join(self.base_dir, "run_backtest.py")
            cmd = f'python "{backtest_script}"'
            
            import subprocess
            result = subprocess.run(
                cmd, 
                shell=True, 
                cwd=self.base_dir,
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
            
            # 3. 组合日志进行解析
            full_log = result.stdout + "\n=== STDERR ===\n" + result.stderr
            
            # 保存日志
            log_file = os.path.join(self.output_dir, f"log_{name}.txt")
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(full_log)
            
            print(f"📄 日志已保存 (Stdout: {len(result.stdout)} chars, Stderr: {len(result.stderr)} chars)")
            return self.extract_metrics(full_log, name)
            
        except Exception as e:
            print(f"❌ 场景执行失败: {e}")
            return None
        finally:
            self._restore_files()

    def _backup_files(self):
        """备份原始文件"""
        import shutil
        if not os.path.exists(self.config_file + '.bak'):
            shutil.copy2(self.config_file, self.config_file + '.bak')
        if not os.path.exists(self.strategy_file + '.bak'):
            shutil.copy2(self.strategy_file, self.strategy_file + '.bak')

    def _restore_files(self):
        """恢复原始文件"""
        import shutil
        if os.path.exists(self.config_file + '.bak'):
            shutil.copy2(self.config_file + '.bak', self.config_file)
            # Do NOT remove .bak yet, keep it for subsequent runs or cleanup at very end
        if os.path.exists(self.strategy_file + '.bak'):
            shutil.copy2(self.strategy_file + '.bak', self.strategy_file)

    def extract_metrics(self, log_text, name):
        """提取指标"""
        metrics = {'name': name}
        
        # 尝试匹配最后的报告
        # BACKTEST REPORT (BUFFER=2, SL=Fixed 20%, TOP_N=Fixed 4)
        # 🚀 Return: 46.03%
        
        # 优先查找 RPM 尾盘模拟报告
        rpm_match = re.search(r'尾盘模回测报告', log_text)
        if rpm_match:
            search_text = log_text[rpm_match.start():]
        else:
            search_text = log_text
            
        # 查找 Return
        ret_match = re.search(r'Return:\s*([-\d.]+)%', search_text)
        dd_match = re.search(r'MaxDD:\s*([-\d.]+)%', search_text)
        sharpe_match = re.search(r'Sharpe:\s*([-\d.]+)', search_text)
        
        metrics['Return'] = float(ret_match.group(1)) if ret_match else 0.0
        metrics['MaxDD'] = float(dd_match.group(1)) if dd_match else 0.0
        metrics['Sharpe'] = float(sharpe_match.group(1)) if sharpe_match else 0.0
                
        print(f"📊 {name} 结果: Return={metrics['Return']}%, MaxDD={metrics['MaxDD']}%, Sharpe={metrics['Sharpe']}")
        return metrics

    def run_all(self):
        scenarios = [
            {"name": "4只_2121基准", "top_n": 4, "weight": "2_1"},
            {"name": "4只_线性衰减", "top_n": 4, "weight": "linear"},
            {"name": "4只_冠军重仓", "top_n": 4, "weight": "heavy_top"},
            {"name": "5只_宽基防守", "top_n": 5, "weight": "weighted_5"},
        ]
        
        results = []
        for s in scenarios:
            res = self.run_scenario(s['name'], s['top_n'], s['weight'])
            if res:
                results.append(res)
                
        self.generate_report(results)

    def generate_report(self, results):
        """生成最终报告"""
        df = pd.DataFrame(results)
        df = df.set_index('name')
        
        print("\n" + "="*80)
        print("🏆 最终对比报告")
        print("="*80)
        print(df)
        
        report_path = os.path.join(self.output_dir, "final_report.csv")
        df.to_csv(report_path)
        print(f"\n报告已保存: {report_path}")
        
        # 绘图
        try:
            fig, axes = plt.subplots(1, 3, figsize=(15, 5))
            
            # Return
            colors = ['#3498db', '#95a5a6', '#e74c3c']
            df['Return'].plot(kind='bar', ax=axes[0], color=colors, title='收益率 %', rot=0)
            for p in axes[0].patches:
                axes[0].annotate(f'{p.get_height():.1f}', (p.get_x() + p.get_width() / 2., p.get_height()), ha='center', va='bottom')

            # MaxDD
            df['MaxDD'].plot(kind='bar', ax=axes[1], color=colors, title='最大回撤 %', rot=0)
            for p in axes[1].patches:
                axes[1].annotate(f'{p.get_height():.1f}', (p.get_x() + p.get_width() / 2., p.get_height()), ha='center', va='bottom')

            # Sharpe
            df['Sharpe'].plot(kind='bar', ax=axes[2], color=colors, title='夏普比率', rot=0)
            for p in axes[2].patches:
                axes[2].annotate(f'{p.get_height():.2f}', (p.get_x() + p.get_width() / 2., p.get_height()), ha='center', va='bottom')
                
            plt.tight_layout()
            plt.savefig(os.path.join(self.output_dir, "comparison_chart.png"))
        except Exception as e:
            print(f"绘图失败: {e}")

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    analyzer = StrategyComparisonAnalyzer(base_dir)
    analyzer.run_all()
