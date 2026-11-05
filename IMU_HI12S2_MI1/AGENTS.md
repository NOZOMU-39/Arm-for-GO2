# AGENTS.md — IMU 双端测量（HIPNUC HI12S2，AI 对接文档）

> 🤖 AI 对接文档（后续 AI 开发自动读取）；人类使用说明见同目录 `README.md`。一手资料：`Database\IMU\HI12系列指令与编程手册.pdf`（65 页）＋`HI12系列规格书.pdf`（30 页）＋`CHCenter_上位机\`（log 也在）；跨模块结论见 `AI间交流\情报\03_通信与IMU.md`（2026-11-03 起情报改为「目录页＋分册」，原「情报.md 第六节」即此册）。⚠️ 两本 PDF 中文为内嵌字体子集，**pdftotext 中文乱码，须 pypdf 提取到 UTF-8**（临时脚本曾放 /tmp/claude，已删）。

## 1. 工程定位与目录

- 任务：双端 IMU 测量链 = HIPNUC 精浦 HI12S2-MI1-000 ×2（枪口端＋基座端），服务论文「后坐扰动抑制」——枪口角/角速度测量 + Jetson 统一时间戳测量链（论文侧叫「测量链 P3」，通过门＝同一事件多通道可靠关联、可复现）。
- 硬件事实：**S2 型号 = IMU/VRU，无磁力计**（规格书型号表实锤；S3 才有磁力计/AHRS）。只能用 6 轴模式：yaw 上电归零、相对航向。这不可惜——手册明示室内/机器人/电机磁场环境慎用 9 轴，本场景全是电机，6DoF 选型正确（2026-08-16 用户确认）。
- 接口：UART（0x91 二进制，**921600 波特实测 1kHz 全量达成**）＋ CAN（CANopen/J1939，默认 500K/100Hz，硬件未到货未实测）＋ 外部 SYNC 触发（800µs）。
- 外设状态（2026-09-03）：本体 ×2 已到手一只在测（USB/UART 直连 CHCenter 可读）；**Jetson 侧 CAN 收发器（T801 无板载收发器，需 SN65HVD230 类）与 USBCAN 均未到货 → CAN 侧一切实测锁死**。
- 外设状态（2026-09-06）：**Jetson 侧 UART 双路 1kHz 全量达成**——双 CH340（第三方 USB-TTL，非官方 CP2104）直插 Jetson 板载 USB 口 + open 后写 1 字节激活（见 2.7 与已知坑表），实测 999.9fps × 2、CRC≈0；CAN 侧仍锁死（等收发器）。

```
IMU_HI12S2_MI1\
├── README.md          # 人类说明书(本文档同目录)
├── AGENTS.md          # 本文件（AI 对接）
├── HI12_SDK\          # 官方 SDK（开源，GitHub hipnuc/products）
│   ├── drivers\       #   解码库：hipnuc_dec(0x91/0x81/0x83)、canopen_parser、hipnuc_j1939_parser
│   ├── examples\C\          #   串口 Linux CLI：hihost
│   ├── examples\CAN\linux\  #   CAN Linux CLI：canhost（主线 J1939，硬件时间戳+JSONL 落盘）
│   ├── examples\CAN\dbc\    #   CANopen.dbc / J1939.dbc + ini（分析仪可直接导入）
│   └── usb_uart_drivers\    #   CP210x 驱动（win/linux）——官方评估用 CP2104，非 CH340
└── tools\
    ├── uart_recorder\       #   Windows 采集器 + 分析器（09-03 基线用）
    └── imu_dt.py            #   帧到达间隔分析器（stdlib，验证 921600 收流完整性/丢帧形态）
