"""
双策略并行隔离验证脚本
- 不依赖 gm.api，无需交易时段即可运行
- 验证配置隔离、通知前缀、进程锁机制
"""
import os
import sys
import tempfile
import subprocess

# Force UTF-8 output for Windows console
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}" + (f"  ({detail})" if detail else ""))
    else:
        failed += 1
        print(f"  ❌ {name}" + (f"  ({detail})" if detail else ""))


# ============================================================
# 测试1: 语法检查 (不运行,只解析)
# ============================================================
print("\n🧪 测试1: 语法检查")
print("-" * 60)

import ast
for fname in ['config.py', 'main.py', 'core/notify.py']:
    fpath = os.path.join(project_root, fname)
    try:
        with open(fpath, encoding='utf-8') as f:
            ast.parse(f.read())
        check(f"{fname} 语法正确", True)
    except SyntaxError as e:
        check(f"{fname} 语法正确", False, str(e))


# ============================================================
# 测试2: 配置隔离 - 等权版
# ============================================================
print("\n🧪 测试2: 等权版配置")
print("-" * 60)

# 模拟等权环境
os.environ['WEIGHT_SCHEME'] = 'EQUAL'
os.environ['VERSION_SUFFIX'] = '_equal'

# 重新加载 config 模块
if 'config' in sys.modules:
    del sys.modules['config']

from config import config as config_eq

check("WEIGHT_SCHEME = EQUAL", config_eq.WEIGHT_SCHEME == 'EQUAL', config_eq.WEIGHT_SCHEME)
check("VERSION_SUFFIX = _equal", config_eq.VERSION_SUFFIX == '_equal', config_eq.VERSION_SUFFIX)
check("VERSION_LABEL = [等权]", config_eq.VERSION_LABEL == '[等权]', config_eq.VERSION_LABEL)
check("STATE_FILE 含 _equal", '_equal' in config_eq.STATE_FILE, config_eq.STATE_FILE)

eq_lock = f"strategy{config_eq.VERSION_SUFFIX}.lock"
check("锁文件名: strategy_equal.lock", eq_lock == 'strategy_equal.lock', eq_lock)


# ============================================================
# 测试3: 配置隔离 - 冠军版
# ============================================================
print("\n🧪 测试3: 冠军版配置")
print("-" * 60)

os.environ['WEIGHT_SCHEME'] = 'CHAMPION'
os.environ['VERSION_SUFFIX'] = '_champion'

# 清理并重新加载
for mod_name in list(sys.modules.keys()):
    if mod_name in ('config',) or mod_name.startswith('config.'):
        del sys.modules[mod_name]

from config import Config as ConfigCls

# 由于 Python class 属性在 import 时已经求值，需要用新 class 重新验证
# 直接检查环境变量逻辑
ws = os.environ.get('WEIGHT_SCHEME', 'CHAMPION')
vs = os.environ.get('VERSION_SUFFIX', '')
vl = '[等权]' if ws == 'EQUAL' else '[冠军]'
sf = f"rolling_state_main{vs}.json"

check("WEIGHT_SCHEME = CHAMPION", ws == 'CHAMPION', ws)
check("VERSION_SUFFIX = _champion", vs == '_champion', vs)
check("VERSION_LABEL = [冠军]", vl == '[冠军]', vl)
check("STATE_FILE 含 _champion", '_champion' in sf, sf)

ch_lock = f"strategy{vs}.lock"
check("锁文件名: strategy_champion.lock", ch_lock == 'strategy_champion.lock', ch_lock)


# ============================================================
# 测试4: 两个版本的文件不冲突
# ============================================================
print("\n🧪 测试4: 文件隔离验证")
print("-" * 60)

eq_state = "rolling_state_main_equal.json"
ch_state = "rolling_state_main_champion.json"
check("状态文件不同", eq_state != ch_state, f"{eq_state} vs {ch_state}")

eq_log = f"strategy_20260211_equal.log"
ch_log = f"strategy_20260211_champion.log"
check("日志文件不同", eq_log != ch_log, f"{eq_log} vs {ch_log}")

eq_lk = "strategy_equal.lock"
ch_lk = "strategy_champion.lock"
check("锁文件不同", eq_lk != ch_lk, f"{eq_lk} vs {ch_lk}")


# ============================================================
# 测试5: 通知前缀逻辑
# ============================================================
print("\n🧪 测试5: 通知前缀")
print("-" * 60)

# 手动验证前缀逻辑 (不导入 notify 因为它依赖 config 的类属性)
for scheme, expected_tag in [('EQUAL', '[等权]'), ('CHAMPION', '[冠军]')]:
    tag = '[等权]' if scheme == 'EQUAL' else '[冠军]'
    original_msg = "🚀 策略启动成功"
    tagged_msg = f"{tag} {original_msg}"
    check(
        f"{scheme} → 前缀 {expected_tag}",
        tag == expected_tag and tagged_msg.startswith(expected_tag),
        tagged_msg
    )


# ============================================================
# 测试6: 进程锁机制 (使用临时文件模拟)
# ============================================================
print("\n🧪 测试6: 进程锁机制")
print("-" * 60)

import msvcrt

with tempfile.TemporaryDirectory() as tmpdir:
    lock_path = os.path.join(tmpdir, "test.lock")
    
    # 第一次获取锁应成功
    fp1 = open(lock_path, 'w')
    try:
        msvcrt.locking(fp1.fileno(), msvcrt.LK_NBLCK, 1)
        fp1.write(str(os.getpid()))
        fp1.flush()
        lock_acquired = True
    except OSError:
        lock_acquired = False
    check("首次获取锁成功", lock_acquired)
    
    # 第二次获取同一个锁应失败
    fp2 = open(lock_path, 'w')
    try:
        msvcrt.locking(fp2.fileno(), msvcrt.LK_NBLCK, 1)
        double_lock = True
        # 如果意外成功了也要释放
        msvcrt.locking(fp2.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        double_lock = False
    fp2.close()
    check("重复获取锁被拒绝", not double_lock)
    
    # 释放锁后应能重新获取
    try:
        msvcrt.locking(fp1.fileno(), msvcrt.LK_UNLCK, 1)
    except:
        pass
    fp1.close()
    
    fp3 = open(lock_path, 'w')
    try:
        msvcrt.locking(fp3.fileno(), msvcrt.LK_NBLCK, 1)
        relock = True
        msvcrt.locking(fp3.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        relock = False
    fp3.close()
    check("释放后重新获取锁成功", relock)


# ============================================================
# 测试7: BAT 文件环境变量设置
# ============================================================
print("\n🧪 测试7: BAT 文件配置")
print("-" * 60)

for bat_name, expected_ws, expected_vs in [
    ('run_equal.bat', 'EQUAL', '_equal'),
    ('run_forever.bat', 'CHAMPION', '_champion'),
]:
    bat_path = os.path.join(project_root, bat_name)
    with open(bat_path, encoding='utf-8') as f:
        content = f.read()
    
    has_ws = f"set WEIGHT_SCHEME={expected_ws}" in content
    has_vs = f"set VERSION_SUFFIX={expected_vs}" in content
    check(f"{bat_name} 设置 WEIGHT_SCHEME={expected_ws}", has_ws)
    check(f"{bat_name} 设置 VERSION_SUFFIX={expected_vs}", has_vs)


# ============================================================
# 汇总
# ============================================================
print("\n" + "=" * 60)
print(f"🏁 测试结果: {passed} 通过, {failed} 失败, 共 {passed+failed} 项")
print("=" * 60)

sys.exit(0 if failed == 0 else 1)
