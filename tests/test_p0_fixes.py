"""
P0修复综合测试脚本
测试所有4个严重风险的修复是否正常工作
"""
import os
import sys
import signal
import time
import json
import tempfile
import pandas as pd
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.portfolio import RollingPortfolioManager, Tranche
from core.strategy import verify_orders
from config import config


class TestResults:
    """测试结果收集器"""
    def __init__(self):
        self.tests = []
        self.passed = 0
        self.failed = 0

    def add_test(self, name, passed, message=""):
        self.tests.append({
            'name': name,
            'passed': passed,
            'message': message
        })
        if passed:
            self.passed += 1
        else:
            self.failed += 1

    def print_summary(self):
        print("\n" + "=" * 70)
        print("测试结果汇总")
        print("=" * 70)

        for test in self.tests:
            status = "✅ PASS" if test['passed'] else "❌ FAIL"
            print(f"{status} | {test['name']}")
            if test['message']:
                print(f"       {test['message']}")

        print("=" * 70)
        print(f"总计: {len(self.tests)} 个测试")
        print(f"通过: {self.passed} 个")
        print(f"失败: {self.failed} 个")
        print(f"成功率: {self.passed/len(self.tests)*100:.1f}%" if self.tests else "0%")
        print("=" * 70)

        return self.failed == 0


results = TestResults()


# ============================================
# P0-1: 优雅退出信号处理器测试
# ============================================

def test_graceful_shutdown():
    """测试优雅退出信号处理器"""
    print("\n🧪 测试 P0-1: 优雅退出信号处理器")
    print("-" * 70)

    try:
        # 导入主模块（会注册信号处理器）
        import main

        # 测试1: 检查信号处理器是否注册
        try:
            # 获取当前的SIGINT处理器
            current_handler = signal.getsignal(signal.SIGINT)
            is_registered = current_handler != signal.SIG_DFL

            results.add_test(
                "信号处理器已注册",
                is_registered,
                f"SIGINT handler: {current_handler.__name__ if hasattr(current_handler, '__name__') else current_handler}"
            )
            print(f"  ✓ 信号处理器注册状态: {current_handler}")
        except Exception as e:
            results.add_test("信号处理器已注册", False, str(e))

        # 测试2: 检查全局变量是否定义
        try:
            has_globals = (
                hasattr(main, '_global_rpm') and
                hasattr(main, '_global_wechat') and
                hasattr(main, '_shutdown_requested')
            )
            results.add_test(
                "全局变量已定义",
                has_globals,
                f"_global_rpm={main._global_rpm}, _global_wechat={main._global_wechat}"
            )
            print(f"  ✓ 全局变量定义完整")
        except Exception as e:
            results.add_test("全局变量已定义", False, str(e))

        # 测试3: 模拟信号处理器调用（不实际退出）
        try:
            # 创建模拟的rpm和wechat对象
            mock_rpm = Mock()
            mock_rpm.initialized = True
            mock_rpm.save_state = Mock()

            mock_wechat = Mock()
            mock_wechat.send_text = Mock()

            # 设置全局变量
            main._global_rpm = mock_rpm
            main._global_wechat = mock_wechat
            main._shutdown_requested = False

            # 模拟信号处理（捕获SystemExit）
            try:
                with patch('sys.exit') as mock_exit:
                    main._graceful_shutdown(signal.SIGINT, None)
            except SystemExit:
                pass

            # 验证save_state被调用
            save_called = mock_rpm.save_state.called
            wechat_called = mock_wechat.send_text.called

            results.add_test(
                "信号处理器调用save_state",
                save_called,
                f"save_state called: {save_called}"
            )
            results.add_test(
                "信号处理器发送微信通知",
                wechat_called,
                f"wechat.send_text called: {wechat_called}"
            )

            print(f"  ✓ 信号处理器逻辑正常")
        except Exception as e:
            results.add_test("信号处理器调用save_state", False, str(e))
            results.add_test("信号处理器发送微信通知", False, str(e))

    except Exception as e:
        print(f"  ❌ 测试失败: {e}")
        results.add_test("优雅退出信号处理器", False, str(e))


# ============================================
# P0-2: save_state() 异常处理测试
# ============================================

