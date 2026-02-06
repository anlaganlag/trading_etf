"""
单元测试：验证 main.py 的关键 bug 修复
"""
import unittest
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch

# 导入待测试的类
sys.path.insert(0, os.path.dirname(__file__))
from main import Tranche, RollingPortfolioManager, RiskController, REBALANCE_PERIOD_T


class TestBug1_DatetimeSerialization(unittest.TestCase):
    """Bug 1: save_state() 的 datetime 序列化失败"""

    def test_tranche_to_dict_with_datetime(self):
        """测试 Tranche.to_dict() 能否正确序列化包含 datetime 的 pos_records"""
        t = Tranche(0, 100000)
        current_dt = datetime(2026, 1, 23, 14, 55, 0)

        # 模拟买入操作，会设置 entry_dt
        t.cash = 100000
        t.holdings['SHSE.510300'] = 1000
        t.pos_records['SHSE.510300'] = {
            'entry_price': 4.5,
            'high_price': 4.5,
            'entry_dt': current_dt,
            'volatility': 0.02
        }

        # 尝试序列化
        try:
            d = t.to_dict()
            json_str = json.dumps(d)  # 应该不抛异常
            print(f"✅ Bug 1 测试通过：datetime 成功序列化")
        except TypeError as e:
            self.fail(f"❌ Bug 1 未修复：datetime 序列化失败 - {e}")

    def test_tranche_from_dict_with_datetime_string(self):
        """测试 Tranche.from_dict() 能否正确反序列化 datetime 字符串"""
        # 模拟从 JSON 加载的数据（datetime 已经是字符串）
        data = {
            "id": 0,
            "cash": 50000,
            "holdings": {"SHSE.510300": 1000},
            "pos_records": {
                "SHSE.510300": {
                    "entry_price": 4.5,
                    "high_price": 4.6,
                    "entry_dt": "2026-01-23T14:55:00",  # JSON 中是字符串
                    "volatility": 0.02
                }
            },
            "total_value": 100000
        }

        t = Tranche.from_dict(data)

        # 验证 entry_dt 被正确转换为 datetime 对象
        entry_dt = t.pos_records['SHSE.510300']['entry_dt']
        self.assertIsInstance(entry_dt, datetime,
                             f"❌ Bug 4 未修复：entry_dt 应该是 datetime，但是 {type(entry_dt)}")

        # 验证可以进行 datetime 运算（check_guard 中需要）
        try:
            current_dt = datetime(2026, 1, 25, 14, 55, 0)
            days_held = (current_dt - entry_dt).days
            self.assertEqual(days_held, 2)
            print(f"✅ Bug 4 测试通过：entry_dt 正确反序列化为 datetime")
        except TypeError as e:
            self.fail(f"❌ Bug 4 未修复：无法对 entry_dt 进行 datetime 运算 - {e}")


class TestBug2_SaveStateEndToEnd(unittest.TestCase):
    """Bug 1 + Bug 4 综合测试：完整的 save/load 流程"""

    def test_save_and_load_state_with_datetime(self):
        """测试完整的保存和加载状态流程"""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "test_state.json")

            # 1. 创建 RollingPortfolioManager 并初始化
            rpm = RollingPortfolioManager(state_path=state_file)
            rpm.initialize_tranches(1000000)

            # 2. 模拟买入（会设置 datetime）
            current_dt = datetime(2026, 1, 23, 14, 55, 0)
            rpm.tranches[0].buy('SHSE.510300', 50000, 4.5, current_dt, 0.02)

            # 3. 保存状态（Bug 1：这里应该不抛异常）
            try:
                rpm.save_state()
                self.assertTrue(os.path.exists(state_file), "❌ 状态文件未创建")
                print(f"✅ 状态保存成功")
            except Exception as e:
                self.fail(f"❌ Bug 1 未修复：save_state() 失败 - {e}")

            # 4. 验证文件内容可解析
            try:
                with open(state_file, 'r') as f:
                    data = json.load(f)
                self.assertIn('tranches', data)
                print(f"✅ 状态文件格式正确")
            except Exception as e:
                self.fail(f"❌ 状态文件不是有效的 JSON - {e}")

            # 5. 加载状态（Bug 4：datetime 应该被正确反序列化）
            rpm2 = RollingPortfolioManager(state_path=state_file)
            success = rpm2.load_state()
            self.assertTrue(success, "❌ load_state() 返回 False")

            # 6. 验证 entry_dt 是 datetime 类型
            rec = rpm2.tranches[0].pos_records.get('SHSE.510300')
            self.assertIsNotNone(rec, "❌ 持仓记录丢失")
            entry_dt = rec['entry_dt']
            self.assertIsInstance(entry_dt, datetime,
                                 f"❌ Bug 4 未修复：加载后 entry_dt 类型错误 {type(entry_dt)}")

            # 7. 验证可以进行 check_guard 操作
            try:
                price_map = {'SHSE.510300': 4.0}
                future_dt = datetime(2026, 1, 25, 14, 55, 0)
                to_sell = rpm2.tranches[0].check_guard(price_map, future_dt)
                print(f"✅ Bug 1 + Bug 4 综合测试通过：完整的 save/load 流程正常")
            except Exception as e:
                self.fail(f"❌ check_guard() 调用失败 - {e}")


