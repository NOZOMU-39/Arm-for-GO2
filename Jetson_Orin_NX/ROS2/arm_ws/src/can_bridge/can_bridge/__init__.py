"""can_bridge — can0 SocketCAN ↔ ROS2 帧桥

帧消息契约: arm_interfaces/msg/CanFrame（原始帧，不解析）。
依赖: 标准库 raw socket（Linux AF_CAN）；Windows 上仅纯函数可用（CanSocket.open 抛错）。
"""

__version__ = "0.1.0"
