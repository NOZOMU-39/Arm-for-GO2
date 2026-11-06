# -*- coding: utf-8 -*-
"""HI12 0x91 帧协议：CRC、切帧、解析。纯逻辑，无 I/O、无 OS 依赖，可在任何机器上测。

帧格式（手册 + 2026-11-06 实测）：
    5A A5 | len u16 LE (=76) | CRC u16 LE | payload 76B
    CRC-16/XMODEM：多项式 0x1021、初值 0、不反转、无终值异或；
    范围 = 帧头2 + 长度2 + 数据域（不含 CRC 自身）。
payload 全小端 float，字段顺序见 P091_FIELDS。

踩过的坑（别再犯）：
  - temperature 是 **i8**，不是 int32。写成 "<BHBifI..." 会报
    "unpack requires a buffer of 80 bytes"。
  - payload 里可能出现伪帧头 5A A5，必须逐字节重同步，不能跳整帧长度。
"""
import struct

HEAD = b"\x5a\xa5"
CMD_END = b"\r\n"

PAYLOAD_091 = struct.Struct("<BHbfI3f3f3f3f4f")
PAYLOAD_091_LEN = PAYLOAD_091.size  # 76

# 伪帧头保护：真实 payload 最长 76 字节（0x81/0x83 也 < 128）。
# 若在 payload 里撞上 5A A5，把后面两字节当长度会得到几万，
# 原实现会一直等 4 万字节才 CRC 失败 —— 1 kHz 下等于丢 0.5 s 数据（本次单测抓出）。
MAX_PAYLOAD = 128

P091_FIELDS = (
    "tag", "main_status", "temperature", "air_pressure", "system_time",
    "ax", "ay", "az", "gx", "gy", "gz",
    "mx", "my", "mz",
    "roll", "pitch", "yaw",
    "qw", "qx", "qy", "qz",
)


def _build_crc_table():
    table = []
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
        table.append(crc)
    return table


_CRC_TABLE = _build_crc_table()


def crc16_xmodem(data):
    """CRC-16/XMODEM。自检：crc16_xmodem(b"123456789") == 0x31C3。"""
    crc = 0
    for b in data:
        crc = ((crc << 8) & 0xFFFF) ^ _CRC_TABLE[((crc >> 8) ^ b) & 0xFF]
    return crc


def crc_selftest():
    return crc16_xmodem(b"123456789") == 0x31C3


class FrameSplitter(object):
    """字节流 -> 0x91 数据域。跨 read() 边界自行拼接，坏帧计数据、不抛异常。"""

    __slots__ = ("buf", "crc_bad", "len_bad", "resync_bytes", "unknown_tag", "frames")

    def __init__(self):
        self.buf = bytearray()
        self.crc_bad = 0
        self.len_bad = 0
        self.resync_bytes = 0
        self.unknown_tag = 0
        self.frames = 0

    def reset_stats(self):
        self.crc_bad = 0
        self.len_bad = 0
        self.resync_bytes = 0
        self.unknown_tag = 0
        self.frames = 0

    def feed(self, data):
        """喂入原始字节，返回本次切出的 0x91 payload 列表。"""
        buf = self.buf
        buf += data
        n = len(buf)
        i = 0
        out = []
        while True:
            j = buf.find(HEAD, i)
            if j < 0:
                self.resync_bytes += n - i
                i = n
                break
            if j > i:
                self.resync_bytes += j - i
            if n - j < 6:
                i = j
                break
            ln = buf[j + 2] | (buf[j + 3] << 8)
            if ln > MAX_PAYLOAD:
                self.resync_bytes += 1     # 伪帧头：长度不合理，按 1 字节推进重新找同步
                i = j + 1
                continue
            total = 6 + ln
            if n - j < total:
                i = j
                break
            payload = bytes(buf[j + 6:j + 6 + ln])
            crc_rx = buf[j + 4] | (buf[j + 5] << 8)
            if crc16_xmodem(bytes(buf[j:j + 4]) + payload) != crc_rx:
                self.crc_bad += 1
                i = j + 1          # 丢掉这个帧头，往后重新找同步
                continue
            if ln != PAYLOAD_091_LEN:
                self.len_bad += 1  # 合法 CRC 但不是 0x91 全量帧（0x81/0x83 等）
            else:
                self.frames += 1
                out.append(payload)
            i = j + total
        if i:
            del buf[:i]
        return out


def parse_091(payload):
    """76 字节数据域 -> dict（21 个字段，含 main_status / system_time）。"""
    return dict(zip(P091_FIELDS, PAYLOAD_091.unpack(payload)))


def build_frame_091(fields):
    """按字段 dict 造一帧 0x91（测试与回放用）。缺的字段用 0 填。"""
    values = []
    for name in P091_FIELDS:
        default = 0
        if name == "tag":
            default = 0x91
        values.append(fields.get(name, default))
    payload = PAYLOAD_091.pack(*values)
    head = HEAD + struct.pack("<H", len(payload))
    return head + struct.pack("<H", crc16_xmodem(head + payload)) + payload
