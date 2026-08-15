# ESP32 WiFi CAN — 基于 WiFi 的 CAN 总线无线中继站

> 适用于 **微雪 Waveshare ESP32-S3-RS485-CAN** 开发板
> **即插即用**：编译下载一次，永远不需要重配 WiFi

---

# 📖 第一部分：用户手册（小白友好）

## 硬件准备

| 项目 | 说明 |
|------|------|
| 开发板 | 微雪 Waveshare ESP32-S3-RS485-CAN |
| 芯片 | ESP32-S3, 16MB Flash, 8MB PSRAM |
| CAN 引脚 | GPIO15 (TX), GPIO16 (RX) |
| I2C 引脚 | GPIO38 (SCL), GPIO39 (SDA) — PCF85063 RTC |
| GPIO | CH1 = GPIO47 (可外接指示灯/继电器) |
| 供电/烧录 | 标 **USB** 的 Type-C 口（原生 USB CDC） |
| 产品资料 | https://www.waveshare.net/wiki/ESP32-S3-RS485-CAN |

> ⚠️ 板子上有两个 Type-C 口：标 **USB** 的接 ESP32-S3 原生 USB（用于烧录+串口），标 **UART** 的接 CH343 串口芯片（仅串口）。**烧录用 USB 口**。

---

## 它能干什么

将 ESP32 作为 **CAN 总线的无线中继站**，笔记本通过 WiFi 实时收发 CAN 数据。三级通道自动降级，永远在线。

```
  ┌──────────┐    WiFi (TCP/HTTP)    ┌─────────────────┐     CAN Bus     ┌──────────┐
  │ 笔记本/PC  │ ◄──────────────────▶ │ ESP32-S3-RS485   │ ◄─────────────▶ │ CAN 设备  │
  │          │   第1级:STA热点(主力)    │ -CAN 模块        │   1Mbps         │ (电机等)  │
  │          │   第2级:AP(自动备用)     │ -WiFi AP+STA    │                 └──────────┘
  │          │   第3级:USB串口(兜底)    │ -TCP Server     │
  └──────────┘                       └─────────────────┘
```

**三级自动降级通道**：
- **第1级（主力）**：STA 连笔记本热点，电脑可同时上网 + 无线 CAN 控制，两不误
- **第2级（备用）**：热点没开时自动顶上 AP，电脑直连 `ESP32-WiFi-CAN` 密码 `12345678`
- **第3级（兜底）**：USB CDC 串口，有线直连，永远可用

---

## 第 1 步：编译下载（3 分钟）

1. 安装 **VS Code** + **PlatformIO** 插件
2. 用 VS Code 打开本项目文件夹 `ESP32 for WiFi CAN Custom`
3. 用 Type-C 线连接板子 **USB 口** 到电脑
4. 点击 PlatformIO 底栏的 **→ Upload** 按钮

```bash
# 或命令行：
pio run -t upload
```

> 编译完成后自动下载到板子，USB CDC 串口自动识别，无需装驱动（Windows 10+）。

---

## 第 2 步：首次配置（仅需一次，1 分钟）

1. 打开电脑 WiFi → 扫描 → 找到 `ESP32-WiFi-CAN`
2. 连接，密码 `12345678`
3. 浏览器打开 `http://192.168.4.1`
4. 点击右上角 **⚙️ 齿轮图标**，展开设置面板
5. 填入笔记本热点信息：
   - **STA 热点**：你笔记本的热点名称（例如 `MyLaptop-Hotspot`）
   - **STA 密码**：你笔记本的热点密码
6. 点击「💾 保存到 ESP32」

> ✨ **此后全自动**：开机即连热点，热点没开就 AP 兜底。换地方、换电脑、断电重启，都不需要任何操作。

---

## 第 3 步：开始使用

### 场景 A：热点在线（主力模式，推荐）

ESP32 会自动连上你笔记本的热点。打开笔记本电脑上的网页或 Python 脚本即可控制。

