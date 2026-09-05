#!/usr/bin/env python3
"""
test.py — ESP32 WiFi CAN 功能自检脚本（带完整日志）

运行:
  python examples/test.py                  # 常规自检 (连接→查询→发帧→读缓冲→监听)
  python examples/test.py --batch-send 5000  # 批量发送自测: 连续发 N 帧测实际速率

每一步都会打印 [INFO]/[OK]/[FAIL] 日志，方便排查问题。
"""
import argparse
import time
import traceback

from wifi_can_client import WiFiCANClient, CANFrame

OK = "\033[32m[OK]\033[0m"
FAIL = "\033[31m[FAIL]\033[0m"
INFO = "\033[36m[INFO]\033[0m"
WARN = "\033[33m[WARN]\033[0m"


def batch_send_test(client: WiFiCANClient, count: int = 5000):
    """批量发送自测: 连续发送 count 帧，统计实际发送速率

    测速原理 (重要):
      sendall() 只是把数据写入系统 TCP 发送缓冲就返回,
      帧数少时 (缓冲装得下) 测出的是"入缓冲速度"——不真实。
      帧数足够大 (>50000, 远超 TCP 缓冲) 时 sendall 会阻塞等待
      内核真正发出去, 计时才是端到端真实吞吐。

    注意:
      - 建议 count ≥ 50000 才测得真实速率
      - CAN 总线上需有至少一个对端设备 (ACK 回应), 否则 ESP32 发送失败
      - ESP32 自收回显会被过滤, 不会重复统计
      - 发送后对照 ESP32 串口日志的 [CAN] TX 统计确认帧数一致
    """
    print(f"\n{INFO} 批量发送自测: {count} 帧, ID=0x7B, 数据 11 22 33 44 (静默发送)...")
    print(f"{INFO} 提示: 帧数 < 50000 时测出的是入缓冲速度(不真实), "
          f"建议 ≥50000 利用 TCP 背压测真实吞吐")
    print(f"{INFO} 提示: CAN 总线需有对端设备 (分析仪/电机) 才能 ACK 成功")

    data = bytes([0x11, 0x22, 0x33, 0x44])
    start = time.perf_counter()
    sent = 0
    try:
        for _ in range(count):
            client.send_can(can_id=0x7B, data=data, extended=False, verbose=False)
            sent += 1
    except Exception as e:
        print(f"{FAIL} 发送中断于第 {sent} 帧: {e}")

    elapsed = time.perf_counter() - start
    rate = sent / elapsed if elapsed > 0 else 0

    # 等待 TCP 缓冲排空, 让最后一帧真正到达 ESP32
    print(f"{INFO} 等待 TCP 缓冲排空 (2s)...")
    time.sleep(2.0)

    if count >= 50000:
        print(f"{OK} 发送完成: {sent} 帧 | 耗时 {elapsed:.2f}s | "
              f"端到端真实吞吐 {rate:.0f} 帧/s")
    else:
        print(f"{WARN} 发送完成: {sent} 帧 | 耗时 {elapsed:.2f}s | "
              f"入缓冲速度 {rate:.0f} 帧/s (帧数太小, 非真实值)")
    print(f"{INFO} 对照检查: ESP32 串口日志的 [CAN] TX 计数应 ≈ {sent}")
    print(f"{INFO} 若 ESP32 串口报 'error passive'/'TX失败' = 总线上没有对端设备")


def main():
    parser = argparse.ArgumentParser(description='ESP32 WiFi CAN 功能自检')
    parser.add_argument('--batch-send', type=int, metavar='N',
                        help='批量发送自测: 连续发送 N 帧 (如 5000)')
    args = parser.parse_args()

    print("=" * 60)
    print("  ESP32 WiFi CAN 功能自检 (v2.1)")
    print("=" * 60)

    # ---- 第 1 步：连接 ----
    print(f"\n{INFO} 连接 ESP32 (自动降级: STA扫描 → 热点网段 → AP → 串口)...")
    try:
        client = WiFiCANClient()   # 默认自动协商批帧模式
    except ConnectionError as e:
        print(f"{FAIL} 连接失败: {e}")
        return
    except Exception as e:
        print(f"{FAIL} 连接异常: {e}")
        traceback.print_exc()
        return

    print(f"{OK} 连接成功 | 模式: {client.mode} "
          f"| 推送: {'批帧(高频推荐)' if client.batch_enabled else '单帧(兼容)'}")

    # ---- 批量发送自测模式 ----
    if args.batch_send:
        try:
            batch_send_test(client, args.batch_send)
        finally:
            client.close()
            print(f"{INFO} 连接已关闭")
        return

    try:
        # ---- 第 2 步：查询基本信息 ----
        print(f"\n{INFO} 查询 ESP32 IP...")
        ip = client.query_ip()
        if ip:
            print(f"{OK} ESP32 IP: {ip}")
        else:
            print(f"{FAIL} IP 查询无响应 (超时? 检查网络)")
        time_str = client.query_rtc_time()
        if time_str:
            print(f"{OK} RTC 时间: {time_str}")
        else:
            print(f"{FAIL} RTC 查询无响应")

        # ---- 第 3 步：发送 CAN 帧 ----
        print(f"\n{INFO} 发送 CAN 帧 (需总线有对端设备 ACK)...")
        try:
            client.send_can(can_id=0x7B, data=bytes([0x11, 0x22, 0x33, 0x44]))
            client.send_can(can_id=0x1F6, data=bytes([0xAA, 0xBB]), extended=True)
            print(f"{OK} 已发送 2 帧 (若 ESP32 串口报 error passive = 总线无对端)")
        except Exception as e:
            print(f"{FAIL} 发送异常: {e}")

        # ---- 第 4 步：读取 CAN 缓冲区 ----
        print(f"\n{INFO} 读取 CAN 接收缓冲区 (3秒内总线上收到的帧)...")
        frames = client.read_can_buffer()
        if frames:
            print(f"{OK} 缓冲区有 {len(frames)} 帧:")
            for f in frames:
                print(f"    ID=0x{f.id:X} extd={f.extd} 数据={f.data.hex(' ')} "
                      f"时间={f.timestamp_ms}ms")
        else:
            print(f"{FAIL} 缓冲区为空 (总线上没有其他设备在发帧?)")

        # ---- 第 5 步：监听 5 秒验证帧率 ----
        print(f"\n{INFO} 监听 5 秒 (观察实时帧率, Ctrl+C 提前结束)...")

        def on_frame(frame: CANFrame):
            print(f"    收到: ID=0x{frame.id:X} {frame.data.hex(' ')} [{frame.timestamp_ms}ms]")

        import threading, time as _t
        stop = threading.Event()

        def timeout():
            _t.sleep(5)
            stop.set()

        threading.Thread(target=timeout, daemon=True).start()
        try:
            client.monitor(callback=on_frame, stop_event=stop)
        except KeyboardInterrupt:
            pass

        print(f"{OK} 自检完成")
    finally:
        client.close()
        print(f"{INFO} 连接已关闭")


if __name__ == '__main__':
    main()
