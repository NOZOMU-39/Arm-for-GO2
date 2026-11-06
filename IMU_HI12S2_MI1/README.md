# IMU 双端测量（HIPNUC HI12S2-MI1）

精浦 HI12S2-MI1-000（UART＋CAN）IMU 开发工程——枪口端＋基座端各一枚，服务机械臂后坐扰动抑制的测量链（枪口角/角速度测量）。

- **这是什么**：HI12 系列 6 轴 VRU 模组（无磁力计，yaw 上电归零）的驱动、配置与实测工程；`HI12_SDK\` 为官方 SDK（解码库＋Linux 工具＋DBC）。
- **当前状态（2026-11-06）**：UART 链路已打通并完成 30 min 长测——双路各 1,800,040 帧、1000 fps、CRC 0；双 CH340 直插或经 HUB 均可，按 UUID 派角色；**CAN 路线停用，IMU 只走 UART**（细节见 AGENTS）。
- **底层实施 M1（进行中）**：驱动代码已在 `Jetson_Orin_NX\ROS2\arm_ws\src\imu_core` 与 `imu_hi12s2` 两包落地，`imu_identify` 可现场认设备并按 UUID 派岗位；29 个单测通过，真机双路识别通过。
- **快速上手**：装驱动（SDK 内 usb_uart_drivers\）→ CHCenter 连串口评估（Database\IMU\CHCenter_上位机\）。
- **深入开发**：AI 开发看同目录 `AGENTS.md`；手册/规格书在 `Database\IMU\`；实测与跨模块结论见 `AI间交流\情报\03_通信与IMU.md`。
