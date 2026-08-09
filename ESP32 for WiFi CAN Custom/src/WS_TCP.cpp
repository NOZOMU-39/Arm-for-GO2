/*============================================================================
 * WS_TCP.cpp — TCP 帧服务器
 *
 * 帧格式: [2B 大端长度] [1B 类型] [载荷]
 *
 * 第1级主力通道。CANTask 接收到的 CAN 帧自动推送到所有连接的 TCP 客户端。
 * 命令分发由共享的 ProcessCommand() 处理（定义在 WS_CAN.cpp）。
 *============================================================================*/
#include "WS_TCP.h"
#include "WS_CAN.h"
#include "WS_RTC.h"

// ---- 外部变量 ----
extern uint8_t g_ip_query_flag;
extern uint8_t g_can_query_flag;
extern uint8_t g_rtc_query_flag;
extern char g_device_ip[16];

// ---- TCP 服务器 ----
static WiFiServer *tcp_server = nullptr;
static WiFiClient  tcp_clients[MAX_TCP_CLIENTS];

// ---- 帧解析状态机 ----
enum TcpState {
    TCP_WAIT_LEN_HI,
    TCP_WAIT_LEN_LO,
    TCP_WAIT_TYPE,
    TCP_WAIT_PAYLOAD
};

struct TcpClientState {
    TcpState  state;
    uint16_t  payload_len;
    uint8_t   frame_type;
    uint8_t   payload[TCP_RX_BUF_SIZE];
    uint16_t  payload_pos;
};

static TcpClientState client_state[MAX_TCP_CLIENTS];

/*============================================================================
 * TCP 帧发送
 *============================================================================*/
void TCP_SendFrame(uint8_t frame_type, const uint8_t *payload, uint16_t payload_len) {
    uint16_t total = 1 + payload_len;  // 类型 + 载荷
    uint8_t header[3];
    header[0] = (total >> 8) & 0xFF;
    header[1] = total & 0xFF;
    header[2] = frame_type;

    for (int i = 0; i < MAX_TCP_CLIENTS; i++) {
        if (tcp_clients[i] && tcp_clients[i].connected()) {
            tcp_clients[i].write(header, 3);
            if (payload_len > 0) {
                tcp_clients[i].write(payload, payload_len);
            }
        }
    }
}

/*============================================================================
 * 推送 CAN 帧给 TCP 客户端
 *============================================================================*/
static void TCP_PushCANFrames(void) {
    bool has_client = false;
    for (int i = 0; i < MAX_TCP_CLIENTS; i++) {
        if (tcp_clients[i] && tcp_clients[i].connected()) {
            has_client = true;
            break;
        }
    }
    if (!has_client) return;

    // 批量推送所有未读 CAN 帧
    CAN_Frame frame;
    while (CAN_ReadFrame(&can_ring_tcp_tail, &frame)) {
        uint8_t buf[18];
        buf[0] = (frame.id >> 24) & 0xFF;
        buf[1] = (frame.id >> 16) & 0xFF;
        buf[2] = (frame.id >> 8) & 0xFF;
        buf[3] = frame.id & 0xFF;
        buf[4] = frame.extd;
        buf[5] = (frame.timestamp_ms >> 24) & 0xFF;
        buf[6] = (frame.timestamp_ms >> 16) & 0xFF;
        buf[7] = (frame.timestamp_ms >> 8) & 0xFF;
        buf[8] = frame.timestamp_ms & 0xFF;
        buf[9] = frame.dlc;
        if (frame.dlc > 0) {
            memcpy(buf + 10, frame.data, frame.dlc);
        }
        TCP_SendFrame(FRAME_CAN_PUSH, buf, 10 + frame.dlc);
    }
}

/*============================================================================
 * 帧解析：逐字节喂入
 *============================================================================*/
static void TCP_ParseByte(int client_idx, uint8_t b) {
    TcpClientState *cs = &client_state[client_idx];

    switch (cs->state) {
        case TCP_WAIT_LEN_HI:
            cs->payload_len = ((uint16_t)b) << 8;
            cs->state = TCP_WAIT_LEN_LO;
            break;

        case TCP_WAIT_LEN_LO:
            cs->payload_len |= b;
            if (cs->payload_len == 0 || cs->payload_len > TCP_RX_BUF_SIZE) {
                printf("[TCP] 客户端%d 无效帧长度: %d\r\n", client_idx, cs->payload_len);
                cs->state = TCP_WAIT_LEN_HI;
            } else {
                cs->state = TCP_WAIT_TYPE;
            }
            break;

        case TCP_WAIT_TYPE:
            cs->frame_type = b;
            cs->payload_pos = 0;
            if (cs->payload_len == 1) {
                // 只有类型字节 — 直接处理
                uint8_t full[1] = {cs->frame_type};
                ProcessCommand(full, 1);
                cs->state = TCP_WAIT_LEN_HI;
            } else {
                cs->payload_len--;  // 减去类型字节
                cs->state = TCP_WAIT_PAYLOAD;
            }
            break;

        case TCP_WAIT_PAYLOAD:
            cs->payload[cs->payload_pos++] = b;
            if (cs->payload_pos >= cs->payload_len) {
                // 完整帧 — 提交给 ProcessCommand
                uint8_t full[TCP_RX_BUF_SIZE + 1];
                full[0] = cs->frame_type;
                memcpy(full + 1, cs->payload, cs->payload_len);
                ProcessCommand(full, cs->payload_len + 1);
                cs->state = TCP_WAIT_LEN_HI;
            }
            break;
    }
}

