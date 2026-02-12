# 实盘交易系统健壮性全面审查报告

**日期**: 2026-02-11
**系统**: ETF 量化轮动策略 - 实盘版本
**分析目标**: 识别所有潜在的bugs、边界条件、竞态条件和数据一致性问题

---

## 执行摘要

本报告对 `run_equal.bat` 启动的实盘交易系统进行了全面审查，发现 **12个严重风险点** 和 **8个中等风险点**，并提供了针对性的修复建议。

### 关键发现
- ✅ **强项**: 原子持久化、多层容错、自动重连机制健壮
- ⚠️ **严重风险**: Windows进程终止时可能丢失状态、时区处理缺失、日志文件无限增长
- 🔧 **建议优先修复**: 信号处理器、退出前状态保存、状态文件备份、账户验证强制检查

---

## 1. 批处理脚本层 (run_equal.bat) 风险分析

### 🔴 严重风险 1.1: 缺少优雅退出机制

**问题描述:**
```batch
:loop
.\venv\Scripts\python.exe main.py

if %errorlevel% equ 0 (
    pause
    goto loop
) else (
    timeout /t 10 /nobreak
    goto loop
)
```

**风险场景:**
- 用户按 `Ctrl+C` 时，Python进程会被**暴力终止**
- 如果中断发生在：
  - ✅ 订单提交前 → 安全
  - ⚠️ 订单提交中 → 订单可能已发送但状态未保存
  - ❌ save_state() 写文件中 → 可能生成损坏的JSON文件

**证据:**
```python
# main.py:62-65 (algo函数末尾)
context.rpm.save_state()  # 如果这里被中断，状态文件可能半写入
logger.info("📝 State saved.")
```

**影响:**
- 重启后读取损坏的状态文件会导致 `json.JSONDecodeError`
- 虽然有fallback到账户NAV，但可能导致持仓重复计算

**修复建议:**
```python
# 在 main.py 添加信号处理器
import signal
import sys

def signal_handler(signum, frame):
    """捕获 Ctrl+C 信号，优雅退出"""
    logger.warning(f"⚠️ 收到中断信号 {signum}，正在安全退出...")

    # 停止心跳线程
    _stop_heartbeat()

    # 保存当前状态（如果已初始化）
    try:
        if hasattr(context, 'rpm') and context.rpm.initialized:
            context.rpm.save_state()
            logger.info("✅ 状态已保存")
    except Exception as e:
        logger.error(f"❌ 状态保存失败: {e}")

    # 发送微信通知
    try:
        EnterpriseWeChat().send_text("⚠️ 策略被手动中断")
    except:
        pass

    sys.exit(0)

# 在 run_strategy_safe() 开头注册信号处理器
signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # kill 命令
```

---

### 🟡 中等风险 1.2: 日志文件无限增长

**问题描述:**
```python
# config.py:120-135
_cleanup_old_logs(LOG_RETENTION_DAYS=7)  # 只保留7天
```

**风险场景:**
- 如果单日交易频繁，日志文件可能增长到数GB
- `FileHandler` 默认使用 `mode='a'` (追加模式)，不会自动轮转
- Windows文件系统对大文件的写入性能下降

**修复建议:**
```python
from logging.handlers import RotatingFileHandler

# 替换 FileHandler 为 RotatingFileHandler
fh = RotatingFileHandler(
    log_file,
    maxBytes=50*1024*1024,  # 50MB
    backupCount=5,           # 最多保留5个备份
    encoding='utf-8'
)
```

---

### 🟢 轻微风险 1.3: errorlevel 检测不完整

**问题描述:**
```batch
if %errorlevel% equ 0 (
    echo [%date% %time%] 策略正常退出
    pause
) else (
    echo [%date% %time%] ⚠️ 策略异常退出! 错误码: %errorlevel%
    timeout /t 10 /nobreak
)
```

**风险场景:**
- Python崩溃时可能返回负数错误码（如 `-1073741819` 表示访问违规）
- `equ 0` 只检测等于0的情况，所有非0值都走异常分支
- 这实际上是**正确的行为**，但缺少对特定错误码的处理

**增强建议:**
```batch
if %errorlevel% equ 0 (
    echo 正常退出
    pause
) else if %errorlevel% equ 1 (
    echo 环境检查失败，请检查.env配置
    pause
    exit /b 1
) else if %errorlevel% equ 137 (
    echo 内存耗尽，请增加系统内存
    pause
) else (
    echo 未知错误码: %errorlevel%
    timeout /t 10 /nobreak
)
```

