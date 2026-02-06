"""
邮件通知模块
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

from gm.api import MODE_BACKTEST
from config import config


class EmailNotifier:
    """战地通讯员：发送每日收盘战报"""
    
    def __init__(self):
        self.smtp_server = config.EMAIL_HOST
        self.smtp_port = config.EMAIL_PORT
        self.sender = config.EMAIL_USER
        self.password = config.EMAIL_PASS
        self.receivers = [config.EMAIL_TO]

    def send_report(self, context):
        """生成并发送 HTML 战报"""
        if context.mode == MODE_BACKTEST:
            return

        try:
            acc = context.account(account_id=context.account_id)
            if not acc:
                return

            nav = acc.cash.nav
            cash = acc.cash.available
            initial = (
                context.risk_safe.initial_nav_today 
                if hasattr(context, 'risk_safe') else nav
            )
            ret_pct = (nav - initial) / initial if initial > 0 else 0.0

            # 持仓列表
            pos_rows = ""
            for p in acc.positions():
                name = context.theme_map.get(p.symbol, p.symbol)
                color = "red" if p.fpnl > 0 else "green"
                pos_rows += (
                    f"<tr><td>{p.symbol}</td><td>{name}</td>"
                    f"<td>{int(p.amount)}</td><td>{p.market_value:.0f}</td>"
                    f"<td style='color:{color}'>{p.fpnl:.0f}</td></tr>"
                )

            state = getattr(context, 'market_state', 'UNKNOWN')
            status_color = {
                'SAFE': 'green', 
                'CAUTION': 'orange', 
                'DANGER': 'red'
            }.get(state, 'black')

            html_content = f"""
            <div style="font-family: Arial;">
                <h2 style="color: #333;">📈 量化策略日报 ({context.now.strftime('%Y-%m-%d')})</h2>
                <ul>
                    <li>💰 NAV: {nav:,.2f}</li>
                    <li>📊 Return: <span style="color: {'red' if ret_pct>=0 else 'green'}">{ret_pct:.2%}</span></li>
                    <li>🚦 State: <span style="background-color: {status_color}; color: white; padding: 2px;">{state}</span></li>
                </ul>
                <table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; width: 100%;">
                    <tr style="background-color: #f2f2f2;"><th>Symbol</th><th>Name</th><th>Vol</th><th>MktVal</th><th>PnL</th></tr>
                    {pos_rows}
                </table>
            </div>
            """

            msg = MIMEMultipart()
            msg['From'] = self.sender
            msg['To'] = ",".join(self.receivers)
            msg['Subject'] = Header(f"策略战报: {ret_pct:.2%} | NAV {int(nav)}", 'utf-8')
            msg.attach(MIMEText(html_content, 'html', 'utf-8'))

            server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
            server.login(self.sender, self.password)
            server.sendmail(self.sender, self.receivers, msg.as_string())
            server.quit()
            print(f"📧 Report sent to {self.receivers}")
        except Exception as e:
            print(f"⚠️ Email Failed: {e}")
