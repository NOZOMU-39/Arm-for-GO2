# -*- coding: utf-8 -*-
"""帧到达间隔分析:判断丢帧形态(周期空洞 vs 均匀)。
用途:Jetson/主机侧验证 HI91 921600 收流完整性——好帧率应≈目标、dt>1.6ms 空洞≈0。
用法:python3 imu_dt.py /dev/ttyUSB0 /dev/ttyUSB1 --secs 8
踩坑(2026-09-08 修正):丢帧真根因=termios lflag ECHO 残留(漏清 ECHO 时 n_tty 回显占
USB 带宽→921600 每 ~15ms 丢整帧 933fps),本工具已内置 lflag 全清修复,open 即满速;
09-06「写 1 字节激活」定论已废。同步用 len==0x4C 校验+逐字节滑动(2026-09-08 v2,
滤除 payload 伪 5A A5 伪同步——CRC 门控的 dt 统计不受伪帧影响但跳帧会吃真帧)。
另:满速收流后 close 可致 ch341 死锁(后续 open 永久挂起),详见 AGENTS.md 已知坑表。"""
import os, time, termios, argparse, struct
from collections import Counter

HI91_LEN = 0x004C   # len 字段固定
FRAME = 82          # 6 头 + 76 payload

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
    at[3] = 0  # lflag 全清(关键:清 ECHO 回显组)。2026-09-08 实锤:ECHO 残留致 n_tty 回显占 USB 带宽,921600 下每~15ms 丢整帧 933fps;清后 open 即 999.9fps 满速
    at[6][termios.VMIN] = 1
    at[6][termios.VTIME] = 2
    termios.tcsetattr(fd, termios.TCSANOW, at)
    at = termios.tcgetattr(fd)
    at[4] = at[5] = termios.B921600
    termios.tcsetattr(fd, termios.TCSANOW, at)
    start = time.time(); buf = b""; t0 = None
    dts = []
    len_bad = crc_bad = 0
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
            if len(buf) < FRAME: break
            if struct.unpack("<H", buf[2:4])[0] != HI91_LEN:
                len_bad += 1
                buf = buf[1:]; continue   # 逐字节滑动,滤伪同步
            crcgot = buf[4] | (buf[5] << 8)
            if crc16_xmodem(buf[0:4] + buf[6:FRAME]) == crcgot:
                now = time.time()
                if t0 is not None:
                    dts.append((now - t0) * 1000.0)
                t0 = now
            else:
                crc_bad += 1
            buf = buf[FRAME:]
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
            f"max={max(dts):.2f}ms len错={len_bad} crc错={crc_bad} 分布ms(0~11)={top}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("ports", nargs="+")
    ap.add_argument("--secs", type=float, default=6.0)
    a = ap.parse_args()
    for p in a.ports:
        print(analyze(p, a.secs), flush=True)