def test_save_state_exception():
    """测试save_state()异常重新抛出"""
    print("\n🧪 测试 P0-2: save_state() 异常处理")
    print("-" * 70)

    try:
        # 创建临时目录
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "test_state.json")

            # 测试1: 正常保存
            try:
                rpm = RollingPortfolioManager(state_path=state_file)
                rpm.initialize_tranches(1000000)
                rpm.save_state()

                # 验证文件存在
                file_exists = os.path.exists(state_file)
                results.add_test(
                    "save_state 正常保存",
                    file_exists,
                    f"文件存在: {file_exists}"
                )
                print(f"  ✓ 正常保存成功")
            except Exception as e:
                results.add_test("save_state 正常保存", False, str(e))

            # 测试2: 模拟磁盘满（写入只读文件）
            try:
                # 创建只读文件
                with open(state_file, 'w') as f:
                    f.write('{"test": "readonly"}')
                os.chmod(state_file, 0o444)  # 只读

                rpm2 = RollingPortfolioManager(state_path=state_file)
                rpm2.initialize_tranches(1000000)

                exception_raised = False
                exception_type = None
                try:
                    rpm2.save_state()
                except RuntimeError as e:
                    exception_raised = True
                    exception_type = "RuntimeError"
                except Exception as e:
                    exception_raised = True
                    exception_type = type(e).__name__

                results.add_test(
                    "save_state 失败时抛出异常",
                    exception_raised,
                    f"异常类型: {exception_type}"
                )
                print(f"  ✓ 异常正确抛出: {exception_type}")

                # 恢复权限以便清理
                os.chmod(state_file, 0o644)
            except Exception as e:
                results.add_test("save_state 失败时抛出异常", False, str(e))

            # 测试3: 验证临时文件清理
            try:
                tmp_file = state_file + '.tmp'
                # 检查临时文件是否被清理
                tmp_exists = os.path.exists(tmp_file)
                results.add_test(
                    "临时文件被清理",
                    not tmp_exists,
                    f"临时文件存在: {tmp_exists}"
                )
                print(f"  ✓ 临时文件清理正常")
            except Exception as e:
                results.add_test("临时文件被清理", False, str(e))

    except Exception as e:
        print(f"  ❌ 测试失败: {e}")
        results.add_test("save_state异常处理", False, str(e))


# ============================================
# P0-3: 订单成交验证测试
# ============================================

def test_order_verification():
    """测试订单成交验证"""
    print("\n🧪 测试 P0-3: 订单成交验证")
    print("-" * 70)

    try:
        # 创建模拟context
        mock_context = Mock()
        mock_context.mode = 2  # MODE_LIVE
        mock_wechat = Mock()
        mock_wechat.send_text = Mock()
        mock_context.wechat = mock_wechat

        # 测试1: 全部成交
        try:
            from gm.api import OrderStatus_Filled

            mock_order1 = Mock()
            mock_order1.status = OrderStatus_Filled
            mock_order1.symbol = "SZSE.159915"

            mock_order2 = Mock()
            mock_order2.status = OrderStatus_Filled
            mock_order2.symbol = "SHSE.510300"

            submitted_orders = [
                {'order': mock_order1, 'symbol': 'SZSE.159915', 'side': 'BUY'},
                {'order': mock_order2, 'symbol': 'SHSE.510300', 'side': 'BUY'}
            ]

            # Mock time.sleep to speed up test
            with patch('time.sleep'):
                result = verify_orders(mock_context, submitted_orders, wait_seconds=0)

            all_filled = result['all_filled']
            results.add_test(
                "订单验证 - 全部成交",
                all_filled and len(result['failed_orders']) == 0,
                f"all_filled={all_filled}, failed={len(result['failed_orders'])}"
            )
            print(f"  ✓ 全部成交场景正常")
        except Exception as e:
            results.add_test("订单验证 - 全部成交", False, str(e))

        # 测试2: 部分成交
        try:
            # 使用条件导入，如果不存在则使用整数值
            try:
                from gm.api import OrderStatus_PartFilled
            except ImportError:
                OrderStatus_PartFilled = 2  # 部分成交状态

            mock_order3 = Mock()
            mock_order3.status = OrderStatus_PartFilled
            mock_order3.symbol = "SZSE.159919"
            mock_order3.filled_volume = 500
            mock_order3.volume = 1000

            submitted_orders2 = [
                {'order': mock_order3, 'symbol': 'SZSE.159919', 'side': 'BUY'}
            ]

            # Reset mock
            mock_wechat.send_text.reset_mock()

            with patch('time.sleep'):
                result2 = verify_orders(mock_context, submitted_orders2, wait_seconds=0)

            has_failed = not result2['all_filled'] and len(result2['failed_orders']) == 1
            results.add_test(
                "订单验证 - 部分成交检测",
                has_failed,
                f"all_filled={result2['all_filled']}, failed={len(result2['failed_orders'])}"
            )
            print(f"  ✓ 部分成交检测正常")
        except Exception as e:
            results.add_test("订单验证 - 部分成交检测", False, str(e))

        # 测试3: 微信通知发送
        try:
            wechat_called = mock_wechat.send_text.called
            results.add_test(
                "订单验证 - 微信通知",
                wechat_called,
                f"wechat.send_text called: {wechat_called}"
            )
            print(f"  ✓ 微信通知发送正常")
        except Exception as e:
            results.add_test("订单验证 - 微信通知", False, str(e))

    except Exception as e:
        print(f"  ❌ 测试失败: {e}")
        results.add_test("订单成交验证", False, str(e))


