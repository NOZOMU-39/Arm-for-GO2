"""字节工具（移植自 PROTO_CORE JS: i16/u16/i32/u32/f32 + pI16..pF32 + hx + pad8）

⚠️ JS 舍入语义: Math.round 向 +∞ 舍入（round(2.5)=3, round(-2.5)=-2），
   Python 内置 round() 是银行家舍入 —— 一律经 js_round() 模拟，否则帧差 1 LSB。
⚠️ 溢出截断: JS 字节数组元素经 (b & 255) 隐式截断；Python 侧 pack 前显式 clamp。
"""

import math
import struct


def i16(b: bytes, o: int) -> int:
    return struct.unpack_from("<h", b, o)[0]


def u16(b: bytes, o: int) -> int:
    return struct.unpack_from("<H", b, o)[0]


def i32(b: bytes, o: int) -> int:
    return struct.unpack_from("<i", b, o)[0]


def u32(b: bytes, o: int) -> int:
    return struct.unpack_from("<I", b, o)[0]


def f32(b: bytes, o: int) -> float:
    return struct.unpack_from("<f", b, o)[0]


def js_round(v: float) -> int:
    """模拟 JS Math.round：floor(x + 0.5)（向 +∞，半值进位）"""
    return math.floor(v + 0.5)


def p_i16(v: float) -> bytes:
    return struct.pack("<h", max(-32768, min(32767, js_round(v))))


def p_u16(v: float) -> bytes:
    return struct.pack("<H", max(0, min(65535, js_round(v))))


def p_i32(v: float) -> bytes:
    return struct.pack("<i", max(-2147483648, min(2147483647, js_round(v))))


def p_u32(v: float) -> bytes:
    return struct.pack("<I", max(0, min(4294967295, js_round(v))))


def p_f32(v: float) -> bytes:
    return struct.pack("<f", v)


def hx(data: bytes) -> str:
    """字节 → "AA BB CC" 大写十六进制（JS hx 语义）"""
    return " ".join(f"{b:02X}" for b in data)


def pad8(data: bytes) -> bytes:
    """补足/截断到 8 字节 CAN 帧（JS pad8 语义：不足补 0，超出截断）"""
    return (data + b"\x00" * 8)[:8]
