"""
信号生成模块
- get_market_regime: 市场状态判断
- get_ranking: ETF排名评分
"""
import os
import numpy as np
import pandas as pd
from config import config, logger


def get_market_regime(context, current_dt):
    """
    1/2年线宏观风控 + 20/60日线微观风控
    返回仓位缩放因子 (0.0 ~ 1.0)
    """
    # 确保时区对齐
    hist = context.prices_df[context.prices_df.index <= current_dt]
    if len(hist) < 60:
        return 1.0
    
    bm_hist = context.benchmark_df[context.benchmark_df.index <= current_dt]

    # 宏观判断：基准是否跌破120日均线
    macro_mult = 1.0
    if len(bm_hist) > 120:
        ma120 = bm_hist.tail(120).mean()
        if bm_hist.iloc[-1] < ma120:
            macro_mult = 0.5
            logger.debug(f"📉 Macro Benchmark below MA120: {bm_hist.iloc[-1]:.2f} < {ma120:.2f}")

    # 微观判断：多少标的站上均线
    recent = hist.tail(60)
    # 鲁棒性改进：对 NaN 值进行处理，避免运算错误
    strength = (
        (recent.iloc[-1] > recent.tail(20).mean()).mean() +
        (recent.iloc[-1] > recent.mean()).mean()
    ) / 2
    
    if np.isnan(strength):
        logger.warning(f"⚠️ Market strength calculation resulted in NaN at {current_dt}")
        strength = 0.0

    base_pos = 1.0 if strength > 0.6 else 0.9 if strength > 0.4 else 0.3
    
    if macro_mult < 1.0 and strength <= 0.4:
        return 0.0
    return base_pos * macro_mult


def get_ranking(context, current_dt):
    """
    Meta-Gate 核心选股逻辑
    返回: (排名DataFrame, 评分Series)
    """
    hist = context.prices_df[context.prices_df.index <= current_dt]
    if len(hist) < 251:
        logger.warning(f"⚠️ Insufficient history for ranking: {len(hist)} days")
        return None, None
    
    last = hist.iloc[-1]

    # 动量评分
    scores = pd.Series(0.0, index=hist.columns)
    periods = {1: 30, 3: -70, 20: 150}
    
    # 预先检查是否有全空列
    valid_cols = last.notna() & (last > 0)
    if not valid_cols.any():
        return None, scores

    rets = {f'r{p}': (last / hist.iloc[-(p+1)]) - 1 for p in [1, 3, 5, 20]}

    for p, pts in periods.items():
        # 处理全为相同值的情况
        ranks = rets[f'r{p}'].rank(ascending=False, method='min')
        scores += ((30 - ranks) / 30).clip(lower=0) * pts

    # Z-Score 结构门控 (核心防御)
    daily_rets = hist.pct_change()
    # 鲁棒性：限制最小波动率，防止除零错误
    vol_ruler = daily_rets.iloc[:-5].tail(60).std().replace(0, 0.01).clip(lower=0.005)
    z_score = rets['r5'] / (vol_ruler * np.sqrt(5))

    # Meta-Gate 状态机维护
    k_crash = float(os.environ.get('OPT_K_CRASH', 2.5))
    universe_z = z_score[z_score.index.isin(context.whitelist)].dropna()
    
    if len(universe_z) >= 20:
        current_br = (universe_z < -k_crash).mean()
        context.br_history = (context.br_history + [current_br])[-3:]
        br_smooth = np.mean(context.br_history)

        # 状态机维护
        danger_in = 0.5 if np.median(universe_z) < -2.3 else context.BR_DANGER_IN
        
        old_state = context.market_state
        if context.market_state == 'SAFE' and br_smooth > context.BR_CAUTION_IN:
            context.market_state = 'CAUTION'
        elif context.market_state == 'CAUTION':
            if br_smooth > danger_in:
                context.market_state = 'DANGER'
            elif br_smooth < context.BR_CAUTION_OUT:
                context.market_state = 'SAFE'
        elif context.market_state == 'DANGER' and br_smooth < context.BR_DANGER_OUT:
            context.market_state = 'CAUTION'
        
        if old_state != context.market_state:
            logger.info(f"🚦 [STATE CHANGE] {old_state} -> {context.market_state} (BR: {br_smooth:.2%})")

        context.risk_scaler = (
            0.0 if context.market_state == 'DANGER'
            else (0.7 if br_smooth >= context.BR_PRE_DANGER else 1.0)
        )

    # 过滤弱势标的 (顺势而为)
    k_entry = float(os.environ.get('OPT_R5_K', 1.6))
    valid_mask = (z_score > -k_entry) & (scores >= config.MIN_SCORE)
    valid_syms = [s for s in list(context.whitelist) if s in valid_mask.index and valid_mask[s]]
    
    if not valid_syms:
        return None, scores

    scores_subset = scores.loc[valid_syms]
    df = pd.DataFrame({
        'score': scores_subset,
        'theme': [context.theme_map.get(c, 'Unknown') for c in valid_syms]
    })
    for p in [1, 3, 5, 20]:
        df[f'r{p}'] = rets[f'r{p}'].loc[valid_syms]
    
    return df.sort_values(by=['score', 'r1', 'r20'], ascending=False), scores