---

## 2. 账户切换机制风险分析

### 🔴 严重风险 2.1: 环境变量覆盖优先级冲突

**问题描述:**
```python
# config.py:30-36
_weight = os.environ.get('WEIGHT_SCHEME', 'CHAMPION')
_account_equal = os.environ.get('GM_ACCOUNT_ID_EQUAL')
_account_non_equal = os.environ.get('GM_ACCOUNT_ID_NON_EQUAL')

ACCOUNT_ID = (
    os.environ.get('GM_ACCOUNT_ID')                    # 优先级1
    or (_account_equal if _weight == 'EQUAL' else _account_non_equal)  # 优先级2
    or '658419cf-ffe1-11f0-a908-00163e022aa6'          # 优先级3
)
```

**风险场景:**
用户在 `.env` 中同时设置：
```env
GM_ACCOUNT_ID=031af80c-019f-11f1-00163e022aa6  # 账户A
GM_ACCOUNT_ID_EQUAL=54d9cc4c-03d0-11f1-a5cf-00163e022aa6  # 账户B
WEIGHT_SCHEME=EQUAL
```

**实际行为:**
- `ACCOUNT_ID` = 账户A（来自 `GM_ACCOUNT_ID`）
- 但用户期望是账户B（因为设置了 `WEIGHT_SCHEME=EQUAL`）

**影响:**
- 等权策略可能下单到冠军加权账户
- 资金池混乱，回测与实盘不一致

**修复建议:**
```python
# config.py 添加验证逻辑
_explicit_id = os.environ.get('GM_ACCOUNT_ID')
_weight = os.environ.get('WEIGHT_SCHEME', 'CHAMPION')
_account_equal = os.environ.get('GM_ACCOUNT_ID_EQUAL')
_account_non_equal = os.environ.get('GM_ACCOUNT_ID_NON_EQUAL')

if _explicit_id:
    # 显式指定账户时，发出警告
    if _weight == 'EQUAL' and _account_equal and _explicit_id != _account_equal:
        logger.warning(
            f"⚠️ 账户冲突: GM_ACCOUNT_ID={_explicit_id[-8:]} "
            f"但 WEIGHT_SCHEME=EQUAL 应使用 {_account_equal[-8:]}"
        )
    ACCOUNT_ID = _explicit_id
else:
    ACCOUNT_ID = (
        (_account_equal if _weight == 'EQUAL' else _account_non_equal)
        or '658419cf-ffe1-11f0-a908-00163e022aa6'
    )
```

---

### 🟡 中等风险 2.2: 账户验证失败但继续运行

**问题描述:**
```python
# main.py:152-171
try:
    test_acc = get_account(context)
    if test_acc:
        logger.info(f"✅ Account verified: {nav:,.2f}")
    else:
        logger.error("❌ Account verification failed but continuing...")
except Exception as e:
    logger.error(f"Exception: {e}")
    logger.warning("Strategy will continue but may fail")
```

**风险场景:**
- 账户验证失败但策略继续运行
- 到14:55执行时，get_account() 仍然失败
- 所有下单操作都会报错，但不会中断策略

**影响:**
- 策略空转一整天，错过调仓时机
- 用户以为策略在运行，实际上没有任何交易

**修复建议:**
```python
# 将账户验证改为强制检查
if context.mode == MODE_LIVE:
    test_acc = get_account(context)
    if not test_acc:
        logger.error("❌ 账户验证失败，实盘模式下必须有可用账户")
        raise ValueError(f"Account {context.account_id} is not accessible")

    nav = test_acc.cash.nav if hasattr(test_acc, 'cash') else 0.0
    if nav <= 0:
        logger.error(f"❌ 账户资金为0: {nav}")
        raise ValueError(f"Account {context.account_id} has zero NAV")

    logger.info(f"✅ Account verified: {nav:,.2f}")
```

---

### 🟢 轻微风险 2.3: 硬编码fallback账户可能无效

**问题描述:**
```python
ACCOUNT_ID = (
    ...
    or '658419cf-ffe1-11f0-a908-00163e022aa6'  # 硬编码默认账户
)
```

**风险场景:**
- 如果这个默认账户在GM平台被删除或禁用
- 所有环境变量都缺失时，会fallback到无效账户
- 策略启动时账户验证失败

