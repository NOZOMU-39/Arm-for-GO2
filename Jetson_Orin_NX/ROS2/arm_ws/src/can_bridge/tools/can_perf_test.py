# -*- coding: utf-8 -*-
"""can_bridge 连续帧吞吐压测: 轮流发 5 电机 0x9A, 统计 rx 回复率与有效吞吐。

用法(Jetson, tmux 会话内): python3 tools/can_perf_test.py
2026-09-05 实测结论: 10ms/帧(每电机 50ms)零丢失; 3ms 极限丢 16% 且各电机均匀丢
=电机固件处理上限, 非桥瓶颈。轮询节奏 >=10ms/帧 安全(已覆盖第一期需求)。
import time
import rclpy
from rclpy.node import Node
from arm_interfaces.msg import CanFrame


class Perf(Node):
    def __init__(self):
        super().__init__("can_bridge_perf")
        self.rx = 0
        self.rx_ids = {}
        self.sub = self.create_subscription(CanFrame, "/arm/can/rx", self.cb, 500)
        self.pub = self.create_publisher(CanFrame, "/arm/can/tx", 500)

    def cb(self, m):
        self.rx += 1
        self.rx_ids[m.can_id] = self.rx_ids.get(m.can_id, 0) + 1


def run_round(v, interval_ms, frames):
    """发 frames 帧(5 电机轮流 0x9A), 返回 (发出, 收到, 耗时s)"""
    v.rx = 0
    v.rx_ids = {}
    sent = 0
    t0 = time.time()
    for i in range(frames):
        mid = i % 5 + 1
        m = CanFrame()
        m.can_id = 0x140 + mid
        m.dlc = 8
        m.data = [0x9A, 0, 0, 0, 0, 0, 0, 0]
        v.pub.publish(m)
        sent += 1
        time.sleep(interval_ms / 1000)
    # 收尾窗口: 等最后回复
    while time.time() - t0 < (frames * interval_ms / 1000) + 3.0:
        rclpy.spin_once(v, timeout_sec=0.05)
    dt = time.time() - t0
    return sent, v.rx, dt


def main():
    rclpy.init()
    v = Perf()
    time.sleep(3)  # discovery
    for interval, frames in ((10, 300), (3, 600)):
        sent, rx, dt = run_round(v, interval, frames)
        rate = sent / dt if dt else 0
        loss = (sent - rx) / sent * 100 if sent else 0
        print(f"间隔{interval}ms: 发 {sent} 收 {rx} | 丢 {loss:.1f}% | 发送速率 {rate:.0f} 帧/s | 电机分布 {dict(sorted(v.rx_ids.items()))}")
    v.destroy_node()
    rclpy.shutdown()
    print("PERF_DONE")


if __name__ == "__main__":
    main()