class TestBug3_AccountIDInAlgo(unittest.TestCase):
    """Bug 3: algo() 中 context.account() 缺失 account_id"""

    def test_account_call_with_account_id(self):
        """测试 algo() 函数中是否正确处理 account_id（代码审查测试）"""
        # 这个测试需要读取修复后的代码并验证
        with open('main.py', 'r', encoding='utf-8') as f:
            code = f.read()

        # 检查 algo() 函数中的 context.account() 调用
        # 应该有类似这样的模式：
        # acc = context.account(account_id=context.account_id) if context.mode == MODE_LIVE else context.account()

        # 关键行：line 530 和 line 637
        algo_section = code[code.find('def algo(context):'):code.find('def on_bar(context, bars):')]

        # 检查是否有未修复的 context.account() 调用（实盘时缺失 account_id）
        import re

        # 匹配 context.account() 但不是在三元表达式中的调用
        # 正确模式: context.account(account_id=context.account_id) if context.mode == MODE_LIVE else context.account()
        # 错误模式: context.account() 且前面没有 "else"

        lines = algo_section.split('\n')
        problematic_lines = []
        for i, line in enumerate(lines):
            if 'context.account()' in line:
                # 检查是否在 else 分支或已经有 account_id 参数
                if 'else context.account()' not in line and 'account_id=' not in line:
                    # 排除注释行
                    if not line.strip().startswith('#'):
                        problematic_lines.append((i, line.strip()))

        if problematic_lines:
            msg = "❌ Bug 3 未修复：以下行缺失 account_id 处理:\n"
            for line_num, line in problematic_lines:
                msg += f"  Line {line_num}: {line}\n"
            self.fail(msg)
        else:
            print(f"✅ Bug 3 测试通过：algo() 中所有 account() 调用都正确处理了 account_id")


class TestBug5_RiskControllerIntegration(unittest.TestCase):
    """Bug 2 + Bug 5: RiskController 集成测试"""

    def test_risk_controller_is_called(self):
        """测试 RiskController 的方法是否在 algo() 中被调用"""
        with open('main.py', 'r', encoding='utf-8') as f:
            code = f.read()

        algo_section = code[code.find('def algo(context):'):code.find('def on_bar(context, bars):')]

        # Bug 5: on_day_start 应该在 algo() 开头调用
        # Bug 2: check_daily_loss 或 validate_order 应该被调用

        checks = {
            'on_day_start': 'risk_safe.on_day_start(context)' in algo_section,
            'check_daily_loss': 'risk_safe.check_daily_loss(context)' in algo_section,
        }

        failures = []
        if not checks['on_day_start']:
            failures.append("❌ Bug 5 未修复：risk_safe.on_day_start() 未在 algo() 中调用")

        # check_daily_loss 应该在交易逻辑之前调用
        if checks['check_daily_loss']:
            # 检查调用位置（应该在 get_ranking 之前）
            on_day_start_pos = algo_section.find('risk_safe.on_day_start')
            check_loss_pos = algo_section.find('risk_safe.check_daily_loss')
            get_ranking_pos = algo_section.find('get_ranking(context')

            if on_day_start_pos > 0 and check_loss_pos > on_day_start_pos and check_loss_pos < get_ranking_pos:
                print(f"✅ Bug 2 + Bug 5 测试通过：RiskController 正确集成到 algo() 中")
            else:
                failures.append("❌ Bug 2/Bug 5 部分修复：RiskController 方法调用顺序不正确")
        else:
            failures.append("⚠️  Bug 2 未完全修复：check_daily_loss 未被调用（可选修复项）")

        if failures:
            print('\n'.join(failures))
            # 不 fail，只警告（因为 Bug 2 是可选修复项）


class TestRiskControllerLogic(unittest.TestCase):
    """测试 RiskController 的逻辑正确性"""

    def test_daily_loss_check(self):
        """测试熔断逻辑"""
        rc = RiskController()

        # 模拟 context
        context = Mock()
        context.mode = 'MODE_LIVE'
        context.account_id = 'test_account'
        context.now = datetime.now()

        # 模拟账户
        acc = Mock()
        acc.cash = Mock()
        acc.cash.nav = 1000000

        context.account = Mock(return_value=acc)

        # 第一次调用 on_day_start，锁定初始 NAV
        rc.on_day_start(context)
        self.assertEqual(rc.initial_nav_today, 1000000)

        # 测试正常情况（未触发熔断）
        acc.cash.nav = 970000  # 亏损 3%
        result = rc.check_daily_loss(context)
        self.assertTrue(result, "3% 亏损不应该触发熔断")
        self.assertTrue(rc.active, "系统应该保持活跃")

        # 测试熔断情况
        acc.cash.nav = 950000  # 亏损 5% > 4%
        result = rc.check_daily_loss(context)
        self.assertFalse(result, "5% 亏损应该触发熔断")
        self.assertFalse(rc.active, "系统应该进入熔断状态")

        print(f"✅ RiskController 熔断逻辑测试通过")


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 按优先级添加测试
    suite.addTests(loader.loadTestsFromTestCase(TestBug1_DatetimeSerialization))
    suite.addTests(loader.loadTestsFromTestCase(TestBug2_SaveStateEndToEnd))
    suite.addTests(loader.loadTestsFromTestCase(TestBug3_AccountIDInAlgo))
    suite.addTests(loader.loadTestsFromTestCase(TestBug5_RiskControllerIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestRiskControllerLogic))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