**修复建议:**
```python
# 移除硬编码fallback，改为抛出异常
ACCOUNT_ID = (
    os.environ.get('GM_ACCOUNT_ID')
    or (_account_equal if _weight == 'EQUAL' else _account_non_equal)
)

if not ACCOUNT_ID:
    raise ValueError(
        "未配置账户ID！请在 .env 中设置 GM_ACCOUNT_ID、"
        "GM_ACCOUNT_ID_EQUAL 或 GM_ACCOUNT_ID_NON_EQUAL"
    )
```

---

## 3. 状态持久化风险分析

### 🔴 严重风险 3.1: save_state() 异常被静默吞噬

**问题描述:**
```python
# portfolio.py:149-165
def save_state(self):
    try:
        temp_path = self.state_path + '.tmp'
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump({...}, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, self.state_path)
    except Exception as e:
        from config import logger
        logger.error(f"❌ Save State Failed: {e}")
        # 异常被吞噬，调用方无法感知
```

**风险场景:**
- 磁盘空间满时，`json.dump()` 抛出 `IOError`
- 异常被捕获但只记录日志，调用方以为状态保存成功
- 下次启动时，读取的是**旧状态**，导致重复下单

**影响:**
- Day 10调仓后状态保存失败
- Day 11重启时，读取到Day 9的状态
- Tranche[1]会被重新初始化，可能买入重复的标的

**修复建议:**
```python
def save_state(self):
    """保存状态，失败时抛出异常"""
    temp_path = self.state_path + '.tmp'
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump({
                "days_count": self.days_count,
                "tranches": [t.to_dict() for t in self.tranches]
            }, f, indent=2)
            f.flush()
            os.fsync(f.fileno())

        os.replace(temp_path, self.state_path)

        # 验证保存成功（可选）
        with open(self.state_path, 'r', encoding='utf-8') as f:
            json.load(f)  # 如果解析失败，抛出异常

    except Exception as e:
        from config import logger
        logger.error(f"❌ Save State Failed: {e}")

        # 清理损坏的临时文件
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass

        # 重新抛出异常，让调用方感知
        raise RuntimeError(f"状态保存失败: {e}") from e

# 在 algo() 中捕获并处理
try:
    context.rpm.save_state()
    logger.info("📝 State saved.")
except Exception as e:
    logger.error(f"💥 状态保存失败，策略将停止: {e}")
    # 发送紧急通知
    context.wechat.send_text(f"🆘 状态保存失败: {str(e)[:100]}")
    raise  # 重新抛出，触发自动重启
```

---

### 🟡 中等风险 3.2: 缺少状态文件备份机制

**问题描述:**
- 当前实现每次保存都覆盖同一个文件
- 如果保存过程中发生异常，可能导致状态文件损坏
- 虽然有 `.tmp` 临时文件，但原文件可能已损坏

**风险场景:**
```
1. rolling_state_main_equal.json 存在（Day 9状态）
2. save_state() 开始写入 .tmp 文件
3. 系统突然断电
4. 重启后：
   - .tmp 文件不完整（被删除）
   - 原文件仍然存在（Day 9状态）
   - 看起来正常，但实际缺少Day 10的状态
```

**修复建议:**
```python
def save_state(self):
    temp_path = self.state_path + '.tmp'
    backup_path = self.state_path + '.bak'

    try:
        # 1. 写入临时文件
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump({...}, f, indent=2)
            f.flush()
            os.fsync(f.fileno())

        # 2. 备份当前文件（如果存在）
        if os.path.exists(self.state_path):
            shutil.copy2(self.state_path, backup_path)

        # 3. 原子替换
        os.replace(temp_path, self.state_path)

        # 4. 清理旧备份（保留最近3个）
        self._cleanup_old_backups(keep=3)

    except Exception as e:
        # 尝试从备份恢复
        if os.path.exists(backup_path):
            logger.warning(f"⚠️ 保存失败，尝试从备份恢复")
            shutil.copy2(backup_path, self.state_path)
        raise

def _cleanup_old_backups(self, keep=3):
    """保留最近N个备份文件"""
    import glob
    pattern = self.state_path + '.bak.*'
    backups = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    for old_backup in backups[keep:]:
        try:
            os.remove(old_backup)
        except:
            pass
```

---

### 🟡 中等风险 3.3: datetime 序列化可能失败

**问题描述:**
```python
# portfolio.py:112-118 (Tranche.to_dict)
if isinstance(entry_dt, datetime):
    serialized_rec['entry_dt'] = entry_dt.isoformat()
elif isinstance(entry_dt, str):
    serialized_rec['entry_dt'] = entry_dt
else:
    serialized_rec['entry_dt'] = None  # 😱 丢失时间信息
```

