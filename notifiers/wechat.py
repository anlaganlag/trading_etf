"""
企业微信通知模块
"""
import json
import urllib.request

from gm.api import MODE_BACKTEST
from config import config


class WechatNotifier:
    """通讯兵：企业微信群机器人通知"""
    
    def __init__(self):
        self.webhook_url = config.WECHAT_WEBHOOK

    def send_report(self, context):
        """发送微信通知"""
        if not self.webhook_url or context.mode == MODE_BACKTEST:
            return
        
        try:
            acc = context.account(account_id=context.account_id)
            if not acc:
                return

            nav = acc.cash.nav
            initial = (
                context.risk_safe.initial_nav_today 
                if hasattr(context, 'risk_safe') else nav
            )
            ret_pct = (nav - initial) / initial if initial > 0 else 0.0

            md_content = (
                f"# 🚀 战报 {context.now.strftime('%m-%d')}\n"
                f"**NAV**: {nav:,.2f}\n"
                f"**P&L**: {ret_pct:.2%}\n"
                f"**State**: {getattr(context, 'market_state', 'N/A')}"
            )

            data = {"msgtype": "markdown", "markdown": {"content": md_content}}
            headers = {'Content-Type': 'application/json'}
            req = urllib.request.Request(
                url=self.webhook_url,
                headers=headers,
                data=json.dumps(data).encode('utf-8')
            )
            urllib.request.urlopen(req)
            print("🤖 WeChat Notification sent.")
        except Exception as e:
            print(f"⚠️ WeChat Send Failed: {e}")