浏览器打开：`http://<ESP32热点IP>` （控制台主页状态栏会显示）

> 电脑同时上网不受影响 ✅

### 场景 B：热点未开（AP 备用模式）

打开电脑 WiFi → 连上 `ESP32-WiFi-CAN`（密码 `12345678`）→ 浏览器打开 `http://192.168.4.1`

> 电脑暂时断网，但 CAN 控制正常工作 ✅

### 场景 C：串口兜底（有线模式）

用 USB 线连 ESP32 → Python 脚本自动检测串口 → 通信照常。

> 电脑 WiFi 完全不受影响 ✅

---

## 三种使用方式

### 方式一：浏览器网页（零安装，推荐新手）

优势：任何有浏览器的设备都能用，手机也能打开。

**ESP32 自带 Web 控制台**：浏览器打开 ESP32 的 IP 地址即可。网页功能：
- 通道状态栏：实时显示 STA/AP 连接状态、CAN 速率、RX/TX 帧率
- 发送 CAN：填 ID + 数据 hex → 点击发送
- 接收 CAN：自动刷新（100ms 间隔，显示本地渲染/ESP32真实 双速率），带自动滚动
- 设置面板：改 WiFi 凭据、CAN 波特率，保存到 NVS 永久存储

**独立 HTML 文件**：双击打开项目中的 `CAN_WiFi助手.html`，输入 ESP32 IP 后连接使用。功能和固件内嵌版完全一致。

---

### 方式二：Python 脚本（可编程集成，推荐进阶）

优势：集成到自动化脚本、上位机程序、机器人控制系统中。

#### 安装

```bash
# 纯 TCP 模式零依赖。串口模式需：
pip install pyserial
```

#### 命令行

```bash
# 全自动连接（并发扫描 1-254 设备，<1 秒发现）
python examples/wifi_can_client.py

# 指定 TCP 地址
python examples/wifi_can_client.py --host 192.168.4.1

# 指定串口
python examples/wifi_can_client.py --serial COM3

# 发送一帧后退出（标准帧）
python examples/wifi_can_client.py --can-data "11 22 33 44" --can-id 0x7B

# 发送扩展帧
python examples/wifi_can_client.py --can-data "AA BB" --can-id 0x1F6 --can-extd

# 设置波特率 1Mbps
python examples/wifi_can_client.py --can-rate 1000

# 查询 RTC 时间
python examples/wifi_can_client.py --query-rtc

# 持续监听模式
python examples/wifi_can_client.py --monitor

# 扫描所有可用设备
python examples/wifi_can_client.py --scan
```

#### 交互命令

进入交互模式后（无参数运行）：

| 全称 | 短别名 | 说明 | 示例 |
|------|--------|------|------|
| `send <ID>:<数据>` | `s` | 发送标准帧 | `send 7B:11 22 33` |
| `sendex <ID>:<数据>` | `se` | 发送扩展帧 | `sendex 1F6:AA BB` |
| `baud <kbps>` | `b` | 设置 CAN 波特率 | `baud 1000` |
| `query` | `q` | 查询 CAN 接收缓冲区 | `query` |
| `wifi` / `ip` | — | 查询 ESP32 IP | `wifi` |
| `rtc` | — | 查询 RTC 时间 | `rtc` |
| `stat` | — | 设备状态概览 | `stat` |
| `mon` | — | 监听模式（Ctrl+C 退出） | `mon` |
| `help` | — | 帮助 | `help` |
| `quit` / `exit` | — | 退出 | `quit` |

#### 在自己的代码中调用

