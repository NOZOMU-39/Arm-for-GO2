#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IMU 0x91 采集文件离线分析(静态基线第一版)。

读 recorder.py 落盘的纯帧流 -> 逐帧解 payload -> 输出中文报告:
  帧率/时长/帧间隔统计(system_time 丢帧检测)、各轴 均值/标准差(噪声抖动)、
  yaw/roll/pitch 漂移(前后半段均值差+总漂移)、温度、CRC 已被 recorder 过滤(此处不再验)。

用法: python analyzer.py capture.bin
0x91 payload 字段(手册 7.2,全小端 float IEEE-754):
  tag u8 / main_status u16 / temp i8 / air_pressure f32 / system_time u32 ms /
  acc f32x3 G / gyr f32x3 deg/s / mag f32x3 uT(6DoF无效) / roll f32 / pitch f32 / yaw f32 / quat f32x4
"""
import struct
import sys

SOF = b"\x5A\xA5"
PAYLOAD = 76
STRUCT_FMT = "<BBhiI9f4f"  # tag, status u16, temp i8 -> "<Bhi..." 修正见下


def parse_payload(p: bytes):
    # 手动按偏移解,避免 fmt 猜错:tag@0 u8, main_status@1 u16, temp@3 i8,
    # pressure@4 f32, system_time@8 u32, acc@12/gyr@24/mag@36 各3f32,
    # roll@48 pitch@52 yaw@56 f32, quat@60 4f32
    tag = p[0]
    main_status = struct.unpack_from("<H", p, 1)[0]
    temp = struct.unpack_from("<b", p, 3)[0]
    pressure = struct.unpack_from("<f", p, 4)[0]
    st = struct.unpack_from("<I", p, 8)[0]
    acc = struct.unpack_from("<3f", p, 12)
    gyr = struct.unpack_from("<3f", p, 24)
    mag = struct.unpack_from("<3f", p, 36)
    rpy = struct.unpack_from("<3f", p, 48)
    quat = struct.unpack_from("<4f", p, 60)
    return dict(tag=tag, status=main_status, temp=temp, pressure=pressure, st=st,
                acc=acc, gyr=gyr, mag=mag, rpy=rpy, quat=quat)


def load_frames(path: str):
    data = open(path, "rb").read()
    frames = []
    i = 0
    n = len(data)
    while True:
        idx = data.find(SOF, i)
        if idx < 0 or idx + 6 > n:
            break
        length = data[idx + 2] | (data[idx + 3] << 8)
        total = 6 + length
        if idx + total > n:
            break
        if length == PAYLOAD:
            frames.append(parse_payload(data[idx + 6:idx + total]))
        i = idx + total
    return frames


def stats(vals):
    """均值/标准差"""
    m = sum(vals) / len(vals)
    var = sum((v - m) ** 2 for v in vals) / len(vals)
    return m, var ** 0.5


def fmt_axis(label, xyz, unit):
    m = [sum(a) / len(a) for a in zip(*xyz)]
    s = [stats(a)[1] for a in zip(*xyz)]
    return f"{label}: 均值 X={m[0]:+.4f} Y={m[1]:+.4f} Z={m[2]:+.4f} | 抖动σ X={s[0]:.4f} Y={s[1]:.4f} Z={s[2]:.4f} ({unit})"


def main():
    if len(sys.argv) < 2:
        print("用法: python analyzer.py capture.bin")
        return
    frames = load_frames(sys.argv[1])
    if not frames:
        print("没有解出任何帧")
        return
    n = len(frames)
    dur_s = (frames[-1]["st"] - frames[0]["st"]) / 1000.0
    print(f"===== 静态基线分析: {n} 帧 =====")
    print(f"时长(按帧内system_time): {dur_s:.2f} s | 平均帧率: {n / dur_s:.1f} fps" if dur_s > 0 else "system_time 异常")

    # 丢帧检测阈值按采样率自适应:读同目录 .meta 的 baud(460800→500Hz 期望2ms,921600→1000Hz 期望1ms)
    gap_ms = 2
    meta_path = sys.argv[1] + ".meta"
    try:
        with open(meta_path, encoding="utf-8") as mf:
            for line in mf:
                if line.startswith("baud="):
                    baud = int(line.split("=")[1].split()[0])
                    gap_ms = 1 if baud >= 921600 else 2
    except FileNotFoundError:
        pass

    # 帧间隔/丢帧检测:system_time ms 单调性
    sts = [f["st"] for f in frames]
    jumps = 0
    max_gap = 0
    for a, b in zip(sts, sts[1:]):
        gap = (b - a) % 86400000  # 24h 回绕
        if gap > gap_ms:  # 期望 1ms@1kHz / 2ms@500Hz;超阈值视为丢帧
            jumps += 1
            max_gap = max(max_gap, gap)
    print(f"丢帧(间隔>{gap_ms}ms)次数: {jumps} | 最大间隔: {max_gap} ms")

    # 温度
    temps = [f["temp"] for f in frames]
    print(f"温度: {temps[0]} ℃ ... {temps[-1]} ℃ (变化 {temps[-1] - temps[0]:+.1f})")

    print(fmt_axis("加速度", [f["acc"] for f in frames], "G(静态应≈0,0,±1)"))
    print(fmt_axis("角速度", [f["gyr"] for f in frames], "deg/s(静态应≈0)"))

    # 姿态角抖动与漂移
    half = n // 2
    names = ["roll", "pitch", "yaw"]
    print("姿态角(deg):")
    for k, name in enumerate(names):
        first = [f["rpy"][k] for f in frames[:half]]
        second = [f["rpy"][k] for f in frames[half:]]
        allv = [f["rpy"][k] for f in frames]
        m1, s1 = stats(allv)
        # 漂移用各帧与首帧差值的线性端点(总漂移)
        drift = allv[-1] - allv[0]
        print(f"  {name}: 均值={m1:+.3f} 抖动σ={s1:.4f} 总漂移(首尾差)={drift:+.4f} deg "
              f"(前半均值{stats(first)[0]:+.3f} 后半均值{stats(second)[0]:+.3f})")

    # system_time 与真实采集时长的差(每帧实际间隔)


if __name__ == "__main__":
    main()
