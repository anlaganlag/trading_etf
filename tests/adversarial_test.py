from __future__ import print_function, absolute_import
from gm.api import *
import pandas as pd
import numpy as np
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from config import config

# 导入主策略代码，但覆盖时间
# 我们用一种 tricky 的方式：直接读取 main.py 并覆盖 start/end date 变量
with open('main.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 定义敌对测试场景
SCENARIOS = {
    "BEAR_2022": ("2022-01-01 09:00:00", "2022-10-31 16:00:00", "熊市 (单边下跌)"),
    "SIDEWAYS_2023": ("2023-06-01 09:00:00", "2024-01-31 16:00:00", "横盘 (无趋势磨损)"),
    "VOLATILE_2024": ("2024-01-15 09:00:00", "2024-03-15 16:00:00", "剧烈波动 (V型反转)"),
    "BULL_2024": ("2024-09-01 09:00:00", "2024-12-31 16:00:00", "牛市 (对照组)")
}

# 动态修改并执行
def run_scenario(name):
    start, end, desc = SCENARIOS[name]
    print(f"\n⚡ Running Scenario: {name} [{desc}] ({start} ~ {end})")
    
    # 替换时间
    new_code = code.replace("START_DATE='2021-12-03 09:00:00'", f"START_DATE='{start}'")
    new_code = new_code.replace("END_DATE='2026-01-23 16:00:00'", f"END_DATE='{end}'")
    
    # 写入临时文件
    temp_file = f"main_adversarial_{name}.py"
    with open(temp_file, 'w', encoding='utf-8') as f:
        f.write(new_code)
    
    # 执行
    os.system(f"python {temp_file}")
    
    # 清理
    try:
        os.remove(temp_file)
    except:
        pass

if __name__ == "__main__":
    print("🛡️ Starting Adversarial Testing...")
    for name in SCENARIOS:
        run_scenario(name)
