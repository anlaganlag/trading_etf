"""
策略核心纯逻辑模块 (Pure Logic)
用于实现像素级对齐：确保回测、实盘、模拟脚本使用完全同一套计算逻辑。
"""
import pandas as pd
from config import config, logger
from .signal import get_ranking, get_market_regime

def calculate_target_holdings(context, current_dt, active_t, price_map):
    """
    计算目标持仓结构 (不涉及下单)
    
    Args:
        context: 上下文对象 (主要用到 whitelist, theme_map, now)
        current_dt: 当前决策时间
        active_t: 当前轮动的 Tranche 对象 (用于获取现有持仓做 Buffer 判定)
        price_map: 当前价格字典
        
    Returns:
        dict: 目标持仓 {symbol: target_weight_score}
              注意：这里返回的是权重的份数 (如 3, 1, 1)，不是百分比
    """
    # 1. 获取排名
    rank_df, _ = get_ranking(context, current_dt)
    
    if rank_df is None:
        logger.warning(f"⚠️ [Logic] Ranking failed for {current_dt}")
        return {}

    current_top_n = config.TOP_N
    
    # 2. 生成候选名单
    candidates = []
    themes = {}
    for code, row in rank_df.iterrows():
        if themes.get(row['theme'], 0) < config.MAX_PER_THEME:
            candidates.append(code)
            themes[row['theme']] = themes.get(row['theme'], 0) + 1
    
    # 截取核心和缓冲名单
    core_targets = candidates[:current_top_n]
    buffer_targets = candidates[:current_top_n + config.TURNOVER_BUFFER]
    
    # 3. 智能保留逻辑 (Soft Rotation)
    existing_holdings = list(active_t.holdings.keys())
    kept_holdings = []
    current_slots_used = 0
    
    # A. 优先保留在 Buffer 中的老持仓
    for s in existing_holdings:
        if s in buffer_targets and current_slots_used < current_top_n:
            kept_holdings.append(s)
            current_slots_used += 1
            # logger.info(f"🤝 [Logic] Kept in Buffer: {s}")
    
    # B. 填充新标的
    targets_to_buy = []
    for s in core_targets:
        if current_slots_used >= current_top_n:
            break
        if s not in kept_holdings:
            targets_to_buy.append(s)
            current_slots_used += 1
            
    final_list = kept_holdings + targets_to_buy
    
    # 4. 权重计算 (核心对齐点)
    # 当前方案: 3:1:1:1 (Champion Heavy)
    # 逻辑: 只有 candidates 里的第一个才给 3 份，其他的给 1 份
    # 注意: s 在 candidates 中的索引 i 决定了它的地位
    
    weights = {}
    for i, s in enumerate(candidates):
        if s in final_list:
            # === 权重逻辑：根据配置选择方案 ===
            # EQUAL: 等权 (1:1:1:1)
            # CHAMPION: 冠军加权 (3:1:1:1)
            if config.WEIGHT_SCHEME == 'EQUAL':
                w = 1
            else:
                w = 3 if i == 0 else 1
            weights[s] = w
            
    return weights

def calculate_position_scale(context, current_dt):
    """
    计算总仓位比例
    """
    # 1. 市场状态缩放 (Trend)
    trend_scale = get_market_regime(context, current_dt) if config.DYNAMIC_POSITION else 1.0
    
    # 2. 风险门缩放 (Meta-Gate)
    risk_scale = context.risk_scaler if config.ENABLE_META_GATE else 1.0
    
    final_scale = trend_scale * risk_scale
    return final_scale, trend_scale, risk_scale