```python
from wifi_can_client import WiFiCANClient, CANFrame

# 自动三级降级连接
client = WiFiCANClient()

# 或手动指定
# client = WiFiCANClient(host="192.168.4.1", port=8888)

print(f"连接模式: {client.mode}")

# 设置 CAN 速率
client.set_can_rate(1000)

# 发送 CAN 帧 — 标准帧
client.send_can(can_id=0x7B, data=bytes([0x11, 0x22, 0x33, 0x44]))
# 发送扩展帧
client.send_can(can_id=0x1F6, data=bytes([0xAA, 0xBB]), extended=True)

# 查询 ESP32 IP
print(client.query_ip())

# 查询 RTC 时间
print(client.query_rtc_time())

# 读取 CAN 接收缓冲区（返回 CANFrame 列表）
frames = client.read_can_buffer()
for f in frames:
    print(f"ID=0x{f.id:X} 数据={f.data.hex(' ')} 时间={f.timestamp_ms}ms")

# 持续监听（回调模式）
def on_frame(frame: CANFrame):
    print(f"收到: {frame}")

client.monitor(callback=on_frame)

# 用完后关闭
client.close()
```

---

### 方式三：TCP 直连（自定义开发）

ESP32 在端口 `8888` 上运行 TCP 帧服务器。任何支持 TCP Socket 的语言都可以直接控制。帧协议见第二部分「二进制帧协议」。

---

# 🔧 第二部分：开发者参考

## 项目结构

```
ESP32 for WiFi CAN Custom/
├── platformio.ini                 # PlatformIO 工程配置
├── README.md                      # 本说明书
├── CAN_WiFi助手.html               # 独立浏览器控制台（双击即用）
├── examples/
│   └── wifi_can_client.py         # Python TCP/串口双模客户端
├── src/
│   ├── main.cpp                   # 入口，初始化各模块 + 启动信息
│   ├── WS_Config.h                # 全局：协议常量、帧结构、参数定义
│   ├── WS_CAN.h / WS_CAN.cpp      # CAN 驱动：TWAI 收发 + 环形缓冲区 + CANTask
│   ├── WS_WIFI.h / WS_WIFI.cpp    # WiFi 管理：AP+STA 双模 + NVS 凭据持久化
│   ├── WS_WebServer.h / .cpp      # HTTP 路由 + 内嵌 SPA Web 控制台
│   ├── WS_TCP.h / WS_TCP.cpp      # TCP 帧服务器 + CAN 数据自动推送
│   ├── WS_Serial.h / WS_Serial.cpp# USB CDC 串口帧协议处理
│   ├── WS_RTC.h / WS_RTC.cpp      # RTC 时钟：按需读取 PCF85063
│   ├── WS_PCF85063.h / .cpp       # RTC 芯片 PCF85063 I2C 底层驱动
│   ├── I2C_Driver.h / .cpp        # I2C 总线底层封装 (Wire)
│   └── WS_GPIO.h / WS_GPIO.cpp    # 引脚定义 + GPIO 工具函数
```

**模块分工清晰**：
- 配置、通信、存储三类模块各司其职
- 无循环依赖，每个 `.cpp` 只 `#include` 需要的头文件
- `WS_WebServer` 从 `WS_WIFI` 中独立出来（旧版混在一起）

---

## 二进制帧协议

TCP 和 USB CDC 串口共用同一套二进制帧协议，不区分物理通道。

### 帧格式

```
┌──────────────┬──────────┬────────────────────┐
│ 2B 长度(大端)  │ 1B 类型  │ 载荷               │
└──────────────┴──────────┴────────────────────┘
```

- **长度字段**：包含类型字节 + 载荷的总长度
- **类型字节**：标识帧的用途，用于帧率分类统计

### 类型字节

| 值 | 名称 | 方向 | 说明 |
|----|------|------|------|
| `0x01` | `FRAME_CMD_REQ` | PC→ESP32 | 命令请求（查询IP、设置波特率等） |
| `0x02` | `FRAME_CMD_RESP` | ESP32→PC | 命令响应（返回查询结果） |
| `0x03` | `FRAME_CAN_PUSH` | ESP32→PC | CAN 接收帧推送 |
| `0x04` | `FRAME_CAN_SEND` | PC→ESP32 | CAN 发送帧 |