```

## 2. 协议与关键结论（已查证，勿再推翻）

### 2.1 0x91 帧（UART 主力，float 无损）
- 总 82B：`5A A5` ＋ len u16 小端(=76) ＋ CRC16 ＋ payload 76B；**CRC-16/XMODEM**（0x1021、初值 0、无反转），范围＝帧头2＋长度2＋数据域（不含 CRC 自身）。
- payload（全小端，float IEEE-754，**勿把 payload 强转 C 结构体**）：tag 0x91 / main_status u16 / temperature i8 ℃ / air_pressure f32 Pa / **system_time u32 ms** / acc_b f32×3 **G** / gyr_b f32×3 **deg/s** / mag_b f32×3 μT（**6DoF 版无效数据**）/ roll·pitch·yaw f32 deg / quat f32×4 WXYZ。
- ⚠️ 单位：0x91 角速度 deg/s；0x81/0x83（INS）帧是 rad/s——差 57.3 倍，SDK 两套勿混。
- **system_time 只有 ms 级**：未 UTC 对时＝上电单调计数、24h 回绕（0~86,399,999）。1kHz 下粒度＝帧周期，**只够丢帧检测，帧级定序必须靠接收端时钟**（测量链统一时间戳不能依赖帧内时标）。

### 2.2 坐标系与轴（可配置体系，不是死的）
- 传感器系 b：X/Y/Z 印在外壳/PCB 丝印＝**唯一物理基准**；acc/gyr/mag 原始量在此系。
- 用户坐标系：`CONFIG IMU URFR <CODE>` 声明安装方向——三位码 ABC＝用户 X/Y/Z 轴分别对准传感器的哪个方向（0=+X 1=−X 2=+Y 3=−Y 4=+Z 5=−Z，须满足右手系 X×Y=Z）；24 种常用安装位（024 默认水平＝与传感器系一致 / 205 前向 / 304 前向 Y 左 / 240 立装 X 上…），支持自定义。**装法定死后按表选码，输出即归一化到「右-前-上」，不用迁就传感器轴**。
- 世界系：ENU（默认）/NWU，`CONFIG IMU COORD` 切；**欧拉旋转序随坐标系变**：ENU=312、NWU=321（roll/pitch 绕的轴会互换）。切系后必须重认航向基准。
- 姿态校准：`CONFIG ATT RST`（航向复位/相对零点/自动校平，须静止）；各轴输出方向可独立反向。
- 欧拉量程：roll ±180°、pitch ±90°、yaw ±180°。**pitch ±90° 万向锁奇异 → 枪口朝天/大仰角场景姿态核心量用四元数**。

### 2.3 yaw 语义（跨协议坑，混用必须归一）
- HI91/CANopen：±180°，逆时针为正（ENU）。
- J1939 YAW 报文：前 4B **0~360° 顺时针为正**；后 4B ±180° 逆时针为正。
- 6 轴 VRU：yaw 上电＝0（无磁力计无绝对航向）；对瞬态扰动测量（毫秒级相对角）无影响，甚至省了绝对基准问题。

### 2.4 CAN 模式（DBC 已解析，硬件未到，帧预算推算已定论）
- CANopen（node ID 默认 8，帧 ID＝0x180+n…0x780+n）：TPDO1 加计（0.001g）/ TPDO2 陀螺（**0.1°/s，int16 上限 ±3276.7°/s < 本体 ±4000°/s，大角速度会溢出**）/ TPDO3 欧拉（0.01°）/ TPDO4 四元数（0.0001）/ TPDO6 气压 / TPDO7 倾角。**每周期 4~6 帧**。
- J1939（canhost 主线）：主机 SA 0x55 周期发请求（0xff34 加计/0xff37 角速度/0xff3d 横滚俯仰/0xff41 航向/0xff46 四元数），设备应答——请求+应答，总线开销翻倍。
- **帧预算定论：双 IMU 1kHz 全量走 CAN 物理不可行**——CANopen ≈8k 帧/s、J1939 更甚，均超 CAN 1M 上限 ~7400/s；**1kHz 高保真唯一通道 = UART 921600 的 0x91 全量帧（已实测达成）**。CAN 侧 100/500/1000Hz 各档实际能力待硬件到货做同款对照实验。
- canhost 已内置可复用：SocketCAN 硬件时间戳（SO_TIMESTAMPING_RAW_HARDWARE）、`stream record -o xx.jsonl` 落盘、`config reg` 读写、`firmware update`、`trigger sync`——**Jetson 侧先复用，不造轮子**。

### 2.5 UART 波特率实测（2026-09-03，CHCenter 1.7.8.14）
- 115200→~142Hz；**460800→~500Hz；921600→~1000Hz**（0x91 全量 82B/帧 ≈ 82KB/s，921600 有效 92KB/s，占用 ≈89%）。
- 心智模型：波特率＝水管粗细，输出频率＝水龙头开度，实际流量＝min——配 1000Hz 必须 921600，只配频率不拉波特率永远 ~142Hz。
- ⚠️ 89% 占用下 USB 桥丢字节风险↑（见 3.1 未解问题）。

### 2.6 配置手段
- 首次配置：Windows CHCenter（USB/UART，支持固件更新、波特率/频率/URFR/协议烧写，配置存 IMU flash 掉电保存）；CLI 侧：canhost `config reg`（J1939 寄存器）+ ASCII CONFIG 命令。改波特率后 CHCenter 连接侧要同步选新值；连不上就断电重启＋自动识别波特率，出厂默认 115200 总能回。
- CHCenter 2026-09-03 已升 1.7.8.14；运行 log 在 `Database\IMU\CHCenter_上位机\log\`（排查利器，纯文本）。

### 2.7 Jetson 侧 USB 收流定论（2026-09-06 首案，2026-09-08 修正根因，写码必读）

- **部署形态定案**：双 CH340 直插 Jetson 板载 USB 口（port1+port3 已验证 1000.0fps×2；**port4 有间歇枚举失败/modem -110 半死史，避用**）；**勿用华升 214b:7260 无源 HUB 接 CH340**（枚举风暴 `descriptor read -110`/`not accepting address -71`——HUB×tegra-xusb 组合不兼容，Windows 双插 996fps×2 正常；该 HUB 供 PCAN/Nordic 低速外设可用，部署形态见情报 09-06 HUB 补充条）。
- **⚠️⚠️ 丢帧真根因 = termios lflag ECHO 残留（2026-09-08 实锤，推翻 09-06「写激活」定论）**：Linux tty 默认 c_lflag 含 ECHO，`os.open` 后若只做部分清除（原 imu_dt.py 写法 `&= ~(ECHONL|ICANON|ISIG|IEXTEN)`，**漏清 ECHO/ECHOE/ECHOK**），n_tty 会把每个输入字节回显到 TX 方向——921600 收流已占 USB 全速 ~89% 带宽，加回显必然周期溢出：**933fps、每 ~15ms 缺整帧、dt 空洞 2ms、CRC 0**（与 09-06 观测形态完全一致）。配置二分实证：V1 部分清除=935fps 丢帧；V2 补清 ECHO 组=999.5fps；lflag 全清=1000.0fps。**采集侧标准配置：`at[3] = 0`（lflag 全清）——open 即满速，无需任何写激活**。09-06「写 1 字节激活、拔插/重启复发、三次可复现」为治标偏方，今证非必需，勿再依赖。
- **⚠️⚠️ ch341 满速收流后 close 高频死锁（2026-09-08 实锤，采集栈设计必读）**：921600 满速收流 ≥30s 后 close，ch341 芯片进死锁——**后续 os.open 永久挂起**（60s+ 超时仍不返回，无 dmesg 报错，USB 层疑似活着但 UART 引擎/控制通道不响应）；当日 4 次收流会话 3 次触发（matrix 重协商、cfg_test 多轮配置、imu_validate 正常收流×2），**正常满速收流直接 close 也锁**。恢复 = 拔插或 sysfs 软重置（`echo 0/1 > /sys/bus/usb/devices/<1-3.x>/authorized`，~2s 重枚举）。**⚠️ 软重置仅限直插板载口的设备；HUB 下游设备做授权循环会引发 HUB clear tt error -71 风暴波及同 HUB 全部设备（含键盘/Nordic 输入）→ X 输入重配 → gnome-shell 崩溃黑屏（2026-09-08 实测事故），HUB 下设备死锁用物理拔插**。**采集栈设计：①进程常驻连续收流避免频繁 close；②收尾勿依赖正常 close，直插设备可 authorized 软重置（HUB 设备改物理拔插）；③或 open 前先 timeout 3s 探测，卡则按链路形态恢复**。
- 验证基线（2026-09-08 修复版）：双 CH340 直插 port1+port3 → 30s 长测 **1000.0fps × 2**（30001 帧/路、mean 1.0000/0.9999ms、大空洞 ≈0）；Windows 对照 996fps×2（同一 HUB 同一设备）。
- 检查工具（均 stdlib，**2026-09-08 v2 同步修复**：len==0x4C 校验+逐字节滑动滤伪同步+坏帧分型；v1 曾把 payload 伪 `5A A5` 误当帧头致坏帧误报/跳帧吃真帧）：①`tools/imu_dt.py` 帧间隔分析（内置 lflag 全清修复，无需手动激活）；②`tools/imu_verify.py` 严格 payload 验证（坏帧分型 len错/crc错、sys_time 跳变 Δ>1ms 全记、静止基线统计——**真丢帧判据以 IMU 侧 system_time 为准，dt 空洞只作参考**）；Jetson 临时脚本跑完即删（/tmp/claude 重启清空）。

## 3. 已知坑 / 未解问题

| 坑/问题 | 记忆点 |
|---|---|
| ch341 丢帧真根因 = termios ECHO 残留（2026-09-08 实锤修正） | 漏清 lflag ECHO 组→n_tty 回显占 USB 带宽→921600 每 ~15ms 丢整帧（933fps）；**配置 `at[3]=0` 即 open 满速**。09-06「写激活」定论已废 |
| ch341 满速收流后 close 高频死锁（2026-09-08 实锤） | ≥30s 满速收流 close → open 永久挂起（当日 3/4 触发）；恢复=拔插或 sysfs authorized 软重置。采集栈须常驻或软重置收尾 |
| 华升 214b HUB × Jetson 不兼容（2026-09-06 定论） | 无源 USB2.0 HUB 插 Jetson 枚举风暴（descriptor -110/-71）；Windows 双插正常。CH340 直插弃 HUB（HUB 供 PCAN/Nordic 低速外设用）；板载 1-3.4 口间歇坏避用（现用 port1+port3） |
| 配 1000Hz 实测 ~142Hz | 波特率没拉高——921600 才行，不是 IMU 坏（2026-09-03 已解决） |
| ch checksum error（**已定案，勿再追**） | 实测为 **IMU 串口流真实 CRC 错**（独立脚本绕过 CHCenter 证实）：460800 下 90s 共 4 帧错、错率 0.0081%、约每 20s 一次，与波特率无关（921600 同量级）。**2026-09-03 用户拍板：错率太低不追根因，管线加 CRC 校验坏帧丢弃兜底**（recorder.py 已实现）；换线可试但非必须 |
| PDF 中文提取 | pdftotext 乱码（字体子集无 ToUnicode 映射）→ pypdf 提取写 UTF-8 |
| 万向锁 | pitch ±90° 奇异；武器臂大仰角场景姿态量用四元数 |
| gyr 单位 | 0x91 deg/s vs 0x81/0x83 rad/s（57.3 倍） |
| CANopen 陀螺溢出 | int16×0.1°/s 上限 3276.7°/s；大角速度需求走 UART float |
| yaw 跨协议 | CANopen ±180° 逆时针正 vs J1939 0~360° 顺时针正——混用必归一（枪口 UART＋基座 CAN 方案必踩） |
| ms 时间戳粒度 | 帧内 system_time 只够丢帧检测；帧级定序靠接收端时钟 |

## 4. 开发路线与测试

四层（对论文侧「测量链 P3」）：P1 驱动解析（读出正确数据）→ P2 同步与时间戳（核心难点）→ P3 标定与基线（静噪/Allan/零偏/坐标系标定文件）→ P4 落盘与呈现（原始只读保存＋元数据＋可回放；交互界面 V1.0 设备面板 SIDEBAR_MODULES/DEVICE_TABS 已预留 IMU 占位）。

- 当前阶段：P1 大半完成（UART 链路通、波特率/帧率上限摸清）；CAN 侧实测等硬件。
- 开发模式（2026-09-03 共识方向）：**代码源 Windows（git 唯一根）→ 同步到 Jetson 跑**（Remote-SSH 既定工作流；can0 已 1Mbps 开机自启）；UART/CHCenter 是 Windows 评估通道。Jetson 上临时文件放 /tmp/claude/ 用完即删。**传文件细节（2026-09-08 补）：/tmp/claude root 属主+重启即清空（含目录）——scp 到 ~/ 中转再 `echo "1" | sudo -S mv`，勿直传；重启后先 `sudo mkdir -p /tmp/claude`；sudo 一律 -S 喂密码勿裸 sudo**。
- 协作姿势：用户当实验员、AI 远程读数据；CHCenter 界面操作让用户截图 → vision.js 识图再指导。
- 数据面方向性理解（**待用户确认，未定案**）：枪口端＝欧拉/四元数＋陀螺 1kHz 高保真（论文指标：枪口角误差/角速度峰值/恢复时间）；基座端＝陀螺为主（yaw 扰动前馈）；加计配角（后坐力激励校核/动量法）；欧拉与四元数冗余，可省一路换帧预算。

### 静态基线 v1（2026-09-03，921600/1000Hz，60.07s，990.9fps 达成，文件 capture1k.bin 留本地不入库）
- 角度抖动 σ：roll 0.0128° / pitch 0.0016° / yaw 0.0015°；静态漂移 60s：roll +0.040° / pitch +0.0004° / yaw −0.0006°（基本零漂）
- 陀螺噪声 σ 0.03~0.07 deg/s；加速度 σ 0.0003~0.0004 G；温度 34℃ 恒定
- 丢帧 5/59518（0.008%，含 1 次 523ms 主机侧大停顿）；CRC 错 5/60s
- **结论：分辨率/漂移/噪声对测量链富余 1~2 个数量级；roll 抖动为 pitch/yaw 8 倍（加计噪声经倾斜耦合）→ 枪口瞬态分析以陀螺+四元数为主量，欧拉角做显示/慢变量**
- 采集器用法见 tools/uart_recorder/README.md；analyzer 丢帧阈值按 meta 波特率自适应

### 双端装法约定（2026-09-03 用户定案草案，装机前升正式坐标系文档）
- **基座端**（狗背/基座）：用户系 X 朝狗本体前方、Y 朝左、Z 上（标准机器人惯例）→ 直接读狗基座姿态
- **枪口端**（枪/模拟器，随动）：用户系 X 沿枪管朝前（射击方向）；**Y 优先朝左**（与基座端同约定→欧拉语义一致＋双端差分零转系），Y 朝上为兜底（结构限制时可用，但欧拉语义反直觉、差分需转系，瞬态主量仍用四元数+角速度分量不受影响）——待枪座结构 CAD 定
- URFR 码=装机后按传感器丝印实际朝向查 24 表填（软件只消 90° 级）；小角度装偏无任意角补偿（手册已查证）→ 机械定位面保证 + 固定偏置记标定文件；上电对准 SOP：基准姿态上电→校平→记初始 yaw 偏置

## 5. 待办与等硬件验证清单

现在（不依赖 CAN 硬件，基线已完成）：
1. ~~静态基线第一份数据~~（2026-09-03 完成，见上）
2. 动态语义验证：手持晃动/翻转确认各轴输出与 URFR 024 默认对应关系（快检，~2 分钟）
3. 安装坐标系定案：枪口端/基座端机械装法 → 选 URFR 码（等模拟器/枪座 CAD 或实物定位）
4. CHCenter 配置项截图归档（安装方向/坐标系/输出勾选在哪）

等 CAN 硬件（收发器＋USBCAN 到货）：
5. canhost 编译跑通（Windows 源 → Jetson 同步）
6. CAN 波特率×频率对照实验（500K/1M × 100/500/1000Hz 实际帧率，验证 2.4 推算）
7. 双 IMU node ID 区分、与电机总线共存拓扑验证（推荐独立第二路 CAN，射击瞬态不与电机抢总线）
8. SYNC 外部触发 800µs 实测（后坐力模拟器相位霍尔 → TTL → HI12S2 SYNC → Jetson 时间戳）

## 6. 文档分工

- 人类：`README.md`；AI：本文件＋`AI间交流\情报\03_通信与IMU.md`（原「情报.md 第六节」）；交接协议见项目根 AGENTS.md。
- 一手来源：`Database\IMU\` 两本 PDF＋CHCenter；官方 SDK 线上仓库 `github.com/hipnuc/products`。
