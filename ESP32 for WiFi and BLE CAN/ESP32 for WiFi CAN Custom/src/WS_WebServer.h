#pragma once

/*============================================================================
 * WS_WebServer.h — HTTP 路由处理 + 内嵌 Web 页面
 *
 * 单页 SPA (Single Page Application)，暗色主题。
 * HTML/CSS/JS 用 C++11 raw string literal 内嵌。
 *============================================================================*/

#include <WebServer.h>
#include "WS_Config.h"
#include "WS_CAN.h"
#include "WS_WIFI.h"
#include "WS_RTC.h"

void WebServer_Init(void);
void WebServer_HandleClient(void);
