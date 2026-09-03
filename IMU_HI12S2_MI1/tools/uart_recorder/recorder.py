#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IMU 0x91 流采集器(Windows/UART 版原型;Jetson 版换收帧源为 SocketCAN 即可复用)。

读串口 -> CRC-16/XMODEM 校验(错帧丢弃) -> 好帧整帧(82B,含头与CRC)连续落盘 -> 汇总。
落盘格式:纯帧流,每帧 82B(5A A5 + len + CRC + 76B payload),无分隔;重放时按 5A A5 帧头同步即可。

用法:
    python recorder.py --port COM6 --baud 460800 --seconds 60 --out capture.bin
跑完后 stdout 打印 REC_OK / 统计;数据文件供 analyzer.py 离线分析。

CRC 校验与 0x91 帧结构依据:Database\\IMU\\HI12系列指令与编程手册.pdf 7.1~7.4 节。
"""
import argparse
import serial
import time

SOF = b"\x5A\xA5"
FRAME_TOTAL = 82  # 头2 + len2 + CRC2 + data76


def crc16_xmodem(data: bytes) -> int:
    """手册 7.4:CRC-16/XMODEM(0x1021,初值 0,无反转无异或),范围=帧头+长度+数据域。"""
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def parse_and_drain(buf: bytes, out, stats):
    """从 buf 中解帧:好帧写入 out(整帧82B),坏帧丢弃计数。返回剩余 buf。"""
    i = 0
    n = len(buf)
    while True:
        idx = buf.find(SOF, i)
        if idx < 0 or idx + 6 > n:
            break
        length = buf[idx + 2] | (buf[idx + 3] << 8)
        total = 6 + length
        if idx + total > n:
            break  # 帧没收全
        frame = buf[idx:idx + total]
        crc_recv = frame[4] | (frame[5] << 8)
        crc_calc = crc16_xmodem(frame[:4] + frame[6:])
        if crc_recv == crc_calc and length == 76:
            out.write(frame)
            stats["good"] += 1
        else:
            stats["bad"] += 1
        i = idx + total
    return buf[i:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM6")
    ap.add_argument("--baud", type=int, default=460800)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--out", default="capture.bin")
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.5)
    stats = {"good": 0, "bad": 0}
    t0 = time.time()
    last = t0
    buf = b""
    print(f"[recorder] {args.port} @ {args.baud}, {args.seconds}s -> {args.out}(原始帧落盘,坏帧丢弃) 保持IMU静止", flush=True)
    with open(args.out, "wb") as f:
        while time.time() - t0 < args.seconds:
            chunk = ser.read(8192)
            if chunk:
                buf += chunk
                buf = parse_and_drain(buf, f, stats)
                if len(buf) > 262144:  # 防垃圾流无限膨胀
                    buf = buf[-8192:]
            if time.time() - last >= 10:
                el = time.time() - t0
                print(f"  t={el:5.0f}s  好帧={stats['good']:7d}  坏帧={stats['bad']:4d}  帧率={stats['good']/el:6.1f} fps", flush=True)
                last = time.time()
    ser.close()
    el = time.time() - t0
    print("=" * 56)
    print(f"REC_OK seconds={el:.1f} good={stats['good']} bad={stats['bad']} "
          f"rate={stats['good']/el:.1f}fps out={args.out}")
    with open(args.out + ".meta", "w", encoding="utf-8") as m:
        m.write(f"port={args.port} baud={args.baud} seconds={el:.1f} good={stats['good']} "
                f"bad={stats['bad']} rate={stats['good']/el:.1f}\n")


if __name__ == "__main__":
    main()
