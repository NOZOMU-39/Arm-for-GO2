# -*- coding: utf-8 -*-
"""落盘格式与录制目录（M2 数据契约，2026-11-06 定；改前先看 03_通信与IMU「数据契约」）。

一条记录固定 **64 字节**，全小端：

    offset  size  field
    0       8     t_rx_ns    u64   接收端 CLOCK_MONOTONIC（ns），唯一时间基准
    8       4     seq        u32   本进程内该设备帧序号（对账用）
    12      4     t_sys_ms   u32   帧内 system_time（只判丢帧，会回绕）
    16      12    acc        3f    单位 g（设备原单位，不换成 m/s^2）
    28      12    gyr        3f    单位 deg/s
    40      16    quat       4f    WXYZ
    56      2     status     u16   原始状态字
    58      1     temp       i8    degC
    59      5     -          5x    保留（以后加字段优先吃掉，不改总长）

为什么定长：逐条校验、mmap 直接扫、MATLAB/Python 用 struct 一行读，不用解析 JSON。
为什么 acc 存 g 不存 m/s^2：与设备原始输出、IMU AGENTS 表格一致，少一层换算歧义；
导出 CSV 时也保持 g，需要 SI 的读者自己乘 9.80665（types.py 有常量）。

目录结构（一次录制 = 一个目录）：

    ~/imu_data/<UTC时间戳>_<标签>/
        meta.json      格式版本、列定义、起止时间、两路 UUID/岗位、配置快照、统计
        muzzle.bin     岗位名的定长记录流
        base.bin
        KEEP           存在即表示人工保护（配额不删）

无 meta.json 的 bin 视为孤儿：写入过程中进程崩了才会出现，导出工具拒绝猜。
"""
import json
import os
import struct
import time

from .types import ImuSample

SCHEMA = "imu-record-v1"
FMT = "<QII3f3f4fHb5x"
RECORD = struct.Struct(FMT)
RECORD_SIZE = RECORD.size
assert RECORD_SIZE == 64, "记录长度必须 64 字节，改动请同步 03 契约与 README"

FIELDS = (
    "t_rx_ns", "seq", "t_sys_ms", "ax", "ay", "az", "gx", "gy", "gz",
    "qw", "qx", "qy", "qz", "status", "temperature",
)
UNITS = {
    "t_rx_ns": "ns (CLOCK_MONOTONIC)",
    "t_sys_ms": "ms (device counter, wraps every 24h)",
    "acc": "g",
    "gyr": "deg/s",
    "quat": "WXYZ",
    "temperature": "degC",
}
CSV_COLUMNS = (
    "t_rel_s", "ax", "ay", "az", "gx", "gy", "gz",
    "qw", "qx", "qy", "qz", "status", "temp",
)
META_NAME = "meta.json"
KEEP_NAME = "KEEP"


def pack(sample):
    """ImuSample -> 64 字节。"""
    return RECORD.pack(
        int(sample.t_rx_ns), int(sample.seq) & 0xFFFFFFFF, int(sample.t_sys_ms) & 0xFFFFFFFF,
        float(sample.ax), float(sample.ay), float(sample.az),
        float(sample.gx), float(sample.gy), float(sample.gz),
        float(sample.qw), float(sample.qx), float(sample.qy), float(sample.qz),
        int(sample.status) & 0xFFFF, max(-128, min(127, int(round(sample.temperature)))),
    )


def pack_fields(t_rx_ns, seq, t_sys_ms, acc, gyr, quat, status, temperature):
    """直接从已解析的字段打包（**快路径**）：不构造 ImuSample，采集热点走这里。

    1 kHz × 2 路下每帧省下 dataclass + 属性访问，实测是「掉帧到 937 fps」的主因之一。
    """
    temp = max(-128, min(127, int(round(temperature))))
    return RECORD.pack(
        int(t_rx_ns), int(seq) & 0xFFFFFFFF, int(t_sys_ms) & 0xFFFFFFFF,
        acc[0], acc[1], acc[2], gyr[0], gyr[1], gyr[2],
        quat[0], quat[1], quat[2], quat[3],
        int(status) & 0xFFFF, temp,
    )


def unpack(buf):
    """64 字节 -> 字段字典（比重建 ImuSample 快，导出/校验用）。"""
    if len(buf) != RECORD_SIZE:
        raise ValueError("记录长度应为 %d，实际 %d" % (RECORD_SIZE, len(buf)))
    (t_rx_ns, seq, t_sys_ms, ax, ay, az, gx, gy, gz,
     qw, qx, qy, qz, status, temp) = RECORD.unpack(buf)
    return {
        "t_rx_ns": t_rx_ns, "seq": seq, "t_sys_ms": t_sys_ms,
        "ax": ax, "ay": ay, "az": az, "gx": gx, "gy": gy, "gz": gz,
        "qw": qw, "qx": qx, "qy": qy, "qz": qz,
        "status": status, "temperature": temp,
    }


