# arm_bringup — 一键启动

Jetson 控制栈的"总开关"：一条命令把该起的节点全拉起来。六包收官（最后一块拼图）。

## 两种模式（总线单主纪律封装）

| 模式 | 命令 | 起的节点 | 谁控制 |
|---|---|---|---|
| **界面主**（默认，v1） | `ros2 launch arm_bringup arm_bringup.launch.py` | can_bridge + tcp_gateway | Windows 界面连 Jetson IP |
| **自主任** | 同上加 `controller:=true` | can_bridge + arm_controller | Jetson 自己（界面请勿连，网关已停防双主） |

## 用法（Jetson，tmux 内先双 source）

```bash
source /opt/ros/humble/setup.bash && source ~/ROS2/arm_ws/install/setup.bash
ros2 launch arm_bringup arm_bringup.launch.py
# 可选参数: controller:=true | poll_interval_ms:=300
# Ctrl+C 一起停全部节点
```

## 注意

- 模式切换=改一条参数，别手动开窗口拼节点（忘停一边就是双主）
- 自主任模式下 controller 档案读 `~/ROS2/arm_ws/config/registry.json`（部署权威副本）