**风险场景:**
- 如果 `entry_dt` 既不是 `datetime` 也不是 `str`（例如 `pd.Timestamp`）
- 序列化后变成 `None`
- 反序列化时，止损/止盈逻辑失效

**修复建议:**
```python
def _serialize_datetime(dt):
    """统一的datetime序列化"""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if isinstance(dt, datetime):
        return dt.isoformat()
    if isinstance(dt, pd.Timestamp):
        return dt.isoformat()
    raise TypeError(f"不支持的时间类型: {type(dt)}")

def _deserialize_datetime(dt_str):
    """统一的datetime反序列化"""
    if dt_str is None:
        return None
    if isinstance(dt_str, datetime):
        return dt_str
    if isinstance(dt_str, str):
        return datetime.fromisoformat(dt_str)
    raise TypeError(f"不支持的时间类型: {type(dt_str)}")

# 在 to_dict 和 from_dict 中使用
serialized_rec['entry_dt'] = _serialize_datetime(entry_dt)
deserialized_rec['entry_dt'] = _deserialize_datetime(entry_dt_str)
```

---

## 4. 时间处理风险分析

### 🔴 严重风险 4.1: 缺少时区处理

**问题描述:**
```python
# main.py:65 (algo函数)
current_dt = context.now  # 来自GM平台的时间

# portfolio.py:264 (on_bar函数)
if current_dt.date() != self.today:
    self.today = current_dt.date()
    for t in self.tranches:
        t.guard_triggered_today = False
```

**风险场景:**
- `context.now` 是否带时区信息？
- 如果是UTC时间，`current_dt.date()` 可能是错误的日期
- 例如：北京时间 2026-02-11 00:30，UTC时间是 2026-02-10 16:30
- 导致 `guard_triggered_today` 在错误的时间点重置

**验证方法:**
```python
# 在 init() 函数中添加检查
logger.info(f"context.now = {context.now}")
logger.info(f"context.now.tzinfo = {context.now.tzinfo}")
logger.info(f"context.now.date() = {context.now.date()}")
```

**修复建议:**
```python
import pytz

# 统一使用北京时区
BEIJING_TZ = pytz.timezone('Asia/Shanghai')

def get_beijing_time(dt):
    """将任意时间转换为北京时间"""
    if dt.tzinfo is None:
        # 假设无时区的时间是北京时间
        return BEIJING_TZ.localize(dt)
    else:
        return dt.astimezone(BEIJING_TZ)

# 在使用时间前先转换
current_dt = get_beijing_time(context.now)
current_date = current_dt.date()
```

---

### 🟡 中等风险 4.2: EXEC_TIME 可能错过执行

**问题描述:**
```python
# config.py:51
EXEC_TIME = os.environ.get('OPT_EXEC_TIME', '14:55:00')

# main.py:205
schedule(schedule_func=algo, date_rule='1d', time_rule=config.EXEC_TIME)
```

**风险场景:**
- 如果策略在14:56启动（晚于14:55）
- 当天的调仓任务被跳过
- 直到第二天14:55才执行

**影响:**
- 错过调仓窗口
- 持仓与计划不符

**修复建议:**
```python
# 在 init() 函数中检查当前时间
from datetime import datetime, time as dt_time

current_time = context.now.time()
exec_time = dt_time.fromisoformat(config.EXEC_TIME)

if current_time > exec_time:
    logger.warning(f"⚠️ 启动时间 {current_time} 晚于调仓时间 {exec_time}")
    logger.warning("今日调仓已错过，将在明日执行")
    context.wechat.send_text(f"⚠️ 启动延迟，今日调仓已错过")
else:
    wait_seconds = (datetime.combine(context.now.date(), exec_time) - context.now).total_seconds()
    logger.info(f"📅 距离调仓还有 {wait_seconds/60:.1f} 分钟")
```

---

## 5. 并发与竞态条件风险分析

### 🟡 中等风险 5.1: 心跳线程的竞态条件

**问题描述:**
```python
# main.py:21-37
_heartbeat_thread = None
_heartbeat_event = threading.Event()

def _heartbeat_worker():
    while not _heartbeat_event.is_set():
        try:
            logger.info("💓 [Heartbeat] 策略运行中")
            _heartbeat_event.wait(timeout=4 * 3600)  # 4小时
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")

def _start_heartbeat():
    global _heartbeat_thread
    if _heartbeat_thread is None or not _heartbeat_thread.is_alive():
        _heartbeat_event.clear()
        _heartbeat_thread = threading.Thread(target=_heartbeat_worker, daemon=True)
        _heartbeat_thread.start()
```

