"""
全流程模拟实盘测试 (Mock End-to-End Test)
目标：在不连接 GM 真实服务器的情况下，跑通 run_equal.bat 的核心逻辑
覆盖：
1. 环境初始化 (init)
2. 账户获取与回落机制 (get_account)
3. 市场状态判断 (get_market_regime)
4. 选股排序 (get_ranking)
5. 资金分配 (calculate_target_holdings)
6. 交易信号生成 (algo -> order_volume)
7. 订单成交验证 (verify_orders - mocked)
8. 状态保存 (save_state)
9. 消息推送 (EnterpriseWeChat - mocked)
"""
import unittest
import sys
import os
import shutil
import tempfile
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch, ANY, Mock
from datetime import datetime, time as dtime

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# 临时设置环境变量以模拟 run_equal.bat
os.environ['WEIGHT_SCHEME'] = 'EQUAL'
os.environ['VERSION_SUFFIX'] = '_equal'
# 这里的环境变量会被 config 模块读取
# 为了不影响真实 config，我们稍后在 TestCase 中不仅 mock，还要 reload config

from config import config

class MockAnalysis:
    """Mock context and analysis tools"""
    pass

class TestLiveMock(unittest.TestCase):
    def setUp(self):
        # 1. 准备临时目录
        self.test_dir = tempfile.mkdtemp()
        self.original_base_dir = config.BASE_DIR
        config.BASE_DIR = self.test_dir
        config.LOG_DIR = os.path.join(self.test_dir, 'logs')
        config.DATA_CACHE_DIR = os.path.join(self.test_dir, 'data_cache')
        # 重定向输出目录
        config.OUTPUT_DIR = os.path.join(self.test_dir, 'output')
        config.DATA_OUTPUT_DIR = os.path.join(config.OUTPUT_DIR, 'data')
        config.REPORT_OUTPUT_DIR = os.path.join(config.OUTPUT_DIR, 'reports')
        config.CHART_OUTPUT_DIR = os.path.join(config.OUTPUT_DIR, 'charts')
        
        # 确保目录存在
        for d in [config.LOG_DIR, config.DATA_CACHE_DIR, config.DATA_OUTPUT_DIR, config.REPORT_OUTPUT_DIR, config.CHART_OUTPUT_DIR]:
            os.makedirs(d, exist_ok=True)
        
        # 2. 准备白名单文件
        self.whitelist_file = os.path.join(self.test_dir, 'ETF合并筛选结果.xlsx')
        df = pd.DataFrame({
            'etf_code': ['SH.510050', 'SZ.159915', 'SH.512000', 'SZ.159919'],
            'etf_name': ['上证50', '创业板', '券商ETF', '沪深300ETF'],
            'theme': ['宽基', '宽基', '金融', '宽基']
        })
        # 模拟真实列名（可能包含 symbol, sec_name, name_cleaned 等）
        # main.py 中会 rename: symbol->etf_code, sec_name->etf_name, name_cleaned->theme
        # 所以我们需要提供原始列名
        df_raw = df.rename(columns={'etf_code': 'symbol', 'etf_name': 'sec_name', 'theme': 'name_cleaned'})
        df_raw.to_excel(self.whitelist_file, index=False)
        config.WHITELIST_FILE = self.whitelist_file
        
        # 3. 构造 Mock Context
        self.context = Mock()
        self.context.now = datetime(2025, 1, 1, 14, 55, 0)
        self.context.mode = 2 # MODE_LIVE
        self.context.account_id = 'mock_account_equal_id'
        
        # Mock account behavior
        self.mock_acc = Mock()
        self.mock_acc.account_id = 'mock_account_equal_id'
        self.mock_acc.cash.nav = 100000.0
        self.mock_acc.cash.available = 100000.0
        self.mock_acc.positions = Mock(return_value=[])
        
        # Context.account() 返回 mock_acc
        self.context.account = Mock(return_value=self.mock_acc)

        # 4. 构造 Mock Market Data
        # 生成足够长的历史数据 (252天+)
        dates = pd.date_range(end='2025-01-01', periods=300, freq='B')
        price_data = {}
        # 构造上涨趋势的数据
        for sym in ['SH.510050', 'SZ.159915', 'SH.512000', 'SZ.159919']:
            base = 1.000
            trend = np.linspace(0, 0.5, 300) # 上涨
            noise = np.random.randn(300) * 0.01
            price_data[sym] = base + trend + noise
        
        self.context.prices_df = pd.DataFrame(price_data, index=dates)
        # Fix: benchmark_df must be a Series, not a DataFrame
        self.context.benchmark_df = pd.Series(price_data['SZ.159915'], index=dates, name='close')

    def tearDown(self):
        try:
            shutil.rmtree(self.test_dir)
        except:
            pass
        # 恢复 config 路径 (虽然它是 module level，但在当前执行中可能有副作用)

    @patch('core.strategy.verify_orders')
    @patch('core.strategy.order_volume') 
    @patch('core.strategy.order_target_percent')
    @patch('core.strategy.current') # Change: Mock the imported function
    @patch('core.notify.EnterpriseWeChat.send_text')
    @patch('core.notify.EmailNotifier.send_email')
    @patch('core.notify.EmailNotifier.send_report')
    def test_end_to_end_flow(self, mock_email_report, mock_email_send, mock_wechat_send, mock_current, mock_otp, mock_ov, mock_verify):
        """
        全流程测试：模拟一次完整的每日调仓
        """
        from main import init, algo 
        from core.portfolio import RollingPortfolioManager
        
        print(f"\n🧪 [E2E] Simulation Start (Theme: EQUAL)...")
        
        # --- A. 初始化 (Init) ---
        print("   [Step 1] Initializing Strategy...")
        
        # 模拟 _load_gateway_data 不做任何事 (因为我们已经注入了数据)
        with patch('main._load_gateway_data') as mock_load:
            # 模拟 subscribe 和 schedule
            with patch('main.subscribe'), patch('main.schedule'):
                init(self.context)
        
        # 验证 context 组装
        self.assertTrue(hasattr(self.context, 'rpm'), "RPM 未注入")
        self.assertTrue(hasattr(self.context, 'risk_controller'), "RiskController 未注入")
        self.assertEqual(len(self.context.whitelist), 4, "白名单加载错误")
        print(f"   ✅ Initialization success. Components loaded.")

        # --- B. 准备实时行情数据 ---
        print("   [Step 2] Simulating Market Data...")
        # 模拟当前 tick 价格
        mock_ticks = [
            {'symbol': 'SH.510050', 'price': 1.550, 'cum_volume': 10000}, 
            {'symbol': 'SZ.159915', 'price': 1.550, 'cum_volume': 10000},
            {'symbol': 'SH.512000', 'price': 1.550, 'cum_volume': 10000},
            {'symbol': 'SZ.159919', 'price': 1.550, 'cum_volume': 10000},
        ]
        mock_current.return_value = mock_ticks
        
        # Mock 验证订单返回成功
        mock_verify.return_value = {'all_filled': True, 'failed_orders': []}

        # --- C. 执行 Algo ---
        print("   [Step 3] Running Algo...")
        
        # 确保 RPM 需要初始化
        self.context.rpm.initialized = False
        
        # 执行
        algo(self.context)
        
        # --- D. 验证结果 ---
        print("   [Step 4] Verifying Results...")
        
        # 1. RPM 初始化
        self.assertTrue(self.context.rpm.initialized, "RPM should be initialized")
        # 10万资产分10份 -> 每份1万
        t0_val = self.context.rpm.tranches[0].total_value
        self.assertAlmostEqual(t0_val, 10000.0, delta=100, msg=f"Tranche value mismatch: {t0_val}")
        print("   ✅ RPM Initialized correctly")
        
        # 2. 状态保存
        # 检查 rolling_state_main_equal.json 是否在 test_dir 中生成
        expected_state_file = os.path.join(config.BASE_DIR, 'rolling_state_main_equal.json')
        self.assertTrue(os.path.exists(expected_state_file), f"State file not found: {expected_state_file}")
        print(f"   ✅ State file generated: {os.path.basename(expected_state_file)}")
        
        # 3. 微信通知
        # 检查是否发送了 "每日汇报" 或其他通知
        # 初始启动有 "启动成功"， algo 结束有 "每日汇报"
        self.assertTrue(mock_wechat_send.call_count >= 1, "WeChat notification not sent")
        calls = [c[0][0] for c in mock_wechat_send.call_args_list]
        print(f"   ✅ WeChat notifications sent: {len(calls)}")
        for msg in calls:
            print(f"      - {msg[:50]}...")
            
        # 4. 账户一致性
        # 确保 algo 中使用的 account_id 与 context 一致
        # 我们 mock 了 context.account()，所以只要它被调用且没报错就行
        self.assertTrue(self.context.account.called, "Context.account() not called")
        print("   ✅ Account access verified")

if __name__ == '__main__':
    unittest.main()