def to_sample(rec, device="", role=""):
    """字段字典 -> ImuSample（导出/回放用；欧拉量不从记录里取，留给调用方）。"""
    return ImuSample(
        t_rx_ns=rec["t_rx_ns"], device=device, role=role, t_sys_ms=rec["t_sys_ms"],
        ax=rec["ax"], ay=rec["ay"], az=rec["az"],
        gx=rec["gx"], gy=rec["gy"], gz=rec["gz"],
        roll=float("nan"), pitch=float("nan"), yaw=float("nan"),
        qw=rec["qw"], qx=rec["qx"], qy=rec["qy"], qz=rec["qz"],
        temperature=rec["temperature"], status=rec["status"], seq=rec["seq"],
    )


def session_name(tag="", now=None):
    """目录名：UTC 时间戳 + 可选标签（只留安全字符）。"""
    now = time.time() if now is None else now
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))
    safe = "".join(c for c in (tag or "") if c.isalnum() or c in "-_.中文字样")
    safe = safe.strip("-_. ")[:40]
    return stamp + ("_" + safe if safe else "")


def _atomic_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class SessionWriter:
    """一次录制的写端：每个岗位一个 bin，meta.json 在关闭时定稿。

    append 只做 pack + write，不做 fsync（1 kHz 下 fsync 会掉帧）；
    崩溃时最多丢最后几秒，meta 里留 state=recording 便于识别半成品。
    """

    def __init__(self, root, tag="", streams=None, config=None, now=None):
        self.dir = os.path.join(root, session_name(tag, now))
        os.makedirs(self.dir, exist_ok=True)
        self.meta_path = os.path.join(self.dir, META_NAME)
        self.t0_ns = None
        self.closed = False
        self.streams = {}
        for role, info in (streams or {}).items():
            name = (info or {}).get("file") or (role + ".bin")
            fh = open(os.path.join(self.dir, name), "wb", buffering=1024 * 256)
            self.streams[role] = {
                "file": name,
                "device": (info or {}).get("device", ""),
                "role": role,
                "frames": 0,
                "fh": fh,
            }
        self.meta = {
            "schema": SCHEMA,
            "record_size": RECORD_SIZE,
            "fmt": FMT,
            "fields": list(FIELDS),
            "units": UNITS,
            "csv_columns": list(CSV_COLUMNS),
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "created_epoch": time.time() if now is None else now,
            "state": "recording",
            "config": config or {},
            "streams": {},
        }
        _atomic_json(self.meta_path, self.meta)

    def append(self, role, sample):
        st = self.streams.get(role)
        if st is None:
            return False
        if self.t0_ns is None:
            self.t0_ns = sample.t_rx_ns
        st["fh"].write(pack(sample))
        st["frames"] += 1
        return True

    def append_blob(self, role, blob, t_rx_ns=None):
        """快路径：直接写已打包的 64 B 记录（避免再经过 ImuSample）。"""
        st = self.streams.get(role)
        if st is None:
            return False
        if self.t0_ns is None and t_rx_ns is not None:
            self.t0_ns = int(t_rx_ns)
        st["fh"].write(blob)
        st["frames"] += 1
        return True

    def close(self):
        if self.closed:
            return self.meta
        for st in self.streams.values():
            try:
                st["fh"].flush()
                os.fsync(st["fh"].fileno())
                st["fh"].close()
            except OSError:
                pass
        now = time.time()
        self.meta["state"] = "closed"
        self.meta["closed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        self.meta["closed_epoch"] = now
        for role, st in self.streams.items():
            self.meta["streams"][role] = {
                "file": st["file"], "device": st["device"], "role": role,
                "frames": st["frames"], "bytes": st["frames"] * RECORD_SIZE,
            }
        self.meta["t0_ns"] = self.t0_ns
        frames = [v["frames"] for v in self.meta["streams"].values()] or [0]
        self.meta["duration_est_s"] = max(frames) / 1000.0
        _atomic_json(self.meta_path, self.meta)
        self.closed = True
        return self.meta


def load_meta(dirpath):
    with open(os.path.join(dirpath, META_NAME), encoding="utf-8") as fh:
        return json.load(fh)


def has_meta(dirpath):
    return os.path.isfile(os.path.join(dirpath, META_NAME))


def read_stream(dirpath, role, meta=None, limit=None):
    """按记录顺序产出字段字典；limit 为最大条数（None=全部）。"""
    meta = meta or load_meta(dirpath)
    info = (meta.get("streams") or {}).get(role)
    name = (info or {}).get("file") or (role + ".bin")
    path = os.path.join(dirpath, name)
    n = 0
    with open(path, "rb", buffering=1024 * 256) as fh:
        while True:
            buf = fh.read(RECORD_SIZE)
            if len(buf) < RECORD_SIZE:
                return
            yield unpack(buf)
            n += 1
            if limit is not None and n >= limit:
                return


def dir_size(dirpath):
    total = 0
    for name in os.listdir(dirpath):
        p = os.path.join(dirpath, name)
        if os.path.isfile(p):
            total += os.path.getsize(p)
    return total


def is_keep(dirpath):
    return os.path.exists(os.path.join(dirpath, KEEP_NAME))


def mark_keep(dirpath, keep=True):
    p = os.path.join(dirpath, KEEP_NAME)
    if keep:
        open(p, "a").close()
    elif os.path.exists(p):
        os.remove(p)
    return os.path.exists(p)
