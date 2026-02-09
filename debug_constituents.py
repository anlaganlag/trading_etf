
from gm.api import *
from config import config
set_token(config.GM_TOKEN)

try:
    c = stk_get_index_constituents(index='SHSE.000906')
    print(f"Type: {type(c)}")
    if len(c) > 0:
        print(f"Item 0: {c[0]}")
except Exception as e:
    print(f"Error: {e}")

try:
    c = get_constituents(index='SHSE.000906', df=True)
    print(f"Old API DF Columns: {c.columns}")
except Exception as e:
    print(f"Old API Error: {e}")
