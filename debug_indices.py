from gm.api import *
from config import config

set_token(config.GM_TOKEN)

# Test multiple indices to find one that works
test_indices = [
    'SHSE.000985',  # 中证全指 (broken)
    'SHSE.000906',  # 中证800
    'SHSE.000905',  # 中证500
    'SHSE.000300',  # 沪深300
    'SZSE.399303',  # 国证2000
    'SHSE.000852',  # 中证1000
]

for idx in test_indices:
    try:
        c = stk_get_index_constituents(index=idx)
        count = len(c) if not c.empty else 0
        print(f"{idx}: {count} stocks")
    except Exception as e:
        print(f"{idx}: Error - {e}")
