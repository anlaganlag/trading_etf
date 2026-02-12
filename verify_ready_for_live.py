
import unittest
import sys
import os
import subprocess
import time
from datetime import datetime

# Define test files to run
TEST_FILES = [
    ("tests/test_dual_isolation.py", "Config & Environment Isolation"),
    ("tests/test_p0_fixes.py", "Critical Bug Fixes (P0)"),
    ("tests/test_reconciliation.py", "Broker Reconciliation Logic"),
    ("tests/test_live_mock.py", "Full End-to-End Simulation"),
]

def run_test_file(filepath, description):
    print(f"\n{'='*60}")
    print(f"🚀 Running: {description}")
    print(f"📂 File: {filepath}")
    print(f"{'='*60}")
    
    start_time = time.time()
    # Force UTF-8 decoding of output
    result = subprocess.run([sys.executable, filepath], capture_output=True, text=True, encoding='utf-8', errors='replace')
    duration = time.time() - start_time
    
    if result.returncode == 0:
        print(f"✅ PASS ({duration:.2f}s)")
        # Print only the summary part or last few lines to keep report clean
        # But for 'verify', maybe we want to see the output?
        # Let's print indented output
        print("-" * 20 + " OUTPUT " + "-" * 20)
        print(result.stdout)
        print("-" * 48)
        return True, result.stdout
    else:
        print(f"❌ FAIL ({duration:.2f}s)")
        print("-" * 20 + " ERROR " + "-" * 20)
        print(result.stdout)
        print(result.stderr)
        print("-" * 48)
        return False, result.stderr

def generate_report(results):
    report_path = "Live_Trading_Readiness_Report.md"
    
    total = len(results)
    passed = sum(1 for r in results if r['passed'])
    failed = total - passed
    
    status_icon = "🟢" if failed == 0 else "🔴"
    status_text = "READY FOR LIVE TRADING" if failed == 0 else "NOT READY - FIX BUGS"
    
    content = f"""# {status_icon} Live Trading Readiness Report
**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Status:** {status_text}

## Summary
| Metric | Value |
| :--- | :--- |
| **Total Test Suites** | {total} |
| **Passed** | {passed} |
| **Failed** | {failed} |
| **Coverage** | Core Logic, Config, Isolation, End-to-End Flow |

## Details

"""
    
    for r in results:
        content += f"### {'✅' if r['passed'] else '❌'} {r['desc']}\n"
        content += f"- **File**: `{r['file']}`\n"
        content += f"- **Result**: {'PASS' if r['passed'] else 'FAIL'}\n"
        if not r['passed']:
            content += "\n**Error Output:**\n```\n" + r['output'][-1000:] + "\n```\n" # Last 1000 chars of error
        content += "\n"
        
    if failed == 0:
        content += """
## 🛡️ Certification
This system has passed all automated verification checks.
- **Configuration**: Verified independent environments for Equal/Champion strategies.
- **Logic**: Verified P0 bug fixes (Shutdown, State Save, Order Verify).
- **Flow**: Verified full end-to-end execution loop via simulation.
- **Safety**: Verified risk control and broker reconciliation tables.

> **Signed**: Automated Verification Agent
"""
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"\n📄 Report generated: {report_path}")
    return failed == 0

def main():
    print("🔍 Starting Comprehensive Live Trading Verification...")
    
    results = []
    all_passed = True
    
    for filepath, desc in TEST_FILES:
        passed, output = run_test_file(filepath, description=desc)
        results.append({
            'file': filepath,
            'desc': desc,
            'passed': passed,
            'output': output
        })
        if not passed:
            all_passed = False
            
    success = generate_report(results)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
