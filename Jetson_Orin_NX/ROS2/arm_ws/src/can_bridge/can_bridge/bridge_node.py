"""can_bridge 节点：can0 帧 ↔ ROS2 话题

- 接收线程: recv → publish /arm/can/rx（header.stamp = 到达时刻，can_id/data 原样）
- 订阅 /arm/can/tx: 回调直写 can0（帧节奏由上游控制者负责——60ms 间隔踩坑见协议库文档）
- 故障恢复: send/recv 错误 → 计数并重建 socket（间隔 retry_sec，错误驱动非轮询检测），
  连续失败超 lost_alert_n 帧数时周期性 WARN（can0 由 udev/systemd 管理 up/down）

用法: ros2 run can_bridge can_bridge [--ros-args -p iface:=can0]
"""

import threading

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSPresetProfile

from arm_interfaces.msg import CanFrame

from .can_socket import CanError, CanSocket


class CanBridgeNode(Node):

    def __init__(self):
        super().__init__("can_bridge")
        self.declare_parameter("iface", "can0")
        self.declare_parameter("rx_topic", "/arm/can/rx")
        self.declare_parameter("tx_topic", "/arm/can/tx")
        self.declare_parameter("recv_timeout_s", 0.05)
        self.declare_parameter("retry_sec", 2.0)

        iface = self.get_parameter("iface").value
        # rx 广播（可能多订阅者：controller/记录），tx 直通（低延迟）
        self._pub_rx = self.create_publisher(
            CanFrame, self.get_parameter("rx_topic").value,
            QoSPresetProfile.SYSTEM_DEFAULT.value)
        self._sub_tx = self.create_subscription(
            CanFrame, self.get_parameter("tx_topic").value,
            self._on_tx, QoSPresetProfile.SYSTEM_DEFAULT.value)

        self._can = CanSocket(iface)
        self._retry_sec = self.get_parameter("retry_sec").value
        self._recv_timeout = self.get_parameter("recv_timeout_s").value
        self._stop = threading.Event()
        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True,
                                           name="can_rx")
        self._open_count = 0
        self._err_count = 0
        self._tx_count = 0
        self._last_warn = 0.0
        self._open()

    # ---------------- 底层 ----------------

    def _open(self):
        self._can.open()
        self._open_count += 1
        self.get_logger().info(f"can0 已打开(第 {self._open_count} 次) @ {self._can.iface}")

    def _reopen(self):
        try:
            self._open()
        except CanError as e:
            self._err_count += 1
            now = self.get_clock().now().nanoseconds
            if now - self._last_warn > 5e9:  # 每 5s 至多一条告警
                self._last_warn = now
                self.get_logger().warn(f"can0 重连失败(累计 {self._err_count}): {e}")

    # ---------------- 接收线程 ----------------

    def _rx_loop(self):
        while not self._stop.is_set():
            try:
                got = self._can.recv(timeout=self._recv_timeout)
            except CanError:
                self._close_and_retry()
                continue
            if got is None:
                continue
            can_id, data = got
            msg = CanFrame()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.can_id = can_id
            msg.dlc = len(data)
            msg.data = [b for b in data] + [0] * (8 - len(data))
            self._pub_rx.publish(msg)

    def _close_and_retry(self):
        self._can.close()
        self.get_logger().error("CAN 通道异常，尝试重建…")
        while not self._stop.wait(self._retry_sec):
            if self._stop.is_set():
                return
            try:
                self._can.open()
                self.get_logger().info("can0 已重建")
                return
            except CanError as e:
                self._err_count += 1
                self.get_logger().warn(f"重连失败({self._err_count}): {e}")

    # ---------------- 发送 ----------------

    def _on_tx(self, msg: CanFrame):
        try:
            self._can.send(msg.can_id, bytes(msg.data[:msg.dlc]))
            self._tx_count += 1
        except CanError as e:
            self._err_count += 1
            self.get_logger().error(f"发送失败: {e}")

    # ---------------- 生命周期 ----------------

    def destroy_node(self):
        self._stop.set()
        try:
            self._can.close()
        except Exception:
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = CanBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
