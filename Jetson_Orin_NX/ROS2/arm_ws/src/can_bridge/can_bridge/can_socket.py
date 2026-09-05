"""SocketCAN raw 封装（Linux 标准库，无 python-can 依赖）

pack_frame/unpack_frame 为纯函数（本机 Windows 可单测）；
CanSocket 依赖 AF_CAN，仅在 Linux/Jetson 可用。
异常策略: 收发错误由调用方（节点）决定重连——can0 由 udev/systemd 管理 up/down。
"""

import socket
import struct

AF_CAN = getattr(socket, "AF_CAN", None)
CAN_RAW = getattr(socket, "CAN_RAW", None)

_HEADER = struct.Struct("=IB3x")
_CAN_ID_MASK = 0x1FFFFFFF


def pack_frame(can_id: int, data: bytes) -> bytes:
    """打包 struct can_frame: 4B id + 1B dlc + 3B pad + 8B data（标准帧）"""
    d = bytes(data[:8]).ljust(8, b"\x00")
    return _HEADER.pack(can_id & _CAN_ID_MASK, len(bytes(data[:8]))) + d


def unpack_frame(raw: bytes):
    """解包 can_frame → (can_id, data_bytes)；raw 为 recv(72) 收到的 16+ 字节"""
    can_id, dlc = _HEADER.unpack_from(raw)
    can_id &= _CAN_ID_MASK
    if dlc > 8:
        dlc = 8
    return can_id, raw[8:8 + dlc]


class CanError(Exception):
    """CAN 收发错误（触发上层重连逻辑）"""


class CanSocket:
    """can0 原始套接字（阻塞 + 可设超时）"""

    def __init__(self, iface: str = "can0"):
        if AF_CAN is None or CAN_RAW is None:
            raise CanError("本平台无 AF_CAN（需 Linux；Windows 仅纯函数可用）")
        self.iface = iface
        self._sock = None

    def open(self):
        if self._sock is not None:
            self.close()
        try:
            s = socket.socket(AF_CAN, socket.SOCK_RAW, CAN_RAW)
            s.bind((self.iface,))
            self._sock = s
        except OSError as e:
            self._sock = None
            raise CanError(f"can0 绑定失败({self.iface}): {e}") from e

    @property
    def opened(self) -> bool:
        return self._sock is not None

    def send(self, can_id: int, data: bytes):
        if self._sock is None:
            raise CanError("socket 未打开")
        try:
            self._sock.send(pack_frame(can_id, data))
        except OSError as e:
            raise CanError(f"发送失败: {e}") from e

    def recv(self, timeout: float | None = None):
        """收一帧 → (can_id, data)；超时返回 None"""
        if self._sock is None:
            raise CanError("socket 未打开")
        if timeout is not None:
            self._sock.settimeout(timeout)
        try:
            raw = self._sock.recv(72)
        except socket.timeout:
            return None
        except OSError as e:
            raise CanError(f"接收失败: {e}") from e
        finally:
            if timeout is not None:
                self._sock.settimeout(None)
        if len(raw) < 16:
            return None
        return unpack_frame(raw)

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