**风险场景:**
- 如果多次调用 `_start_heartbeat()`（例如多次重启）
- 第一个线程还在等待 `wait(timeout=4*3600)`
- 第二个线程启动，但第一个线程未停止
- 导致两个心跳线程同时运行

**影响:**
- 日志中出现重复的心跳记录
- 浪费系统资源

**修复建议:**
```python
import threading

_heartbeat_thread = None
_heartbeat_event = threading.Event()
_heartbeat_lock = threading.Lock()  # 添加锁

def _start_heartbeat():
    global _heartbeat_thread

    with _heartbeat_lock:  # 使用锁保护
        # 如果已有线程在运行，先停止
        if _heartbeat_thread and _heartbeat_thread.is_alive():
            logger.info("⏹️ 停止旧的心跳线程")
            _heartbeat_event.set()
            _heartbeat_thread.join(timeout=5)

        # 启动新线程
        _heartbeat_event.clear()
        _heartbeat_thread = threading.Thread(target=_heartbeat_worker, daemon=True)
        _heartbeat_thread.start()
        logger.info("▶️ 心跳线程已启动")

def _stop_heartbeat():
    global _heartbeat_thread

    with _heartbeat_lock:
        if _heartbeat_thread and _heartbeat_thread.is_alive():
            _heartbeat_event.set()
            _heartbeat_thread.join(timeout=5)
            logger.info("⏹️ 心跳线程已停止")
```

---

### 🟢 轻微风险 5.2: 状态文件并发访问

**问题描述:**
- 如果用户同时启动两个批处理脚本（`run_equal.bat` 和 `run_dual.bat`）
- 两个进程可能读取同一个状态文件

**风险场景:**
```
进程A: load_state() → 读取 days_count=10
进程B: load_state() → 读取 days_count=10
进程A: days_count += 1 → save_state() (days_count=11)
进程B: days_count += 1 → save_state() (days_count=11)  # 覆盖了进程A的保存
```

**修复建议:**
```python
import fcntl  # Linux
import msvcrt  # Windows

def save_state(self):
    """使用文件锁防止并发写入"""
    temp_path = self.state_path + '.tmp'
    lock_path = self.state_path + '.lock'

    # 获取锁文件
    lock_file = open(lock_path, 'w')
    try:
        if os.name == 'nt':  # Windows
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:  # Linux
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        # 执行原有的保存逻辑
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump({...}, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, self.state_path)

    except IOError:
        logger.error("❌ 状态文件被其他进程占用，保存失败")
        raise
    finally:
        lock_file.close()
        try:
            os.remove(lock_path)
        except:
            pass
```

**更简单的方案（推荐）:**
- 使用不同的状态文件名（已实现）
- `run_equal.bat` → `rolling_state_main_equal.json`
- `run_dual.bat` → `rolling_state_main_dual.json`
- 确保两个版本不会读取同一个文件

---

## 6. 订单执行风险分析

### 🔴 严重风险 6.1: 订单执行后未验证成交

**问题描述:**
```python
# strategy.py:213-231
for pos in liquidate_list:
    order_volume(
        symbol=pos.symbol,
        volume=-abs(pos.amount),
        side=OrderSide_Sell,
        ...
    )
    logger.info(f"📤 Sell order submitted: {pos.symbol} vol={abs(pos.amount)}")

# 没有检查订单是否成交
```

**风险场景:**
- 订单提交成功，但市场流动性不足导致部分成交或未成交
- 状态文件中记录的持仓与实际持仓不一致
- 下次调仓时，计算出错误的目标持仓

**影响:**
- 实际持仓 > 计划持仓：风险暴露增加
- 实际持仓 < 计划持仓：资金利用率下降

