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
    升级版双维度风控：趋势 (Trend) + 情绪 (Breadth)
    返回仓位缩放因子 (0.0 ~ 1.0)
    """
    hist = context.prices_df[context.prices_df.index <= current_dt]
    if len(hist) < 60:
        return 1.0
    
    bm_hist = context.benchmark_df[context.benchmark_df.index <= current_dt]
    
    # 1. 趋势因子 (Trend Indicator): 基于均线
    trend_score = 0.0
    if len(bm_hist) >= 120:
        ma20 = bm_hist.tail(20).mean()
        ma120 = bm_hist.tail(120).mean()
        price_now = bm_hist.iloc[-1]
        # 站上20日线 0.3，站上120日线 0.7
        if price_now > ma20: trend_score += 0.3
        if price_now > ma120: trend_score += 0.7
    
    # 2. 情绪因子 (Market Breadth): 多少标的站上20日均线
    recent = hist.tail(20)
    ma20_all = recent.mean()
    breadth = (recent.iloc[-1] > ma20_all).mean()
    
    # 3. 综合判定 (Release Alpha Logic)
    # 只要趋势和情绪其中一个很差，就必须大幅控资
    if trend_score < 0.3 and breadth < 0.4:
        return 0.0 # 极端规避
    
    # 正常波动区间：权重配合
    final_regime = (trend_score * 0.6) + (breadth * 0.4)
    return np.clip(final_regime, 0.0, 1.0)


# AI 最优权重 (1-20日) - 保持不变 (Release Alpha 原则：不碰模型)
AI_WEIGHTS = {
    1: 0.040, 2: 0.009, 3: -0.071, 4: 0.014, 5: -0.073, 
    6: 0.023, 7: 0.083, 8: -0.041, 9: 0.061, 10: 0.111,
    11: 0.094, 12: 0.014, 13: 0.084, 14: 0.055, 15: 0.066, 
    16: -0.035, 17: 0.047, 18: -0.003, 19: 0.035, 20: -0.040
}

def get_ranking(context, current_dt):
    """
    全功能选股引擎：释放 Alpha 专用版
    返回包含丰富元数据的 DataFrame
    """
    hist = context.prices_df[context.prices_df.index <= current_dt]
    vols = context.volumes_df[context.volumes_df.index <= current_dt] if hasattr(context, 'volumes_df') else None
    
    if len(hist) < 251:
        logger.warning(f"⚠️ Insufficient history for ranking: {len(hist)} days")
        return None, None
    
    last_price = hist.iloc[-1]
    symbols = hist.columns
    ind_groups = pd.Series({s: s.split('.')[-1][0] for s in symbols})
    
    # === 1. AI 权重打分 (1-20日 Top 100 逻辑) ===
    scores = pd.Series(0.0, index=symbols)
    rets_map = {}
    for p, w in AI_WEIGHTS.items():
        ret_p = (last_price / hist.iloc[-(p+1)]) - 1
        rets_map[p] = ret_p
        ranks = ret_p.rank(ascending=False, method='min')
        top_100_mask = ranks <= 100
        scores[top_100_mask] += (101 - ranks[top_100_mask]) / 100.0 * w

    # === 2. 结构失效名单 (Structural Failures) ===
    # [A] 追高过滤
    today_ret = (last_price / hist.iloc[-2]) - 1
    too_high_mask = today_ret > 0.08
    # [B] 量价过滤
    if vols is not None and len(vols) >= 20:
        vol_cb = vols.iloc[-5:-2].mean()    
        vol_ut = vols.iloc[-20:-10].mean()   
        last_vol = vols.iloc[-1]
        v_p_mask = (vol_cb > vol_ut) | (last_vol < vol_cb * 1.2)
    else:
        v_p_mask = pd.Series(False, index=symbols)
    # [C] 板块过滤
    ret_20d = rets_map[20]
    sector_ret_20d = ret_20d.groupby(ind_groups).mean()
    sector_mask = ~ind_groups.map(sector_ret_20d.rank(pct=True) > 0.6)
    
    fail_mask = too_high_mask | v_p_mask | sector_mask

    # === 3. 大盘环境侦测 ===
    market_bull = False
    if hasattr(context, 'benchmark_df'):
        bm_hist = context.benchmark_df[context.benchmark_df.index <= current_dt]
        if len(bm_hist) >= 21:
            market_bull = bm_hist.iloc[-1] > bm_hist.iloc[-21]

    # === 4. 应用闸门 (Gate) ===
    final_scores = scores.copy()
    if market_bull:
        final_scores[fail_mask] *= 0.5  # Soft Gate
    else:
        final_scores[fail_mask] = -999.0 # Hard Gate

    # === 5. 输出准备 (Metadata) ===
    # 标记前 50 名，用于 logic 层执行“摩擦保护”
    top_50_list = final_scores.nlargest(50).index.tolist()
    
    valid_mask = final_scores > 0
    valid_syms = [s for s in list(context.whitelist) if s in symbols and valid_mask.get(s, False)]
    
    if not valid_syms:
        return None, scores

    df = pd.DataFrame({
        'score': final_scores.loc[valid_syms],
        'is_structural_ok': ~fail_mask.loc[valid_syms],
        'is_top_50': [s in top_50_list for s in valid_syms],
        'theme': [context.theme_map.get(c, 'Unknown') for c in valid_syms]
    })
    
    context.last_market_bull = market_bull
    return df.sort_values(by='score', ascending=False), scores
