import os
import sys
import pandas as pd
from datetime import datetime
from unittest.mock import MagicMock

# 确保可以导入项目模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from core.notify import EmailNotifier

def generate_preview():
    # 1. 模拟数据
    print("🎨 Generating mock data for email preview...")
    
    # 模拟排名数据
    rank_data = {
        'score': [141.0, 140.0, 116.3, 115.0, 105.0, 98.0],
        'theme': ['石油', '建材', '黄金', '石化', '港股', '医药']
    }
    symbols = ['SZSE.159697', 'SZSE.159745', 'SHSE.517520', 'SZSE.159731', 'SHSE.513010', 'SHSE.512010']
    rank_df = pd.DataFrame(rank_data, index=symbols)
    
    # 模拟 Context
    context = MagicMock()
    context.now = datetime.now()
    context.market_state = 'SAFE'
    context.name_map = {
        'SZSE.159697': '鹏华石油天然气ETF',
        'SZSE.159745': '国泰建筑材料ETF',
        'SHSE.517520': '永赢沪深港黄金产业ETF',
        'SZSE.159731': '华夏石化产业ETF',
        'SHSE.513010': '腾讯ETF',
        'SHSE.512010': '沪深300医药ETF'
    }
    context.today_targets = rank_df
    context.today_weights = {s: (3 if i == 0 else 1) for i, s in enumerate(symbols[:4])}
    context.today_scale_info = {'scale': 1.0, 'trend_scale': 1.0, 'risk_scale': 1.0}
    context.today_order_summary = [
        "🛒 BUY  SZSE.159697 2200股",
        "🛒 BUY  SZSE.159745 1500股",
        "📦 SELL SHSE.510300 3000股 (清仓)"
    ]
    context.today_active_tranche_idx = 2
    
    # 模拟 RPM
    rpm = MagicMock()
    rpm.days_count = 42
    rpm.total_holdings = {
        'SZSE.159697': 5400,
        'SZSE.159745': 3200,
        'SHSE.517520': 4100,
        'SZSE.159731': 3800
    }
    
    # 模拟 Tranches 以计算总资产
    t1 = MagicMock(); t1.total_value = 250000.0
    t2 = MagicMock(); t2.total_value = 265432.1
    rpm.tranches = [t1, t2]
    context.rpm = rpm
    
    # 2. 拦截发送逻辑，捕获 HTML
    notifier = EmailNotifier()
    captured_html = []
    
    def mock_send_email(subject, body, content_type='plain'):
        if content_type == 'html':
            captured_html.append(body)
            print(f"✅ Captured HTML email with subject: {subject}")
        else:
            print(f"ℹ️ Captured plain text email: {subject}")

    notifier.send_email = mock_send_email
    
    # 3. 执行生成
    notifier.send_report(context)
    
    # 4. 写入文件
    if captured_html:
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        file_path = os.path.join(output_dir, "email_preview.html")
        with open(file_path, "w", encoding='utf-8') as f:
            f.write(captured_html[0])
        
        print(f"\n🚀 Preview successfully generated at: {file_path}")
        print("Please open this file in your browser to check the design.")
    else:
        print("❌ Failed to capture HTML.")

if __name__ == "__main__":
    generate_preview()
