# -*- coding: utf-8 -*-
"""统一数据类型：IMU 样本、状态位解码、单位常量。

两条设计取舍（2026-11-06 用户定，别改）：
  1. **数据语义不抽象**：不同厂家的融合算法不同，硬套一个“通用姿态”反而会错。
     本层只统一【字段名与单位】，原始字节由各驱动自己保留。
  2. **时间戳只有一个基准**：接收端 CLOCK_MONOTONIC（t_rx_ns）。
     帧内 system_time 是 u32 毫秒、24 小时回绕，只做丢帧判据，**绝不当时间基准**。
"""
from dataclasses import dataclass, asdict
from typing import Tuple

# 单位换算（对外一律 SI：m/s^2、rad/s；驱动层保留设备原单位并在注释里写明）
G_TO_MS2 = 9.80665
DPS_TO_RADS = 0.017453292519943295

# MAIN_STATUS 位定义（HI12 手册 p10 明确 bit5/bit6；其余位为实测推断，见 IMU AGENTS）
STATUS_BITS = {
    5: "acc_sat",
    6: "gyr_sat",
    9: "static",
    11: "utc_unsync",
    12: "sout_pulse",
}


def decode_status(value):
    """u16 状态字 -> 已识别位名元组。未识别位忽略（原始值仍留在 sample.status）。"""
    return tuple(name for bit, name in sorted(STATUS_BITS.items()) if value & (1 << bit))


@dataclass
class ImuSample:
    """一条统一后的 IMU 样本。

    t_rx_ns  接收端单调时钟（ns）——**唯一时间基准**，双路对齐、与其它子系统对时都用它
    t_sys_ms 帧内计数器（ms）——只用于判断丢帧（相邻步长应为 1000/rate），会回绕
    seq      本进程内该设备的帧序号（从 0 起），用于对账
    """

    t_rx_ns: int
    device: str            # 身份键，如 "uuid:24B4EB573C480701"
    role: str              # muzzle / base / unassigned
    t_sys_ms: int
    ax: float              # g
    ay: float
    az: float
    gx: float              # deg/s
    gy: float
    gz: float
    roll: float            # deg
    pitch: float
    yaw: float
    qw: float
    qx: float
    qy: float
    qz: float
    temperature: float     # degC
    status: int            # 原始 u16 状态字
    seq: int = 0

    @property
    def flags(self) -> Tuple[str, ...]:
        return decode_status(self.status)

    @property
    def acc_ms2(self) -> Tuple[float, float, float]:
        return (self.ax * G_TO_MS2, self.ay * G_TO_MS2, self.az * G_TO_MS2)

    @property
    def gyr_rads(self) -> Tuple[float, float, float]:
        return (self.gx * DPS_TO_RADS, self.gy * DPS_TO_RADS, self.gz * DPS_TO_RADS)

    def as_row(self):
        """按 COLUMNS 顺序返回一行，供 CSV/JSONL 落盘。"""
        return [getattr(self, name) for name in COLUMNS]

    def as_dict(self):
        return asdict(self)


COLUMNS = (
    "t_rx_ns", "device", "role", "seq", "t_sys_ms",
    "ax", "ay", "az", "gx", "gy", "gz",
    "roll", "pitch", "yaw", "qw", "qx", "qy", "qz",
    "temperature", "status",
)
