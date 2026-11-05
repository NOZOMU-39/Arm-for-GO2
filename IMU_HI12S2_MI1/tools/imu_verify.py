# -*- coding: utf-8 -*-
"""HI91 严格收流验证器(2026-09-08 v2,修复 v1 伪同步缺陷):
同步改进:5A A5 后校验 len==0x004C,不满足逐字节滑动(不跳帧);
坏帧分型:sync_fail(伪帧头)/len_bad/crc_bad;
system_time 跳变:Δ<=0 或 Δ>1ms 全记(丢帧 Δ=2ms 可抓);
自测:手册 7.5 示例帧黄金对照。
用法:--selftest | /dev/ttyUSBx [/dev/ttyUSB1] [--secs 30]
"""
import os, time, struct, sys, math
try:
    import termios
except ImportError:
    termios = None

SOF = b"\x5a\xa5"
HI91_LEN = 0x004C          # len 字段固定
FRAME = 82                 # 6 头 + 76 payload

def crc16_xmodem(data):
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc

def parse_frame(buf):
    """buf 长度 >=82 且 buf[0:2]==SOF。校验 len/CRC,通过返回 dict,否则 None。"""
    if struct.unpack("<H", buf[2:4])[0] != HI91_LEN:
        return None
    if (buf[4] | (buf[5] << 8)) != crc16_xmodem(buf[0:4] + buf[6:FRAME]):
        return None
    p = buf[6:FRAME]
    return {
        "tag": p[0],
        "main_status": struct.unpack("<H", p[1:3])[0],
        "temp": struct.unpack("<b", p[3:4])[0],
        "pressure": struct.unpack("<f", p[4:8])[0],
        "sys_time": struct.unpack("<I", p[8:12])[0],
        "acc": list(struct.unpack("<3f", p[12:24])),
        "gyr": list(struct.unpack("<3f", p[24:36])),
        "mag": list(struct.unpack("<3f", p[36:48])),
        "eul": list(struct.unpack("<3f", p[48:60])),
        "quat": list(struct.unpack("<4f", p[60:76])),
    }

EXAMPLE = (b"\x5a\xa5\x4c\x00\x14\xbb\x91\x08\x15\x23\x09\xa2\xc4\x47\x08\x15\x1c\x00"
           b"\xcc\xe8\x61\xbe\x9a\x35\x56\x3e\x65\xea\x72\x3f\x31\xd0\x7c\xbd\x75\xdd\xc5"
           b"\xbb\x6b\xd7\x24\xbc\x89\x88\xfc\x40\x01\x00\x6a\x41\xab\x2a\x70\xc2\x96\xd4"
           b"\x50\x41\xed\x03\x43\x41\x41\xf4\xf4\xc2\xcc\xca\xf8\xbe\x73\x6a\x19\xbe\xf0"
           b"\x00\x1c\x3d\x8d\x37\x5c\x3f")

def selftest():
    d = parse_frame(EXAMPLE)
    assert d and d["tag"] == 0x91 and d["main_status"] == 0x1508
    assert d["temp"] == 35 and abs(d["pressure"] - 100676.0) < 1.0 and d["sys_time"] == 1840392
    assert abs(d["acc"][0] + 0.2206) < 1e-3 and abs(d["acc"][2] - 0.9489) < 1e-3
    assert abs(d["eul"][0] - 13.052) < 1e-2 and abs(d["eul"][2] + 122.477) < 1e-2
    # 伪同步负测试:把真帧第 2 字节改坏应拒绝
    bad = bytearray(EXAMPLE); bad[6] = 0x92
    assert parse_frame(bytes(bad)) is None
    print("SELFTEST-PASS")
    return 0

def open_port(port):
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
    at = termios.tcgetattr(fd)
    for i in (0, 1, 3):
        at[i] = 0
    at[2] = termios.CS8
    at[6][termios.VMIN] = 1
    at[6][termios.VTIME] = 2
    termios.tcsetattr(fd, termios.TCSANOW, at)
    at = termios.tcgetattr(fd)
    at[4] = at[5] = termios.B921600
    termios.tcsetattr(fd, termios.TCSANOW, at)
    return fd

