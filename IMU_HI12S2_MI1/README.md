# IMU 双端测量（HIPNUC HI12S2-MI1）

精浦 HI12S2-MI1-000（UART＋CAN）IMU 开发工程——枪口端＋基座端各一枚，服务机械臂后坐扰动抑制的测量链（枪口角/角速度测量）。

- **这是什么**：HI12 系列 6 轴 VRU 模组（无磁力计，yaw 上电归零）的驱动、配置与实测工程；`HI12_SDK\` 为官方 SDK（解码库＋Linux 工具＋DBC）。
- **当前状态（2026-09-06）**：UART 链路已打通——921600 实测 1000Hz 全量；**Jetson 侧双 CH340 直插 + 写 1 字节激活后双路 999.9fps 达成**（ch341 枚举后丢帧坑与 HUB 兼容坑详见 AGENTS/情报）；CAN 收发器未到货，CAN 侧实测待做。
- **快速上手**：装驱动（SDK 内 usb_uart_drivers\）→ CHCenter 连串口评估（Database\IMU\CHCenter_上位机\）。
- **深入开发**：AI 开发看同目录 `AGENTS.md`；手册/规格书在 `Database\IMU\`；实测与跨模块结论见 `AI间交流\情报.md` 第六节。