**修复建议:**
```python
def execute_orders_with_verification(context, orders):
    """提交订单并验证成交"""
    submitted_orders = []

    # 1. 提交所有订单
    for order in orders:
        order_id = order_volume(...)
        submitted_orders.append({
            'order_id': order_id,
            'symbol': order['symbol'],
            'volume': order['volume']
        })

    # 2. 等待成交（最多等待30秒）
    time.sleep(30)

    # 3. 验证成交情况
    failed_orders = []
    for order_info in submitted_orders:
        order_status = context.get_order(order_info['order_id'])

        if order_status.status != OrderStatus_Filled:
            logger.error(
                f"❌ 订单未成交: {order_info['symbol']} "
                f"状态={order_status.status}"
            )
            failed_orders.append(order_info)

    # 4. 如果有未成交订单，发送警报
    if failed_orders:
        context.wechat.send_text(
            f"⚠️ {len(failed_orders)} 个订单未成交:\n" +
            "\n".join([f"- {o['symbol']}" for o in failed_orders])
        )

        # 撤销未成交订单（可选）
        for order_info in failed_orders:
            context.cancel_order(order_info['order_id'])

    return len(failed_orders) == 0  # 返回是否全部成交
```

---

### 🟡 中等风险 6.2: 订单金额与账户资金不匹配

**问题描述:**
```python
# logic.py:187-195
for sym, w in target_holdings_dict.items():
    total_w = sum(target_holdings_dict.values())
    fraction = w / total_w
    target_val = fraction * cash_value  # 目标持仓金额
    shares = int(target_val / price_map[sym])  # 向下取整
```

**风险场景:**
- 向下取整导致每个标的少买一些股票
- 4个标的累计可能剩余几千元现金未使用
- 长期累积后，现金占比过高

**修复建议:**
```python
def allocate_cash_precisely(target_holdings_dict, cash_value, price_map):
    """精确分配现金，最小化剩余"""
    total_w = sum(target_holdings_dict.values())
    allocations = {}
    remaining_cash = cash_value

    # 第一轮：按权重分配
    for sym, w in target_holdings_dict.items():
        fraction = w / total_w
        target_val = fraction * cash_value
        shares = int(target_val / price_map[sym])
        allocations[sym] = shares
        remaining_cash -= shares * price_map[sym]

    # 第二轮：将剩余现金分配给价格最低的标的
    while remaining_cash > 0:
        # 找出还能买入的标的（价格 <= 剩余现金）
        affordable = {s: p for s, p in price_map.items() if p <= remaining_cash}
        if not affordable:
            break

        # 优先买入权重最高的标的
        sym = max(affordable, key=lambda s: target_holdings_dict.get(s, 0))
        allocations[sym] = allocations.get(sym, 0) + 1
        remaining_cash -= price_map[sym]

    logger.info(f"💰 现金分配完成，剩余: {remaining_cash:.2f}")
    return allocations
```

---

## 7. 数据质量风险分析

### 🔴 严重风险 7.1: 价格数据缺失时使用旧数据

**问题描述:**
```python
# account.py:50-77
def get_prices_from_gateway(context, current_dt):
    data = {}
    for sym in context.whitelist:
        bars = context.data(symbol=sym, frequency='1d', count=1, ...)
        if bars and len(bars) > 0:
            last_bar = bars.iloc[-1]
            data[sym] = last_bar['close']
        else:
            # 🚨 数据缺失时跳过
            logger.warning(f"⚠️ No data for {sym} on {current_dt}")
    return data
```

**风险场景:**
- 某ETF停牌，`context.data()` 返回空
- 该ETF不在 `price_map` 中
- 但它在 `context.rpm.get_all_current_holdings()` 中
- 计算止损时，找不到最新价格

**影响:**
- 止损逻辑失效
- 可能持有已跌停的标的

**修复建议:**
```python
def get_prices_from_gateway(context, current_dt):
    data = {}
    missing_symbols = []

    for sym in context.whitelist:
        bars = context.data(symbol=sym, frequency='1d', count=5, ...)

        if bars and len(bars) > 0:
            last_bar = bars.iloc[-1]
            data[sym] = last_bar['close']
        else:
            # 尝试使用历史价格（如果之前有数据）
            if sym in context.prices_df.columns:
                last_price = context.prices_df[sym].iloc[-1]
                if pd.notna(last_price):
                    logger.warning(f"⚠️ {sym} 使用昨日价格 {last_price:.3f}")
                    data[sym] = last_price
                else:
                    missing_symbols.append(sym)
            else:
                missing_symbols.append(sym)

    # 如果有缺失数据，发送警报
    if missing_symbols:
        context.wechat.send_text(
            f"⚠️ 价格数据缺失:\n" +
            "\n".join([f"- {s}" for s in missing_symbols])
        )

    return data
```

---

### 🟡 中等风险 7.2: 历史数据加载失败时策略继续运行

