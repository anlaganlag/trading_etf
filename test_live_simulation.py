"""
集成测试：模拟实盘运行场景
验证修复后的代码能否在实盘环境下正常运行
"""
import unittest
import os
import sys
import tempfile
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.dirname(__file__))


class TestLiveSimulation(unittest.TestCase):
    """模拟完整的实盘运行场景"""

    def setUp(self):
        """设置模拟环境"""
        # 创建临时状态文件目录
        self.tmpdir = tempfile.mkdtemp()
        self.state_file = os.path.join(self.tmpdir, "rolling_state_main.json")

    def tearDown(self):
        """清理"""
        import shutil
        if os.path.exists(self.tmpdir):
            shutil.rmtree(self.tmpdir)

    @patch('main.history')
    @patch('main.current')
    @patch('main.subscribe')
    @patch('main.schedule')
    @patch('main.order_target_volume')
    @patch('main.order_volume')
    @patch('main.pd.read_excel')
    def test_multi_day_live_scenario(self, mock_excel, mock_order_vol, mock_order_target,
                                      mock_schedule, mock_subscribe, mock_current, mock_history):
        """测试多天实盘运行场景"""
        from main import init, algo, RollingPortfolioManager, MODE_LIVE, MODE_BACKTEST
        import pandas as pd
        import numpy as np

        # Mock Excel 数据
        mock_excel.return_value = pd.DataFrame({
            'etf_code': ['SHSE.510300', 'SHSE.510500', 'SZSE.159915', 'SZSE.159919'],
            'etf_name': ['沪深300ETF', '中证500ETF', '创业板ETF', '300ETF'],
            'theme': ['指数', '指数', '创业板', '指数']
        })

        # Mock 历史数据
        dates = pd.date_range('2025-01-01', '2025-12-31', freq='D')
        mock_prices = pd.DataFrame(
            np.random.uniform(3, 5, (len(dates), 4)),
            index=dates,
            columns=['SHSE.510300', 'SHSE.510500', 'SZSE.159915', 'SZSE.159919']
        )

        def mock_history_func(symbol, **kwargs):
            syms = symbol.split(',')
            data = []
            for d in dates[-100:]:
                for s in syms:
                    data.append({
                        'symbol': s,
                        'close': mock_prices.loc[d, s] if s in mock_prices.columns else 3.5,
                        'volume': 100000,
                        'eob': d
                    })
            return pd.DataFrame(data)

        mock_history.side_effect = mock_history_func

        # Mock 实时行情
        def mock_current_func(symbols):
            return [{'symbol': s, 'price': 4.0 + np.random.uniform(-0.1, 0.1)} for s in symbols]

        mock_current.side_effect = mock_current_func

        # 模拟 context
        context = Mock()
        context.mode = MODE_LIVE
        context.account_id = 'test_account_123'
        context.now = datetime(2025, 6, 1, 14, 55, 0)

        # 模拟账户
        acc = Mock()
        acc.cash = Mock()
        acc.cash.nav = 1000000
        acc.cash.available = 500000

        # 模拟持仓
        mock_position = Mock()
        mock_position.symbol = 'SHSE.510300'
        mock_position.amount = 10000
        mock_position.available = 10000
        mock_position.market_value = 40000
        mock_position.fpnl = 500

        acc.positions = Mock(return_value=[mock_position])
        context.account = Mock(return_value=acc)

        # 运行 init
        print("\n=== 模拟实盘场景测试 ===")
        print("Day 1: 初始化策略")

        # Patch config.BASE_DIR
        with patch('main.config') as mock_config:
            mock_config.BASE_DIR = self.tmpdir

            try:
                init(context)
                print("✅ init() 执行成功")
            except Exception as e:
                self.fail(f"❌ init() 失败: {e}")

            # Day 1: 首次运行 algo
            print("\nDay 1: 首次调仓")
            try:
                algo(context)
                print("✅ Day 1 algo() 执行成功")

                # 验证状态文件已创建
                state_path = os.path.join(self.tmpdir, "rolling_state_main.json")
                self.assertTrue(os.path.exists(state_path),
                               "❌ 状态文件未创建")
                print("✅ 状态文件已创建")

            except Exception as e:
                self.fail(f"❌ Day 1 algo() 失败: {e}")

            # Day 2: 模拟重启后恢复状态
            print("\nDay 2: 模拟重启后恢复状态")
            context2 = Mock()
            context2.mode = MODE_LIVE
            context2.account_id = 'test_account_123'
            context2.now = datetime(2025, 6, 2, 14, 55, 0)
            context2.account = Mock(return_value=acc)

            try:
                init(context2)
                print("✅ Day 2 init() 执行成功")

                # 验证状态已恢复
                self.assertTrue(context2.rpm.initialized,
                               "❌ 状态未正确恢复")
                print("✅ 状态已从文件恢复")

            except Exception as e:
                self.fail(f"❌ Day 2 init() 失败: {e}")

            # Day 2: 运行 algo
            try:
                algo(context2)
                print("✅ Day 2 algo() 执行成功")

            except Exception as e:
                self.fail(f"❌ Day 2 algo() 失败: {e}")

            # Day 3: 测试熔断场景
            print("\nDay 3: 测试熔断场景")
            context3 = Mock()
            context3.mode = MODE_LIVE
            context3.account_id = 'test_account_123'
            context3.now = datetime(2025, 6, 3, 14, 55, 0)

            # 模拟大幅亏损
            acc_loss = Mock()
            acc_loss.cash = Mock()
            acc_loss.cash.nav = 950000  # 亏损5%，触发熔断
            acc_loss.positions = Mock(return_value=[])
            context3.account = Mock(return_value=acc_loss)

            try:
                init(context3)
                algo(context3)
                print("✅ Day 3 熔断场景处理正常")

            except Exception as e:
                self.fail(f"❌ Day 3 熔断场景失败: {e}")

        print("\n=== 实盘模拟测试完成 ===")

    def test_datetime_persistence_across_restarts(self):
        """测试 datetime 在重启后能否正确持久化"""
        from main import RollingPortfolioManager
        from datetime import datetime

        # 创建管理器并初始化
        rpm1 = RollingPortfolioManager(state_path=self.state_file)
        rpm1.initialize_tranches(1000000)

        # 买入并设置 entry_dt
        buy_time = datetime(2025, 6, 1, 14, 55, 0)
        rpm1.tranches[0].buy('SHSE.510300', 50000, 4.5, buy_time, 0.02)

        # 保存状态
        rpm1.save_state()
        print(f"✅ 状态已保存，entry_dt = {buy_time}")

        # 模拟重启：创建新的管理器并加载
        rpm2 = RollingPortfolioManager(state_path=self.state_file)
        success = rpm2.load_state()
        self.assertTrue(success, "❌ 状态加载失败")

        # 验证 entry_dt 正确恢复
        rec = rpm2.tranches[0].pos_records.get('SHSE.510300')
        self.assertIsNotNone(rec, "❌ 持仓记录丢失")
        self.assertIsInstance(rec['entry_dt'], datetime, "❌ entry_dt 类型错误")
        self.assertEqual(rec['entry_dt'], buy_time, "❌ entry_dt 值不匹配")

        print(f"✅ 重启后 entry_dt 正确恢复: {rec['entry_dt']}")

        # 测试保护期检查
        check_time = datetime(2025, 6, 1, 15, 0, 0)  # 同一天
        price_map = {'SHSE.510300': 4.0}
        to_sell = rpm2.tranches[0].check_guard(price_map, check_time)

        print(f"✅ check_guard() 执行成功，待卖出标的: {to_sell}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
