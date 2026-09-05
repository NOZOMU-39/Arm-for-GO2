# -*- coding: utf-8 -*-
"""低势能自落位参考校正工具(V4 甩动丢圈软件折回) —— 2026-09-06

用途: 急停/掉电甩动丢圈后, 臂自落低势能谷 → 读 0x92 vs 档案 restDeg →
     差 ≈ N×turnDeg → E4 += N×turnDeg(纯软件折回, 零 ROM 写入)。
用法(Jetson, tmux ops):
    source ~/ROS2/arm_ws/install/setup.bash && python3 rest_calib.py        # dry-run
    python3 rest_calib.py --apply                                           # 落盘 registry.json(自动备份)
前置: registry.json 每台 V4 已标 restDeg/turnDeg(谷位期望/一圈输出角);
      arm 在低势能谷位(自落到位); 总线仅本工具活动(勿与界面 TCP 并发轮询)。
安全: 全只读+档案写, 不碰电机 ROM/运动。
"""
import argparse
import json
import shutil
import socket
import struct
import time

from arm_controller.rest import lost_turns
from arm_protocol import parse

REG_PATH = "/home/nvidia/ROS2/arm_ws/config/registry.json"
CAND = {1: "V3", 2: "V43", 3: "V43", 4: "V44", 5: "V44"}


def read_registry():
    with open(REG_PATH, encoding="utf-8") as f:
        return json.load(f)


def write_registry(motors):
    shutil.copy(REG_PATH, REG_PATH + ".bak-restcalib")
    with open(REG_PATH, "w", encoding="utf-8") as f:
        json.dump(motors, f, indent=1, ensure_ascii=False)


def read_angle(mid, proto, s):
    s.send(struct.pack("=IB3x8s", 0x140 + mid, 8, bytes([0x92, 0, 0, 0, 0, 0, 0, 0])))
    time.sleep(0.12)
    try:
        f = s.recv(72)
        rcid = struct.unpack("=I", f[:4])[0] & 0x1FFFFFFF
        meta = {"proto": proto, "gear": 1, "dir": 1, "id": mid}
        out = parse.parse_reply(proto, rcid, f[8:16], meta)
        return out["values"]["pos"]
    except (socket.timeout, KeyError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="落盘 E4(默认 dry-run 只打印)")
    ap.add_argument("--mark-rest", action="store_true",
                    help="标定谷位档案: 读当前角 → 写 restDeg/restDegDate(⚠️ 人工确认臂在谷位后执行)")
    ap.add_argument("--tol", type=float, default=2.0, help="谷位散布容差°(须 < turnDeg/2)")
    args = ap.parse_args()

    motors = read_registry()
    s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    s.bind(("can0",))
    s.settimeout(0.5)

    if args.mark_rest:
        # ---- 谷位档案标定模式: 结构参数, 变更后必须人工重标 ----
        import datetime
        today = datetime.date.today().isoformat()
        print("== 标定谷位档案(--mark-rest) ==")
        print("⚠️ 前提: 臂已无电自落低势能谷位, 且刚完成设零(显示角=机械真实角)")
        print("   本操作把『当前读角』写为 restDeg——结构更改/重新设零后必须重跑本命令")
        n_ok = 0
        for m in motors:
            mid = m.get("id")
            if m.get("proto") == "V3":
                continue
            read = read_angle(mid, m["proto"], s)
            if read is None:
                print(f"ID{mid}: 0x92 无回复, 跳过")
                continue
            m["restDeg"] = round(read, 4)
            m["restDegDate"] = today
            n_ok += 1
            print(f"ID{mid}: restDeg ← {read:.2f}° (标定 {today})")
        if n_ok:
            write_registry(motors)
            print(f"== 已落盘 {n_ok} 台谷位档案, 备份 .bak-restcalib ==")
            print("⚠️ 界面注册表(Windows)的 restDeg/restDegDate 需同步; 换电机时核对 turnDeg")
        else:
            print("== 无电机可标定(总线无回复?) ==")
        return

    print("== 自落参考校正", "(apply 落盘)" if args.apply else "(dry-run)", "==")
    changed = []
    for m in motors:
        mid = m.get("id")
        if m.get("proto") == "V3":
            continue  # V3 无此机制(0x92 校准/E0 档案体系)
        rest, turn, e4 = m.get("restDeg"), m.get("turnDeg"), m.get("E4") or 0.0
        date = m.get("restDegDate") or "?"
        if rest is None or not turn:
            print(f"ID{mid}: 档案缺 restDeg/turnDeg, 跳过(先跑 --mark-rest 标定谷位)")
            continue
        read = read_angle(mid, m["proto"], s)
        if read is None:
            print(f"ID{mid}: 0x92 无回复, 跳过")
            continue
        n = lost_turns(read, rest, turn, tol_deg=args.tol)
        if n is None:
            print(f"ID{mid}: 读 {read:.2f}° vs 谷位 {rest}°(标定 {date}) → 非整圈偏差, 不校, 交人工")
            print(f"       可能: ①臂不在谷位(手动移回或等自落) ②谷位档案过期(结构更改/重设零后没重标 → 跑 --mark-rest)")
            continue
        if n == 0:
            print(f"ID{mid}: 读 {read:.2f}° 与谷位一致(差 {read-rest:+.2f}°, 档案 {date}), 无需校正 ✅")
            continue
        new_e4 = e4 + n * turn
        print(f"ID{mid}: 丢圈 N={n:+d} (读 {read:.2f}° → 谷位 {rest}°, 档案 {date}) → E4 {e4:+.2f} → {new_e4:+.2f}°")
        m["E4"] = round(new_e4, 4)
        changed.append(mid)
    if args.apply and changed:
        write_registry(motors)
        print(f"== 已落盘 registry.json(E4 更新: ID{changed}), 备份 .bak-restcalib ==")
        print("⚠️ 界面注册表(Windows 机械臂注册表.json)的 E4 需同步——重新导入或手工同步")
    elif changed:
        print("== dry-run: 加 --apply 落盘 ==")
    else:
        print("== 无校正项 ==")


if __name__ == "__main__":
    main()