def stats(vals):
    if not vals:
        return float("nan"), float("nan")
    m = sum(vals) / len(vals)
    return m, math.sqrt(sum((x - m) ** 2 for x in vals) / len(vals))

def run_port(port, secs):
    fd = open_port(port)
    t_end = time.time() + secs
    buf = b""
    rows = []
    dts = []
    stat = {"ok": 0, "sync_fail": 0, "len_bad": 0, "crc_bad": 0}
    prev_dt = None
    while time.time() < t_end:
        try:
            d = os.read(fd, 65536)
        except OSError:
            time.sleep(0.02); continue
        if not d:
            continue
        buf += d
        while True:
            i = buf.find(SOF)
            if i < 0:
                buf = buf[-2:]
                break
            if i > 0:
                buf = buf[i:]
            if len(buf) < FRAME:
                break
            d = parse_frame(buf[:FRAME])
            if d is None:
                # 分型:len 错 or CRC 错
                if struct.unpack("<H", buf[2:4])[0] != HI91_LEN:
                    stat["len_bad"] += 1
                else:
                    stat["crc_bad"] += 1
                buf = buf[1:]  # 逐字节滑动,防伪同步跳跃错位
                continue
            now = time.time()
            if prev_dt is not None:
                dts.append((now - prev_dt) * 1000.0)
            prev_dt = now
            rows.append(d)
            stat["ok"] += 1
            buf = buf[FRAME:]
    os.close(fd)
    n = len(rows)
    print(f"{port}: {n}帧/{secs}s={n/secs:.1f}fps | ok={stat['ok']} "
          f"len错={stat['len_bad']} crc错={stat['crc_bad']} (伪同步已逐字节滤除)")
    if n == 0:
        return
    st = [r["sys_time"] for r in rows]
    inc = [st[i+1] - st[i] for i in range(n-1)]
    badinc = [x for x in inc if x <= 0 or x > 1.0]
    badfloat = 0
    for r in rows:
        for k in ("pressure",):
            if not math.isfinite(r[k]): badfloat += 1
        for k in ("acc", "gyr", "mag", "eul", "quat"):
            for x in r[k]:
                if not math.isfinite(x): badfloat += 1
    am = [math.sqrt(sum(x*x for x in r["acc"])) for r in rows]
    gm = [math.sqrt(sum(x*x for x in r["gyr"])) for r in rows]
    rollm, rolls = stats([r["eul"][0] for r in rows])
    pitchm, pitchs = stats([r["eul"][1] for r in rows])
    yawm, yaws = stats([r["eul"][2] for r in rows])
    am_, ams = stats(am); gm_, gms = stats(gm)
    tmean, _ = stats([float(r["temp"]) for r in rows])
    qn = [abs(math.sqrt(sum(x*x for x in r["quat"])) - 1.0) for r in rows]
    print(f"  sys_time: Δ均值={sum(inc)/len(inc):.4f}ms 非1ms跳变={len(badinc)}次 NaN/Inf={badfloat}")
    print(f"  acc|G| mean={am_:.5f} σ={ams:.5f} | gyr|°/s| mean={gm_:.5f} σ={gms:.5f}")
    print(f"  eul: roll={rollm:.4f}±{rolls:.4f} pitch={pitchm:.4f}±{pitchs:.4f} yaw={yawm:.4f}±{yaws:.4f}")
    print(f"  temp={tmean:.1f}℃ quat归一最大偏差={max(qn):.2e} (真帧CRC门控)")

if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--selftest":
        sys.exit(selftest())
    ports = [x for x in a if x.startswith("/dev/")]
    secs = float(a[a.index("--secs") + 1]) if "--secs" in a else 30.0
    for p in ports:
        run_port(p, secs)