> **为什么用类型字节：** 接收端根据类型字节区分帧来源，实现精确的 TX/RX 帧率分别统计。

### 命令字（FRAME_CMD_REQ 载荷前 2 字节）

| 命令 | 值 | 说明 |
|------|-----|------|
| `CMD_CAN_SEND` | `0A 0C` | 发送 CAN 帧（载荷格式见下） |
| `CMD_QUERY_IP` | `0A 0D` | 查询 WiFi STA IP |
| `CMD_QUERY_CAN` | `0A 0F` | 查询 CAN 接收环形缓冲区 |
| `CMD_SET_CAN_RATE` | `0A 10` | 设置 CAN 波特率（后跟 4B 大端 kbps 值） |
| `CMD_QUERY_RTC` | `0A 11` | 查询 RTC 时间 |

### CAN_FRAME 载荷结构（类型 0x03，ESP32→PC）

```
[4B CAN_ID(大端)] [1B 扩展帧标志] [4B 时间戳ms(大端)] [1B DLC] [0-8B 数据]
```

总共 10-18 字节。时间戳为 ESP32 开机以来的毫秒数。

### CAN_SEND 载荷结构（类型 0x04，PC→ESP32）

```
[4B CAN_ID(大端)] [1B 扩展帧标志] [N字节 数据]
```

> 直通模式：ESP32 不解析内层命令字，直接将 CAN ID + 数据发送到 CAN 总线。

### HEX 示例

| 操作 | 完整帧 |
|------|--------|
| 发送标准帧 ID=0x7B 数据=11 22 33 | `00 0A  04  00 00 00 7B 00 11 22 33` |
| 发送扩展帧 ID=0x1F6 数据=AA BB | `00 09  04  00 00 01 F6 01 AA BB` |
| 查询 WiFi IP | `00 03  01  0A 0D` |
| 查询 CAN 缓冲区 | `00 03  01  0A 0F` |
| 设置波特率 1M (1000=0x3E8) | `00 07  01  0A 10 00 00 03 E8` |
| 查询 RTC 时间 | `00 03  01  0A 11` |

> 帧格式解读：`00 0A` = 长度=10字节 → 类型 `04` = CAN_SEND → 载荷 8 字节 = `00 00 00 7B 00 11 22 33`

---

## Web API 参考

所有 API 在 AP (`192.168.4.1`) 和 STA (热点 IP) 上均可使用。

### 状态 & 设置

| 路由 | 方法 | 响应 | 说明 |
|------|------|------|------|
| `GET /` | GET | HTML | Web 控制台 SPA |
| `GET /getStatus` | GET | JSON | 设备状态（WiFi/CAN/帧率/版本） |
| `POST /SaveSettings` | POST | `Saved` | 保存 WiFi + CAN 设置到 NVS（FormData） |
| `GET /GetRtcTime` | GET | text | 当前 RTC 时间字符串 |

### CAN 操作

| 路由 | 方法 | 响应 | 说明 |
|------|------|------|------|
| `GET /getCANData` | GET | JSON 数组 | 取最多 200 帧文本行，格式: `"ID:0x7B S DLC:8 11 22 33 ... [1234ms]"` |
| `POST /CANSend` | POST | `OK` | 发送 CAN 帧（JSON body: `{"id":123,"extd":0,"data":"11 22 33"}`） |
| `POST /CANSetRate` | POST | `OK` | 设置 CAN 速率（JSON body: `{"rate":1000}`） |

### getStatus 返回字段

```json
{
  "ap_ssid": "ESP32-WiFi-CAN",
  "sta_ssid": "MyHotspot",
  "sta_connected": true,
  "sta_ip": "192.168.137.2",
  "can_rate": 1000,
  "can_rx_rate": 847.2,
  "can_tx_rate": 12.1,
  "can_rx_count": 384729,
  "can_tx_count": 5123,
  "firmware": "v2.0"
}
```

---

## Python API 参考