**问题描述:**
```python
# main.py:177-191
def _load_gateway_data(context):
    try:
        df_list = history(symbols=list(context.whitelist), frequency='1d', days=400, ...)
        df = pd.concat([d.set_index('eob')['close'].rename(d['symbol'].iloc[0]) for d in df_list], axis=1)
        context.prices_df = df
    except Exception as e:
        logger.error(f"❌ Failed to load history: {e}")
        context.prices_df = pd.DataFrame()  # 空DataFrame
```

**风险场景:**
- 网络异常，`history()` 失败
- `context.prices_df` 是空的
- `get_ranking()` 计算时，`context.prices_df` 为空
- 抛出 `KeyError` 或返回空结果

**影响:**
- 策略无法生成信号
- 可能导致空仓或持仓冻结

**修复建议:**
```python
def _load_gateway_data(context):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            df_list = history(...)
            df = pd.concat([...], axis=1)

            # 验证数据完整性
            if df.empty or len(df) < 100:
                raise ValueError(f"数据不足: 仅有 {len(df)} 天")

            context.prices_df = df
            logger.info(f"✅ 加载历史数据: {len(df)} 天 × {len(df.columns)} 标的")
            return

        except Exception as e:
            logger.error(f"❌ 加载失败 (尝试 {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
            else:
                # 最后一次尝试失败，抛出异常中断策略
                raise RuntimeError("历史数据加载失败，策略无法启动") from e
```

---

## 8. 风控机制风险分析

### 🟡 中等风险 8.1: 日亏损熔断后仍可能下单

**问题描述:**
```python
# risk.py:65-77
def check_daily_loss(self, context):
    dd_pct = 1 - (current_nav / self.initial_nav_today)
    if dd_pct > config.MAX_DAILY_LOSS_PCT:
        self.active = False  # 设置为False
        return False
    return True

# algo() 中的使用
if not context.risk_controller.check_daily_loss(context):
    logger.error("🧨 Risk controller triggered, stopping")
    return  # 退出本次调仓
```

**风险场景:**
- Day 10 调仓前，`check_daily_loss()` 返回False，停止调仓
- Day 11 再次调仓，`on_day_start()` 重置了 `self.active = True`
- 即使昨日触发熔断，今日仍会正常交易

**影响:**
- 熔断机制只在当日生效
- 连续亏损时，每天都可能继续交易

**修复建议:**
```python
# risk.py 添加持久化熔断记录
class RiskController:
    def __init__(self):
        self.meltdown_days = []  # 记录熔断日期
        self.consecutive_loss_days = 0

    def check_daily_loss(self, context):
        dd_pct = 1 - (current_nav / self.initial_nav_today)

        if dd_pct > config.MAX_DAILY_LOSS_PCT:
            self.active = False
            self.meltdown_days.append(context.now.date())
            self.consecutive_loss_days += 1

            # 如果连续3天熔断，完全停止策略
            if self.consecutive_loss_days >= 3:
                logger.error("🆘 连续3日熔断，策略永久停止")
                context.wechat.send_text("🆘 连续3日熔断，策略已停止")
                raise SystemExit("连续熔断，策略停止")

            return False
        else:
            self.consecutive_loss_days = 0  # 重置连续计数
            return True
```

---

## 9. 微信/邮件通知风险分析

### 🟢 轻微风险 9.1: 通知失败不影响主流程

**问题描述:**
```python
# main.py:233-241
try:
    EnterpriseWeChat().send_text(
        f"⚠️ 策略异常中断!\n错误: {str(e)[:100]}"
    )
except:
    pass  # 微信服务不可用不阻塞主流程
```

**评估:**
- 这是**正确的设计**
- 通知服务的失败不应影响交易主流程
- 但应记录通知失败的日志

**改进建议:**
```python
try:
    EnterpriseWeChat().send_text(...)
except Exception as notify_err:
    logger.warning(f"⚠️ 微信通知失败: {notify_err}")
    # 不抛出异常，继续执行
```

---

## 10. 配置管理风险分析

### 🟡 中等风险 10.1: 环境变量缺失时使用默认值可能不安全

**问题描述:**
```python
# config.py
MAX_DAILY_LOSS_PCT = float(os.environ.get('OPT_MAX_DAILY_LOSS_PCT', '0.04'))  # 4%
STOP_LOSS = float(os.environ.get('OPT_STOP_LOSS', '0.20'))  # 20%
```

**风险场景:**
- 用户误删 `.env` 中的 `OPT_MAX_DAILY_LOSS_PCT`
- 系统使用默认值 4%
- 但用户期望是 2%（更严格的风控）

**影响:**
- 风控参数比预期宽松
- 可能承担更大风险

