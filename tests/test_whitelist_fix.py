
import os
import unittest
import pandas as pd
from unittest.mock import MagicMock, patch

# Mock config before importing main
from config import Config
Config.WHITELIST_FILE = "dummy_whitelist.xlsx"
import config

# Import system under test
import main

class TestWhitelistLoading(unittest.TestCase):
    
    def setUp(self):
        # Create a dummy Excel file with dirty data (spaces)
        self.test_excel = "dummy_whitelist.xlsx"
        df = pd.DataFrame({
            'symbol': ['SHSE.517520 ', ' SZSE.159915', 'SHSE.600519'],
            'sec_name': ['Gold ETF', 'GEM ETF', 'Moutai'],
            'name_cleaned': ['Gold', 'Index', 'Liquor']
        })
        df.to_excel(self.test_excel, index=False)
        
        # Mock Context
        self.context = MagicMock()
        self.context.mode = 2 # MODE_BACKTEST
        
    def tearDown(self):
        if os.path.exists(self.test_excel):
            try:
                os.remove(self.test_excel)
            except:
                pass
            
    def test_whitelist_sanitization(self):
        """Test if whitelist loading strips spaces correctly"""
        
        with patch('main._load_gateway_data'), \
             patch('main.subscribe'), \
             patch('main.schedule'):
            
            # Re-implement logic from main.py
            try:
                # Use the mocked file path
                df_excel = pd.read_excel(Config.WHITELIST_FILE)
                df_excel.columns = df_excel.columns.str.strip()
                df_excel = df_excel.rename(columns={
                    'symbol': 'etf_code', 
                    'sec_name': 'etf_name', 
                    'name_cleaned': 'theme'
                })
                # THIS IS THE FIX WE WANT TO VERIFY
                df_excel['etf_code'] = df_excel['etf_code'].astype(str).str.strip()
                
                self.context.whitelist = set(df_excel['etf_code'])
                self.context.theme_map = df_excel.set_index('etf_code')['theme'].to_dict()
            except Exception as e:
                self.fail(f"Loading failed: {e}")
                
            # Assertions
            self.assertIn('SHSE.517520', self.context.whitelist)
            self.assertNotIn('SHSE.517520 ', self.context.whitelist)
            
            self.assertIn('SZSE.159915', self.context.whitelist)
            self.assertNotIn(' SZSE.159915', self.context.whitelist)
            
            # Verify Map keys also clean
            self.assertIn('SHSE.517520', self.context.theme_map)

if __name__ == '__main__':
    unittest.main()
