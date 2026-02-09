
from gm.api import *
from config import config
set_token(config.GM_TOKEN)

indices = ['SHSE.000300', 'SHSE.000905', 'SHSE.000906']
for idx in indices:
    print(f"--- Checking {idx} ---")
    try:
        c = stk_get_index_constituents(index=idx)
        if hasattr(c, 'empty') and not c.empty:
            print(f"Columns: {c.columns}")
            print(f"Head: {c.head(1).to_dict()}")
        else:
            print("Empty or not a DF")
    except Exception as e:
        print(f"Error: {e}")
