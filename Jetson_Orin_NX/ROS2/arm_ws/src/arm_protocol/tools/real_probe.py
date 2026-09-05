# -*- coding: utf-8 -*-
"""真机只读验证工具: 逐 id 发 0x9A 状态读(零写入零运动), 有回复则补 0x92 读角。

前置条件: 电机 24V 上电 + USB-CAN(PCAN) 插 Jetson + 电机接入 can0 总线。
用法(Jetson 上, 建议在 tmux ops 会话):
    source ~/ROS2/arm_ws/install/setup.bash && python3 tools/real_probe.py
验收对照: 0x92 读数与 Windows 工具(交互界面/上位机)同电机同时刻读数一致(±0.01°)。
2026-09-05 首跑: 总线无外设 → 预期 8 个 ID 全静默; 接电机后再跑即达真机验证。
"""
import socket, struct
from arm_protocol import parse
from arm_protocol.bytes_ops import hx

# 候选电机: id -> proto (注册表记忆; 探测阶段仅影响解析分派, 命令帧同构)
CAND = {1: "V3", 2: "V43", 3: "V43", 4: "V44", 5: "V44"}

s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
s.bind(("can0",))
s.settimeout(0.08)

def send(can_id, data):
    s.send(struct.pack("=IB3x8s", can_id, len(data), data))

def recv_one():
    try:
        f = s.recv(72)
        cid = struct.unpack("=I", f[:4])[0] & 0x1FFFFFFF
        return cid, f[8:16]
    except socket.timeout:
        return None, None

print("== 只读探测 0x9A (id 1~8) ==")
online = []
for mid in range(1, 9):
    send(0x140 + mid, bytes([0x9A, 0, 0, 0, 0, 0, 0, 0]))
    rcid, rdata = recv_one()
    if rcid is None:
        continue
    online.append(mid)
    # 0x9A 回复 V3/V44 布局同构(D2=V44 MOS 温), 用候选 proto 解析
    p = CAND.get(mid, "V44")
    out = parse.parse_reply(p, rcid, rdata, {"id": mid, "gear": 1, "dir": 1, "proto": p})
    print(f"  ID {mid}: 回帧 {hx(rdata)} | {out['summary'] if out else '?'}")

print(f"== 在线电机: {online or '无(总线空/电机未上电未接入)'} ==")
if online:
    print("== 补读 0x92 多圈角 (只读) ==")
    for mid in online:
        send(0x140 + mid, bytes([0x92, 0, 0, 0, 0, 0, 0, 0]))
        rcid, rdata = recv_one()
        if rcid is None:
            print(f"  ID {mid}: 0x92 无回复"); continue
        p = CAND.get(mid, "V44")
        m = {"id": mid, "gear": 1, "dir": 1, "proto": p}
        out = parse.parse_reply(p, rcid, rdata, m)
        print(f"  ID {mid}: {hx(rdata)} | {out['summary'] if out else '?'}")
print("== 探测结束(只读,未写任何东西) ==")
