"""
黄金基准一致性验证脚本
用于确保重构后的代码产生与预期完全一致的结果。
"""
import subprocess
import re
import sys
from config import logger

# 预期的黄金结果
EXPECTED_RETURN = 51.33  # 基于当前代码版本的基准
EXPECTED_SHARPE = 0.71

def run_verify():
    logger.info("🧪 Starting Consistency Verification...")
    
    # 运行回测
    try:
        result = subprocess.run(
            ['python', 'run_backtest.py'],
            capture_output=True,
            text=True,
            check=True
        )
        output = result.stdout + result.stderr
        # logger.debug(f"Combined Output: {output}") 
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Backtest failed to run: {e}")
        logger.error(f"Error output: {e.stderr}")
        return False

    # 解析结果 (适配 logger 格式)
    # 查找内容样式: 2026-02-06 10:57:08,230 - INFO - 🚀 Return: 51.33%
    ret_match = re.search(r"Return:\s+([\d\.]+)%", output)
    sharpe_match = re.search(r"Sharpe:\s+([\d\.]+)", output)

    if not ret_match or not sharpe_match:
        logger.error("❌ Could not parse backtest results from output!")
        logger.error(f"Captured output length: {len(output)}")
        logger.error(f"Last 1000 chars of output:\n{output[-1000:]}") 
        return False

    actual_return = float(ret_match.group(1))
    actual_sharpe = float(sharpe_match.group(1))

    logger.info(f"📊 Results: Return={actual_return}%, Sharpe={actual_sharpe}")

    # 严格比对
    success = True
    if abs(actual_return - EXPECTED_RETURN) > 0.01:
        logger.error(f"🚨 RETURN DEVIATION detected! Expected {EXPECTED_RETURN}%, got {actual_return}%")
        success = False
    
    if abs(actual_sharpe - EXPECTED_SHARPE) > 0.01:
        logger.error(f"🚨 SHARPE DEVIATION detected! Expected {EXPECTED_SHARPE}, got {actual_sharpe}")
        success = False

    if success:
        logger.info("✅ CONSISTENCY CHECK PASSED. Code is robust and reproducible.")
    else:
        logger.error("❌ CONSISTENCY CHECK FAILED!")
    
    return success

if __name__ == '__main__':
    if run_verify():
        sys.exit(0)
    else:
        sys.exit(1)
