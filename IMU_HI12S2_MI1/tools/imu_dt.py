# -*- coding: utf-8 -*-
"""帧到达间隔分析:判断丢帧形态(周期空洞 vs 均匀)。
用途:Jetson/主机侧验证 HI91 921600 收流完整性——好帧率应≈目标、dt>1.6ms 空洞≈0。
用法:python3 imu_dt.py /dev/ttyUSB0 /dev/ttyUSB1 --secs 8
踩坑(2026-09-06 Jetson 实测定论):ch341 驱动在 tegra-xusb 上枚举后 921600 收流固有丢
~6.8%(933fps,每 ~15ms 缺整帧,CRC 全 0)——**采集侧 open 后先写 1 字节(0x00)激活,
即达 999.9fps 完整**;拔插/重启后需重新激活。详见 IMU_HI12S2_MI1/AGENTS.md 已知坑表。"""
import os, time, termios, argparse, struct
from collections import Counter

def crc16_xmodem(data):
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc

def analyze(port, secs):
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
    at = termios.tcgetattr(fd)
    at[0] &= ~(termios.IGNBRK | termios.BRKINT | termios.PARMRK | termios.ISTRIP |
               termios.INLCR | termios.IGNCR | termios.ICRNL | termios.IXON)
    at[1] &= ~(termios.OPOST)
    at[2] &= ~(termios.CSIZE | termios.PARENB | termios.CSTOPB)
    at[2] |= termios.CS8
    at[3] &= ~(termios.ECHONL | termios.ICANON | termios.ISIG | termios.IEXTEN)
    at[6][termios.VMIN] = 1
    at[6][termios.VTIME] = 2
    termios.tcsetattr(fd, termios.TCSANOW, at)
    at = termios.tcgetattr(fd)
    at[4] = at[5] = termios.B921600
    termios.tcsetattr(fd, termios.TCSANOW, at)
    start = time.time(); buf = b""; t0 = None
    dts = []
    while time.time() - start < secs:
        try:
            d = os.read(fd, 65536)
        except OSError:
            time.sleep(0.02); continue
        if not d: continue
        buf += d
        while True:
            i = buf.find(b"\x5a\xa5")
            if i < 0:
                buf = buf[-2:]; break
            if i > 0: buf = buf[i:]
            if len(buf) < 8: break
            (ln,) = struct.unpack("<H", buf[2:4])
            fl = ln + 6
            if fl < 8 or fl > 400:
                buf = buf[4:]; continue
            if len(buf) < fl: break
            crcgot = buf[4] | (buf[5] << 8)
            if crc16_xmodem(buf[0:4] + buf[6:fl]) == crcgot:
                now = time.time()
                if t0 is not None:
                    dts.append((now - t0) * 1000.0)
                t0 = now
            buf = buf[fl:]
    os.close(fd)
    n = len(dts)
    if n == 0: return f"{port}: no frames"
    mean = sum(dts) / n
    over = [x for x in dts if x > 1.6]
    over2 = [x for x in dts if x > 2.6]
    hist = Counter(int(x) for x in dts)
    top = sorted(hist.items())[:12]
    return (f"{port}: {n}帧 mean={mean:.4f}ms  "
            f"dt∈(1.6,2.6]ms={len(over)-len(over2)}次 dt>2.6ms={len(over2)}次 "
            f"max={max(dts):.2f}ms 分布ms(0~11)={top}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("ports", nargs="+")
    ap.add_argument("--secs", type=float, default=6.0)
    a = ap.parse_args()
    for p in a.ports:
        print(analyze(p, a.secs), flush=True)
