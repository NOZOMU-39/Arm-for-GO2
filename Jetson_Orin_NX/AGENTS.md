# Jetson_Orin_NX — AI 对接文档

> 本目录 = Jetson 主控（图为 T801 + Orin NX 16GB）开发侧；人看 `README.md`；AI 看本文件。
> 事实层（硬件/协议/结论）以 `AI间交流\情报.md` Jetson 条目为准；本文件只放 AI 干活要用的对接信息。
> **目录边界（2026-09-05 用户定案）**：本目录只放 Jetson 板上运行的内容（`ROS2\arm_ws\`＝ROS2 源码单一源，与 Jetson 侧 `~/ROS2/arm_ws` 同名镜像）；Windows 操作前端＝顶层 `机械臂操作交互界面\`，与本目录是客户端-服务端关系（tcp_gateway 接入），**不并入本目录**；其协议逻辑第 1 步单一源化时改指向 `ROS2\arm_ws\src\arm_protocol`。

## 快速接入

- SSH：`192.168.31.114` / `nvidia` / 密码 `1`（登录界面有提示；sudo 密码同 `1`）；**免密已配（2026-09-05）**：Windows `~/.ssh/id_ed25519_jetson_go2`（无口令，`ssh -i` 直连；旧带口令密钥备份为 `.old-passphrase`）
- **远程操作可见性（用户规定）**：一切 Jetson 操作在 Jetson 的 tmux `ops` 会话内执行（send-keys + capture-pane），用户桌面「查看Claude操作」实时可见；不得旁路 SSH 直连（详见 `AI间交流\AGENTS.md` 规则 8）
- 临时文件一律 `/tmp/claude/`（重启自动清，不留垃圾）；Jetson 重启后 tmux 会话需重建
- 日常写码环境：Jetson 上已装 VS Code + Claude Code（DeepSeek 供应商）

## 系统现状速查（2026-09-05）

| 项 | 状态 |
|---|---|
| 密码 | `1`（用户定案，keyring 无密码） |
| 桌面 | 自动登录 nvidia（GDM），ToDesk 远程 |
| CAN | **can0 = USB-CAN（PCAN）**，开机自启 1Mbps，udev 热插拔自动 up；板载 mttcan 已 blacklist |
| 串口 | CH340 插上即用 ttyUSB0/1（IMU 921600→1000Hz）；⚠️ 插拔顺序导致名字互换 |
| 禁更新 | 图为约束已配（NVIDIA 源停用/apt-daily 禁/6 内核包 hold）——**不得擅自升级 JetPack/L4T/内核/rootfs/BSP** |
| 开机/关机 | 短按两下开机；**关机=长按 10 秒（优雅）**；桌面短按弹 60 秒框；电源键非 input 设备，logind 收不到，勿再折腾短按直关 |

## CAN 技术档案（干活必读）

- 驱动：**PEAK 官方 peak-linux-driver 8.15.2 `make netdev`** 编译的 SocketCAN 版 pcan.ko（源码在 `Database\USBCAN卡资料_PCAN\02-Linux下驱动\`；chardev 版≠SocketCAN 版）
- 开机服务：`/etc/systemd/system/can0.service`（modprobe can/can_raw/pcan + up can0 1M）
- 热插拔：`/etc/udev/rules.d/99-can0-autoup.rules` + `/usr/local/bin/can0-autoup.sh`（KERNEL can* 匹配 + %k 接口名，多块 USB-CAN 各自触发）
- **已知坑**：
  - can 接口是**虚拟 net 设备**（DEVPATH virtual）——udev 厂商属性匹配不上，只能 KERNEL 名匹配
  - 写脚本别用 shell 嵌套转义（`$1` 会被外层吃掉）——用 sftp 直接写文件
  - brltty 服务抢 USB 串口（已 mask brltty.service + brltty-udev.service + udev 规则禁用）——新装系统要重做
  - 链路验证方法：与 Windows ZLG 分析仪双向对发 1000 帧零丢帧（Jetson cansend / candump）
- 电机协议帧：与上位机/交互界面同协议（ID=0x140+电机号，0xA4/0x92 等）——移植协议库时参考 `电机上位机开发\` 与 `机械臂操作交互界面\`

## 工程约束（本领域）

- **图为禁更新约束**：不升级 JetPack/L4T/内核/设备树/启动链；不替换 rootfs/BSP；任何升级先备份并核对图为兼容包（详见情报）
- **开发提醒（用户 2026-09-04 要求）**：写外设程序（IMU/摄像头/手柄/电机）必须考虑热插拔——udev 事件/固定设备名＋应用层重连，**禁止轮询检测设备**
- **代码注释纪律（用户 2026-09-05 规定，所有 ROS 包模块强制）**：每个功能模块必须有**模块级 docstring**——干什么/移植自哪（JS 源与函数名）/关键语义；移植函数逐句保留 JS 行为注释（不许"看起来等价"擅自简化——limit.py 教训：自以为是优化分支链被测试逮住）；常量带单位与来源（实测档案/手册节号）；真机实证结论就地注日期；节点类/回调注明职责与调用频率；**controller 未来内容量大（流程/算法模块陆续入住），不留注释默认看不懂——新增模块无注释不入库**
- **领域边界**：IMU 域工作归 IMU 会话（`Database\IMU`），跨域只讨论不定案不落盘；情报写入须用户明确同意
- 禁更新包列表（hold）：nvidia-l4t-display-kernel / nvidia-l4t-kernel / -dtbs / -headers / -oot-headers / -oot-modules

## ROS2 控制栈（开发进度 2026-09-05）

- **包地图与边界规则（2026-09-05 架构决议，勿破）**：
  - **命名规律**：`arm_` 前缀 = 臂脉塔电机域专属（interfaces/protocol/can_bridge/controller）；**外设（IMU/摄像头/手柄）独立 driver 包、用自己的名**（如 hi12s2_imu），不并入臂域；ROS 惯例=协议随设备走，**arm_protocol 只装脉塔电机协议**，其余设备协议归各自 driver，不得并入（边界声明在包 README）
  - **arm_controller = 臂主控总包，一名到底**（命名决议：曾议拆 supervisor+controller，撤销——中小型项目一包演进更常用）：一期=档案/轮询/安全链/流程服务；**二期控制算法模块（后坐抑制等）挂入本包 control/ 或作扩展节点**，届时安全语义=controller 持总闸与授权包络、算法在包络内自主（生成 vs 执行判据写架构文档）
  - **tcp_gateway = Windows 前端（公用）↔ Jetson 统一入口**（非 arm 专属，故不叫 arm_gateway）：一期 v1 帧透传（臂域）→ 二期语义化接 controller → 三期接入外设监控（IMU 曲线/手柄回显/摄像头状态）；**边界：视频走独立流不进帧网关；实验高频数据不出 Jetson（1kHz 采样本地 rosbag），前端只看降频**
  - **单主纪律**：任何时刻总线只有一个轮询/命令主（Windows 界面或 Jetson 栈，二选一，v1 透传期=界面主、controller 只旁听不轮询）
- **第一期六包已完三**：arm_interfaces（5 msg/7 srv）→ arm_protocol（协议库全移植，pytest 5212）→ can_bridge（真机双向打通）——详见情报「Jetson 控制栈开发进度」条目；剩 arm_controller → tcp_gateway → arm_bringup
- **同步机制（已实践）**：Windows 改源码 → `scp -i ~/.ssh/id_ed25519_jetson_go2 -r ROS2/arm_ws/src/<包> nvidia@…:~/ROS2/arm_ws/src/` → tmux ops 内 `cd ~/ROS2/arm_ws && source /opt/ros/humble/setup.bash && colcon build --packages-select <包>` → `source install/setup.bash`
- **⚠️ 新终端环境**：bashrc 未配 ROS——每个新 tmux 会话必须显式 `source /opt/ros/humble/setup.bash && source ~/ROS2/arm_ws/install/setup.bash`（否则 ros2 命令找不到）
- **⚠️ Humble 兼容（2026-09-05 真机踩坑）**：无 `QoSPresetProfile`（用 `QoSProfile(depth=100, history=HistoryPolicy.KEEP_LAST)`）；CLI `topic pub/echo` 默认 BEST_EFFORT 与节点 RELIABLE 不匹配——CLI 测试要加 `--qos-reliability reliable`；接口包构建需 rosidl_default_generators（已装）
- **ROS2 节点跑法**：`ros2 run` 找 executable 有兼容怪癖（setuptools 新版装 bin/）→ 直接跑命令名（`can_bridge`）更稳
- **can_bridge 真机验证工具链**：tools/real_probe.py（0x9A/0x92 快速探测）、tools/full_read_probe.py（全只读命令 static/dynamic 两段）；跑法见文件头注释
- **协议改动联动纪律**：改交互界面 index.html（JS 源）→ 界面 Node 回归 → arm_protocol 重跑 `tools/gen_golden.js` + `gen_rand_vectors.js` → pytest 全绿 → 同步 Jetson
- **tcp_gateway 演进备忘（不许止步 v1）**：v1 帧透传(ESP32 TCP 兼容，界面零改动) → 二期界面语义化+安全链下沉 arm_controller → 三期多前端接入（详见情报）
- V3 相位跟踪/限幅判定（v3TrackOf/v3PosDual/limitBlock）归 arm_controller 轮移植（见界面测试文件）；电机闭环运动验证按 SOP 待 controller 阶段
- **⚠️ 待办（2026-09-05，0x9D 教训派生）**：arm_protocol 未真机验证解析分支**逐分支盘点**（黄金向量只保证"两实现一致"，不保证"实现正确"——对拍过的每个分支都要对照 V3.9/V4.4 手册原文 + 真机帧库复核；盘点结果落情报）

## 日志与验证

- 操作监控：用户桌面「查看Claude操作」→ tmux ops 会话
- 内核/系统日志：`journalctl`（sudo）；CAN 错误看 `ip -d link show can0` 的 berr-counter
- 串口读 IMU：`sudo stty -F /dev/ttyUSB0 921600 raw -echo && sudo timeout 2 cat /dev/ttyUSB0 | xxd | head`
