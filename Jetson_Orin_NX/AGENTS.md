# Jetson_Orin_NX — AI 对接文档

> 本目录 = Jetson 主控（图为 T801 + Orin NX 16GB）开发侧；人看 `README.md`；AI 看本文件。
> 事实层（硬件/协议/结论）以 `AI间交流\情报.md` Jetson 条目为准；本文件只放 AI 干活要用的对接信息。

## 快速接入

- SSH：`192.168.31.114` / `nvidia` / 密码 `1`（登录界面有提示；sudo 密码同 `1`）
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
- **领域边界**：IMU 域工作归 IMU 会话（`Database\IMU`），跨域只讨论不定案不落盘；情报写入须用户明确同意
- 禁更新包列表（hold）：nvidia-l4t-display-kernel / nvidia-l4t-kernel / -dtbs / -headers / -oot-headers / -oot-modules

## 下一步（接手入口）

- Jetson 控制核心服务（协议库移植 + CAN 通信 + 轮询 + 安全逻辑，供 Windows 界面与手柄双前端连接）——尚未开始
- 收发/链路已验证；电机闭环待接电机实测

## 日志与验证

- 操作监控：用户桌面「查看Claude操作」→ tmux ops 会话
- 内核/系统日志：`journalctl`（sudo）；CAN 错误看 `ip -d link show can0` 的 berr-counter
- 串口读 IMU：`sudo stty -F /dev/ttyUSB0 921600 raw -echo && sudo timeout 2 cat /dev/ttyUSB0 | xxd | head`