/*============================================================================
 * TCP 初始化
 *============================================================================*/
void TCP_Init(void) {
    tcp_server = new WiFiServer(TCP_SERVER_PORT);
    tcp_server->begin();
    tcp_server->setNoDelay(true);

    for (int i = 0; i < MAX_TCP_CLIENTS; i++) {
        tcp_clients[i] = WiFiClient();
        client_state[i].state = TCP_WAIT_LEN_HI;
    }

    printf("[TCP] 服务器启动, 端口 %d\r\n", TCP_SERVER_PORT);

    xTaskCreatePinnedToCore(TCPTask, "TCPTask", 8192, nullptr, 3, nullptr, 0);
}

/*============================================================================
 * TCPTask 主循环
 *============================================================================*/
void TCPTask(void *parameter) {
    const TickType_t loop_delay = pdMS_TO_TICKS(1);

    while (1) {
        // ---- 响应标志位查询（给所有客户端）----
        if (g_ip_query_flag) {
            g_ip_query_flag = 0;
            TCP_SendFrame(FRAME_CMD_RESP, (const uint8_t *)g_device_ip, strlen(g_device_ip));
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        if (g_can_query_flag) {
            g_can_query_flag = 0;
            CAN_Frame frame;
            if (CAN_ReadFrame(&can_ring_tcp_tail, &frame)) {
                uint8_t buf[18];
                buf[0] = (frame.id >> 24) & 0xFF;
                buf[1] = (frame.id >> 16) & 0xFF;
                buf[2] = (frame.id >> 8) & 0xFF;
                buf[3] = frame.id & 0xFF;
                buf[4] = frame.extd;
                buf[5] = (frame.timestamp_ms >> 24) & 0xFF;
                buf[6] = (frame.timestamp_ms >> 16) & 0xFF;
                buf[7] = (frame.timestamp_ms >> 8) & 0xFF;
                buf[8] = frame.timestamp_ms & 0xFF;
                buf[9] = frame.dlc;
                if (frame.dlc > 0) memcpy(buf + 10, frame.data, frame.dlc);
                TCP_SendFrame(FRAME_CAN_PUSH, buf, 10 + frame.dlc);
            } else {
                TCP_SendFrame(FRAME_CMD_RESP, (const uint8_t *)"[CAN Buffer Empty]", 18);
            }
            continue;
        }
        if (g_rtc_query_flag) {
            g_rtc_query_flag = 0;
            char time_str[50];
            RTC_GetTimeStr(time_str, sizeof(time_str));
            TCP_SendFrame(FRAME_CMD_RESP, (const uint8_t *)time_str, strlen(time_str));
            continue;
        }

        // ---- 推送 CAN 帧 ----
        TCP_PushCANFrames();

        // ---- 接受新连接 ----
        if (tcp_server->hasClient()) {
            WiFiClient new_client = tcp_server->accept();
            bool added = false;
            for (int i = 0; i < MAX_TCP_CLIENTS; i++) {
                if (!tcp_clients[i] || !tcp_clients[i].connected()) {
                    tcp_clients[i] = new_client;
                    tcp_clients[i].setNoDelay(true);
                    client_state[i].state = TCP_WAIT_LEN_HI;
                    printf("[TCP] 客户端%d 已连接: %s\r\n", i,
                           tcp_clients[i].remoteIP().toString().c_str());
                    added = true;
                    break;
                }
            }
            if (!added) {
                printf("[TCP] 客户端已满 (%d), 拒绝新连接\r\n", MAX_TCP_CLIENTS);
                new_client.stop();
            }
        }

        // ---- 处理客户端数据 ----
        for (int i = 0; i < MAX_TCP_CLIENTS; i++) {
            if (tcp_clients[i] && tcp_clients[i].connected()) {
                while (tcp_clients[i].available() > 0) {
                    uint8_t b = tcp_clients[i].read();
                    TCP_ParseByte(i, b);
                }
            } else if (tcp_clients[i]) {
                printf("[TCP] 客户端%d 已断开\r\n", i);
                tcp_clients[i].stop();
                client_state[i].state = TCP_WAIT_LEN_HI;
            }
        }

        vTaskDelay(loop_delay);
    }
    vTaskDelete(nullptr);
}
