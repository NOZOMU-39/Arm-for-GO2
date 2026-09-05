"""tcp_gateway — Windows 前端(公用) ↔ Jetson 统一入口(v1 帧透传)

仿 ESP32 v2.1.3 TCP 协议, Windows 交互界面零改动接入(连 Jetson IP 即可)。
一期 v1 = 帧透传(总线单主=界面); 二期语义化接 arm_controller; 三期外设监控接入。
"""
