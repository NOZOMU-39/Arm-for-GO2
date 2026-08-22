# ESP32-S3-RS485-CAN 蓝牙无线CAN中继站

> ⚠️ **已弃用**：蓝牙方案实测太慢（远低于 WiFi 版），本工程只留作参考，勿改勿用。主力见 `..\ESP32 for WiFi CAN Custom\`。

# ESP32-S3-RS485-CAN 蓝牙无线CAN中继站

## 硬件

| 项目 | 说明 |
|------|------|
| 开发板 | 微雪 Waveshare ESP32-S3-RS485-CAN |
| 芯片 | ESP32-S3, 16MB Flash, 8MB PSRAM |
| CAN 引脚 | GPIO15 (TX), GPIO16 (RX) |
| RS485 引脚 | GPIO17 (TX), GPIO18 (RX), GPIO21 (EN) |
| I2C 引脚 | GPIO38 (SCL), GPIO39 (SDA) — 连接 PCF85063 RTC |
| 供电/烧录 | 标 **USB** 的 Type-C 口（原生 USB CDC） |
| 产品资料 | https://www.waveshare.net/wiki/ESP32-S3-RS485-CAN |

## 功能

将 ESP32 作为 **CAN 总线的无线中继站**，笔记本/手机通过蓝牙 (BLE) 实时收发 CAN 数据。

```
  ┌──────────┐     BLE      ┌─────────────────┐     CAN Bus     ┌──────────┐
  │ 笔记本/手机 │ ◄──────────▶ │ ESP32-S3-RS485   │ ◄─────────────▶ │ CAN 设备   │
  │          │   实时双向     │ -CAN 模块        │   1Mbps         │ (GO2等)   │
  └──────────┘              └─────────────────┘                 └──────────┘
```

---

# 性能特性

## CAN 总线层

| 参数 | 值 | 说明 |
|------|-----|------|
| CANTask 循环间隔 | **2ms** | 理论最高 ~500 帧/秒 |
| 支持波特率 | 25/50/100/125/250/500/800/1000 kbps | 可通过 BLE 或 Web 实时切换 |
| 发送 | 支持自动分帧（>8字节自动拆多帧） | 每帧最多 8 字节 |
| 接收缓冲区 | PSRAM, 最大 1000 字节 | 满后自动清空 |

## BLE 推送层

| 参数 | 值 | 说明 |
|------|-----|------|
| BLETask 轮询间隔 | **10ms** | 空闲时每 10ms 检查 CAN 缓冲区 |
| 推送后等待 | **5ms** | 连续数据时最小间隔 |
| **实际推送速率上限** | **~20-50 帧/秒** | ⚠️ 受 BLE 连接间隔限制 (默认 ~30ms) |

> ⚠️ **重要提示**：BLE 推送速率受蓝牙协议本身的连接间隔限制（Connection Interval），这是硬件/协议层面的限制，不是代码能突破的。CAN 硬件层可以 500+ 帧/秒，但通过 BLE 推送到笔记本的实际速率通常在 20-50 帧/秒。如果需要更高频率（如机械臂 100Hz+ 控制），建议改用 **WiFi WebSocket** 方案。

## 速率监控

- **Python 脚本**：每秒汇总 `⚡ 速率: 发送 xx.x fps | 接收 xx.x fps`（自收回显自动排除）
- **网页控制台**：接收区标题实时显示 `速率: xx.x 帧/秒`

---

# 外部调用方式

## 方式一：依赖 HTML（零安装，推荐入门）

使用 Chrome / Edge 浏览器打开 `CAN_BLE助手.html`，全中文界面。

### 操作步骤

1. 确认 ESP32 已上电烧录本工程固件
2. 用 Chrome 打开 `CAN_BLE助手.html`
3. 点击 **🔍 扫描设备** → 浏览器弹窗选 `ESP32-BLE-CAN` → 配对
4. 点击 **🔗 连接**
5. 连接成功后：
   - **设置波特率**：在下拉框选好，点 **⚡ 设置波特率**（必须和 CAN 总线一致）
   - **发送 CAN**：填 CAN ID + 数据 → 点 **🚀 发送**
   - **接收 CAN**：自动推送，实时显示在接收区，标题栏显示帧率
   - **快速指令**：一键查 WiFi IP / 查 CAN 缓冲区

### 适用场景

- 临时调试，不想装任何软件
- 快速验证 CAN 通信
- 不写代码的用户

---

## 方式二：不依赖 HTML（Python 脚本，可编程集成）

### 安装依赖

```bash
pip install bleak
```

### 用法

```bash
# 交互式命令行（推荐入门）
python examples/ble_can_client.py

# 发送一帧后退出
python examples/ble_can_client.py --send "7B:11 22 33"

# 发送扩展帧
python examples/ble_can_client.py --send "1F6:AA BB CC" --extended

# 设置波特率 1Mbps 后进入交互模式
python examples/ble_can_client.py --baudrate 1000