### WiFiCANClient 类

```python
class WiFiCANClient:
    def __init__(self, host=None, port=8888, serial_port=None)
    def send_can(self, can_id: int, data: bytes, extended: bool = False) -> None
    def set_can_rate(self, rate_kbps: int) -> None
    def query_ip(self) -> str
    def query_rtc_time(self) -> str
    def read_can_buffer(self) -> List[CANFrame]
    def monitor(self, callback: Callable[[CANFrame], None] = None) -> None
    def close(self) -> None
```

### CANFrame 数据类

```python
@dataclass
class CANFrame:
    id: int              # CAN ID
    extd: bool           # True=扩展帧
    dlc: int             # 数据长度 0-8
    data: bytes          # 帧数据
    timestamp_ms: int    # ESP32 开机计时（毫秒）
```

### 自动发现策略

Python 客户端的四级自动发现算法：
1. 探测本机所有网卡子网 → 并发扫描 1-254（16线程，<1 秒完成）
2. 预置热点网段扫描（192.168.137/0/1/43, 172.20.10）
3. TCP 直连 AP IP（192.168.4.1）
4. USB 串口自动检测（关键词匹配 ESP32-S3 特征串）

---

# 🧠 第三部分：技术内幕

## 整体架构

```
main.cpp setup()
 ├─ I2C_Init()           → Wire.begin(38, 39)
 ├─ CAN_Init()           → TWAI 驱动 + CANTask (FreeRTOS, 1ms 循环)
 ├─ RTC_Init()           → PCF85063_Init (按需读取，无后台任务)
 ├─ WIFI_Init()          → AP+STA 双模 + WebServer + WebTask
 ├─ TCP_Init()           → TCP 帧服务器 (端口 8888) + TCPTask
 └─ Serial_Init()        → USB CDC 串口 + SerialTask

main.cpp loop()
 └─ 空循环，所有工作在 FreeRTOS 任务中并行运行
```

### 设计理由
- **I2C 最先**：RTC 和后续初始化不需要 I2C，但提前初始化避免时序问题
- **CAN 在 RTC 之前**：CAN 帧入环时需要时间戳，若 RTC 未就绪则用系统毫秒计数
- **WiFi 在 TCP/Serial 之前**：TCP 服务器启动后立即可以接受连接，WiFi 必须先就绪
- **loop() 空循环**：所有工作在 FreeRTOS 任务中，main loop 只休眠

---

## FreeRTOS 任务架构

| 任务 | 优先级 | 循环 | 栈 | 核心 | 功能 |
|------|--------|------|-----|------|------|
| CANTask | 3 | 1ms | 4KB | 0 | CAN 收发 + 环形缓冲区写入 + 速率统计 |
| TCPTask | 3 | 1ms | 6KB | 0 | TCP 帧服务器 + CAN 帧推送 + 客户端管理 |
| WebTask | 2 | 10ms | 8KB | 0 | HTTP 请求处理 + STA 自动重连（30s 间隔） |
| SerialTask | 1 | 2ms | 4KB | 0 | USB CDC 串口帧协议处理 |

> 共 4 个任务（旧版有 7 个），总栈 22KB（旧版 ~32KB）。

### 优先级设计理由
- **CANTask = TCPTask = 3**：CAN 收发和 TCP 推送同等重要，1ms 循环确保高吞吐
- **WebTask = 2**：HTTP 是辅助通道，不需要抢占 CAN/TCP
- **SerialTask = 1**：串口是兜底通道，最低优先级，不影响主力 WiFi 通信
- 同优先级任务通过 FreeRTOS 时间片轮转调度，不会互相饿死

---

## CAN 环形缓冲区设计

### 为什么用环形缓冲区

旧版的 `CAN_Read_Data` 是一个简单的 PSRAM 字符缓冲区（最大 1000 字节），多个消费者（TCP、Serial、Web）共享一个读指针。一旦某个消费者读了数据，其他消费者就看不到了，造成数据丢失。

