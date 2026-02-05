import smtplib
from email.mime.text import MIMEText
from email.header import Header

# 配置信息
smtp_server = 'smtp.163.com'
smtp_port = 465
sender = 'tanjhu@163.com'
password = 'KHdqTEPNXViSJpJs'
receivers = ['tanjhu@163.com']

try:
    print(f"正在尝试连接 {smtp_server}:{smtp_port}...")
    message = MIMEText('恭喜！您的量化策略 [Special Forces V2] 邮件通知模块配置成功。\n\n这将确保您每天收盘后能收到策略的资产净值、持仓变动和风控状态。\n\nSafe Trading!', 'plain', 'utf-8')
    message['From'] = sender
    message['To'] = receivers[0]
    message['Subject'] = Header('✅ [Quant] 策略邮件功能验证通过', 'utf-8')

    server = smtplib.SMTP_SSL(smtp_server, smtp_port)
    print("连接成功，正在登录...")
    server.login(sender, password)
    print("登录成功，正在发送...")
    server.sendmail(sender, receivers, message.as_string())
    server.quit()
    print("\n✅ 邮件发送成功！请检查您的收件箱 (包括垃圾邮件文件夹)。")
except Exception as e:
    print(f"\n❌ 邮件发送失败: {e}")