# 仅监听模式
python examples/ble_can_client.py --monitor
```

### 交互命令

| 全称 | 短别名 | 说明 | 示例 |
|------|--------|------|------|
| `send <ID>:<数据>` | `s` | 发送 CAN 标准帧 | `send 7B:11 22 33` |
| `sendex <ID>:<数据>` | `se` | 发送 CAN 扩展帧 | `sendex 1F6:AA BB` |
| `baud <波特率>` | `b` | 设置 CAN 波特率 (kbps) | `baud 1000` |
| `query` | `q` | 查询 CAN 接收缓冲区 | `query` |
| `wifi` | `ip` | 查询 WiFi IP 地址 | `wifi` |
| `quit` / `exit` | — | 退出程序 | `quit` |

### 在自己的 Python 项目中调用

```python
import asyncio
from ble_can_client import CAN_BLE_Client

async def my_can_app():
    client = CAN_BLE_Client()

    # 注册接收回调
    def on_receive(text):
        print(f"收到 CAN 数据: {text}")
        # 在这里写你的业务逻辑（解析、控制等）
    client.on_can_data(on_receive)

    # 连接
    await client.connect()

    # 设置波特率 1M
    await client.set_baudrate(1000)

    # 发送 CAN 帧
    await client.send_can(can_id=0x7B, data=bytes([0x11, 0x22, 0x33]))

    # 持续接收...
    while True:
        await asyncio.sleep(1)

asyncio.run(my_can_app())
```

### 适用场景

- 集成到自动化测试脚本
- 集成到机器人上位机程序
- 批量收发，无人值守

---

# BLE 指令参考

ESP32 收到蓝牙写操作后，根据数据前 2 字节判断指令类型：

| 指令头 | 后续字节 | 功能 |
|--------|---------|------|
| `0A 0B` | N 字节数据 | 将数据转发到 RS485 |
| `0A 0C` | 4 字节 CAN ID（大端）+ 1 字节帧类型 + N 字节数据 | 发送 CAN 帧 |
| `0A 0D` | 无 | 返回 WiFi IP 地址 |
| `0A 0F` | 无 | 返回 CAN 接收缓冲区内容 |
| `0A 10` | 4 字节波特率（大端, 单位 kbps）| 设置 CAN 波特率 |

### 帧类型字节

| 值 | 含义 | CAN ID 范围 |
|----|------|-------------|
| `00` | 标准帧 | 0x000 ~ 0x7FF |
| `01` | 扩展帧 | 0x00000000 ~ 0x1FFFFFFF |

### 示例

| 想要的操作 | HEX 指令 |
|-----------|---------|
| CAN 发标准帧 ID=0x7B 数据=11 22 33 | `0A 0C 00 00 00 7B 00 11 22 33` |
| CAN 发扩展帧 ID=0x000001F6 数据=AA BB | `0A 0C 00 00 01 F6 01 AA BB` |
| 查 WiFi IP | `0A 0D` |
| 查 CAN 缓冲区 | `0A 0F` |
| 设波特率 1M | `0A 10 00 00 03 E8` |

---

# ⚠️ 注意事项

## 1. CAN 总线必须有至少 2 个设备

CAN 协议要求每个帧必须有另一个设备回 ACK 确认。如果只有 ESP32 一块板子，发送会失败并报：
```
TWAI controller has become error passive
Failed to queue message for transmission
```
**解决**：确保 CAN 总线上至少有一个其他设备（CAN 分析仪 / GO2 / 另一块板子），并且**波特率一致**。

## 2. 波特率必须匹配

ESP32 默认 **1000 kbps (1M)**。在发送前务必确认 CAN 分析仪/对端设备的波特率，然后通过 BLE 设置一致的速率（支持 25/50/100/125/250/500/800/1000 kbps）。

## 3. BLE 推送速率限制

BLE 的 Connection Interval 限制了通知频率。如果发现网页/Python 端接收速率瓶颈在 ~20-50 帧/秒，这是 BLE 协议本身的限制，不是 ESP32 或代码的问题。解决方法：

- **方案 A**：适当降低 CAN 总线上的数据频率
- **方案 B**：改用 WiFi WebSocket（需要额外开发）
- **方案 C**：在 ESP32 端做数据聚合（多帧合并为一次 BLE 推送）

## 4. 烧录时连接 USB 口

板子上有两个 Type-C 口：标 **USB** 的接 ESP32-S3 原生 USB（用于烧录+串口），标 **UART** 的接 CH343 串口芯片（仅串口）。**烧录用 USB 口**。

## 5. 蓝牙独占

一个 ESP32 只能同时被一个 BLE 客户端连接。如果手机或其他电脑已经连上了，新设备会扫描不到或连接失败。

## 6. 串口监视器波特率

VSCode PlatformIO Serial Monitor 默认 115200。如果看到乱码，确认状态栏波特率为 115200。

## 7. 编译注意事项

- 本项目基于 PlatformIO + Arduino 框架
- ESP32 Arduino 核心 v3.x 中 BLE 库使用 `std::string` 而非 Arduino `String`
- 如果从 Demo 原始代码迁移，需要修改 `WS_Bluetooth.cpp` 中的 `String` → `std::string`

---

# 工程内部原理

## 整体架构

```
main.cpp setup()
 ├─ I2C_Init()           → Wire.begin(38,39)
 ├─ RS485_Init()         → 串口1 + RS485Task (FreeRTOS)
 ├─ CAN_Init()           → TWAI驱动 + CANTask (FreeRTOS, 2ms循环)
 ├─ RTC_Init()           → PCF85063_Init + RTCTask + Continuous_Task (FreeRTOS)
 ├─ Bluetooth_Init()     → BLE服务器 + BLETask (FreeRTOS, 10ms轮询)
 └─ WIFI_Init()          → WiFi AP 热点 + WebServer (HTTP路由)