### 订阅者模式

```cpp
#define CAN_RING_SIZE 512  // 512 帧 ≈ 0.5 秒缓冲区 @ 1000fps

CAN_Frame* can_ring;  // 环形缓冲，分配在 PSRAM
volatile uint16_t can_ring_head;       // 生产者写入位置
volatile uint16_t can_ring_tcp_tail;   // TCP 消费者读位置
volatile uint16_t can_ring_serial_tail;// 串口消费者读位置
volatile uint16_t can_ring_web_tail;   // Web 消费者读位置
```

每个消费者有独立的读指针，互不干扰。TCP 客户端可以丢掉一些帧，Web 控制台每隔 100ms 来取，串口用户也可以看到自己那份——**三个消费者各读各的，不冲突**。

### 为什么是 512 帧

- 目标 CAN 吞吐 1000 fps，512 帧 ≈ 0.5 秒缓冲
- 8MB PSRAM，512 × 18B = 9KB，完全放得下
- 足够覆盖 TCP 客户端短暂卡顿（WiFi 抖动、Python GC 暂停）
- 多了浪费 PSRAM，少了容易丢帧

### 覆盖检测

当生产者追上消费者时（head 绕一圈又追上 tail），消费者指针被**强制推进**到 head，同时输出覆盖警告。每个消费者独立检测自己的 tail 是否被覆盖。

### 线程安全

所有环形缓冲区操作在 `can_ring_mutex` (FreeRTOS `SemaphoreHandle_t`) 保护下执行。生产者写锁、消费者读锁各自持锁时间极短（微秒级），不影响 1ms 循环。

---

## 自收回显过滤

### 问题

CAN 总线上发送的帧，ESP32 自己也能收到（回显）。如果不加过滤，每发一帧都会看到自己的帧被当作"接收"推回来，造成 RX 帧率虚高。

### 方案

维护最近 **16 个发送帧签名**的环形数组 + 500ms 生存时间（TTL）：

```cpp
typedef struct {
    uint32_t id;
    uint8_t  extd;
    uint8_t  dlc;
    uint8_t  data[8];
    uint32_t sent_at_ms;  // 发送时间戳
} EchoSignature;

EchoSignature echo_filter[16];
```

**匹配逻辑**：收到 CAN 帧后，遍历 16 个签名，若 `{id, extd, dlc, data[0..7]}` 全部匹配且 `now - sent_at_ms < 500ms`，则判定为回显，丢弃不入环。

**为什么 16 个 + 500ms：** 高负载下可能连续发送多帧，16 个签名覆盖极端场景。500ms TTL 确保不误伤正常帧（外部设备不可能在 500ms 内发出完全相同内容和 ID 的帧）。

---

## HTML 内嵌方式：C++11 Raw String Literal

### 技术选型

旧版使用 SPIFFS 文件系统存储 HTML，烧录固件后还需单独上传 SPIFFS 镜像。这对新手不友好。

### v2.0 方案

```cpp
static const char PAGE_MAIN[] = R"====(
<!DOCTYPE html>
<html>
...HTML 内容...
</html>
)====";
```

用 C++11 **raw string literal** 语法 `R"====( ... )===="` 将整个 SPA 页面嵌入固件代码。编译时 HTML 成为 `.rodata` 段的一部分，烧录固件即包含 Web 控制台。

**优势**：
- 烧录一次，什么都不用管
- 不需要 SPIFFS/LittleFS 文件系统
- 不需要单独上传数据文件
- HTML 作为常量编译在固件中，读取零开销

**开发流程**：
1. 修改独立 `CAN_WiFi助手.html` 文件
2. 用浏览器打开调试，确认功能正常
3. 复制 HTML 内容到 `WS_WebServer.cpp` 的 `R"====( ... )===="` 中
4. 重新编译下载

---

## CAN 速率切换原理

