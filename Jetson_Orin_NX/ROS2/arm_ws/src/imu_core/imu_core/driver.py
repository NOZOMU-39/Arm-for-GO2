# -*- coding: utf-8 -*-
"""驱动抽象：核心层只向驱动要三样东西（用户 2026-11-06 定，边界刻意划窄）。

    1. 问名字  identify()   -> DeviceIdentity      （UUID / 端口 / 未知）
    2. 要数据  read_batch() -> [ImuSample]         （统一字段与单位）
    3. 配置    configure()  -> dict                （“我要 1000 Hz”，驱动自己翻译）

**数据语义不抽象**：不同厂家融合算法不同，硬套“通用姿态”会出错；
统一层只统一字段名与单位，原始字节各驱动自己保留。

为什么不用 pluginlib：本层是纯 Python，配置里写驱动类名即可，
少一层 C++/ament 依赖，换厂家只加一个包。
"""
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True)
class DriverInfo:
    """驱动的自述信息，写进日志与元数据，便于复现。"""

    name: str            # 包名，如 "imu_hi12s2"
    vendor: str          # 厂家，如 "HIPNUC"
    model: str           # 型号，如 "HI12S2-MI1-000"
    transport: str       # uart / can / spi
    default_rate_hz: int
    notes: str = ""


class ImuDriver(ABC):
    """所有 IMU 驱动实现的接口。"""

    info: DriverInfo = DriverInfo("abstract", "", "", "", 0)

    def __init__(self, dev, **options):
        self.dev = dev
        self.options = options
        self._opened = False

    # ---- 生命周期

    @abstractmethod
    def open(self):
        """打开设备。失败抛 OSError/DriverError，由上层决定是否恢复。"""

    @abstractmethod
    def close(self):
        """关闭设备。注意：CH340 满速收流后 close 有概率 wedged，具体策略由驱动负责。"""

    @property
    def opened(self):
        return self._opened

    @contextmanager
    def session(self):
        self.open()
        try:
            yield self
        finally:
            self.close()

    # ---- 身份

    @abstractmethod
    def identify(self):
        """-> DeviceIdentity。问不出来时返回 IDENTITY_UNKNOWN 而不是抛异常。"""

    # ---- 数据

    @abstractmethod
    def read_batch(self, timeout=0.2):
        """读一批样本（>=0 条）。除 I/O 错误外不抛异常；坏帧计入驱动统计。"""

    # ---- 配置

    def configure(self, **kwargs):
        """按“要 1000 Hz / 要哪些量”配置设备，返回实际生效的配置字典。"""
        return {}

    # ---- 统计（给日志/质量门用）

    def stats(self):
        return {}
