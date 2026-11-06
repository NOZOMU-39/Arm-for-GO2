# -*- coding: utf-8 -*-
"""HI12S2 驱动：把“串口 + 0x91 帧”包装成 imu_core.ImuDriver。

职责边界：
  - 只实现 imu_core 规定的三个动作（问名字 / 要数据 / 按需求配置）；
  - 身份、花名册、质量位、时间戳契约都在 imu_core，这里不重复；
  - 恢复（hub-first reset）不在这里做，见 tools/baseline/ch340_recover.py。

单位约定（对外 SI，见 imu_core.types）：
  设备给的是 g 与 deg/s；ImuSample 里保持 g / deg-s（用 G_TO_MS2、DPS_TO_RADS 换算），
  这是为了让原始量与本机显示对得上，避免“看起来换了单位其实没换”的混淆。
"""
import os
import time

from imu_core.driver import DriverInfo, ImuDriver
from imu_core.identity import (
    DeviceIdentity,
    IDENTITY_UNKNOWN,
    IDENTITY_USB_PATH,
    IDENTITY_UUID,
)
from imu_core import record
from imu_core.registry import usb_path_of
from imu_core.types import ImuSample

from .link import BAUD_TABLE, Hi12Link
from .protocol import FrameSplitter, parse_091, unpack_091_fast

# 采样率 -> 波特率（实测：115200≈142 Hz、460800≈500 Hz、921600=1000 Hz）
# 记住用户那句：**波特率是派生量**——先定 1000 Hz，921600 是被逼出来的。
RATE_TO_BAUD = {
    2000: 921600,   # 设备上限 1000 Hz，这里留占位
    1000: 921600,
    500: 460800,
    250: 230400,
    200: 230400,
    100: 115200,
}


class Hi12s2Driver(ImuDriver):
    """一台 HI12S2-MI1-000（UART / 0x91 全量帧）。"""

    info = DriverInfo(
        name="imu_hi12s2",
        vendor="HIPNUC",
        model="HI12S2-MI1-000",
        transport="uart",
        default_rate_hz=1000,
        notes="0x91 全量帧 82B@1kHz；8N1；lflag 必须全清（at[3]=0）",
    )

    def __init__(self, dev, baud=921600, rate_hz=1000, **options):
        super(Hi12s2Driver, self).__init__(dev, **options)
        self.link = Hi12Link(dev, baud)
        self.baud = baud
        self.rate_hz = rate_hz
        self.splitter = FrameSplitter()
        self._identity = None
        self._seq = 0

    # ---- 生命周期

    def open(self):
        self.link.open()
        self._opened = True
        return self

    def close(self):
        self.link.quiet_close()
        self._opened = False

    # ---- 身份

    def identify(self):
        """读 LOG VERSION 拿 UUID。必须在 open() 之后调用。

        失败返回 IDENTITY_UNKNOWN —— **认不出来也要能出数据**，绝不因此罢工。
        """
        if self._identity is not None:
            return self._identity
        port = usb_path_of(self.dev) or ""
        try:
            kv, _text = self.link.query_version()
        except (OSError, IOError):
            kv = {}
        uuid = (kv.get("UUID") or "").strip()
        model = (kv.get("PNAME") or "").strip()
        serial = (kv.get("SN") or "").strip()
        build = (kv.get("BUILD") or "").strip()
        if uuid:
            self._identity = DeviceIdentity(
                IDENTITY_UUID, uuid.upper(), vendor="HIPNUC", model=model,
                serial=serial, build=build, usb_path=port,
            )
        elif port:
            self._identity = DeviceIdentity(
                IDENTITY_USB_PATH, port, vendor="HIPNUC", model=model,
                serial=serial, build=build, usb_path=port,
            )
        else:
            self._identity = DeviceIdentity(IDENTITY_UNKNOWN, self.dev, vendor="HIPNUC", model=model)
        return self._identity

    def device_key(self):
        ident = self._identity
        return ident.key if ident is not None else "dev:%s" % self.dev

    # ---- 配置

    def configure(self, sample_rate_hz=None, baud=None):
        """按“要 1000 Hz”配置，驱动自己翻译成波特率与 LOG HI91 命令。

        注意：改波特率/输出周期会写进设备（掉电保存），属于**会影响下次上电**的操作，
        调用方要显式传入，不做隐式默认。
        """
        applied = {"baud": self.baud, "sample_rate_hz": self.rate_hz}
        if baud is not None:
            self.link.set_baud(baud)
            self.baud = baud
            applied["baud"] = baud
        if sample_rate_hz is not None:
            period = 1.0 / float(sample_rate_hz)
            self.link.mute()
            self.link.send("LOG HI91 ONTIME %.6f" % period)
            time.sleep(0.05)
            self.link.flush()
            self.rate_hz = sample_rate_hz
            applied["sample_rate_hz"] = sample_rate_hz
        return applied

    def start_stream(self, sample_rate_hz=None):
        """恢复 0x91 输出（不读回包，否则会被 1 kHz 流卡死）。"""
        rate = sample_rate_hz or self.rate_hz
        self.link.unmute(1.0 / float(rate))
        return rate

    def stop_stream(self):
        self.link.mute()

    # ---- 数据

    def read_batch(self, timeout=0.2):
        """读一批样本。除 I/O 错误外不抛异常；坏帧只计数。

        时间戳说明：同一批读完的帧共用一个接收时刻（now）。
        采集器应保持小批量（读超时 2~5 ms），这样时间戳抖动 < 采样周期。
        """
        data = self.link.read(timeout=timeout)
        if not data:
            return []
        now_ns = time.monotonic_ns()
        key = self.device_key()
        out = []
        for payload in self.splitter.feed(data):
            field = parse_091(payload)
            self._seq += 1
            out.append(ImuSample(
                t_rx_ns=now_ns,
                device=key,
                role="",
                t_sys_ms=int(field["system_time"]),
                ax=field["ax"], ay=field["ay"], az=field["az"],
                gx=field["gx"], gy=field["gy"], gz=field["gz"],
                roll=field["roll"], pitch=field["pitch"], yaw=field["yaw"],
                qw=field["qw"], qx=field["qx"], qy=field["qy"], qz=field["qz"],
                temperature=float(field["temperature"]),
                status=int(field["main_status"]),
                seq=self._seq,
            ))
        return out

    # ---- 快路径（常驻采集用）
    def read_records(self):
        """读一次（非阻塞）并直接产出 64 B 记录：[(seq, blob, t_rx_ns), ...]。

        与 read_batch 的区别是**不构造 ImuSample/dict**——1 kHz x 2 路时这点开销
        足以让采集掉到 ~937 fps（2026-11-06 实测）。常驻进程请用本方法。
        调用前应由调用方 select() 确认可读。
        """
        data = os.read(self.link.fd, 262144)
        if not data:
            return []
        now_ns = time.monotonic_ns()
        out = []
        for payload in self.splitter.feed(data):
            status, temp, sys_ms, acc, gyr, quat = unpack_091_fast(payload)
            self._seq += 1
            out.append((self._seq,
                        record.pack_fields(now_ns, self._seq, sys_ms, acc, gyr, quat, status, temp),
                        now_ns))
        return out

    # ---- 统计

    def stats(self):
        sp = self.splitter
        return {
            "dev": self.dev,
            "frames": sp.frames,
            "crc_bad": sp.crc_bad,
            "len_bad": sp.len_bad,
            "resync_bytes": sp.resync_bytes,
            "baud": self.baud,
            "rate_hz": self.rate_hz,
        }
