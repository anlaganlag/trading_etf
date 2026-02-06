import urllib.request
import json
import datetime

# 您的 Webhook 地址
webhook_url = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=aa6eb940-0d50-489f-801e-26c467d77a30'

def test_send():
    print(f"🔗 正在尝试连接企业微信机器人: {webhook_url[-10:]}...")
    
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 构造 Markdown 消息
    md_content = f"""# ✅ 微信机器人连通性检查
**时间**: {current_time}
**状态**: <font color="info">通信正常</font>
> 这是一个测试信号，如果您能看到这条消息，说明量化策略的[双通道汇报]系统已就绪。
"""
    
    data = {
        "msgtype": "markdown",
        "markdown": {"content": md_content}
    }
    
    headers = {'Content-Type': 'application/json'}
    
    try:
        req = urllib.request.Request(url=webhook_url, headers=headers, data=json.dumps(data).encode('utf-8'))
        resp = urllib.request.urlopen(req)
        resp_data = resp.read().decode('utf-8')
        
        # 检查返回值
        res_json = json.loads(resp_data)
        if res_json.get("errcode") == 0:
            print("\n✅ 发送成功！请查看您的企业微信群。")
        else:
            print(f"\n❌ 发送失败，API 返回错误: {resp_data}")

    except Exception as e:
        print(f"\n❌ 发送异常: {e}")

if __name__ == "__main__":
    test_send()
