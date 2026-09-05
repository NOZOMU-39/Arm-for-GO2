"""ESP32 v2.1.3 TCP 帧协议编解码(纯函数, 零 ROS 依赖) —— 兼容 wifi_can_client.py(界面原样复制)

协议(wifi_can_client.py 实证 2026-09-05):
  帧封装: [2B 总长 BE = 1+len(payload)] [1B 类型] [载荷]; 长度上限 4096
  类型:   0x01 CMD_REQ(PC→设备) / 0x02 CMD_RESP / 0x03 CAN_PUSH 单帧(未协商)
          0x04 CAN_SEND(PC→设备) / 0x05 CAN_BATCH 批帧推送(协商后)
  CAN 帧载荷(0x03/0x05 内帧块): [4B can_id BE][1B extd][4B timestamp_ms BE][1B dlc][data]
  0x04 发送载荷: [4B can_id BE][1B extd][data](dlc 隐式=len(data))
  批帧 0x05 载荷: [2B 帧数 BE][N × 帧块]
  命令 0x01 载荷: 2B 命令码 BE: 0x0A13 协商批帧(响应 0x02 + b'BATCH')
                    0x0A0D 查 IP / 0x0A0F 查缓冲 / 0x0A10 设波特率 / 0x0A11 查 RTC
"""
from __future__ import annotations

import struct

# 帧类型
FRAME_CMD_REQ = 0x01
FRAME_CMD_RESP = 0x02
FRAME_CAN_PUSH = 0x03
FRAME_CAN_SEND = 0x04
FRAME_CAN_BATCH = 0x05

# 命令码
CMD_ENABLE_BATCH = 0x0A13
CMD_QUERY_IP = 0x0A0D
CMD_QUERY_CAN = 0x0A0F
CMD_SET_CAN_RATE = 0x0A10
CMD_QUERY_RTC = 0x0A11

MAX_FRAME = 4096


# ---------- 解码(收) ----------

def recv_exact(sock, n: int, timeout: float = 1.0) -> bytes | None:
    """读满 n 字节。

    语义(2026-09-06 修复, 曾致设零断连):
      - 对端关闭(recv 返回空) / 其他 OSError / 半帧超时(已读部分数据后静默=流损坏) → None(断开)
      - 纯静默超时(一个字节都没收到) → 抛 TimeoutError(上层继续等待, 不踢客户端)
    背景: 旧实现把"超时"与"断开"都返回 None → 界面设零节奏(0x64 后停 1s、
    0x76 后停 10s, 期间暂停轮询不发帧)停发 >1s 即被 gateway 踢下线, 0x76 永远发不出。
    """
    sock.settimeout(timeout)
    buf = b""
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except TimeoutError:
            if buf:
                return None  # 半帧超时: 协议流已损坏, 断开等客户端重连
            raise            # 纯静默: 客户端只是停顿(设零节奏), 上层 continue
        except OSError:
            return None
        if not chunk:
            return None
        buf += chunk
    return buf


def decode_frame(sock) -> tuple[int, bytes] | None:
    """读一个完整帧 → (类型, 载荷)。封装/长度校验与 wifi_can_client._recv_frame 一致。"""
    header = recv_exact(sock, 2)
    if header is None:
        return None
    total = struct.unpack(">H", header)[0]
    if total == 0 or total > MAX_FRAME:
        return None
    body = recv_exact(sock, total)
    if body is None or len(body) < 1:
        return None
    return body[0], body[1:]


def decode_can_send(payload: bytes) -> tuple[int, bool, bytes] | None:
    """0x04 发送载荷 → (can_id, extd, data)。dlc 隐式 = 剩余长度(≤8)。"""
    if len(payload) < 5 or len(payload) > 13:
        return None
    can_id = struct.unpack(">I", payload[0:4])[0] & 0x1FFFFFFF
    extd = payload[4] != 0
    data = payload[5:]
    return can_id, extd, data


def decode_batch(payload: bytes) -> list[tuple[int, bool, int, bytes]]:
    """0x05 批帧载荷 → [(can_id, extd, ts_ms, data), ...]"""
    if len(payload) < 2:
        return []
    n = struct.unpack(">H", payload[0:2])[0]
    frames, pos = [], 2
    for _ in range(n):
        if pos + 10 > len(payload):
            break
        can_id = struct.unpack(">I", payload[pos:pos + 4])[0]
        extd = payload[pos + 4] != 0
        ts = struct.unpack(">I", payload[pos + 5:pos + 9])[0]
        dlc = payload[pos + 9]
        if pos + 10 + dlc > len(payload):
            break
        data = payload[pos + 10:pos + 10 + dlc]
        frames.append((can_id, extd, ts, data))
        pos += 10 + dlc
    return frames


def decode_can_block(payload: bytes) -> tuple[int, bool, int, bytes] | None:
    """0x03 单帧载荷 → (can_id, extd, ts_ms, data)"""
    if len(payload) < 10:
        return None
    can_id = struct.unpack(">I", payload[0:4])[0] & 0x1FFFFFFF
    extd = payload[4] != 0
    ts = struct.unpack(">I", payload[5:9])[0]
    dlc = payload[9]
    if len(payload) < 10 + dlc:
        return None
    return can_id, extd, ts, payload[10:10 + dlc]


# ---------- 编码(发) ----------

def encode_frame(frame_type: int, payload: bytes = b"") -> bytes:
    """帧封装: [2B 总长 BE][1B 类型][载荷]"""
    total = 1 + len(payload)
    return struct.pack(">H", total) + bytes([frame_type]) + payload


def encode_can_block(can_id: int, extd: bool, ts_ms: int, data: bytes) -> bytes:
    """单帧块(0x03 载荷 / 0x05 内帧块共用格式)"""
    return (struct.pack(">I", can_id & 0x1FFFFFFF) + bytes([1 if extd else 0])
            + struct.pack(">I", ts_ms & 0xFFFFFFFF) + bytes([len(data)]) + data)


def encode_single_push(can_id: int, extd: bool, ts_ms: int, data: bytes) -> bytes:
    """0x03 单帧推送整帧"""
    return encode_frame(FRAME_CAN_PUSH, encode_can_block(can_id, extd, ts_ms, data))


def encode_batch_push(frames: list[tuple[int, bool, int, bytes]]) -> bytes:
    """0x05 批帧推送整帧([2B n][帧块...])"""
    payload = struct.pack(">H", len(frames)) + b"".join(
        encode_can_block(cid, extd, ts, d) for cid, extd, ts, d in frames)
    return encode_frame(FRAME_CAN_BATCH, payload)