# ============================================
# P0-4: 价格数据缺失容错测试
# ============================================

def test_price_data_tolerance():
    """测试价格数据缺失容错处理"""
    print("\n🧪 测试 P0-4: 价格数据缺失容错")
    print("-" * 70)

    try:
        # 测试1: update_value 处理NaN价格
        try:
            tranche = Tranche(t_id=0, initial_cash=100000)
            tranche.holdings = {'SZSE.159915': 1000}
            tranche.pos_records = {
                'SZSE.159915': {
                    'entry_price': 2.5,
                    'high_price': 2.5,
                    'entry_dt': datetime.now(),
                    'volatility': 0.02
                }
            }

            # 价格包含NaN
            price_map_with_nan = {
                'SZSE.159915': float('nan')
            }

            # 应该使用entry_price作为备选
            tranche.update_value(price_map_with_nan)
            expected_value = 100000 + 1000 * 2.5  # cash + shares * entry_price
            value_correct = abs(tranche.total_value - expected_value) < 1

            results.add_test(
                "update_value 处理NaN价格",
                value_correct,
                f"实际值={tranche.total_value:.2f}, 期望值={expected_value:.2f}"
            )
            print(f"  ✓ update_value NaN处理正常")
        except Exception as e:
            results.add_test("update_value 处理NaN价格", False, str(e))

        # 测试2: update_value 处理缺失价格
        try:
            tranche2 = Tranche(t_id=1, initial_cash=50000)
            tranche2.holdings = {'SHSE.510300': 2000}
            tranche2.pos_records = {
                'SHSE.510300': {
                    'entry_price': 3.8,
                    'high_price': 3.8,
                    'entry_dt': datetime.now(),
                    'volatility': 0.015
                }
            }

            # 价格字典中不包含该标的
            price_map_missing = {}

            tranche2.update_value(price_map_missing)
            expected_value2 = 50000 + 2000 * 3.8
            value_correct2 = abs(tranche2.total_value - expected_value2) < 1

            results.add_test(
                "update_value 处理缺失价格",
                value_correct2,
                f"实际值={tranche2.total_value:.2f}, 期望值={expected_value2:.2f}"
            )
            print(f"  ✓ update_value 缺失价格处理正常")
        except Exception as e:
            results.add_test("update_value 处理缺失价格", False, str(e))

        # 测试3: check_guard 跳过NaN价格
        try:
            tranche3 = Tranche(t_id=2, initial_cash=0)
            tranche3.holdings = {'SZSE.159919': 1500}
            tranche3.pos_records = {
                'SZSE.159919': {
                    'entry_price': 2.0,
                    'high_price': 2.5,
                    'entry_dt': datetime.now(),
                    'volatility': 0.03
                }
            }

            # 价格为NaN，应该跳过止损检查
            price_map_nan = {'SZSE.159919': float('nan')}
            to_sell = tranche3.check_guard(price_map_nan, datetime.now())

            no_sell = len(to_sell) == 0
            results.add_test(
                "check_guard 跳过NaN价格",
                no_sell,
                f"to_sell={to_sell}"
            )
            print(f"  ✓ check_guard NaN跳过正常")
        except Exception as e:
            results.add_test("check_guard 跳过NaN价格", False, str(e))

        # 测试4: check_guard 跳过缺失价格
        try:
            price_map_missing2 = {}
            to_sell2 = tranche3.check_guard(price_map_missing2, datetime.now())

            no_sell2 = len(to_sell2) == 0
            results.add_test(
                "check_guard 跳过缺失价格",
                no_sell2,
                f"to_sell={to_sell2}"
            )
            print(f"  ✓ check_guard 缺失价格跳过正常")
        except Exception as e:
            results.add_test("check_guard 跳过缺失价格", False, str(e))

    except Exception as e:
        print(f"  ❌ 测试失败: {e}")
        results.add_test("价格数据缺失容错", False, str(e))


# ============================================
# 主测试流程
# ============================================

def main():
    """运行所有测试"""
    print("=" * 70)
    print("P0修复综合测试")
    print("=" * 70)
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 运行所有测试
    test_graceful_shutdown()
    test_save_state_exception()
    test_order_verification()
    test_price_data_tolerance()

    # 打印汇总
    all_passed = results.print_summary()

    # 返回退出码
    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
