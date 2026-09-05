# arm_ws — Jetson 机械臂 ROS2 控制软件（源码）

> 机械臂主控（Jetson Orin NX）的 ROS2 控制软件源码。
> 开发在 Windows 电脑的仓库内进行（本目录为**源码单一源**，git 管理）；Jetson 上的 `~/ROS2/arm_ws` 是从这里同步的构建副本。
> AI 开发细节见 `Jetson_Orin_NX\AGENTS.md`；架构决策见 `AI间交流\情报.md`。

---

# 📖 第一部分：这是什么

Jetson 控制机械臂电机的一套软件，按包分块搭建：

| 软件包 | 干什么 |
|---|---|
| arm_interfaces | 消息/服务定义（各软件包之间的"通信格式"契约） |
| arm_protocol | 电机协议库（把指令编成电机帧、把回复译成人话） |
| can_bridge | CAN 帧桥（软件 ↔ can0 总线之间的通道） |
| arm_controller | 控制核心（轮询/安全限幅/设零）——开发中 |
| tcp_gateway / arm_bringup | 界面接入 / 一键启动——待做 |

目录结构：

```
arm_ws/
├── src/            # 各软件包源码（与 Jetson 端同构）
├── build/install/log/   # 构建产物（Jetson 端生成，不入 git）
└── README.md
```

---

# 📖 第二部分：新用户操作

一次"改代码 → 上真机"的标准流程：

1. **改源码**：在仓库 `src/` 下对应包内修改；
2. **本机自测**：进包目录跑 `python -m pytest test/`（协议库有 5000+ 项自动测试）；
3. **推送 Jetson**：`scp -i ~/.ssh/id_ed25519_jetson_go2 -r src/<包名> nvidia@192.168.31.114:~/ROS2/arm_ws/src/`；
4. **Jetson 构建**（在 Jetson 终端，先开环境）：
   ```bash
   source /opt/ros/humble/setup.bash && cd ~/ROS2/arm_ws
   colcon build --packages-select <包名>
   source install/setup.bash
   ```
5. **跑节点**：`can_bridge`（当前可跑的帧桥节点；建议在 tmux 会话里跑方便停）。

> ⚠️ Jetson 每个新终端都要先执行第 4 步的两个 `source`（环境未写进 bashrc）。

---

# 🔍 第三部分：深度开发参考

- **协议改动联动纪律**：协议库（arm_protocol）的逻辑以交互界面的 JS 版为源——改 JS 后必须重跑两个黄金向量生成器并双端测试全绿才允许提交（详见 `机械臂操作交互界面\AGENTS.md`）；
- 各包内部结构与接口：见包内源码注释与 `Jetson_Orin_NX\AGENTS.md`；
- 真机验证工具：`arm_protocol/tools/real_probe.py`（快速探测）、`full_read_probe.py`（全只读命令验证）；
- 构建产物不入库：`build/ install/ log/` 已在 `.gitignore`；
- 开发进度：见 `Jetson_Orin_NX\README.md`「深度参考」。
