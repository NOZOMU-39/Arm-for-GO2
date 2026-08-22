# AGENTS.md — ESP32 无线 CAN 中继(AI 对接文档)

> 🤖 AI 对接文档(后续 AI 开发自动读取);人类使用说明见 `ESP32 for WiFi CAN Custom\README.md`(三部分:用户手册/开发者参考/技术内幕),协议细节与性能实测见 `AI间交流\情报.md` 第五节。

## 1. 工程定位与目录

- 微雪 ESP32-S3-RS485-CAN 无线中继:笔记本经 WiFi(TCP/HTTP)/USB 串口实时收发 CAN,三级通道自动降级(STA 热点主力 → AP 备用 → USB 串口兜底),永远在线。
- 两个工程:**WiFi 版**(主力,`ESP32 for WiFi CAN Custom\`)+ **BLE 版**(`ESP32 for BLE CAN Custom\`,蓝牙方案,因慢被弃用,只留作参考)。
- 开发环境:VS Code + PlatformIO(espressif32 Arduino 框架),烧录用板子 **USB 口**(Type-C 标 USB 的那个)。

```
ESP32 for WiFi and BLE CAN\
├── ESP32 for WiFi CAN Custom\   # 主力工程(WiFi 版)
│   ├── src\WS_*.cpp/h           # 模块化:Config/CAN/WIFI/WebServer/TCP/UDP/Serial/RTC/GPIO
│   ├── examples\wifi_can_client.py  # Python 客户端(纯 TCP 零依赖,串口需 pyserial)
│   ├── CAN_WiFi助手.html        # 独立浏览器控制台
│   └── README.md                # 人类说明书(三部分)
├── ESP32 for BLE CAN Custom\    # BLE 版(已弃用,勿改勿用)
└── ESP32-S3-RS485-CAN-Demo\     # 微雪官方 Demo
```

## 2. 协议与关键结论(已查证,勿再推翻)

- **帧协议**(TCP 8888 与 USB 串口共用):`[2B 长度大端][1B 类型][载荷]`;类型 0x01 CMD_REQ / 0x02 CMD_RESP / 0x03 CAN_PUSH(单帧) / 0x04 CAN_SEND / 0x05 CAN_BATCH(批帧)。
- **批帧协商(0x0A12)**:客户端主动协商,成功推 0x05 批帧(满 64 帧或 10ms 超时);旧固件无响应自动回退单帧;新旧客户端可同时在线。**命令字 0x0A12 保留给批帧协商,0x0A13 预留给心跳看门狗**(心跳固件暂缓)。
- **UDP 8889**:任意数据报即订阅,单向批帧推送(高频数据流与可靠控制分离),30s 无订阅自动移除。
- **实测性能(v2.1.3)**:接收方向 750 帧/s 全通零丢失(瓶颈是分析仪发送端,ESP32 真实上限未测出 ≥750/s);发送方向 AP ~630/s、STA ~430/s;批帧打包 + UDP 可到 3~5k+ 帧/s。
- **回显过滤**:16 签名 + 500ms TTL(发帧不会被自己当接收推回)。
- **自锁恢复**:v2.1.1 起无 ACK 自动恢复 BUS-OFF,发送 10ms 超时快速失败。
- 环形缓冲区 512 帧 PSRAM,4 个消费者独立读指针(TCP/Serial/Web/UDP)。

## 3. 已知坑

| 坑 | 记忆点 |
|---|---|
| CAN 总线必须 ≥2 设备 | 单板发帧无 ACK 会 error passive(已加固自动恢复) |
| 波特率必须一致 | 默认 1Mbps,对端不一致会通信失败 |
| 烧录用 USB 口 | 板子两个 Type-C:USB(烧录+串口)/ UART(仅串口) |
| 串口监视器 115200 | 乱码查波特率 |
| v2.1.2 任务核心分配 | 5 个任务曾全挤核心 0 抢占 WiFi 协议栈致 TCP 卡死;现 CANTask/TCPTask/UDPTask 优先级 3(核心 0)、WebTask 2、SerialTask 1 |
| Web 控制台改版流程 | 先改独立 CAN_WiFi助手.html 调试,再复制进 WS_WebServer.cpp 的 R"====( )====" 编译 |

## 4. 开发与测试

- 编译下载:`pio run -t upload`(VS Code PlatformIO 或命令行);串口监视 `pio device monitor`。
- Python 客户端自检:`python examples/test.py`(连接→查询→发帧→读缓冲→5 秒监听全流程)。
- 版本号:改固件后同步 `WS_Config.h` 版本常量与 README/情报。

## 5. 文档分工

- 人类:工程内 README.md(三部分式);AI:本文件 + `AI间交流\情报.md` 第五节;交接协议见项目根 AGENTS.md。
