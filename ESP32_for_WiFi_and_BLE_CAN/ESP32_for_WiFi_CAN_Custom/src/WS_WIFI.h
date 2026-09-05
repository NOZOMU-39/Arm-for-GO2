#pragma once

/*============================================================================
 * WS_WIFI.h — WiFi AP+STA 双模管理
 *
 * 职责：
 *   1. WiFi AP+STA 双模初始化
 *   2. NVS 持久化（WiFi 凭据 + CAN 波特率）
 *   3. WiFi 事件回调（STA 连接/断开/IP获取）
 *   4. 全局状态变量暴露
 *
 * Web 服务器路由处理拆分到 WS_WebServer.h/cpp
 *============================================================================*/

#include <WiFi.h>
#include <Preferences.h>
#include "WS_Config.h"

// ---- 全局 WiFi 状态 ----
extern char g_ap_ssid[33];
extern char g_ap_psk[33];
extern char g_sta_ssid[33];
extern char g_sta_psk[33];
extern char g_sta_ip[16];
extern char g_device_ip[16];
extern bool g_sta_connected;

void WIFI_Init(void);
void WIFI_LoadSettings(void);
void WIFI_SaveSettings(void);
void WebTask(void *parameter);
