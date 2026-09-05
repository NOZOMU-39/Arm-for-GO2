# arm_controller — 机械臂主控（臂脉塔电机域总包）

机械臂的"大脑管家"：拿着电机档案、轮流问每台电机状态、盯限幅安全、执行设零等流程——上层告诉它"想去哪"，它负责"怎么安全地到那、到了没有、出事怎么办"。一期监督型（只执行显式命令不自主运动）；二期控制算法模块（后坐抑制等）挂入本包。

## 模块

| 文件 | 干什么 |
|---|---|
| `arm_controller/registry.py` | 电机档案：字段规范化/校验 + RegistryStore 运行时容器（CRUD/版本号/落盘） |
| `arm_controller/track.py` | V3 相位跟踪（0x9C 编码器积分 + 0x92 校准，E0 显示角换算） |
| `arm_controller/limit.py` | 限幅判定纯函数（发送前拦截 / 运行中监控，越限锁只放反向） |
| `arm_controller/state.py` | 单台电机运行时状态（回复帧 → 角度/速度/在线更新，只 9C/92 驱动角度） |
| `arm_controller/supervisor.py` | 臂级状态机（全失联 2s → 整臂锁；SafetyReset 校验） |
| `arm_controller/controller_node.py` | ROS2 主节点（轮询线程/7 个服务/状态发布，接线都在这里） |
| `config/registry.json` | 档案种子（部署时 scp 到 ~/ROS2/arm_ws/config/registry.json 为权威副本） |
| `test/` | pytest 全套（纯逻辑模块零 ROS 依赖，源码树直跑） |

## 常用入口

```bash
python -m pytest test/ -q        # 本机（Windows/Jetson 均可）
controller_node                  # Jetson: 启动节点（tmux 内,先双 source）
ros2 service list                # 看 7 个服务是否就位
```

## 设计红线（勿破）

- 纯逻辑（registry/track/limit/state/supervisor）**零 ROS 依赖**，全部可单测；节点只做接线与编排
- 安全链：越限**先发 0x81 停再报警**、全失联 ≥2s 才锁（防热插拔误锁）、设零期间暂停轮询独占总线
- 轮询帧间隔由周期推导（0.8×周期÷帧数，下限 5ms）——勿改回无线时代固定 60ms
- 角度=显示语义角（V3 经 E0、V4 经 +E4），换算只在 registry/state/track 里发生
