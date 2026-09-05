"""tcp_gateway 主节点(v1 帧透传) —— Windows 界面(现 exe 零改动) ↔ Jetson 总线

仿 ESP32 v2.1.3 TCP 协议(帧协议细节见 frames.py, 客户端 = 界面 wifi_can_client.py 原样可用):
  - 监听 8888(TCP), 兼容帧封装/批帧协商(0x0A13→回 BATCH)/命令响应
  - 0x04 CAN_SEND → 发布 /arm/can/tx(can_bridge 发上总线)
  - 订阅 /arm/can/rx → 按客户端协商状态推 0x03 单帧 / 0x05 批帧
  - timestamp_ms = 进程单调时钟(ESP32 开机计时语义的替代)
  - 单主纪律(v1): 界面是总线主(它自己轮询/安全链), controller 不启动或 poll_enable:=false
  - 界面"无线"通道填 Jetson IP 即连(协议同 ESP32, 端口同 8888)

QoS 与 can_bridge/arm_controller 一致(KEEP_LAST reliable)。
"""
import socket
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy

from arm_interfaces.msg import CanFrame

from .frames import (CMD_ENABLE_BATCH, CMD_QUERY_CAN, CMD_QUERY_IP, CMD_QUERY_RTC,
                     CMD_SET_CAN_RATE, FRAME_CAN_PUSH, FRAME_CAN_SEND, FRAME_CMD_RESP,
                     FRAME_CMD_REQ, decode_can_send, decode_frame, encode_batch_push,
                     encode_frame, encode_single_push)

Q = lambda: QoSProfile(depth=100, history=HistoryPolicy.KEEP_LAST,
                       reliability=ReliabilityPolicy.RELIABLE)

LISTEN_PORT = 8888
_T0 = time.monotonic()


def _ts_ms() -> int:
    return int((time.monotonic() - _T0) * 1000) & 0xFFFFFFFF


class GatewayNode(Node):
    def __init__(self):
        super().__init__("tcp_gateway")
        self.declare_parameter("listen_port", LISTEN_PORT)
        self.pub_tx = self.create_publisher(CanFrame, "/arm/can/tx", Q())
        self.sub_rx = self.create_subscription(CanFrame, "/arm/can/rx", self._on_rx, Q())
        self._rx_frames: list[tuple[int, bool, int, bytes]] = []
        self._rx_lock = threading.Lock()
        self._tcp_clients: set[socket.socket] = set()
        # ⚠️ socket 是 C 扩展类型不可动态加属性(conn._batch 曾 AttributeError)——批帧标志按 fileno 存表
        self._batch_flags: dict[int, bool] = {}
        self._stop = threading.Event()
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        port = int(self.get_parameter("listen_port").value)
        self._server.bind(("0.0.0.0", port))
        self._server.listen(4)
        self._server.settimeout(1.0)
        threading.Thread(target=self._accept_loop, daemon=True).start()
        self.get_logger().info(f"TCP 监听 0.0.0.0:{port} (ESP32 v2.1.3 协议兼容, 界面连 Jetson IP 即可)")
        self.create_timer(0.05, self._flush_rx)     # 20Hz 批帧推送窗

    # ---------------- rx → 客户端推送 ----------------
    def _on_rx(self, msg: CanFrame):
        with self._rx_lock:
            self._rx_frames.append((int(msg.can_id), False, _ts_ms(),
                                    bytes(msg.data[: msg.dlc])))

    def _flush_rx(self):
        with self._rx_lock:
            frames, self._rx_frames = self._rx_frames, []
        if not frames:
            return
        for c in list(self._tcp_clients):
            try:
                if self._batch_flags.get(c.fileno()):
                    c.sendall(encode_batch_push(frames))
                else:
                    for cid, extd, ts, data in frames:
                        c.sendall(encode_single_push(cid, extd, ts, data))
            except OSError:
                self._tcp_clients.discard(c)
                self._batch_flags.pop(c.fileno(), None)
                try:
                    c.close()
                except OSError:
                    pass

    # ---------------- TCP 服务 ----------------
    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, addr = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            conn.settimeout(1.0)
            self._tcp_clients.add(conn)
            self._batch_flags[conn.fileno()] = False
            self.get_logger().info(f"客户端接入: {addr[0]}:{addr[1]}")
            threading.Thread(target=self._client_loop, args=(conn, addr), daemon=True).start()

    def _client_loop(self, conn: socket.socket, addr):
        try:
            while not self._stop.is_set():
                try:
                    got = decode_frame(conn)
                except TimeoutError:
                    continue                  # 客户端静默(设零节奏等) → 继续等, 不踢
                if got is None:
                    break                     # 断开/帧损坏
                ftype, payload = got
                if ftype == FRAME_CAN_SEND:    # CAN 发送帧 → 总线
                    r = decode_can_send(payload)
                    if r is None:
                        continue
                    cid, _extd, data = r
                    msg = CanFrame()
                    msg.can_id = cid
                    msg.dlc = len(data)
                    for i, b in enumerate(data):
                        msg.data[i] = b
                    self.pub_tx.publish(msg)
                elif ftype == FRAME_CMD_REQ:
                    self._handle_cmd(conn, payload)
                else:
                    self.get_logger().warn(f"未知帧类型 0x{ftype:02X}")
        except OSError:
            pass
        finally:
            self._tcp_clients.discard(conn)
            self._batch_flags.pop(conn.fileno(), None)
            try:
                conn.close()
            except OSError:
                pass
            self.get_logger().info(f"客户端断开: {addr[0]}")

    def _handle_cmd(self, conn: socket.socket, payload: bytes):
        """命令码 2B BE; 响应 0x02。兼容 wifi_can_client 会用到的命令。"""
        if len(payload) < 2:
            return
        cmd = (payload[0] << 8) | payload[1]
        if cmd == CMD_ENABLE_BATCH:            # 批帧协商 → 回 BATCH
            self._batch_flags[conn.fileno()] = True
            conn.sendall(encode_frame(FRAME_CMD_RESP, b"BATCH"))
            self.get_logger().info("批帧模式已协商")
        elif cmd == CMD_QUERY_IP:              # 查 IP → 回本机地址
            ip = self._local_ip()
            conn.sendall(encode_frame(FRAME_CMD_RESP, ip.encode()))
        elif cmd == CMD_QUERY_RTC:
            conn.sendall(encode_frame(FRAME_CMD_RESP, time.strftime("%Y%m%d%H%M%S").encode()))
        elif cmd == CMD_SET_CAN_RATE:          # 设波特率: 总线由 can0.service 固定, 回 OK 不真改
            conn.sendall(encode_frame(FRAME_CMD_RESP, b"OK"))
        elif cmd == CMD_QUERY_CAN:             # 查缓冲: 实时推送模式下无缓冲, 回空批
            conn.sendall(encode_frame(FRAME_CMD_RESP, b""))
        else:
            self.get_logger().warn(f"未知命令 0x{cmd:04X}")

    @staticmethod
    def _local_ip() -> str:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except OSError:
            return "192.168.31.114"
        finally:
            s.close()

    def destroy_node(self):
        self._stop.set()
        try:
            self._server.close()
        except OSError:
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = GatewayNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
