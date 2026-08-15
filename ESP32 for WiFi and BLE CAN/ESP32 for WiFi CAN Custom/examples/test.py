from wifi_can_client import WiFiCANClient, CANFrame

# 自动三级降级连接
client = WiFiCANClient()

# 或手动指定
# client = WiFiCANClient(host="192.168.4.1", port=8888)

print(f"连接模式: {client.mode}")

# 设置 CAN 速率
client.set_can_rate(1000)

# 发送 CAN 帧 — 标准帧
client.send_can(can_id=0x7B, data=bytes([0x11, 0x22, 0x33, 0x44]))
# 发送扩展帧
client.send_can(can_id=0x1F6, data=bytes([0xAA, 0xBB]), extended=True)

# 查询 ESP32 IP
print(client.query_ip())

# 查询 RTC 时间
print(client.query_rtc_time())

# 读取 CAN 接收缓冲区（返回 CANFrame 列表）
frames = client.read_can_buffer()
for f in frames:
    print(f"ID=0x{f.id:X} 数据={f.data.hex(' ')} 时间={f.timestamp_ms}ms")

# 持续监听（回调模式）
def on_frame(frame: CANFrame):
    print(f"收到: {frame}")

client.monitor(callback=on_frame)

# 用完后关闭
client.close()
