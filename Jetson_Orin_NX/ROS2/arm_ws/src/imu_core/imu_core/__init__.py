# -*- coding: utf-8 -*-
"""imu_core —— 厂商无关的 IMU 核心层。

分层（2026-11-06 用户批准）：
    imu_core     身份 / 花名册 / 时间戳契约 / 质量位 / 驱动抽象      <- 换厂家不用改
    imu_<型号>   串口收发、帧解析、配置翻译、恢复                     <- 换厂家新增一个
    imu_bringup  launch 与配置                                       <- 只改配置

本包在 M1 阶段【不依赖 ROS】：纯 Python 标准库，可以在 Jetson 上直接 import 跑，
到 M4 才加 rclpy 节点把数据发出来。
"""
from .types import ImuSample, decode_status, G_TO_MS2, DPS_TO_RADS, STATUS_BITS
from .identity import DeviceIdentity, IDENTITY_UUID, IDENTITY_USB_PATH, IDENTITY_UNKNOWN
from .roster import Roster, ROLE_MUZZLE, ROLE_BASE, ROLE_UNASSIGNED, ROLES
from .quality import Quality, WindowQuality
from .driver import ImuDriver, DriverInfo
from .discriminator import DiscriminatorResult, discriminate, motion_stats
from .registry import enumerate_tty_devices, usb_path_of, assign_roles

__version__ = "0.1.0"

__all__ = [
    "ImuSample", "decode_status", "G_TO_MS2", "DPS_TO_RADS", "STATUS_BITS",
    "DeviceIdentity", "IDENTITY_UUID", "IDENTITY_USB_PATH", "IDENTITY_UNKNOWN",
    "Roster", "ROLE_MUZZLE", "ROLE_BASE", "ROLE_UNASSIGNED", "ROLES",
    "Quality", "WindowQuality", "ImuDriver", "DriverInfo",
    "DiscriminatorResult", "discriminate", "motion_stats",
    "enumerate_tty_devices", "usb_path_of", "assign_roles",
]
