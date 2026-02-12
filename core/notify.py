"""
通知模块 - 企业微信与邮件通知
"""
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import config, logger


class EnterpriseWeChat:
    """企业微信机器人推送"""
    
    def __init__(self, webhook_url=None):
        self.webhook_url = webhook_url or config.WECHAT_WEBHOOK
        self._tag = config.VERSION_LABEL  # [等权] 或 [冠军]
    
    def send_text(self, content):
        """发送文本消息（自动加版本前缀）"""
        try:
            tagged = f"{self._tag} {content}"
            data = {
                "msgtype": "text",
                "text": {"content": tagged}
            }
            resp = requests.post(self.webhook_url, json=data, timeout=10)
            if resp.status_code == 200:
                logger.debug(f"📨 WeChat message sent successfully.")
            else:
                logger.warning(f"⚠️ WeChat send failed: {resp.text}")
        except Exception as e:
            logger.error(f"❌ WeChat send error: {str(e)}")
    
    def send_report(self, context):
        """发送每日汇报"""
        try:
            rpm = context.rpm
            total_val = sum(t.total_value for t in rpm.tranches)
            holdings_summary = ", ".join([f"{k}:{v}" for k, v in rpm.total_holdings.items()][:5])
            
            msg = (
                f"📊 每日汇报\n"
                f"市场状态: {context.market_state}\n"
                f"总资产: ¥{total_val:,.2f}\n"
                f"当日: Day {rpm.days_count}\n"
                f"持仓: {holdings_summary or '无'}"
            )
            self.send_text(msg)
        except Exception as e:
            logger.error(f"❌ WeChat report error: {str(e)}")


class EmailNotifier:
    """邮件通知类"""
    
    def __init__(self):
        self.host = config.EMAIL_HOST
        self.port = config.EMAIL_PORT
        self.user = config.EMAIL_USER
        self.password = config.EMAIL_PASS
        self.to = config.EMAIL_TO
        self._tag = config.VERSION_LABEL  # [等权] 或 [冠军]
    
    def send_email(self, subject, body):
        """发送邮件（主题自动加版本前缀）"""
        try:
            tagged_subject = f"{self._tag} {subject}"
            msg = MIMEMultipart()
            msg['From'] = self.user
            msg['To'] = self.to
            msg['Subject'] = tagged_subject
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            with smtplib.SMTP_SSL(self.host, self.port) as server:
                server.login(self.user, self.password)
                server.sendmail(self.user, self.to, msg.as_string())
            
            logger.info(f"📧 Email sent: {tagged_subject}")
        except Exception as e:
            logger.error(f"❌ Email send error: {str(e)}")
    
    def send_report(self, context):
        """发送每日汇报邮件"""
        try:
            rpm = context.rpm
            total_val = sum(t.total_value for t in rpm.tranches)
            
            subject = f"[ETF策略] 每日汇报 - Day {rpm.days_count}"
            body = (
                f"市场状态: {context.market_state}\n"
                f"总资产: ¥{total_val:,.2f}\n"
                f"持仓数量: {len(rpm.total_holdings)}\n"
                f"详细持仓: {rpm.total_holdings}\n"
            )
            self.send_email(subject, body)
        except Exception as e:
            logger.error(f"❌ Email report error: {str(e)}")
