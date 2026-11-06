# -*- coding: utf-8 -*-
"""imu_hi12s2 —— HIPNUC HI12S2-MI1-000 的驱动实现（UART / 0x91 帧）。

边界：只做“和这台设备说话”——串口、切帧、校验、解析、ASCII 配置命令。
身份/花名册/时间戳契约/质量位在 imu_core，**这里不重复实现**。
换厂家时新增 imu_<型号> 包即可，imu_core 一行不用改。

注意：本 __init__ 只导出**纯逻辑**部分（protocol），这样在没有 termios 的机器上
（比如 Windows 上跑单元测试）也能 import；串口对象用 imu_hi12s2.link / .driver 直接取。
"""
from .protocol import PAYLOAD_091, FrameSplitter, build_frame_091, crc16_xmodem, parse_091

__version__ = "0.1.0"

__all__ = ["PAYLOAD_091", "FrameSplitter", "build_frame_091", "crc16_xmodem", "parse_091"]


def __getattr__(name):
    """惰性导出串口相关对象，避免在无 termios 的平台上 import 失败。"""
    if name in ("Hi12Link", "parse_kv", "probe_open", "detect_baud_on_link", "BAUD_TABLE"):
        from . import link as _link
        return getattr(_link, name)
    if name == "Hi12s2Driver":
        from .driver import Hi12s2Driver
        return Hi12s2Driver
    raise AttributeError(name)
