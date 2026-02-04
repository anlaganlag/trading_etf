import subprocess
import os
import itertools
import csv
import pandas as pd
from datetime import datetime

# === 配置搜索空间 (核心 18 组) ===
STOP_LOSS_RANGE = [0.10, 0.15, 0.20]
TRAILING_TRIGGER_RANGE = [0.12, 0.15, 0.20]
TRAILING_DROP_RANGE = [0.03, 0.05]

MAIN_SCRIPT = "main.py"
RESULT_CSV = "matrix_results_stop_tp.csv"

def run_backtest(sl, tt, td):
    """运行单个回测组合并提取结果"""
    env = os.environ.copy()
    env["OPT_STOP_LOSS"] = str(sl)
    env["OPT_TRAILING_TRIGGER"] = str(tt)
    env["OPT_TRAILING_DROP"] = str(td)
    env["GM_MODE"] = "BACKTEST"
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Testing: SL={sl}, TT={tt}, TD={td} ...", end="", flush=True)
    
    try:
        # 运行 main.py
        result = subprocess.run(
            ["python", MAIN_SCRIPT], 
            env=env, 
            capture_output=True, 
            text=True, 
            encoding='utf-8'
        )
        
        # 解析结果摘要
        # 寻找格式如: RESULT_SUMMARY|0.2|0.15|0.03|收益|回撤
        for line in result.stdout.splitlines():
            if line.startswith("RESULT_SUMMARY|"):
                parts = line.split("|")
                if len(parts) >= 6:
                    pnl = float(parts[4])
                    dd = float(parts[5])
                    print(f" Done. PnL: {pnl:.2f}%, MaxDD: {dd:.2f}%")
                    return pnl, dd
        
        print(" Failed (No summary found)")
        return None, None
    except Exception as e:
        print(f" Error: {e}")
        return None, None

def main():
    combinations = list(itertools.product(STOP_LOSS_RANGE, TRAILING_TRIGGER_RANGE, TRAILING_DROP_RANGE))
    total = len(combinations)
    print(f"Starting Matrix Search: {total} combinations found.\n")
    
    results = []
    
    for i, (sl, tt, td) in enumerate(combinations):
        print(f"Iter {i+1}/{total} | ", end="")
        pnl, dd = run_backtest(sl, tt, td)
        if pnl is not None:
            results.append({
                "STOP_LOSS": sl,
                "TRAILING_TRIGGER": tt,
                "TRAILING_DROP": td,
                "PnL": pnl,
                "MaxDD": dd,
                "Calmar": pnl / abs(dd) if dd != 0 else 0
            })
            
            # 实时保存，防止中断
            df = pd.DataFrame(results)
            df.to_csv(RESULT_CSV, index=False)

    print(f"\nMatrix search finished. Results saved to {RESULT_CSV}")
    
    # 打印排名前 5 的结果（按 Calmar 比率）
    if results:
        df = pd.DataFrame(results)
        top_5 = df.sort_values(by="Calmar", ascending=False).head(5)
        print("\nTop 5 Parameters (by Calmar Ratio):")
        print(top_5.to_string(index=False))

if __name__ == "__main__":
    main()