main.cpp loop()
 └─ 空循环，所有工作在 7 个 FreeRTOS 任务中并行运行
```

## CAN 接收 → BLE 推送 数据流

```
外部 CAN 设备发送数据到总线上
  │
  ▼
CANTask (FreeRTOS, 核心0, 每 2ms)
  │  twai_receive() 接收 CAN 帧
  │  handle_rx_message() 解析
  │  格式化为带时间戳文本 → 存入 CAN_Read_Data
  ▼
CAN_Read_Data (PSRAM 缓冲区, 最大 1000 字节)
  │
  ▼
BLETask (FreeRTOS, 核心0, 每 10ms 轮询)
  │  检查 CAN_Received_Len > 0 且蓝牙已连接
  │  Bluetooth_SendData() → pTxCharacteristic->notify()
  │  清空缓冲区
  ▼
笔记本/手机 BLE 客户端
  │  实时收到 CAN 数据文本 + 帧率统计
```

## BLE 发送 → CAN 总线 数据流

```
笔记本 BLE 客户端
  │  发送 HEX: 0A 0C 00 00 00 7B 00 11 22 33
  ▼
ESP32 BLE 写特征值回调 MyRXCallback::onWrite()
  │  解析指令头 0A 0C
  │  提取 CAN ID = 0x0000007B, 标准帧, 数据 = 11 22 33
  ▼
send_message_Bytes()
  │  构造 twai_message_t, 调用 twai_transmit()
  │  TWAI_ALERT_TX_SUCCESS → g_tx_total++ 发送计数
  ▼
CAN 总线
  │  CAN 分析仪 / GO2 / 其他设备接收
```

## 文件结构

```
ESP32 for WiFi and BLE CAN Custom/
├── platformio.ini          PlatformIO 工程配置
├── CAN_BLE助手.html        中文网页 BLE 控制台 (方式一)
├── README.md               本说明书
├── examples/
│   └── ble_can_client.py   Python BLE 客户端 (方式二)
└── src/
    ├── main.cpp            主入口，调用各模块 Init()
    ├── WS_Bluetooth.cpp    蓝牙 BLE: 指令解析、CAN 数据自动推送、BLETask
    │                       支持指令: 0A0B/0A0C/0A0D/0A0F/0A10
    ├── WS_CAN.cpp          CAN 驱动: TWAI 初始化、收发、波特率切换、CANTask
    │                       速率统计: CAN_rx_rate / CAN_tx_rate (帧/秒)
    ├── WS_RS485.cpp        RS485 驱动: 串口1、半双工、RS485Task
    ├── WS_WIFI.cpp         WiFi AP + Web 服务器 + HTTP 路由
    ├── WS_RTC.cpp          RTC 定时事件引擎: RTCTask + Continuous_Task
    ├── WS_PCF85063.cpp     RTC 芯片 PCF85063 I2C 驱动
    ├── I2C_Driver.cpp      I2C 底层封装 (Wire)
    ├── WS_GPIO.cpp         引脚定义
    ├── WS_Information.h    全局配置 (WiFi名/密码, 功能开关)
    ├── WS_Struct.h         通用数据结构
    └── *.h                 各模块头文件
```

## FreeRTOS 任务一览

| 任务名 | 优先级 | 循环间隔 | 功能 |
|--------|--------|----------|------|
| WebTask | 4 | 10ms | WiFi HTTP 请求处理 |
| PCF85063Task | 3 | 100ms | RTC 时间读取 |
| RTCTask | 3 | 100ms | 秒级定时事件检查 |
| Continuous_Task | 3 | 动态 | 毫秒/秒/分/时重复事件 |
| CANTask | 3 | **2ms** | CAN 收发 + 速率统计 |
| RS485Task | 3 | 50ms | RS485 收发 |
| BLETask | 2 | **10ms** | BLE 推送: IP / CAN 数据 / 查询响应 |
