from gm.api import *
from config import config

set_token(config.GM_TOKEN)

print("Testing SHSE.000985...")
try:
    c = stk_get_index_constituents(index='SHSE.000985')
    print(f'Type: {type(c)}')
    print(f'Length: {len(c) if hasattr(c, "__len__") else "N/A"}')
    print(f'Columns: {c.columns.tolist() if hasattr(c, "columns") else "N/A"}')
    print(c.head(3) if hasattr(c, 'head') else c)
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