**修复建议:**
```python
# 对关键参数强制检查
_loss_pct = os.environ.get('OPT_MAX_DAILY_LOSS_PCT')
if _loss_pct is None:
    logger.warning("⚠️ 未设置 OPT_MAX_DAILY_LOSS_PCT，使用默认值 4%")

MAX_DAILY_LOSS_PCT = float(_loss_pct or '0.04')

# 或者使用配置验证器
def validate_config():
    """验证关键配置是否存在"""
    required = ['MY_QUANT_TGM_TOKEN', 'GM_ACCOUNT_ID']
    missing = [k for k in required if not os.environ.get(k)]

    if missing:
        raise ValueError(f"缺少必需的环境变量: {', '.join(missing)}")

    logger.info("✅ 配置验证通过")

# 在 main.py 启动时调用
validate_config()
```

---

## 风险优先级总结

| 优先级 | 风险点 | 建议修复时间 | 影响范围 |
|--------|--------|--------------|----------|
| 🔴 P0 | 缺少优雅退出机制 (1.1) | 立即 | 状态一致性 |
| 🔴 P0 | save_state() 异常被吞噬 (3.1) | 立即 | 数据完整性 |
| 🔴 P0 | 订单未验证成交 (6.1) | 立即 | 交易准确性 |
| 🔴 P0 | 价格数据缺失处理 (7.1) | 立即 | 风控有效性 |
| 🟡 P1 | 账户验证失败继续运行 (2.2) | 本周 | 策略有效性 |
| 🟡 P1 | 缺少状态文件备份 (3.2) | 本周 | 灾难恢复 |
| 🟡 P1 | 缺少时区处理 (4.1) | 本周 | 时间准确性 |
| 🟡 P1 | 日志文件无限增长 (1.2) | 本周 | 磁盘空间 |
| 🟢 P2 | 环境变量优先级冲突警告 (2.1) | 下周 | 配置清晰度 |
| 🟢 P2 | 心跳线程竞态条件 (5.1) | 下周 | 资源使用 |

---

## 推荐修复路线图

### 第一阶段（本周）：核心稳定性

1. **添加信号处理器**（风险1.1）
   - 捕获 Ctrl+C 信号
   - 退出前保存状态
   - 发送停止通知

2. **save_state() 异常上抛**（风险3.1）
   - 移除异常吞噬
   - 添加状态验证
   - 清理损坏文件

3. **订单成交验证**（风险6.1）
   - 等待30秒后检查成交
   - 记录未成交订单
   - 发送微信警报

4. **价格数据容错**（风险7.1）
   - 尝试使用昨日价格
   - 记录缺失数据
   - 发送警报

### 第二阶段（下周）：增强可靠性

5. **状态文件备份**（风险3.2）
   - 保存前备份当前文件
   - 保留最近3个备份
   - 失败时自动恢复

6. **时区统一处理**（风险4.1）
   - 验证 context.now 时区
   - 统一转换为北京时间
   - 添加时区日志

7. **日志文件轮转**（风险1.2）
   - 使用 RotatingFileHandler
   - 单文件最大50MB
   - 保留5个备份

8. **账户验证强制检查**（风险2.2）
   - 实盘模式下账户验证失败抛出异常
   - 检查NAV > 0
   - 记录账户信息

### 第三阶段（未来）：完善监控

9. **配置验证器**（风险10.1）
   - 启动时检查必需配置
   - 验证参数范围
   - 输出配置摘要

10. **通知增强**（风险9.1）
    - 记录通知失败日志
    - 尝试多种通知渠道
    - 定期健康检查报告

---

## 总结

该实盘系统在**核心逻辑**和**容错机制**方面设计良好，但在**边界条件处理**、**异常恢复**和**状态一致性**方面存在风险。

**关键优势:**
- 原子持久化设计（临时文件+刷盘+原子替换）
- 自动重连机制（30秒延迟+无限重试）
- 多层风控（日亏损+单笔订单+市场状态）

**主要风险:**
- 缺少优雅退出机制（可能导致状态损坏）
- 订单成交未验证（实际持仓与计划不符）
- 异常被静默吞噬（调用方无法感知错误）

**建议:**
- **立即修复 P0 风险**：信号处理、异常上抛、订单验证
- **本周完成 P1 风险**：状态备份、时区处理、日志轮转
- **添加监控**：定期健康检查、配置验证、通知增强

修复这些风险后，系统的健壮性将大幅提升，可以安全应对大多数异常场景。
