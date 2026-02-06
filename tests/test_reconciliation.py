import unittest
from core.portfolio import RollingPortfolioManager, Tranche

class TestReconciliation(unittest.TestCase):
    def setUp(self):
        self.rpm = RollingPortfolioManager()
        # Initialize with 1 tranche for simplicity in this test
        self.rpm.tranches = [Tranche(0, 100000)]
        self.rpm.days_count = 1
        self.rpm.initialized = True
        
        # Scenario: 
        # RPM thinks it bought 1000 shares of ETF_A at price 10.0
        # Tranche 0 holds this.
        t = self.rpm.tranches[0]
        t.cash = 90000  # Spent 10000
        t.holdings = {'ETF_A': 1000}
        t.pos_records = {
            'ETF_A': {'entry_price': 10.0, 'high_price': 10.0, 'entry_dt': '2025-01-01', 'volatility': 0.02}
        }
        t.total_value = 100000

    def test_reconciliation_gap_up_partial_fill(self):
        """
        Test case: 
        Planned to buy 1000 shares.
        Actually bought 900 shares (e.g. due to gap up/insufficient cash).
        RPM should reduce holdings to 900.
        """
        # Current Virtual State
        self.assertEqual(self.rpm.total_holdings['ETF_A'], 1000)
        
        # Actual Broker State (Simulated)
        real_positions = {'ETF_A': 900}
        
        # Execute Reconciliation
        self.rpm.reconcile_with_broker(real_positions)
        
        # Verify Virtual State matches Real State
        self.assertEqual(self.rpm.total_holdings['ETF_A'], 900)
        self.assertEqual(self.rpm.tranches[0].holdings['ETF_A'], 900)
        
        # Verify logic implies we don't buy back the missing 100
        # The logic simply accepts the reduction.
        
    def test_reconciliation_buy_failed_completely(self):
        """
        Test case:
        Planned to buy 1000 shares.
        Actually bought 0 shares (e.g. limit up).
        RPM should remove the holding completely.
        """
        self.assertEqual(self.rpm.total_holdings['ETF_A'], 1000)
        
        real_positions = {} # Empty
        
        self.rpm.reconcile_with_broker(real_positions)
        
        self.assertNotIn('ETF_A', self.rpm.total_holdings)
        self.assertEqual(len(self.rpm.tranches[0].holdings), 0)

    def test_reconciliation_multiple_tranches(self):
        """
        Test case:
        Tranche 0 has 500 shares.
        Tranche 1 has 500 shares.
        Total Virtual: 1000.
        Real: 800.
        Should reduce 200 shares total.
        """
        # Setup multiple tranches
        self.rpm.tranches = [Tranche(0, 50000), Tranche(1, 50000)]
        self.rpm.tranches[0].holdings = {'ETF_A': 500}
        self.rpm.tranches[1].holdings = {'ETF_A': 500}
        
        real_positions = {'ETF_A': 800}
        
        self.rpm.reconcile_with_broker(real_positions)
        
        total_virtual = self.rpm.total_holdings.get('ETF_A', 0)
        self.assertEqual(total_virtual, 800)
        
        # Check distribution (implementation detail: it iterates and reduces)
        # It usually reduces from the first tranche it finds
        # T0: 500, T1: 500. Diff: 200.
        # It might reduce T0 to 300, T1 stays 500. Or T0=500, T1=300.
        # Based on loop order in portfolio.py: for t in self.tranches...
        # It should reduce T0 first.
        
        t0_holding = self.rpm.tranches[0].holdings.get('ETF_A', 0)
        t1_holding = self.rpm.tranches[1].holdings.get('ETF_A', 0)
        
        self.assertEqual(t0_holding + t1_holding, 800)

if __name__ == '__main__':
    unittest.main()
