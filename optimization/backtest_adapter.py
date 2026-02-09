"""
回测适配器 - 支持动态权重参数

将自定义权重注入到现有回测系统中
"""
import os
import sys
import tempfile
import shutil
from pathlib import Path
from config import logger

class BacktestAdapter:
    """
    回测适配器类

    作用：临时修改 core/signal.py 中的权重参数，运行回测后恢复
    """

    def __init__(self, base_dir=None):
        if base_dir is None:
            base_dir = Path(__file__).parent.parent
        self.base_dir = Path(base_dir)
        self.signal_file = self.base_dir / 'core' / 'signal.py'
        self.backup_file = None

    def __enter__(self):
        """进入上下文时备份原始文件"""
        self.backup_file = tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            delete=False,
            suffix='_signal_backup.py'
        )
        with open(self.signal_file, 'r', encoding='utf-8') as f:
            content = f.read()
        self.backup_file.write(content)
        self.backup_file.close()
        logger.debug(f"Backed up signal.py to {self.backup_file.name}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文时恢复原始文件"""
        if self.backup_file:
            shutil.copy(self.backup_file.name, self.signal_file)
            os.unlink(self.backup_file.name)
            logger.debug("Restored signal.py from backup")

    def inject_weights(self, weights: dict):
        """
        注入自定义权重到 signal.py

        Args:
            weights: {1: w1, 2: w2, ..., 20: w20} 权重字典
        """
        with open(self.signal_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # 构建新的权重字典代码
        # 只保留非零权重（简化代码）
        non_zero_weights = {p: w for p, w in weights.items() if abs(w) > 0.1}

        weights_code = "periods = {"
        weights_code += ", ".join(f"{p}: {w}" for p, w in sorted(non_zero_weights.items()))
        weights_code += "}"

        # 替换 periods = {1: 30, 3: -70, 20: 150} 这一行
        import re
        pattern = r'periods\s*=\s*\{[^}]+\}'
        new_content = re.sub(pattern, weights_code, content)

        # 写回文件
        with open(self.signal_file, 'w', encoding='utf-8') as f:
            f.write(new_content)

        logger.debug(f"Injected weights: {non_zero_weights}")


def run_backtest_with_weights(
    weights: dict,
    start_date: str = '2023-01-01',
    end_date: str = '2023-12-31'
) -> dict:
    """
    使用自定义权重运行回测

    Args:
        weights: {1: w1, 2: w2, ..., 20: w20} 权重字典
        start_date: 回测起始日期
        end_date: 回测结束日期

    Returns:
        {
            'metrics': {
                'win_rate': float,
                'excess_return': float,
                'max_drawdown': float,
                'sharpe_ratio': float
            },
            'trades': [...],
            'equity_curve': [...]
        }
    """
    # 这是一个简化的模拟实现
    # 实际应该调用你的回测系统，但由于我不知道完整的回测接口，
    # 这里提供一个框架，你需要根据实际情况修改

    logger.info(f"Running backtest with custom weights from {start_date} to {end_date}")

    # 方案1：使用 BacktestAdapter 临时修改 signal.py
    with BacktestAdapter() as adapter:
        adapter.inject_weights(weights)

        # TODO: 调用你的实际回测系统
        # 可能是：
        # - 使用 gm.api 的 backtest 函数
        # - 或运行 run_backtest.py 脚本
        # - 或直接调用 strategy 模块

        # 这里先返回模拟数据，你需要替换为真实回测
        logger.warning("⚠️ Using simulated backtest results! Replace with real backtest!")

        result = simulate_backtest(weights, start_date, end_date)

    return result


def simulate_backtest(weights: dict, start_date: str, end_date: str) -> dict:
    """
    模拟回测结果（仅用于测试）

    实际使用时请删除此函数，使用真实回测系统
    """
    import numpy as np

    # 计算权重得分（越大越"进取"）
    aggressiveness = sum(w for w in weights.values() if w > 0) / 100

    # 模拟指标（基于权重的启发式）
    np.random.seed(hash(str(sorted(weights.items()))) % 2**32)

    base_win_rate = 0.55 + aggressiveness * 0.1
    base_return = 0.02 + aggressiveness * 0.03
    base_drawdown = 0.08 + aggressiveness * 0.05

    # 添加随机噪声
    win_rate = np.clip(base_win_rate + np.random.normal(0, 0.05), 0, 1)
    excess_return = base_return + np.random.normal(0, 0.01)
    max_drawdown = base_drawdown + np.random.normal(0, 0.02)
    sharpe_ratio = excess_return / max_drawdown if max_drawdown > 0 else 0

    return {
        'metrics': {
            'win_rate': win_rate,
            'excess_return': excess_return,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio
        },
        'trades': [],
        'equity_curve': []
    }