```cpp
void CAN_UpdateRate(uint32_t rate_kbps) {
    twai_stop();           // 停止 TWAI 外设
    twai_driver_uninstall();// 卸载驱动
    CAN_bitrate_kbps = rate_kbps;
    twai_install_and_start();// 重新安装 + 启动
}
```

`stop → uninstall → reinstall` 三步走：
1. 先 `stop()` 确保总线安静
2. `uninstall()` 释放 TWAI 资源（消息队列、中断）
3. 更新 `CAN_bitrate_kbps` 全局变量后重新 `install_and_start()`

不卸载驱动直接改参数在某些 ESP32-S3 版本上有兼容问题，三步走是最稳定的做法。

---

## 支持的 CAN 波特率

| 值 | 波特率 | 典型应用 |
|----|--------|---------|
| 25 | 25 kbps | 低速设备 |
| 50 | 50 kbps | 低速率 CANopen |
| 100 | 100 kbps | 低速控制 |
| 125 | 125 kbps | CANopen 标准 |
| 250 | 250 kbps | 中型网络 |
| 500 | 500 kbps | 高速控制 |
| 800 | 800 kbps | 高速 |
| 1000 | 1 Mbps | 通用高速（默认） |

---

## 三级通道自动降级流程

```
开机
 │
 ├─ AP 启动（始终在线）→ 192.168.4.1
 │
 ├─ NVS 中有 STA 凭据？
 │   ├─ 是 → WiFi.begin(热点SSID, 密码)
 │   │        ├─ 连上 → g_sta_connected=true → 主力通道工作
 │   │        └─ 失败 → AP 兜底（WebTask 每 30s 自动重试）
 │   └─ 否 → 仅 AP，等用户进设置页配一次
 │
 └─ USB CDC 串口始终可用（优先级最低的最高兜底）
```

STA 重连逻辑放在 WebTask 中（10ms 循环，30s 间隔检查），不占用 CANTask 和 TCPTask 的时间片。

---

## 速率 & 性能

| 参数 | 设计值 | 实测条件 |
|------|--------|---------|
| CANTask 循环 | 1ms | 目标吞吐 1000 fps |
| CAN 环形缓冲 | 512 帧 PSRAM | 3 个消费者独立读指针 |
| TCP 最大客户端 | 4 个 | CAN 帧广播到所有客户端 |
| Nagle 算法 | 已禁用 (`TCP_NODELAY`) | 减少延迟 |
| 回显过滤 | 16 签名 + 500ms TTL | 匹配 id/extd/dlc/data |
| 帧率统计 | 每秒刷新 (`can_rx_rate`/`can_tx_rate`) | 浮点帧/秒，Web API 查询 |

---

## 注意事项

### 1. CAN 总线必须有至少 2 个设备

CAN 协议要求每个帧必须有至少一个其他设备回 ACK。如果只有 ESP32 一块板子，发送会进入错误被动状态：
```
TWAI controller has become error passive
Failed to queue message for transmission
```
**解决**：确保总线上有至少一个其他设备（CAN 分析仪 / 电机驱动器），且**波特率一致**。

### 2. 波特率必须一致

ESP32 默认 1 Mbps。发送前确认对端设备波特率，不一致会导致通信失败和总线错误。

### 3. 烧录用 USB 口

板子有两个 Type-C：**USB** 口（ESP32-S3 原生）用于烧录+串口；**UART** 口（CH343）仅串口。

### 4. 串口监视器波特率 115200

VSCode PlatformIO Serial Monitor 默认 115200。乱码时确认右下角状态栏波特率。

---

## 编译环境

- **IDE**：VS Code + PlatformIO 插件
- **平台**：`espressif32` (Arduino 框架)
- **板子**：`esp32-s3-rs485-can` (自定义 board 配置)

```bash
pio run              # 编译
pio run -t upload    # 编译 + 下载
pio device monitor   # 串口监视 (115200)
```

---

> 🤖 Generated with [Claude Code](https://claude.com/claude-code)
