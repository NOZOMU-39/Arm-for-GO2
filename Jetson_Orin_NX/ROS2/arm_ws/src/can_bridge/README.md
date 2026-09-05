# can_bridge — CAN 帧桥

软件与 can0 总线之间的"邮差"：订阅 /arm/can/tx 把命令帧发上总线，把电机回帧收下来发布到 /arm/can/rx。**只搬字节不解析**——电机协议的翻译是 arm_protocol/arm_controller 的活。

## 模块

| 文件 | 干什么 |
|---|---|
| `can_bridge/can_socket.py` | SocketCAN 底层（raw socket 收发、热插拔重建，标准库零依赖） |
| `can_bridge/bridge_node.py` | ROS2 节点（tx 订阅 → can0；can0 → rx 发布，带时间戳） |
| `tools/can_perf_test.py` | 压测工具（真机三路计数：发出/总线/话题，验证桥零丢帧） |
| `test/` | 单测（can_socket 收发逻辑） |

## 常用入口

```bash
# 跑桥（tmux 会话内，先双 source）
source /opt/ros/humble/setup.bash && source ~/ROS2/arm_ws/install/setup.bash
can_bridge
# 验证（终端 B）：ros2 topic pub/echo 带 --qos-reliability reliable
```

> 注意：桥自己不主动发帧——"谁在发"由上层（arm_controller 轮询/命令通道）决定，总线单主纪律见 Jetson AGENTS。
