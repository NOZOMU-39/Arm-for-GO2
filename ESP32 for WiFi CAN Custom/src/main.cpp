/*============================================================================
 * main.cpp — ESP32 WiFi CAN 无线中继站
 *
 * 三级通道自动降级:
 *   第1级(主力) : STA 连笔记本热点 → TCP 8888 端口
 *   第2级(备选) : AP 直连 192.168.4.1 → TCP 8888 端口
 *   第3级(兜底) : USB CDC 串口 → 二进制帧协议
 *
 * 初始化顺序：
 *   I2C → CAN → RTC → WiFi(含WebServer) → TCP → Serial
 *
 * 模块    文件          职责
 *  配置    WS_Config.h   协议常量、帧结构、全局参数
 *  CAN     WS_CAN        环形缓冲区 + TWAI 驱动 + 命令分发
 *  RTC     WS_RTC        PCF85063 时钟（按需读取）
 *  WiFi    WS_WIFI       AP+STA 双模 + NVS 持久化
 *  Web     WS_WebServer  HTTP 路由 + 内嵌 SPA 控制台
 *  TCP     WS_TCP        帧服务器 + CAN 数据自动推送
 *  Serial  WS_Serial     USB CDC 串口指令处理
 *============================================================================*/
#include <Arduino.h>
#include "WS_CAN.h"
#include "WS_RTC.h"
#include "WS_WIFI.h"
#include "WS_TCP.h"
#include "WS_Serial.h"

void setup() {
    // 等待 USB CDC 稳定
    delay(500);

    I2C_Init();       // I2C 总线 (PCF85063 RTC)
    CAN_Init();       // TWAI 驱动 + CANTask (1ms 循环, 目标 1000Hz)
    RTC_Init();       // PCF85063 时钟初始化
    WIFI_Init();      // WiFi AP+STA 双模 + WebServer + WebTask
    TCP_Init();       // TCP 帧服务器 + TCPTask (端口 8888)
    Serial_Init();    // USB CDC 串口 + SerialTask (第3级兜底)

    // 打印启动信息
    printf("========================================\r\n");
    printf("  %s v%s\r\n", DEVICE_NAME, FIRMWARE_VERSION);
    printf("  AP : %s @ 192.168.4.1\r\n", g_ap_ssid);
    if (g_sta_connected) {
        printf("  STA: %s (热点已连接)\r\n", g_sta_ip);
    } else if (strlen(g_sta_ssid) > 0) {
        printf("  STA: 正在连接 %s ...\r\n", g_sta_ssid);
    } else {
        printf("  STA: 未配置 (在设置页填入笔记本热点名)\r\n");
    }
    printf("  TCP: 端口 %d\r\n", TCP_SERVER_PORT);
    printf("  USB: CDC 串口就绪\r\n");
    printf("  Web: http://192.168.4.1\r\n");
    printf("  CAN : %lu kbps\r\n", CAN_bitrate_kbps);
    printf("========================================\r\n");
}

void loop() {
    // 所有工作在 FreeRTOS 任务中并行运行
    // CANTask (3, 1ms) → CAN 收发 + 环形缓冲区
    // TCPTask (3, 1ms) → TCP 帧服务器 + CAN 推送
    // WebTask (2, 10ms)→ HTTP 处理 + STA 自动重连
    // SerialTask(1, 2ms)→ USB CDC 串口指令
    delay(1000);
}
