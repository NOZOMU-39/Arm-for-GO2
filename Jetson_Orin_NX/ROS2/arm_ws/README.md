# arm_ws — Jetson 机械臂 ROS2 工作空间（源码单一源）

> 机械臂主控（Jetson Orin NX / T801）的 ROS2 控制栈源码。
> 开发在这台 Windows 电脑进行，本目录为**源码单一源**（git）；Jetson 板上的 `~/ROS2/arm_ws` 是从本目录同步的**构建/运行副本**。
> 架构决策/接口消息契约等见项目 `AI间交流\情报.md` 与 `Jetson_Orin_NX\AGENTS.md`。

## 结构

```
arm_ws/
├── src/            # ROS2 包源码（colcon 工作空间 src，与 Jetson 端同构）
├── build/install/log/   # 构建产物（Jetson 端生成，已 gitignore，本机不生成）
└── README.md
```

## 第一期包（定案顺序，2026-09-05）

1. **arm_interfaces**（消息/服务定义，契约先行——字段已与用户过目确认）
2. **arm_protocol**（电机协议库：PROTO_CORE JS 版移植，52 项回归迁 pytest）
3. **can_bridge**（can0 SocketCAN ↔ ROS2 帧桥）
4. **arm_controller**（控制核心：轮询/限幅安全链/设零/状态机）
5. **tcp_gateway**（v1 帧透传 = ESP32 TCP 兼容，Windows 界面零改动接入）
6. **arm_bringup**（launch 一键启动）

tcp_gateway 演进（二期界面语义化、三期多前端）见情报「tcp_gateway 演进路线」条目——不许止步 v1。

## 同步机制（现状）

- 仓库含 Database/ 大二进制，Jetson **不可整体 clone**——Windows ↔ Jetson 同步机制待敲定（候选：sftp/rsync 定向推送 src、或 git over ssh 子目录）
- 暂定工作流：Windows 本机开发 → pytest/模拟验证 → 推送 `src/` 到 Jetson `~/ROS2/arm_ws/src` → `colcon build --packages-select <包>` → 真机只读小步验证
