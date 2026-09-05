# -*- coding: utf-8 -*-
"""0xA4 位置指令命令率测定(交接待办 3, 2026-09-05 真机测定):
对指定电机(V44)发 A4 小角度摆动(±2°, 60dps, 限幅内), 间隔档位 200→5ms, 统计 A4 回复率。
实测结论(2026-09-05, ID5 末端 Yaw/X2-7, 总线空闲, 20帧/档):
  200/100/50/33/20/10/5 ms 全档 100% —— **0xA4 指令命令率 ≥200/s(5ms 全通), 与 0x9A 查询率同档**
  (档案: V4 0x9A 单机 5ms≈200Hz 全通; A4 与查询命令共享固件处理能力)
  用途: 抑制/轮询预算按 V4 ≤100/s(200 的一半留余量)设计。
  未测: X8(V3) A4 率(需固件角目标换算, 其 0x9A 查询 333Hz 档案可参考)、更密(<5ms)档。
用法(Jetson, 总线空闲时): python3 tools/a4_rate_test.py [mid=5]
安全: 目标在当前角 ±2° 内摆动, 速度 60dps, 全程可随时中断(Ctrl+C)。
"""
import socket
import struct
import sys
import time

sys.path.insert(0, "/home/nvidia/ROS2/arm_ws/src/arm_protocol")
from arm_protocol.build import v44_pos

mid = int(sys.argv[1]) if len(sys.argv) > 1 else 5
s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
s.bind(("can0",))
s.settimeout(0.05)


def send(data):
    s.send(struct.pack("=IB3x8s", 0x140 + mid, len(data), data))


def recv_all(timeout=0.3):
    s.settimeout(timeout)
    got = []
    while True:
        try:
            f = s.recv(72)
            got.append((struct.unpack("=I", f[:4])[0] & 0x1FFFFFFF, bytes(f[8:16])))
        except socket.timeout:
            break
    s.settimeout(0.05)
    return got


# 读当前角(0x92)定摆动中心
send(bytes([0x92, 0, 0, 0, 0, 0, 0, 0]))
time.sleep(0.3)
center = None
for cid, d8 in recv_all():
    if cid == 0x240 + mid and d8[0] == 0x92:
        center = struct.unpack_from("<i", d8, 4)[0] / 100.0
        print(f"ID{mid} 当前角 {center:.2f}°", flush=True)
if center is None:
    print("读角失败, 用 -3.8 兜底", flush=True)
    center = -3.8

lo, hi = center - 2.0, center + 2.0
print(f"摆动范围 [{lo:.2f}, {hi:.2f}]°, 60dps", flush=True)

INTERVALS = [200, 100, 50, 33, 20, 10, 5]
N = 20
print("档位ms  发出  A4回复  回复率", flush=True)
for iv in INTERVALS:
    sent = 0
    a4_replies = 0
    target = lo
    for i in range(N):
        target = hi if target <= lo else lo          # 来回摆
        send(v44_pos(0xA4, 60, target))
        sent += 1
        time.sleep(iv / 1000.0)
        if i % 5 == 4:
            for cid, d8 in recv_all():
                if cid == 0x240 + mid and d8[0] == 0xA4:
                    a4_replies += 1
    for cid, d8 in recv_all(0.4):
        if cid == 0x240 + mid and d8[0] == 0xA4:
            a4_replies += 1
    print(f"{iv:6d}  {sent:4d}  {a4_replies:4d}  {a4_replies / sent * 100:6.1f}%", flush=True)
    time.sleep(0.3)

send(v44_pos(0xA4, 60, center))
time.sleep(0.8)
print(f"已回 {center:.2f}°, 完成", flush=True)
