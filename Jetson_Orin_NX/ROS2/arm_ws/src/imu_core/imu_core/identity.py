# -*- coding: utf-8 -*-
"""设备身份：不管插在哪个口，都要能问出“它是谁”。

为什么要专门一层（2026-11-06 实测）：
  - 两颗 CH340 的 USB 描述符完全相同（ID_SERIAL 都是 1a86_USB_Serial），
    /dev/serial/by-id 只有一个条目，**不能用来区分两台**；
  - /dev/serial/by-path 会随插口变，换了插口名字就变；
  - ttyUSB 编号更是每次 reset 都可能对调。
  -> 唯一可靠的身份是模块固件里的只读 UUID（LOG VERSION 命令读回）。
     没有 UUID 的厂家降级为“按 USB 物理端口记名”＝弱身份，日志里必须明说。
"""
from dataclasses import dataclass

IDENTITY_UUID = "uuid"          # 强身份：随模块走，与插口无关
IDENTITY_USB_PATH = "usb_path"  # 弱身份：随物理插口走
IDENTITY_UNKNOWN = "unknown"    # 问不出来：仍要出数据，但必须告警


@dataclass(frozen=True)
class DeviceIdentity:
    """一台设备的身份。frozen：作为字典键用，创建后不可改。"""

    kind: str                 # IDENTITY_*
    value: str                # uuid 串，或 USB 物理端口名如 "1-3.3.1"
    vendor: str = ""
    model: str = ""
    serial: str = ""
    build: str = ""
    usb_path: str = ""        # 当前所在物理口（会变，只做诊断信息）

    @property
    def key(self) -> str:
        """稳定键，用于花名册与日志：uuid:<UUID> 或 usb_path:<PORT>。"""
        return "%s:%s" % (self.kind, self.value)

    @property
    def weak(self) -> bool:
        """弱身份 = 不能扛换插口。调用方据此在日志里提示“勿随意换插口”。"""
        return self.kind != IDENTITY_UUID

    @property
    def label(self) -> str:
        model = self.model or "IMU"
        return "%s[%s]" % (model, self.value)

    def as_dict(self):
        return {
            "kind": self.kind,
            "value": self.value,
            "vendor": self.vendor,
            "model": self.model,
            "serial": self.serial,
            "build": self.build,
            "usb_path": self.usb_path,
        }
