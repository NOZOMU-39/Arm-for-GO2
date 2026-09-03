# uart_recorder — 0x91 数据采集器(Windows/UART 版)

IMU 数据采集与离线分析的最小工具链,开发路线 P4「落盘与验证」的雏形:
**Jetson 版只把 `recorder.py` 的收帧源从串口换成 SocketCAN,analyzer 原样复用**。

- `recorder.py`:读串口 → CRC-16/XMODEM 校验(坏帧丢弃,CRC 错率实测 ~0.008% 已工程化兜底)→ 好帧整帧(82B)连续落盘 + meta 文件。
  `python recorder.py --port COM6 --baud 460800 --seconds 60 --out capture.bin`
- `analyzer.py`:离线读 capture.bin → 帧率/丢帧检测(system_time ms 间隔)/各轴抖动σ/姿态角漂移/温度中文报告。
  `python analyzer.py capture.bin`

依赖:pyserial。用途:静态基线、动态语义验证、将来所有台架采集的落盘格式基础。
帧格式与 CRC 依据:Database\IMU\HI12系列指令与编程手册.pdf 7.1~7.4。
