# Jetson Orin NX — 使用说明

> 机械臂主控设备（图为 TWOWIN T801 定制载板 + NVIDIA 原装 Orin NX 16GB 模组）
> AI 协作细节见项目 `AI间交流\情报\03_通信与IMU.md`（2026-11-03 起该站情报改为「目录页＋分册」，Jetson 条目在此册）
> 目录边界（2026-09-05 用户定案）：本目录只放 **Jetson 板上运行**的内容（`ROS2\arm_ws\` 控制软件源码等）；Windows 操作前端 `机械臂操作交互界面\` 保持顶层独立、经 TCP 接入（客户端-服务端）

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

## 开机自启与联网（2026-09-06 起）

- **控制栈开机自启**：Jetson 开机自动拉起 can_bridge + tcp_gateway（界面主模式），等 USB-CAN 就绪后启动，无需手动开窗口
- **联网三档策略**：插网线（路由器）优先 → 没网线自动连电脑热点  → 都没网时桌面弹提醒
- **查 IP/状态**：桌面终端敲 （界面连接 IP 以它为准，DHCP 会变）；部署详情见 

## 机械臂控制软件（ROS2，可选使用）
- Jetson 正逐步搭载一套 ROS2 机械臂控制软件（源码与进度见文末「深度参考」）
- 看总线原始帧：`candump can0`（Ctrl+C 退出）
- 跑 CAN 帧桥节点（当前唯一可跑的软件节点）：
  ```bash
  source /opt/ros/humble/setup.bash && source ~/ROS2/arm_ws/install/setup.bash
  can_bridge            # 在 tmux 会话里跑，方便 Ctrl+C 停
  ```

## 掉电丢圈与上电位置校正（2026-09-06 起，日常必读）

机械臂无抱闸，急停/掉电后若臂转动过（垂落/手动摆臂），转子整圈发生在无电期间 → 重新上电后角度可能差整圈（X6 每圈 10°、X2 每圈约 12.8°）。**V4 四台的多圈掉电保存（索引 4）已持久开启**——静止掉电零丢失；丢圈只发生在"掉电后转动过"的场景。

- **正常流程（用 Windows 界面的用户）**：急停后把臂摆回固定姿态再上电，连界面**自动检测修正**（弹提示"检测到掉电丢圈，已自动修正"）——什么都不用做；首次使用先在界面点一次「📍 记录机械臂上电位置」；
- **不用界面（纯 Jetson 侧）**：摆好臂上电后跑一次校正工具（在 tmux 会话里）：
  ```bash
  cd ~/ROS2/arm_ws/src/arm_controller && source /opt/ros/humble/setup.bash && source ~/ROS2/arm_ws/install/setup.bash
  python3 tools/rest_calib.py         # 先 dry-run 看判定（丢圈 N / 一致）
  python3 tools/rest_calib.py --apply # 确认后落盘（自动备份 registry.json）
  ```
  ⚠️ 校正前断开 Windows 界面连接（总线独占）；换结构/换电机/重新设零后需重新记录上电位置（界面按钮或 `--mark-rest`）。

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

## 常见问题

| 现象 | 原因与处理 |
|---|---|
| SSH 连不上 `192.168.31.114` | 先 Ping——不通多半是没开机或 IP 被 DHCP 换了（桌面看 IP） |
| 按电源键没反应 | 开机要**短按两下**；关机用**长按 10 秒**（别直接拔电） |
| can0 状态不是 ERROR-ACTIVE | `ip -d link show can0` 看；USB-CAN 拔插一下，udev 会自动重新 up |
| 找不到 /dev/ttyUSB0/1 | CH340 没插或顺序变了（插拔顺序会互换名字，程序按实际设备名适配） |
| 想确认有没有被别人远程占着 | 桌面终端 `who` / `tmux ls`——所有远程操作都在 tmux `ops` 会话里可见 |
| 控制软件命令找不到/跑不起来 | 见 `ROS2\arm_ws\README.md`「常见问题」 |

---

# 🔍 深度参考（需要时再看）

## ROS2 控制栈（进度 2026-09-06：六包全部完成）

| 软件包 | 干什么 | 状态 |
|---|---|---|
| arm_interfaces | 消息/服务定义（控制软件间的"通信格式"） | ✅ 完成 |
| arm_protocol | 电机协议库（把指令编成电机帧、把回复译成人话） | ✅ 完成（5228 项自动测试 + 真机覆盖过） |
| can_bridge | CAN 帧桥（软件与 can0 总线之间的"翻译通道"） | ✅ 完成（真机双向验证过） |
| arm_controller | 控制核心（档案/轮询/安全限幅/设零服务/上电位置校正） | ✅ 完成（97 项单测 + 真机全路径） |
| tcp_gateway | 界面 TCP 接入（仿 ESP32 协议，界面零改动） | ✅ 完成（真机键盘点动实测过） |
| arm_bringup | 一键启动（界面主模式默认 / controller:=true 自主任） | ✅ 完成 |

- 源码在 Windows 仓库 `Jetson_Orin_NX\ROS2\arm_ws\`（开发在 Windows 侧），本机 `~/ROS2/arm_ws` 是同步构建副本
- 上电位置校正工具：`~/ROS2/arm_ws/src/arm_controller/tools/rest_calib.py`（用法见上文「掉电丢圈」节）
- 架构决策与开发细节：见 `AI间交流\情报\03_通信与IMU.md`（Jetson 条目，AI 协作文档）

## 资料索引

| 想看什么 | 去哪 |
|---|---|
| 硬件接口图解（40pin/CAN/电源） | `Database\Jetson\TW-T801-User-Guide.pdf`（p13-18 接口图） |
| CAN/USB-CAN 驱动与踩坑（AI 向） | `AI间交流\情报\03_通信与IMU.md`（Jetson 条目） |
| 刷机资料 | `Database\Jetson\JP6.2.2\`（rootfs + BSP） |
| PCAN 驱动源码 | `Database\USBCAN卡资料_PCAN\` |
