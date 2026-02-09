"""
测试获取中证全指(SHSE.000985)成分股的替代方案
"""
from gm.api import *
from config import config

set_token(config.GM_TOKEN)

# 方案1: 试用 get_instruments 获取所有 A股
print("=== 方案1: get_instruments 获取全市场股票 ===")
try:
    # 获取沪深两市所有股票
    all_stocks = get_instruments(
        symbols=None,
        exchanges=['SHSE', 'SZSE'],
        sec_types=[1],  # 1 = 股票
        is_active=True,  # 只要活跃的
    )
    if hasattr(all_stocks, '__len__'):
        print(f"✅ 获取到 {len(all_stocks)} 只股票")
        if hasattr(all_stocks, 'columns'):
            print(f"列名: {all_stocks.columns.tolist()}")
            print(all_stocks.head(3))
    else:
        print(f"返回类型: {type(all_stocks)}")
except Exception as e:
    print(f"❌ 方案1失败: {e}")

# 方案2: 组合多个指数
print("\n=== 方案2: 组合多个大型指数 ===")
try:
    indices = [
        'SHSE.000300',  # 沪深300
        'SHSE.000905',  # 中证500
        'SHSE.000852',  # 中证1000
        'SZSE.399303',  # 国证2000
    ]
    all_symbols = set()
    for idx in indices:
        c = stk_get_index_constituents(index=idx)
        if not c.empty:
            all_symbols.update(c['symbol'].tolist())
    print(f"✅ 组合后共 {len(all_symbols)} 只股票 (去重后)")
except Exception as e:
    print(f"❌ 方案2失败: {e}")

# 方案3: 使用 get_history_constituents 带日期参数
print("\n=== 方案3: get_history_constituents (带日期) ===")
try:
    from datetime import datetime
    today = datetime.now().strftime('%Y-%m-%d')
    hc = get_history_constituents(index='SHSE.000985', start_date=today, end_date=today)
    if hc:
        print(f"✅ 返回类型: {type(hc)}")
        if isinstance(hc, list):
            print(f"列表长度: {len(hc)}")
            if len(hc) > 0:
                print(f"第一个元素: {hc[0]}")
    else:
        print("❌ 返回空")
except Exception as e:
    print(f"❌ 方案3失败: {e}")
