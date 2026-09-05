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

## 同步机制（已实践 2026-09-05）

- 仓库含 Database/ 大二进制，Jetson **不可整体 clone**——用免密 SSH + `scp -r` 定向推送 `src/` 各包（key：`~/.ssh/id_ed25519_jetson_go2`）
- 标准工作流（已跑通三轮）：Windows 本机开发 → pytest 全绿 → `scp -r src/<包> → ~/ROS2/arm_ws/src/` → Jetson `colcon build --packages-select <包>` → 真机小步验证
- Jetson 新终端必须显式 `source /opt/ros/humble/setup.bash && source ~/ROS2/arm_ws/install/setup.bash`（bashrc 未配）

## 开发进度（2026-09-05）

| 包 | 状态 |
|---|---|
| arm_interfaces | ✅ 5 msg/7 srv 契约（含 CanFrame） |
| arm_protocol | ✅ 全移植，pytest 5212（黄金向量+随机对拍），真机只读验收过 |
| can_bridge | ✅ 真机双向验证通过 |
| arm_controller | ⏳ 下一步（V3 相位跟踪/限幅判定归此包） |
| tcp_gateway / arm_bringup | ⏳ 待做 |
