/*============================================================================
 * WS_UDP.cpp — UDP 推送通道 (v2.1, 可选)
 *
 * 单向 CAN 批帧推送：客户端向 8889 端口发任意数据报即订阅，
 * ESP32 持续向该 IP:port 推送 0x05 批帧（攒批参数与 TCP 相同）。
 * 30s 无刷新自动移除订阅者，最多 UDP_MAX_CLIENTS 个。
 *
 * 数据报复用二进制帧格式 [2B 大端长度] [1B 类型] [载荷]，
 * 客户端解析器与 TCP 完全通用。
 *============================================================================*/
#include "WS_UDP.h"
#include "WS_CAN.h"
#include <WiFi.h>
#include <WiFiUdp.h>

static WiFiUDP udp;

// ---- 订阅者表 ----
typedef struct {
    IPAddress ip;
    uint16_t  port;
    uint32_t  last_seen_ms;
    bool      active;
} UdpSubscriber;

static UdpSubscriber subscribers[UDP_MAX_CLIENTS];

// ---- 攒批缓冲（UDP 通道独立一份，与 TCP 的 batch 互不干扰） ----
static CAN_Frame batch_frames[CAN_BATCH_MAX_FRAMES];
static uint16_t batch_count = 0;
static uint32_t batch_start_ms = 0;

static int udp_subscriber_count(void) {
    int n = 0;
    for (int i = 0; i < UDP_MAX_CLIENTS; i++) {
        if (subscribers[i].active) n++;
    }
    return n;
}

/*============================================================================
 * 刷新/添加订阅者
 *============================================================================*/
static void udp_subscribe(IPAddress ip, uint16_t port) {
    // 已存在 → 刷新最后活动时间
    for (int i = 0; i < UDP_MAX_CLIENTS; i++) {
        if (subscribers[i].active && subscribers[i].ip == ip &&
            subscribers[i].port == port) {
            subscribers[i].last_seen_ms = millis();
            return;
        }
    }
    // 空位添加
    for (int i = 0; i < UDP_MAX_CLIENTS; i++) {
        if (!subscribers[i].active) {
            subscribers[i].ip = ip;
            subscribers[i].port = port;
            subscribers[i].last_seen_ms = millis();
            subscribers[i].active = true;
            printf("[UDP] 订阅者: %s:%d (共%d个)\r\n",
                   ip.toString().c_str(), port, udp_subscriber_count());
            return;
        }
    }
    // 满员：踢掉最久未活动的
    int oldest = 0;
    for (int i = 1; i < UDP_MAX_CLIENTS; i++) {
        if (subscribers[i].last_seen_ms < subscribers[oldest].last_seen_ms) {
            oldest = i;
        }
    }
    subscribers[oldest].ip = ip;
    subscribers[oldest].port = port;
    subscribers[oldest].last_seen_ms = millis();
    printf("[UDP] 订阅者满, 替换最旧 %s:%d\r\n", ip.toString().c_str(), port);
}

/*============================================================================
 * 批帧 flush → 发给所有订阅者
 *============================================================================*/
static void udp_flush_batch(void) {
    if (batch_count == 0) return;

    uint8_t buf[2 + CAN_BATCH_MAX_FRAMES * 18];
    uint16_t len = CAN_SerializeBatch(buf, batch_frames, batch_count);
    batch_count = 0;

    // v2.1.3: 头+载荷拼一个缓冲一次 write
    uint8_t pkt[3 + 2 + CAN_BATCH_MAX_FRAMES * 18];
    uint16_t total = 1 + len;
    pkt[0] = (total >> 8) & 0xFF;
    pkt[1] = total & 0xFF;
    pkt[2] = FRAME_CAN_BATCH;
    memcpy(pkt + 3, buf, len);

    for (int i = 0; i < UDP_MAX_CLIENTS; i++) {
        if (subscribers[i].active) {
            udp.beginPacket(subscribers[i].ip, subscribers[i].port);
            udp.write(pkt, 3 + len);
            udp.endPacket();
        }
    }
}

/*============================================================================
 * UDP 初始化
 *============================================================================*/
void UDP_Init(void) {
    udp.begin(UDP_SERVER_PORT);
    for (int i = 0; i < UDP_MAX_CLIENTS; i++) {
        subscribers[i].active = false;
    }
    batch_count = 0;

    printf("[UDP] 服务器启动, 端口 %d (订阅式批帧推送)\r\n", UDP_SERVER_PORT);

    // 核心 1 (APP_CPU): 核心 0 必须独占给 WiFi/lwIP 协议栈 (v2.1.2 修复)
    xTaskCreatePinnedToCore(UDPTask, "UDPTask", 4096, nullptr, 3, nullptr, 1);
}

/*============================================================================
 * UDPTask 主循环
 *============================================================================*/
void UDPTask(void *parameter) {
    while (1) {
        // ---- 处理订阅数据报（任意内容即订阅请求） ----
        int packet_size = udp.parsePacket();
        if (packet_size > 0) {
            uint8_t dummy[8];
            udp.read(dummy, sizeof(dummy));
            udp_subscribe(udp.remoteIP(), udp.remotePort());
        }

        // ---- 订阅者超时清理 ----
        uint32_t now = millis();
        for (int i = 0; i < UDP_MAX_CLIENTS; i++) {
            if (subscribers[i].active &&
                (now - subscribers[i].last_seen_ms) >= UDP_KEEPALIVE_MS) {
                printf("[UDP] 订阅者超时移除: %s:%d\r\n",
                       subscribers[i].ip.toString().c_str(), subscribers[i].port);
                subscribers[i].active = false;
            }
        }

        // ---- 攒批超时兜底：没新帧也要把已攒的帧发出去 ----
        if (batch_count > 0 &&
            (uint32_t)(millis() - batch_start_ms) >= CAN_BATCH_TIMEOUT_MS) {
            udp_flush_batch();
        }

        // ---- 读环形缓冲区攒批 ----
        if (udp_subscriber_count() > 0) {
            CAN_Frame frame;
            while (CAN_ReadFrame(&can_ring_udp_tail, &frame)) {
                if (batch_count == 0) batch_start_ms = millis();
                batch_frames[batch_count++] = frame;
                if (batch_count >= CAN_BATCH_MAX_FRAMES) udp_flush_batch();
            }
        }

        vTaskDelay(pdMS_TO_TICKS(1));
    }
    vTaskDelete(nullptr);
}
