/*============================================================================
 * WS_WIFI.cpp — WiFi AP+STA 双模管理
 *
 * 三级通道架构:
 *   第1级(主力): STA 连笔记本热点 → 电脑保持上网 + 无线控制 CAN
 *   第2级(备选): AP 始终在线 → 电脑连 ESP32 AP 直接用
 *   第3级(兜底): USB CDC 串口 → 永远可用
 *
 * Web 路由处理在 WS_WebServer.cpp 中。
 *============================================================================*/
#include "WS_WIFI.h"
#include "WS_CAN.h"
#include "WS_WebServer.h"

// ====== 全局 WiFi 状态 ======
char g_ap_ssid[33] = DEFAULT_AP_SSID;
char g_ap_psk[33] = DEFAULT_AP_PSK;
char g_sta_ssid[33] = DEFAULT_STA_SSID;
char g_sta_psk[33] = DEFAULT_STA_PSK;
char g_sta_ip[16] = "0.0.0.0";
char g_device_ip[16] = "0.0.0.0";
bool g_sta_connected = false;

// ====== 内部变量 ======
static IPAddress ap_ip(192, 168, 4, 1);
static char ip_str[16];
static unsigned sta_disconnect_count = 0;
static unsigned sta_last_reason = 0;

/*============================================================================
 * WiFi 事件回调
 *============================================================================*/
static void WiFiEvent(WiFiEvent_t event, WiFiEventInfo_t info) {
    switch (event) {
        case ARDUINO_EVENT_WIFI_STA_CONNECTED:
            sta_disconnect_count = 0;
            printf("[WiFi] STA 已关联: %s\r\n", (char*)info.wifi_sta_connected.ssid);
            break;
        case ARDUINO_EVENT_WIFI_STA_GOT_IP:
            snprintf(ip_str, 16, "%s",
                     IPAddress((uint32_t)info.got_ip.ip_info.ip.addr).toString().c_str());
            snprintf(g_sta_ip, 16, "%s", ip_str);
            snprintf(g_device_ip, 16, "%s", ip_str);
            g_sta_connected = true;
            printf("[WiFi] STA IP: %s\r\n", ip_str);
            break;
        case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
            g_sta_connected = false;
            sta_disconnect_count++;
            if (info.wifi_sta_disconnected.reason != sta_last_reason ||
                sta_disconnect_count % 10 == 1) {
                printf("[WiFi] STA 断开 (reason=%d, 次数=%u)\r\n",
                       info.wifi_sta_disconnected.reason, sta_disconnect_count);
            }
            sta_last_reason = info.wifi_sta_disconnected.reason;
            break;
        default:
            break;
    }
}

/*============================================================================
 * NVS 持久化
 *============================================================================*/
void WIFI_LoadSettings(void) {
    Preferences prefs;
    if (prefs.begin("wifi-can", true)) {
        String s = prefs.getString("sta_ssid", "");
        strncpy(g_sta_ssid, s.c_str(), 32);
        s = prefs.getString("sta_psk", "");
        strncpy(g_sta_psk, s.c_str(), 32);
        s = prefs.getString("ap_ssid", DEFAULT_AP_SSID);
        strncpy(g_ap_ssid, s.c_str(), 32);
        s = prefs.getString("ap_psk", DEFAULT_AP_PSK);
        strncpy(g_ap_psk, s.c_str(), 32);
        uint32_t rate = prefs.getUInt("can_rate", CAN_DEFAULT_BITRATE_KBPS);
        if (rate > 0) CAN_bitrate_kbps = rate;
        prefs.end();
        printf("[WiFi] NVS 设置已加载\r\n");
    }
}

void WIFI_SaveSettings(void) {
    Preferences prefs;
    if (prefs.begin("wifi-can", false)) {
        prefs.putString("sta_ssid", g_sta_ssid);
        prefs.putString("sta_psk", g_sta_psk);
        prefs.putString("ap_ssid", g_ap_ssid);
        prefs.putString("ap_psk", g_ap_psk);
        prefs.putUInt("can_rate", CAN_bitrate_kbps);
        prefs.end();
        printf("[WiFi] NVS 设置已保存\r\n");
    }
}

/*============================================================================
 * WiFi 初始化
 *============================================================================*/
void WIFI_Init(void) {
    WIFI_LoadSettings();

    WiFi.onEvent(WiFiEvent);
    WiFi.mode(WIFI_AP_STA);
    WiFi.softAPConfig(ap_ip, ap_ip, IPAddress(255, 255, 255, 0));

    // AP 启动（始终在线）
    while (!WiFi.softAP(g_ap_ssid, g_ap_psk)) {
        printf("[WiFi] AP 创建失败, 重试...\r\n");
        delay(1000);
    }
    delay(100);

    IPAddress my_ip = WiFi.softAPIP();
    snprintf(g_device_ip, 16, "%d.%d.%d.%d", my_ip[0], my_ip[1], my_ip[2], my_ip[3]);
    printf("[WiFi] AP: %s @ %s\r\n", g_ap_ssid, g_device_ip);

    // STA 连接（如果已配置）
    if (strlen(g_sta_ssid) > 0 && strlen(g_sta_psk) > 0) {
        WiFi.begin(g_sta_ssid, g_sta_psk);
        printf("[WiFi] STA 正在连接 %s...\r\n", g_sta_ssid);
    } else {
        printf("[WiFi] STA 未配置 (请在设置页填入笔记本热点名)\r\n");
    }

    // 注册 Web 路由
    WebServer_Init();

    xTaskCreatePinnedToCore(WebTask, "WebTask", 8192, nullptr, 2, nullptr, 0);
}

/*============================================================================
 * WebTask — HTTP 请求处理 + STA 自动重连
 *============================================================================*/
void WebTask(void *parameter) {
    static unsigned long last_sta_check = 0;

    while (1) {
        WebServer_HandleClient();

        // STA 断线自动重连（每30秒）
        if (strlen(g_sta_ssid) > 0 && !g_sta_connected) {
            unsigned long now = millis();
            if (now - last_sta_check > 30000) {
                last_sta_check = now;
                if (WiFi.status() != WL_CONNECTED) {
                    WiFi.begin(g_sta_ssid, g_sta_psk);
                    printf("[WiFi] STA 重试连接 %s...\r\n", g_sta_ssid);
                }
            }
        }

        vTaskDelay(pdMS_TO_TICKS(10));
    }
    vTaskDelete(nullptr);
}
