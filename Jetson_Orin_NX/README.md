# Jetson Orin NX — 使用说明

> 机械臂主控设备（图为 TWOWIN T801 定制载板 + NVIDIA 原装 Orin NX 16GB 模组）
> AI 协作细节见项目 `AI间交流\情报.md`（Jetson 条目）
> 目录边界（2026-09-05 用户定案）：本目录只放 **Jetson 板上运行**的内容（`control\` ROS2 源码等）；Windows 操作前端 `机械臂操作交互界面\` 保持顶层独立、经 TCP 接入（客户端-服务端）

---

# 📖 这是什么

| 项 | 内容 |
|---|---|
| 设备 | Jetson Orin NX 16GB（图为 T801 载板，100 TOPS） |
| 系统 | Ubuntu 22.04 + JetPack 6.2.3（已刷机交付，禁自动更新已配） |
| 角色 | 机械臂主控：本地 CAN 控制电机 + IMU 采样 |
| 访问 | 局域网 `192.168.31.114`，SSH 用户名 `nvidia` |

---

# 🔧 日常操作

## 登录
- **用户名/密码**：`nvidia` / `1`（登录界面有提示）
- **远程桌面**：ToDesk（Jetson 上已装）
- **SSH**：`ssh nvidia@192.168.31.114`（密码 1）

## 开关机（重要）
| 操作 | 方法 |
|---|---|
| **开机** | 短按两下外置电源键（硬件设计） |
| **关机（推荐）** | **长按电源键 10 秒**——优雅关机（已验证安全，等同系统 poweroff） |
| 关机（桌面态） | 短按弹框 → 点确认或等 60 秒自动关 |
| 远程关机 | `sudo poweroff` |

⚠️ 关机前别直接拔电源——突然断电有数据丢失/文件系统风险；Jetson 供电为独立 9-19V 电源。

## CAN（USB-CAN，机械臂电机总线）
- 设备：**PCAN-USB**（USB 转 CAN），插 Jetson 任意 USB 口
- **开机自动就绪**：`can0` @ 1Mbps（systemd 服务）
- **热插拔**：随时拔插/换 USB 口，插上自动 up（udev 规则）——无需手动配置
- 速查：
  ```bash
  ip -d link show can0        # 看状态（ERROR-ACTIVE = 正常）
  candump can0                # 监听总线
  cansend can0 141#A4000000   # 发一帧（电机 ID 1 的指令示例）
  ```
- 板载 CAN 端子（扩展端子组 TX/RX）已禁用（软件 blacklist），CAN 统一走 USB-CAN

## 串口（IMU 用 CH340）
- CH340 USB 转 TTL 插上即用：`/dev/ttyUSB0`、`/dev/ttyUSB1`（按插入顺序）
- IMU 实测波特率：921600 → 1000Hz 输出
- ⚠️ 插拔顺序变化会导致 ttyUSB0/1 互换——程序按实际设备名适配

## 常用命令速查
```bash
# 系统状态
cat /etc/nv_tegra_release     # L4T 版本
tegrastats                    # 实时负载/温度/功耗（Ctrl+C 退出）

# 串口读 IMU（示例）
sudo stty -F /dev/ttyUSB0 921600 raw -echo && sudo timeout 2 cat /dev/ttyUSB0 | xxd | head

# 临时文件
# 统一放 /tmp/claude/（重启自动清）
```

---

# 🤖 ROS2 控制栈（开发进度 2026-09-05）

> 机械臂控制核心按 ROS2 布局（见 `AI间交流\情报.md` 架构条目）；源码在仓库 `Jetson_Orin_NX\ROS2\arm_ws\`（Windows 开发），本机 `~/ROS2/arm_ws` 是同步构建副本。

| 包 | 状态 |
|---|---|
| arm_interfaces（消息契约） | ✅ 完成（5 消息/7 服务，真机构建验证过） |
| arm_protocol（电机协议库） | ✅ 完成（黄金向量+随机对拍 5212 项测试，真机只读验证通过） |
| can_bridge（can0 帧桥） | ✅ 完成（真机双向验证：tx 话题→电机→rx 话题） |
| arm_controller（控制核心） | ⏳ 下一个 |
| tcp_gateway / arm_bringup | ⏳ 待做 |

看状态/收发：`candump can0`（总线直看）；跑节点：`source /opt/ros/humble/setup.bash && source ~/ROS2/arm_ws/install/setup.bash && can_bridge`（在 tmux 会话里跑，方便 Ctrl+C）。

---

# 🔍 深度参考（需要时再看）

| 想看什么 | 去哪 |
|---|---|
| 硬件接口图解（40pin/CAN/电源） | `Database\Jetson\TW-T801-User-Guide.pdf`（p13-18 接口图） |
| CAN/USB-CAN 驱动与踩坑（AI 向） | `AI间交流\情报.md` Jetson 条目 |
| 刷机资料 | `Database\Jetson\JP6.2.2\`（rootfs + BSP） |
| PCAN 驱动源码 | `Database\USBCAN卡资料_PCAN\` |
