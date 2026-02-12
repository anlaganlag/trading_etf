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
    """邮件通知类：发送每日富文本战报"""
    
    def __init__(self):
        self.host = config.EMAIL_HOST
        self.port = config.EMAIL_PORT
        self.user = config.EMAIL_USER
        self.password = config.EMAIL_PASS
        self.to = config.EMAIL_TO
        self._tag = config.VERSION_LABEL  # [等权] 或 [冠军]
    
    def send_email(self, subject, body, content_type='plain'):
        """发送邮件（主题自动加版本前缀）"""
        try:
            tagged_subject = f"{self._tag} {subject}"
            msg = MIMEMultipart()
            msg['From'] = self.user
            msg['To'] = self.to
            msg['Subject'] = tagged_subject
            msg.attach(MIMEText(body, content_type, 'utf-8'))
            
            with smtplib.SMTP_SSL(self.host, self.port) as server:
                server.login(self.user, self.password)
                server.sendmail(self.user, self.to, msg.as_string())
            
            logger.info(f"📧 Email sent: {tagged_subject}")
        except Exception as e:
            logger.error(f"❌ Email send error: {str(e)}")
    
    def send_report(self, context):
        """发送每日富文本 HTML 汇报邮件"""
        try:
            rpm = context.rpm
            total_val = sum(t.total_value for t in rpm.tranches)
            now_str = context.now.strftime('%Y-%m-%d %H:%M:%S')
            
            # 1. 策略概况
            weight_desc = "等权 (1:1:1:1)" if config.WEIGHT_SCHEME == 'EQUAL' else "冠军加权 (3:1:1:1)"
            active_idx = getattr(context, 'today_active_tranche_idx', '-')
            
            # 2. 优选目标表格
            targets_html = ""
            targets_df = getattr(context, 'today_targets', None)
            if targets_df is not None:
                rows = ""
                for idx, (code, row) in enumerate(targets_df.iterrows()):
                    score = row.get('score', 0)
                    theme = row.get('theme', 'Unknown')
                    name = context.name_map.get(code, code)
                    # 只有排名前 N 的才高亮
                    bg = "#f9f9f9" if idx < config.TOP_N else "#ffffff"
                    label = f"<b>{idx+1}.</b>" if idx < config.TOP_N else f"{idx+1}."
                    rows += f"""<tr style="background-color: {bg};">
                        <td style="padding: 8px; border: 1px solid #ddd;">{label}</td>
                        <td style="padding: 8px; border: 1px solid #ddd;">{name}<br><small style="color:#666">{code}</small></td>
                        <td style="padding: 8px; border: 1px solid #ddd;">{theme}</td>
                        <td style="padding: 8px; border: 1px solid #ddd; text-align: right;">{score:.1f}</td>
                    </tr>"""
                targets_html = f"""
                <table style="width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px;">
                    <thead><tr style="background-color: #eee; text-align: left;">
                        <th style="padding: 8px; border: 1px solid #ddd;">#</th>
                        <th style="padding: 8px; border: 1px solid #ddd;">ETF名称</th>
                        <th style="padding: 8px; border: 1px solid #ddd;">主题</th>
                        <th style="padding: 8px; border: 1px solid #ddd;">评分</th>
                    </tr></thead>
                    <tbody>{rows}</tbody>
                </table>"""
            else:
                targets_html = "<p style='color: #666;'>今日无评分数据（可能触发熔断或停盘）</p>"

            # 3. 风控信号解释
            state = getattr(context, 'market_state', 'SAFE')
            state_colors = {'SAFE': '#28a745', 'CAUTION': '#ffc107', 'DANGER': '#dc3545'}
            state_color = state_colors.get(state, '#333')
            
            scale_info = getattr(context, 'today_scale_info', {'scale': 1.0, 'trend_scale': 1.0, 'risk_scale': 1.0})
            
            state_desc = {
                'SAFE': "🟢 <b>SAFE</b>: 指数处于120日均线之上，且站妥均线的标的数量较多，建议积极运作。",
                'CAUTION': "🟡 <b>CAUTION</b>: 指数或微观信号出现走弱迹象，Meta-Gate 建议适度收缩仓位。",
                'DANGER': "🔴 <b>DANGER</b>: 系统性风险触发，Meta-Gate 建议清空仓位或降至最低。"
            }.get(state, "状态未知")

            # 4. 交易执行
            order_summary = getattr(context, 'today_order_summary', [])
            if order_summary:
                orders_html = "<ul>" + "".join([f"<li style='margin-bottom: 4px;'>{s}</li>" for s in order_summary]) + "</ul>"
            else:
                orders_html = "<p style='color: #666;'>😴 今日持仓未变 (或已达标)</p>"

            # 5. 持仓详情
            pos_dict = rpm.total_holdings
            pos_html = ""
            if pos_dict:
                p_rows = ""
                for sym, qty in pos_dict.items():
                    name = context.name_map.get(sym, sym)
                    p_rows += f"<tr><td style='padding: 6px; border: 1px solid #eee;'>{name}</td><td style='text-align:right; padding: 6px; border: 1px solid #eee;'>{int(qty)}股</td></tr>"
                pos_html = f"<table style='width: 100%; border-collapse: collapse; font-size: 13px;'>{p_rows}</table>"
            else:
                pos_html = "<p style='color: #666;'>无持仓</p>"

            # 构建最终 HTML
            html_content = f"""
            <div style="font-family: 'Microsoft YaHei', sans-serif; color: #333; max-width: 600px; margin: auto; border: 1px solid #efefef; padding: 20px;">
                <h2 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; margin-bottom: 20px;">📈 量化策略每日战报 ({context.now.strftime('%Y-%m-%d')})</h2>
                
                <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px;">
                    <h3 style="margin-top: 0; color: #34495e; font-size: 16px;">1️⃣ 策略概况</h3>
                    <ul style="padding-left: 20px; margin-bottom: 0;">
                        <li>权重方案: <b>{weight_desc}</b></li>
                        <li>运行进度: Day {rpm.days_count}</li>
                        <li>调仓切片: Tranche #{active_idx}</li>
                    </ul>
                </div>

                <div style="margin-bottom: 25px;">
                    <h3 style="color: #34495e; font-size: 16px; border-left: 4px solid #3498db; padding-left: 10px;">2️⃣ 今日优选 ETF 目标 (Top {config.TOP_N})</h3>
                    {targets_html}
                </div>

                <div style="margin-bottom: 25px;">
                    <h3 style="color: #34495e; font-size: 16px; border-left: 4px solid {state_color}; padding-left: 10px;">3️⃣ 风控信号 🚦</h3>
                    <div style="padding: 10px; background-color: {state_color}10; border-radius: 4px;">
                        <p style="margin: 0 0 10px 0;">{state_desc}</p>
                        <table style="font-size: 13px; color: #555;">
                            <tr><td>• 趋势仓位:</td><td><b>{scale_info['trend_scale']:.0%}</b></td></tr>
                            <tr><td>• 风险门控:</td><td><b>{scale_info['risk_scale']:.0%}</b></td></tr>
                            <tr><td>• 建议仓位:</td><td><b style="color: {state_color}; font-size: 15px;">{scale_info['scale']:.0%}</b></td></tr>
                        </table>
                    </div>
                </div>

                <div style="margin-bottom: 25px;">
                    <h3 style="color: #34495e; font-size: 16px; border-left: 4px solid #9b59b6; padding-left: 10px;">4️⃣ 今日交易执行</h3>
                    {orders_html}
                </div>

                <div style="background-color: #fdfdfd; padding: 15px; border: 1px solid #eee; border-radius: 5px;">
                    <h3 style="margin-top: 0; color: #34495e; font-size: 16px;">5️⃣ 组合概况</h3>
                    <p style="font-size: 18px; margin: 5px 0 15px 0;">总资产: <b style="color: #27ae60;">¥{total_val:,.2f}</b></p>
                    <p style="margin-bottom: 5px; color: #666; font-size: 14px;">当前持仓列表 ({len(pos_dict)} 只):</p>
                    {pos_html}
                </div>

                <div style="margin-top: 30px; font-size: 12px; color: #999; text-align: center;">
                    <p>报告生成时间: {now_str}</p>
                    <p>ETF Strategy - Automatical Quant Report</p>
                </div>
            </div>
            """
            
            subject = f"策略日报: {'交易执行' if order_summary else '持仓守望'} | {state} | 总资产 {int(total_val/10000)}k"
            self.send_email(subject, html_content, content_type='html')
            
        except Exception as e:
            logger.error(f"❌ Email report error: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
