# 交接：ESP32 WiFi CAN 固件 v2.1.3 与无线性能实测

> 生成日期：2026-08-24　来源：Claude（会话退休）　状态：待接手
> 本会话主职：ESP32 for WiFi CAN Custom 固件重写 + 性能实测 + 批帧/UDP 优化落地。
> 接手方必读：项目根 `AGENTS.md` + `ESP32 for WiFi and BLE CAN\AGENTS.md`（领域对接文档）+ `AI间交流\情报.md`（第五节通信与控制/第六节速率预算已更新至 v2.1.3 实测）。

## 一、现状（已完成）

**固件 v2.1.3（`ESP32 for WiFi and BLE CAN\ESP32 for WiFi CAN Custom\`，编译零警告）**：
1. **批帧推送**（v2.1.0）：帧类型 0x05，客户端发 `CMD_ENABLE_BATCH=0x0A13` 协商后启用（**0x0A12 预留给心跳看门狗，勿占用**）；攒批参数 64 帧/10ms 超时（WS_Config.h `CAN_BATCH_MAX_FRAMES/TIMEOUT_MS`）；旧客户端不发协商 → 保持 0x03 单帧，兼容；
2. **UDP 通道**（v2.1.1，可选）：8889 端口，发任意包即订阅，批帧推送，30s 保活，最多 4 订阅者；
3. **任务核心分配**（v2.1.2，关键修复）：CANTask/TCPTask/UDPTask/WebTask/SerialTask 全部 pin 核心 1；**核心 0 必须独占给 WiFi/lwIP 协议栈**——此前全部任务挤核心 0 抢占 tcpip_thread CPU，导致 TCP 收包卡死（"发 1000 显示 700"、批量发送 5469 帧超时的根因）；
4. **发送健壮性**（v2.1.1）：twai_transmit 超时 1s→10ms（`CAN_TX_TIMEOUT_MS`，无 ACK 不卡死 TCPTask）；BUS-OFF 自动恢复（twai_initiate_recovery）；[CMD] 每帧 printf 节流为每秒统计（`CMD: N` 并入 [CAN] 统计行）；TX/RX 队列 5→64；`twai_message_t msg = {}` 清零初始化（原未初始化有垃圾值风险）；
5. **性能优化**（v2.1.3）：TCPTask 批量 read（256B 缓冲，原逐字节 read 每帧 13 次 lwIP 调用）；TCP/UDP 发送头+载荷合并一次 write；Python 客户端自动发现把 AP 直连提到第 0 级（AP 模式秒连，STA 只多 0.3s）；
6. **Python 客户端**（examples\wifi_can_client.py + test.py）：批帧解析（`CANFrame.parse_batch`）、自动协商、`--udp` 模式、test.py 带完整日志自检 + `--batch-send N` 批量测速；`send_can(verbose=False)` 静默发送。

**性能实测结论（分析仪 II 作测试源，用户确认）**：
- **接收方向 750 帧/s 全通零丢失**（STA 750.4 / AP 754.6 一致；ESP32 串口 RX ≈ Python [STATS] RX ≈ 分析仪上位机统计）；
- **瓶颈 = 分析仪发送端**（Windows 定时精度，"1ms 间隔"实际 ~1.33ms ≈ 750/s）；**ESP32 真实接收上限未测出（≥750/s）**；
- 发送方向：AP ~630/s、STA ~430/s（命令逐帧 TCP 段，够控制场景用）；
- 理论上限核算：接收 ~5000-6400/s（CAN 物理 ~7400 × 批帧参数 64帧×100包/s × CANTask 轮询 2ms 周期），符合情报.md「无线 ≥5k」目标；发送需命令批帧化才能上 2k+。

## 二、待办（接手方按此继续）

- [ ] **git 提交 v2.1.3 里程碑**（本交接文件生成时尚未提交；改动：src\ 10+ 文件、platformio.ini、examples\、README.md、情报.md。注意 `git add` 用精确路径，勿 `git add -A` 卷进 Database/ 等资料）
- [ ] **双 ESP32 回环实测接收上限**（用户已计划再买一块）：一块发、一块收，绕开分析仪 750/s 限制，验证 5-6.4k 理论值
- [ ] （可选）**命令批帧化**：PC→ESP32 增加批命令类型，发送方向从 ~630/s 提到 2-5k/s（协议扩展，需用户批准）
- [ ] （可选）突发尖峰场景：CANTask 轮询 2ms 周期对 5k/s 每周期 10 帧、队列 64 帧余量不大，必要时改中断驱动或缩短轮询

## 三、下一步

1. 读项目根 `AGENTS.md` + `AI间交流\AGENTS.md` + `情报.md`（已更新至 v2.1.3）+ `git log --oneline -20`；
2. 完成 v2.1.3 的 git 提交（见待办，先问用户）；
3. 新硬件到后做双 ESP32 回环测试，**测试类任务先报数据，不擅自改代码**；
4. 有优化方案先给用户拍板再动（动代码前必须经用户同意——本会话曾因未请示直接改代码被批评）。

## 四、踩坑（本会话实测教训，接手方必读）

- **任务核心分配是最大坑**：ESP32-S3 的 WiFi 协议栈 + lwIP tcpip_thread 跑核心 0，用户任务必须 pin 核心 1；此前所有任务挤核心 0 导致 TCP 收包卡死、未读=0、CMD 停——表现为"数据到不了 ESP32"；
- **0x0A12 命令字冲突**：心跳看门狗规格占用 0x0A12，批帧协商必须用 0x0A13（情报.md 有记录，勿再撞）；
- **Windows TCP 发送缓冲 64KB**：批量发送 ~5470 帧（×12B≈65.6KB）后 sendall 必超时——这是 Windows SO_SNDBUF 上限，与 ESP32 无关；测真实吞吐要靠 ESP32 串口 `CMD: N` 计数对照，不要信 Python 侧速率；
- **分析仪"1ms 间隔"≈750/s 实际**（Windows 定时精度），其自身统计也是 ~750——三端（分析仪/ESP32/Python）一致时链路就是零丢失；
- **Arduino-only 框架下 sdkconfig.defaults 不生效**（PlatformIO 已知限制），不要从 PlatformIO/sdkconfig 下手调参（用户明确不认可该方向）；
- **Python 客户端坑**：`parse_batch` 是 staticmethod 不能写 `cls(...)`（须用 CANFrame(...)）；monitor 只发不收会因接收缓冲填满死锁（ESP32 推送方向阻塞 TCPTask）——高频测试要让 Python 边发边收；
- **printf 节流**：[CMD] 每帧打印在高速时拖慢 TCPTask，已节流为每秒统计（`[CAN] ... | CMD: N`）；
- **ESP32 串口日志格式**（v2.1.3）：`[CAN] RX: x.x fps (N帧) | TX: x.x fps (N帧) | CMD: N`，每秒一行；启动横幅版本号 `v2.1.3`。

---
按项目根 AGENTS.md「对话交接协议」执行：接手方先读本文件 + 领域 AGENTS.md + 情报.md + git log，再向用户汇报确认。
