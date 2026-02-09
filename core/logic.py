"""
策略核心纯逻辑模块 (Pure Logic)
用于实现像素级对齐：确保回测、实盘、模拟脚本使用完全同一套计算逻辑。
"""
import pandas as pd
from config import config, logger
from .signal import get_ranking, get_market_regime

def calculate_target_holdings(context, current_dt, active_t, price_map):
    """
    计算目标持仓结构 - 释放 Alpha 增强版 (降摩擦)
    """
    rank_df, _ = get_ranking(context, current_dt)
    if rank_df is None: return {}

    current_top_n = config.TOP_N
    
    # 记录元数据供 Scale 使用
    valid_count = rank_df['is_structural_ok'].sum() if 'is_structural_ok' in rank_df.columns else 0
    top_4_mean_score = rank_df['score'].head(4).mean()
    
    context.last_rank_info = {
        'valid_count': int(valid_count),
        'avg_score': float(top_4_mean_score),
        'market_bull': getattr(context, 'last_market_bull', False)
    }
    
    # 候选池过滤 (主题限制)
    candidates = []
    themes = {}
    for code, row in rank_df.iterrows():
        if themes.get(row['theme'], 0) < config.MAX_PER_THEME:
            candidates.append(code)
            themes[row['theme']] = themes.get(row['theme'], 0) + 1
    
    core_targets = candidates[:current_top_n]
    
    # 3. 降摩擦逻辑 (Smart Retention)
    # 只要老股票还在 Top 50 且结构没死 (is_structural_ok)，就强制保留，避免频繁调仓
    existing_holdings = list(active_t.holdings.keys())
    final_list = []
    
    # A. 优先检查并保留符合条件的老持仓
    for s in existing_holdings:
        if s in rank_df.index:
            row = rank_df.loc[s]
            # 核心保留条件：结构未坏 且 仍在前 50 名 (Alpha 保护位)
            if row['is_structural_ok'] and row['is_top_50'] and len(final_list) < current_top_n:
                final_list.append(s)
    
    # B. 填充新核心标的直到满员
    for s in core_targets:
        if len(final_list) >= current_top_n: break
        if s not in final_list:
            final_list.append(s)
            
    # 4. 权重分配
    weights = {}
    for i, s in enumerate(candidates):
        if s in final_list:
            if config.WEIGHT_SCHEME == 'EQUAL': w = 1
            else: w = 3 if i == 0 else 1
            weights[s] = w
            
    return weights

def calculate_position_scale(context, current_dt):
    """
    升级版仓位管理：双向调节 (释放 Alpha)
    1. 基础环境缩放 (Regime: Trend + Breadth)
    2. 信号信心缩放 (Conviction: AI Scores)
    """
    import numpy as np
    # 1. 基础环境缩放
    regime_scale = get_market_regime(context, current_dt)
    
    # 2. 信号与信念缩放
    rank_info = getattr(context, 'last_rank_info', None)
    conviction_scale = 1.0
    
    if rank_info:
        valid_count = rank_info.get('valid_count', 0)
        avg_score = rank_info.get('avg_score', 0.0)
        market_bull = rank_info.get('market_bull', False)
        
        # 信念调节 (Conviction Scaling): 4只全优评分 > 0.4 为满信心，< 0.1 为低信心
        # 赋予 0.4 ~ 1.2 的系数支持
        conviction_mult = np.clip(avg_score / 0.4, 0.4, 1.2)
        
        # 密度调节 (Signal Density)
        density_base = valid_count / config.TOP_N
        bull_floor = 0.5 if market_bull else 0.0
        
        density_scale = max(bull_floor, density_base)
        conviction_scale = density_scale * conviction_mult
        
        logger.info(f"⚖️ [Logic] Scale: Regime={regime_scale:.2f}, Conviction={conviction_scale:.2f} (AvgSc:{avg_score:.3f})")

    final_scale = regime_scale * conviction_scale
    return float(np.clip(final_scale, 0.0, 1.0)), regime_scale, conviction_scale
