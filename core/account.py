"""
统一获取 GM 账户：带 fallback，避免 account(account_id=...) 返回 None 时直接失败。
当指定 account_id 不可用时，尝试无参 account() 取默认账户并回写 context.account_id。
"""
from gm.api import MODE_LIVE
from config import logger


def get_account(context):
    """
    获取当前账户对象。LIVE 模式下先按 account_id 取，失败则尝试默认账户并更新 context.account_id。
    返回: 账户对象或 None
    """
    acc = None
    if context.mode == MODE_LIVE:
        acc = context.account(account_id=context.account_id)
        if not acc:
            acc = context.account()
            if acc and getattr(acc, 'account_id', None):
                context.account_id = acc.account_id
                logger.warning(f"⚠️ Using default account (account_id updated to {context.account_id[-8:]})")
    else:
        acc = context.account()
    return acc
