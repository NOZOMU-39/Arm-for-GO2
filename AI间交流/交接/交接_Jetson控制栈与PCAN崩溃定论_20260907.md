# 交接：Jetson 控制栈 + PCAN 崩溃根因定论（2026-09-07）

> 生成日期：2026-09-07　来源：Claude　状态：待接手
> 接手方读序：项目根 AGENTS → AI间交流 AGENTS → 情报.md → 本文件 → Jetson_Orin_NX\AGENTS.md → git log --oneline -20 → 向用户汇报确认后开工。
> 本文件取代「交接_Jetson控制栈_20260906晨.md」中关于卡死/崩溃的部分（该文件保留历史）。

## 一、现状（2026-09-07，跨 9/6 夜~9/7 晨 12 小时排查战役的终态）

**系统部署（全部已生效并验证）**：
- arm-stack（can_bridge+tcp_gateway，界面主模式）+ can0 @1M + GDM 桌面 + ToDesk（服务+客户端）自启全链路正常
- **pcan 驱动已升级 8.15.2 → 8.20.0**（Release_20250213，`make netdev` 编译；旧 ko 备份 `~/backups/pcan-8.15.2.ko.bak`，**勿回退**）
- **⚠️ 使用提醒（无自动机制，靠提醒）**：界面(8888)满速轮询与 ToDesk 远程查看**不可同时**（实测叠加必崩，见情报 09-07）——曾尝试自动化互斥守护（todesk-ui-conflict-guard，界面接入退 ToDesk/会话断界面/iptables 拒连多版）**均已撤回**：界面断连后秒级重连使机制失效并干扰 ToDesk。**未来 AI 见用户同时使用两者应主动提醒错峰**（mttcan 根治前有效）
- 内核留痕：`/etc/sysctl.d/90-hang-detect.conf`（panic_on_oops=1、panic_on_rcu_stall=1、panic=0——**panic=0 是 9/7 改的，防重启死循环，勿改回 1**）
- GPU 画像 `~/gpu_profile.log`（gpu-profile.service 每 30s）+ Windows 哨兵 monitor_*.log（每 5min）——观察期工具

**崩溃根因定论（情报.md 09-07 两条 + 本文件）**：
- **整机反复崩溃/重启 = PEAK pcan 驱动 8.15.2 收包缺陷**（CAN 流量下 `pcan_netdev_rx` Oops/hang，崩溃点随机；曾致开机即崩死循环，拔 PCAN 即解）
- **8.20.0 只降频未根治**（同指令崩溃在 ~20 分钟重现）；**ToDesk 是放大器**（其 GPU/显示路径活动 + 界面满速轮询叠加时分钟级必崩；纯界面无 ToDesk 1h37m+ 稳定，memtester 8GB 零错排除内存）
- **可用形态 = 纯界面（长时间稳定实证）或人工错峰（不同时用 ToDesk 查看）**；**根治方向 = CAN 收发器（SN65HVD230 类）到货后启用板载 mttcan**（不经 USB/tegra-xusb 路径，SoC 内置控制器，当前 blacklist 中）

**文档归档**：崩溃档案 5 份 `~/crash_archive/`（pcan 现场×2、acct/exit、console 等）；pcan 8.20.0 源码已入库 Database\USBCAN卡资料_PCAN\02-Linux下驱动\PCAN\peak-linux-driver\；驱动 8.13~8.20 四版并列。

## 二、待办

- [ ] **mttcan 根治（收发器到货后，P0）**：解除 blacklist-mttcan → can0 迁移板载 CAN → can0.service/udev 规则更新 → 界面全开压测（届时「界面+ToDesk 同开」的崩溃约束有望解除）
- [ ] 观察期（几天）：守护+全开跑稳定后停哨兵/gpu-profile（问用户同意再停，临时文件规则）
- [ ] arm_protocol 未真机验证解析分支逐分支盘点（09-05 旧待办，0x9D 教训派生）
- [ ] 界面 dist 误入库治理：USBCANFD800U.log/注册表 json（打包产物，gitignore 待补）
- [ ] gnome-shell 偶发崩溃（桌面错误页，非系统崩）与 ToDesk 应用级崩溃——低优先观察项，/var/crash 有留档

## 三、下一步（接续顺序）

1. 用户日常使用观察（**提醒错峰**：界面与 ToDesk 不同时；若见用户同开，AI 主动提醒）
2. 收发器到货 → 按二.1 走 mttcan 根治
3. 期间再崩 → 现场三查：pstore(sudo ls!)/哨兵日志/~/crash_archive 归档；崩溃常现成可诊断事件（留痕已配）

## 四、踩坑（12 小时真金白银，接手方必读）

- **pcan 驱动版本即生死**：8.15.2 分钟级崩、8.20.0 ~20 分钟级崩（同一函数 `pcan_netdev_rx` 同指令 `f9000860`，缺陷未根治仅降频）——崩溃与 USB 口/路径/驱动版本无关，是 tegra-xusb FS 收包路径底层问题，只能错峰或绕开（mttcan）
- **崩溃循环的成因链**：panic_on_oops=1 + panic=1（我 9/6 夜设的观察参数）→ 开机即崩→自动重启→死循环；**panic=1 已改回 0**。当时拔 PCAN 才解循环
- **pstore 读法**：`/sys/fs/pstore/` 需 sudo（nvidia 直接 ls 报"没有那个文件或目录"= 权限误判，曾致误判"无痕"）——**查 pstore 一律 sudo**
- **pstore 会因强制断电丢失**（ramoops 是 RAM 保留区）——崩溃档案及时归档到 ~/crash_archive/（磁盘）
- **ToDesk 高级设置存 `/opt/todesk/config/config.ini` 的 `[connectconfiginfo]` 段**（globalrenderaccelerate/globalhardencodecpriority/globalvsync）——GUI 改设置要 **todeskd 服务在跑**才存得住（服务停了设置关不掉、重启恢复默认）
- **ToDesk 桌面自启三处**：todeskd.service(enable) + ~/.config/autostart/todesk.desktop + config.ini autostart=1——9/7 曾全禁过又恢复，勿再动（守护替代了"禁自启"方案）
- **ToDesk 客户端被杀会自己重启吗**：守护杀的是客户端进程；todeskd 服务常驻无害
- **临时文件教训**：Jetson /tmp/claude 重启即清空+变 root 属主（每次都踩）——**传文件用 ~/ 中转再 sudo cp**；临时脚本命名一眼懂、用完即删（用户讨厌乱糟糟）
- **关机慢是正常的**：systemd 收尾 gdm/ToDesk/循环服务，最长 ~90s，非故障
- IMU 侧（另一会话结论，仅引用）：CH340 枚举后 921600 丢 6.8% 需写 1 字节激活；华升 HUB 与 tegra 不兼容弃用——详见 IMU AGENTS 2.7

---
按项目根 AGENTS.md「对话交接协议」执行：接手方先读本文件 + 领域 AGENTS.md + 情报.md + git log，再向用户汇报确认。
