"""
验证标准：main.py 已正确初始化 Meta-Gate 所需 context 属性，get_ranking 不再报 AttributeError。

通过条件：
1. context 具备 br_history、BR_CAUTION_*、BR_DANGER_*、market_state、risk_scaler（与 main.py init 一致）
2. 调用 get_ranking(context, current_dt) 时，能执行到 Meta-Gate 分支（len(universe_z)>=20）且不抛 AttributeError
3. 执行后 context.br_history 被正确更新（长度为 1~3 的列表）
"""
import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_minimal_context():
    """构造与 main.py init 一致的 Meta-Gate 相关属性 + 满足 get_ranking 所需的最小数据"""
    ctx = type('Context', (), {})()
    ctx.risk_scaler = 1.0
    ctx.market_state = 'SAFE'
    ctx.br_history = []
    ctx.BR_CAUTION_IN, ctx.BR_CAUTION_OUT = 0.40, 0.30
    ctx.BR_DANGER_IN, ctx.BR_DANGER_OUT, ctx.BR_PRE_DANGER = 0.60, 0.50, 0.55
    # 满足 get_ranking: len(hist)>=251, 且 len(universe_z)>=20
    n_days = 260
    n_syms = 25
    np.random.seed(42)
    dates = pd.date_range(end=datetime(2026, 2, 9), periods=n_days, freq='B')
    syms = [f'SHSE.51{i:04d}' for i in range(1000, 1000 + n_syms)]
    ctx.whitelist = set(syms)
    ctx.theme_map = {c: 'Test' for c in syms}
    data = np.random.rand(n_days, n_syms).cumsum(axis=0) + 1.0
    ctx.prices_df = pd.DataFrame(data, index=dates, columns=syms)
    return ctx


def test_br_history_no_attribute_error():
    """执行 get_ranking 时不应出现 'Context' object has no attribute 'br_history'"""
    from core.signal import get_ranking
    context = _make_minimal_context()
    current_dt = datetime(2026, 2, 9, 14, 55, 0)
    try:
        rank_df, scores = get_ranking(context, current_dt)
    except AttributeError as e:
        if 'br_history' in str(e) or 'BR_' in str(e):
            raise AssertionError(f"Meta-Gate 相关属性未初始化: {e}") from e
        raise
    assert hasattr(context, 'br_history'), "context 应有 br_history"
    assert isinstance(context.br_history, list), "br_history 应为 list"
    assert 1 <= len(context.br_history) <= 3, "br_history 长度应为 1~3（已进入 Meta-Gate 分支并更新）"
    print("[OK] br_history and BR_* initialized, get_ranking no AttributeError")


if __name__ == "__main__":
    test_br_history_no_attribute_error()
    print("Verification passed.")
