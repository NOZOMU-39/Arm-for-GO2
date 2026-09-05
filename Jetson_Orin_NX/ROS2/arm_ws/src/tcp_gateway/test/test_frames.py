"""frames 编解码单测 —— 协议格式按 wifi_can_client.py(界面客户端) 手工推算的固定字节向量"""
import socket

import pytest

from tcp_gateway.frames import (CMD_ENABLE_BATCH, FRAME_CAN_BATCH, FRAME_CAN_PUSH,
                                FRAME_CAN_SEND, FRAME_CMD_REQ, FRAME_CMD_RESP,
                                decode_batch, decode_can_block, decode_can_send,
                                decode_frame, encode_batch_push, encode_can_block,
                                encode_frame, encode_single_push)


def test_frame_envelope():
    """帧封装 [2B 总长][1B 类型][载荷]: 类型 0x04 + 载荷 6 字节 → 总长 7"""
    f = encode_frame(0x04, b"\x00\x00\x01\x45\x00\x00")
    assert f == b"\x00\x07\x04\x00\x00\x01\x45\x00\x00"


def test_can_block_format():
    """帧块: id 0x141 BE 00000141 + extd 00 + ts 1234 BE 000004D2 + dlc 08 + 8 字节"""
    b = encode_can_block(0x141, False, 1234, bytes([0x9A, 0, 0, 0, 0, 0, 0, 0]))
    assert b == b"\x00\x00\x01\x41\x00\x00\x00\x04\xD2\x08" + bytes([0x9A, 0, 0, 0, 0, 0, 0, 0])


def test_single_push_frame():
    f = encode_single_push(0x141, False, 1234, bytes(8))
    # 总长 0x13=19(1 类型 + 18 帧块), 类型 0x03 在 f[2]
    assert (f[0] << 8) | f[1] == 19 and f[2] == FRAME_CAN_PUSH


def test_batch_push_frame():
    f = encode_batch_push([(0x141, False, 1, bytes(8)), (0x242, False, 2, bytes(8))])
    assert f[2] == FRAME_CAN_BATCH
    total = (f[0] << 8) | f[1]
    assert total == 1 + 2 + 2 * 18    # 类型 + 帧数2B + 2×18B 帧块
    frames = decode_batch(f[3:])
    assert len(frames) == 2 and frames[0][0] == 0x141 and frames[1][0] == 0x242


def test_decode_can_send_implicit_dlc():
    """0x04 发送: id+extd+data(无 dlc 字段), 长度隐式"""
    payload = b"\x00\x00\x01\x45\x00" + bytes([0xA4, 0, 60, 0, 0, 0, 0, 0])
    cid, extd, data = decode_can_send(payload)
    assert (cid, extd) == (0x145, False) and len(data) == 8 and data[0] == 0xA4


def test_decode_can_send_oversize_rejected():
    assert decode_can_send(b"\x00\x00\x01\x45\x00" + bytes(12)) is None


def test_decode_batch_truncated_safe():
    frames = decode_batch(b"\x00\x02\x00\x00\x01\x41\x00\x00\x00\x01\x08")  # 截断
    assert isinstance(frames, list) and len(frames) == 0


def test_decode_can_block():
    blk = encode_can_block(0x242, False, 99, bytes([0x92, 0, 0, 0, 0, 0, 0, 0]))
    cid, extd, ts, data = decode_can_block(blk)
    assert (cid, extd, ts) == (0x242, False, 99) and data[0] == 0x92


def test_negotiate_command_payload():
    """协商命令载荷 = 2B 命令码 BE 0x0A13"""
    assert CMD_ENABLE_BATCH == 0x0A13
    f = encode_frame(FRAME_CMD_REQ, b"\x0A\x13")
    assert f == b"\x00\x03\x01\x0A\x13"
    # 响应 BATCH
    r = encode_frame(FRAME_CMD_RESP, b"BATCH")
    assert r == b"\x00\x06\x02BATCH"


def test_socket_roundtrip():
    """TCP 双端往返: 发端编码 → 收端 decode_frame 还原"""
    a, b = socket.socketpair()
    try:
        a.sendall(encode_batch_push([(0x245, False, 7, bytes([0x9C]) + bytes(7))]))
        got = decode_frame(b)
        assert got is not None and got[0] == FRAME_CAN_BATCH
        frames = decode_batch(got[1])
        assert frames[0][0] == 0x245 and frames[0][2] == 7
    finally:
        a.close()
        b.close()
