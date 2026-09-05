"""can_socket 纯函数测试（本机 Windows 可跑；CanSocket 需 Linux）"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

from can_bridge.can_socket import CanError, CanSocket, pack_frame, unpack_frame


def test_pack_unpack_roundtrip():
    can_id, data = 0x141, b"\x9A\x00\x00\x00\x00\x00\x00\x00"
    raw = pack_frame(can_id, data)
    assert len(raw) == 16
    assert unpack_frame(raw) == (0x141, data)


def test_pack_short_data_padded():
    raw = pack_frame(0x142, b"\x9A")
    cid, data = unpack_frame(raw)
    assert cid == 0x142
    assert data == b"\x9A"          # dlc=1, 只回 1 字节


def test_pack_long_data_truncated_to_8():
    raw = pack_frame(0x100, b"\x01" * 12)
    cid, data = unpack_frame(raw)
    assert cid == 0x100 and len(data) == 8


def test_pack_id_masked_to_29bit():
    raw = pack_frame(0x1FFFFFFF + 5, b"\x00" * 8)
    cid, _ = unpack_frame(raw)
    assert cid == 4   # 29bit 掩码后 5&0x1FFFFFFF... 实际 (0x20000004 & 0x1FFFFFFF)=4


def test_unpack_dlc_over_8_clamped():
    raw = bytearray(pack_frame(0x100, b"\x01" * 8))
    raw[4] = 12                       # 人为破坏 dlc
    cid, data = unpack_frame(bytes(raw))
    assert cid == 0x100 and len(data) == 8


def test_unpack_short_raw_returns_none_like():
    # recv 返回 <16B 时上层判 None；此处直接验证 unpack 不越界由调用方处理——
    # 纯函数对 16B 以下输入：dlc 读取可能越界，保证至少不静默错（由 recv 层防御）
    with pytest.raises(Exception):
        unpack_frame(b"\x00" * 4)


def test_can_socket_unavailable_on_windows():
    if sys.platform == "win32":
        with pytest.raises(CanError):   # 构造时检测平台并 fail-fast
            CanSocket("can0")
    else:
        pytest.skip("Linux 上需要真实 can0 接口，跳单测")
