# -*- coding: utf-8 -*-
"""全只读命令真机探测（扩展 real_probe 的 0x9A/0x92）：覆盖 parse 更多解析分支。

全部命令零写入零运动：0x9C(状态)/0x9D(相电流)/0x30(PID读)/0x60/61(编码器读)
/0x90/0x94(V3/V4 单圈)/0x71(V3功率)/0xB2(固件日期)/0xB5(型号)/0x79(读ID)。
用法(Jetson): python3 full_read_probe.py static | dynamic
  static  = 静止段: 逐电机发全部只读命令
  dynamic = 动态段: 循环读 ID5 0x9C——需用户同时均匀来回转动 ID5 输出轴
前置: source ~/ROS2/arm_ws/install/setup.bash（注册表参数来自界面 2026-08 备份）
"""
import socket
import struct
import sys
import time

from arm_protocol import parse

# 注册表真实参数: id -> {proto, gear, dir}
REG = {
    1: {"proto": "V3", "gear": 6, "dir": -1},
    2: {"proto": "V43", "gear": 1, "dir": 1},
    3: {"proto": "V43", "gear": 1, "dir": 1},
    4: {"proto": "V44", "gear": 1, "dir": 1},
    5: {"proto": "V44", "gear": 1, "dir": 1},
}

S = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
S.bind(("can0",))


def send(cid, data):
    S.send(struct.pack("=IB3x8s", cid, len(data), data))


def drain(timeout=0.2, max_frames=6):
    """收窗内收集全部回复帧"""
    S.settimeout(timeout)
    got = []
    for _ in range(max_frames):
        try:
            f = S.recv(72)
            rcid = struct.unpack("=I", f[:4])[0] & 0x1FFFFFFF
            got.append((rcid, f[8:16]))
        except socket.timeout:
            break
    S.settimeout(None)
    return got


def show(mid, rcid, rdata, tag):
    cfg = REG[mid]
    out = parse.parse_reply(cfg["proto"], rcid, rdata, cfg)
    if out:
        print(f"  [{tag}] ID{mid} <- {rcid:03X} {bytes(rdata).hex(' ').upper()} | {out['summary']}")
    else:
        print(f"  [{tag}] ID{mid} <- {rcid:03X} {bytes(rdata).hex(' ').upper()} | (无法识别)")


def query(mid, cmd, payload=None, tag=""):
    cfg = REG[mid]
    data = payload if payload is not None else bytes([cmd, 0, 0, 0, 0, 0, 0, 0])
    send(0x140 + mid, data)
    frames = drain()
    if not frames:
        print(f"  [{tag}] ID{mid} cmd=0x{cmd:02X}: 无回复")
        return
    for rcid, rdata in frames:
        show(mid, rcid, rdata, tag or f"0x{cmd:02X}")


def static():
    print("== 静止段: 全只读命令 (零写入零运动) ==")
    # ID1 (V3 旧款): 0x60-64/写类实测无效不发; 0x30 读 PID 六参数无参
    for cmd in [0x9C, 0x9D, 0x90, 0x94, 0x30, 0x71, 0xB2, 0xB5, 0x79]:
        payload = bytes([0x79, 0, 1, 0, 0, 0, 0, 0]) if cmd == 0x79 else None
        query(1, cmd, payload)
        time.sleep(0.12)
    # ID2/3 (V43) / ID4/5 (V44): V4 读族; 0x30 带 PID 索引 1
    for mid in (2, 3, 4, 5):
        for cmd in [0x9C, 0x9D, 0x30, 0x94, 0x60, 0x61, 0xB2, 0xB5, 0x79]:
            if cmd == 0x30:
                payload = bytes([0x30, 1, 0, 0, 0, 0, 0, 0])
            elif cmd == 0x79:
                payload = bytes([0x79, 0, 1, 0, 0, 0, 0, 0])
            else:
                payload = None
            query(mid, cmd, payload)
            time.sleep(0.12)
    print("== 静止段完成 ==")


def dynamic():
    print("== 动态段: 请匀速来回转动 ID5 末端输出轴约 12 秒 ==")
    for i in range(12):
        send(0x140 + 5, bytes([0x9C, 0, 0, 0, 0, 0, 0, 0]))
        frames = drain(0.15)
        for rcid, rdata in frames:
            show(5, rcid, rdata, f"t{i}")
        time.sleep(0.5)
    # 收尾: 0x92 对比静止读数
    query(5, 0x92, tag="END-0x92")
    print("== 动态段完成(只读) ==")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "static"
    (static if mode == "static" else dynamic)()
